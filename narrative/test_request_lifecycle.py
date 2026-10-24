"""Durable dispatch/cancellation tests, using disposable Evennia test databases."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from evennia.objects.models import ObjectDB
from twisted.internet.defer import Deferred
from twisted.internet.task import Clock

from chronicle import generation
from chronicle.models import ChronicleEvent, ChronicleGenerationRequest
from traits.models import CharacterBio

from . import services
from .models import MemoryFact, NarrativeConsent, NarrativePersona, StoryGenerationRequest, StorySession
from .provider_transport import ProviderLimits


class LateProviderDeferred(Deferred):
    """Model a transport that can finish after receiving cancellation."""

    def __init__(self):
        super().__init__()
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True


class ControlledProvider:
    def __init__(self):
        self.clock = Clock()
        self.limits = ProviderLimits(request_timeout_seconds=3)
        self.messages = []
        self.responses = []
        self.on_generate = None

    def generate(self, messages):
        if self.on_generate:
            self.on_generate()
        self.messages.append(messages)
        response = LateProviderDeferred()
        self.responses.append(response)
        return response

    def respond(self, prose="The night is quiet.", citations=None, index=-1):
        self.responses[index].callback(json.dumps({"prose": prose, "citations": citations or []}))


def story_fixture(prefix):
    account = get_user_model().objects.create_user(username=prefix)
    other = get_user_model().objects.create_user(username=f"{prefix}-other")
    character = ObjectDB.objects.create(
        db_key=prefix, db_typeclass_path="typeclasses.characters.Character", db_account=account
    )
    CharacterBio.objects.create(character=character, account=account)
    NarrativeConsent.objects.create(account=account, character=character, opted_in=True)
    session = StorySession.objects.create(
        character=character,
        current_action="private action",
        deterministic_outcome={"success": True, "hunger_after": 2},
        resume_state={"phase": "approach"},
    )
    return account, other, character, session


class StoryRequestLifecycleTests(TestCase):
    def setUp(self):
        self.account, self.other, self.character, self.session = story_fixture("lifecycle-player")
        self.provider = ControlledProvider()
        self.results, self.errors = [], []

    def start(self, action="private action", scheduler=None):
        result = services.generate_story(
            self.session, action, self.provider, scheduler or (lambda callback: callback())
        )
        result.addCallbacks(self.results.append, self.errors.append)
        return result

    def assert_failed(self, request, category=None):
        request.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(request.status, "failed")
        self.assertEqual(request.action_text, "")
        if category:
            self.assertEqual(request.error, category)
        self.assertEqual(self.session.deterministic_outcome, {"success": True, "hunger_after": 2})

    def test_claim_is_conditional_and_snapshot_is_immutable(self):
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="private action")
        claim = services.claim_story_request(request.pk)
        self.assertIsNotNone(claim)
        self.assertIsNone(services.claim_story_request(request.pk))
        request.refresh_from_db()
        self.assertIsNotNone(request.dispatched_at)
        self.assertGreater(request.deadline_at, request.dispatched_at)
        altered = claim.messages
        altered[-1]["content"] = "rewritten"
        self.assertIn("private action", claim.messages[-1]["content"])

    def test_crash_before_claim_recovers_once(self):
        queued = []
        result = self.start(scheduler=queued.append)
        self.assertEqual(services.recover_pending_requests(self.provider, lambda callback: callback()), 1)
        queued[0]()
        self.assertEqual(len(self.provider.messages), 1)
        self.provider.respond()
        self.assertTrue(result.called)
        self.assertEqual(self.results, ["The night is quiet."])

    def test_crash_after_claim_before_send_is_not_redispatched(self):
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="private action")
        services.claim_story_request(request.pk)
        self.assertEqual(services.recover_pending_requests(self.provider, lambda callback: callback()), 0)
        self.assertEqual(self.provider.messages, [])
        self.assert_failed(request, "interrupted")

    def test_crash_after_send_fails_waiter_and_ignores_late_completion(self):
        result = self.start()
        request = StoryGenerationRequest.objects.get()
        self.assertEqual(services.recover_pending_requests(self.provider, lambda callback: callback()), 0)
        self.assertTrue(result.called)
        self.assertEqual(len(self.errors), 1)
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.provider.respond()
        self.assert_failed(request, "interrupted")
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.provider.messages), 1)

    def test_network_begins_after_committed_claim(self):
        observed = []
        baseline_savepoints = connection.savepoint_ids[:]

        def observe():
            request = StoryGenerationRequest.objects.get()
            observed.append((connection.savepoint_ids[:], request.dispatched_at, request.deadline_at))

        self.provider.on_generate = observe
        self.start()
        self.assertEqual(observed[0][0], baseline_savepoints)
        self.assertIsNotNone(observed[0][1])
        self.assertIsNotNone(observed[0][2])
        self.provider.respond()

    def test_cancel_before_dispatch_settles_without_http(self):
        queued = []
        result = self.start(scheduler=queued.append)
        result.cancel()
        queued[0]()
        self.assertEqual(self.provider.messages, [])
        self.assert_failed(StoryGenerationRequest.objects.get(), "canceled")
        self.assertEqual(len(self.errors), 1)

    def _deactivate_warmed_requester(self):
        self.assertTrue(self.account.is_active)
        get_user_model().objects.filter(pk=self.account.pk).update(is_active=False)
        # A cached account object must not confer authority after a DB update.
        self.assertTrue(self.account.is_active)

    def test_deactivated_requester_before_dispatch_never_sends(self):
        queued = []
        result = self.start(scheduler=queued.append)
        self._deactivate_warmed_requester()
        queued[0]()
        self.assertTrue(result.called)
        self.assertEqual(self.provider.messages, [])
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        self.assert_failed(StoryGenerationRequest.objects.get(), "canceled")
        self.assertEqual(self.provider.clock.getDelayedCalls(), [])

    def test_deactivated_requester_after_claim_never_sends(self):
        claim_request = services.claim_story_request

        def claim_then_deactivate(request_id):
            claim = claim_request(request_id)
            self.assertIsNotNone(claim)
            self._deactivate_warmed_requester()
            return claim

        with patch.object(services, "claim_story_request", side_effect=claim_then_deactivate):
            result = self.start()
        self.assertTrue(result.called)
        self.assertEqual(self.provider.messages, [])
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        self.assert_failed(StoryGenerationRequest.objects.get(), "canceled")

    def test_deactivated_requester_inflight_cancels_late_prose(self):
        result = self.start()
        self._deactivate_warmed_requester()
        self.provider.respond("Late private prose after deactivation.")
        self.assertTrue(result.called)
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        self.assert_failed(StoryGenerationRequest.objects.get(), "canceled")
        self.assertEqual(self.session.resume_state, {"phase": "approach"})
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(self.provider.clock.getDelayedCalls(), [])

    def test_deactivated_requester_at_acceptance_write_cancels_late_prose(self):
        result = self.start()
        validate_context = services._validated_context

        def validate_then_deactivate(session, context):
            resume = validate_context(session, context)
            self._deactivate_warmed_requester()
            return resume

        with patch.object(services, "_validated_context", side_effect=validate_then_deactivate):
            self.provider.respond("Prose racing requester deactivation.")
        self.assertTrue(result.called)
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        self.assert_failed(StoryGenerationRequest.objects.get(), "canceled")
        self.assertEqual(self.session.resume_state, {"phase": "approach"})

    def test_cancel_during_http_aborts_and_preserves_newer_action(self):
        first = self.start()
        request = StoryGenerationRequest.objects.get()
        first.cancel()
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.session.current_action = "new action"
        self.session.save(update_fields=("current_action",))
        second = self.start("new action")
        self.provider.respond(index=0, prose="late old response")
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "new action")
        self.assertFalse(second.called)
        self.assert_failed(request, "canceled")
        self.provider.respond(index=1)
        self.assertTrue(second.called)

    def test_consent_withdrawal_settles_waiter_without_waiting_for_provider(self):
        result = self.start()
        services.set_consent(self.account, self.character, False)
        self.assertTrue(result.called)
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.provider.respond()
        self.assert_failed(StoryGenerationRequest.objects.get())
        self.assertEqual(len(self.errors), 1)

    def test_revocation_settles_waiter_after_foreign_terminal_write_without_displaying_prose(self):
        result = self.start(scheduler=lambda _callback: None)
        request = StoryGenerationRequest.objects.get()
        StoryGenerationRequest.objects.filter(pk=request.pk).update(
            status="succeeded", response="Retained historical prose.", action_text=""
        )
        services.set_consent(self.account, self.character, False)
        self.assertTrue(result.called)
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        request.refresh_from_db()
        self.assertEqual((request.status, request.response), ("succeeded", "Retained historical prose."))

    def _foreign_success_awaiting_delivery(self):
        queued = []
        result = self.start(scheduler=queued.append)
        request = StoryGenerationRequest.objects.get()
        StoryGenerationRequest.objects.filter(pk=request.pk).update(
            status="succeeded", response="Foreign worker historical prose.", action_text="", completed_at=timezone.now()
        )
        StorySession.objects.filter(pk=self.session.pk).update(
            resume_state={
                "phase": "approach",
                "last_response": "Foreign worker historical prose.",
                "last_response_provenance": {
                    "version": 1,
                    "request_id": request.pk,
                    "response": services._fingerprint("Foreign worker historical prose."),
                    "scene": services._scene_provenance(self.session),
                    "dependencies": [],
                },
            }
        )
        return result, request, queued[0]

    def _assert_foreign_delivery_denied(self, result, request, callback):
        callback()
        callback()  # A stale scheduler callback may be replayed after settlement.
        self.assertTrue(result.called)
        self.assertEqual(self.results, [])
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(getattr(self.errors[0].value, "category", None), "canceled")
        self.assertEqual(self.provider.messages, [])
        request.refresh_from_db()
        self.assertEqual((request.status, request.response), ("succeeded", "Foreign worker historical prose."))
        self.assertEqual(self.provider.clock.getDelayedCalls(), [])

    def test_foreign_success_is_not_delivered_after_owner_transfer_with_new_consent(self):
        result, request, callback = self._foreign_success_awaiting_delivery()
        CharacterBio.objects.filter(character=self.character).update(account=self.other)
        NarrativeConsent.objects.create(account=self.other, character=self.character, opted_in=True)
        self._assert_foreign_delivery_denied(result, request, callback)

    def test_foreign_success_is_not_delivered_after_foreign_session_closure(self):
        result, request, callback = self._foreign_success_awaiting_delivery()
        StorySession.objects.filter(pk=self.session.pk).update(status="closed")
        self._assert_foreign_delivery_denied(result, request, callback)

    def test_foreign_success_is_not_delivered_after_foreign_consent_revocation(self):
        result, request, callback = self._foreign_success_awaiting_delivery()
        NarrativeConsent.objects.filter(account=self.account, character=self.character).update(opted_in=False)
        self._assert_foreign_delivery_denied(result, request, callback)

    def test_foreign_success_is_not_delivered_after_requester_deactivation(self):
        result, request, callback = self._foreign_success_awaiting_delivery()
        self._deactivate_warmed_requester()
        self._assert_foreign_delivery_denied(result, request, callback)
        self.session.refresh_from_db()
        self.assertEqual(self.session.deterministic_outcome, {"success": True, "hunger_after": 2})

    def test_authorized_foreign_success_is_delivered_once_without_redispatch(self):
        result, request, callback = self._foreign_success_awaiting_delivery()
        callback()
        callback()
        self.assertTrue(result.called)
        self.assertEqual(self.results, ["Foreign worker historical prose."])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.provider.messages, [])
        request.refresh_from_db()
        self.assertEqual((request.status, request.response), ("succeeded", "Foreign worker historical prose."))
        self.assertEqual(self.provider.clock.getDelayedCalls(), [])

    def _foreign_source_success_awaiting_delivery(self):
        source = ChronicleEvent.objects.create(
            idempotency_key="foreign-delivery-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="Reviewed source",
            summary="Sensitive source prose.",
            status="published",
            visibility="public",
        )
        recap = ChronicleEvent.objects.create(
            idempotency_key="foreign-delivery-recap",
            source_app="staff",
            source_type="scene",
            source_id="2",
            kind="scene.curated",
            title="Derived source",
            summary="Retained derivative prose.",
            status="published",
            visibility="public",
        )
        recap.source_events.add(source)
        npc = ObjectDB.objects.create(
            db_key="Foreign-delivery NPC", db_typeclass_path="typeclasses.characters.Character"
        )
        persona = NarrativePersona.objects.create(character=npc)
        fact = MemoryFact.objects.create(
            persona=persona, text="Sensitive memory.", source_event=recap, status="approved", visibility="public"
        )
        self.session.persona = persona
        self.session.save(update_fields=("persona",))
        queued = []
        result = self.start(scheduler=queued.append)
        request = StoryGenerationRequest.objects.get()
        claim = services.claim_story_request(request.pk)
        self.assertIsNotNone(claim)
        waiting = services._story_waiters.pop(request.pk)
        try:
            # Simulate the foreign worker's committed acceptance without this
            # process's local waiter map or any provider/network dispatch.
            services._accept_response(
                request.pk,
                {"prose": "Foreign worker source-backed prose.", "citations": [str(fact.pk)]},
                claim.allowed_ids,
                claim.provenance,
                None,
                claim.dispatched_at,
            )
        finally:
            services._story_waiters[request.pk] = waiting
        request.refresh_from_db()
        self.assertEqual(request.status, "succeeded")
        return result, request, queued[0], source

    def _assert_source_foreign_delivery(self, result, request, callback, *, allowed):
        callback()
        callback()
        self.assertTrue(result.called)
        self.assertEqual(self.results, ["Foreign worker source-backed prose."] if allowed else [])
        self.assertEqual(len(self.errors), 0 if allowed else 1)
        if not allowed:
            self.assertEqual(getattr(self.errors[0].value, "category", None), "canceled")
        self.assertEqual(self.provider.messages, [])
        self.assertEqual(self.provider.clock.getDelayedCalls(), [])
        request.refresh_from_db()
        self.assertEqual((request.status, request.response), ("succeeded", "Foreign worker source-backed prose."))
        self.session.refresh_from_db()
        self.assertEqual(self.session.deterministic_outcome, {"success": True, "hunger_after": 2})

    def test_foreign_source_backed_success_is_not_delivered_after_ancestor_redaction(self):
        from chronicle.services import redact_event

        result, request, callback, source = self._foreign_source_success_awaiting_delivery()
        self.account.permissions.add("Builder")
        redact_event(source.pk, self.account)
        self._assert_source_foreign_delivery(result, request, callback, allowed=False)

    def test_foreign_source_backed_success_delivers_once_while_exact_provenance_remains_current(self):
        result, request, callback, _source = self._foreign_source_success_awaiting_delivery()
        self._assert_source_foreign_delivery(result, request, callback, allowed=True)

    def test_foreign_success_cannot_borrow_a_newer_responses_provenance(self):
        result, request, callback, _source = self._foreign_source_success_awaiting_delivery()
        self.session.refresh_from_db()
        state = self.session.resume_state
        state["last_response_provenance"]["request_id"] = request.pk + 1
        state["last_response_provenance"]["dependencies"] = []
        StorySession.objects.filter(pk=self.session.pk).update(resume_state=state)
        self._assert_source_foreign_delivery(result, request, callback, allowed=False)

    def test_foreign_success_is_not_delivered_after_its_scene_provenance_changes(self):
        result, request, callback, _source = self._foreign_source_success_awaiting_delivery()
        StorySession.objects.filter(pk=self.session.pk).update(location="changed-scene")
        self._assert_source_foreign_delivery(result, request, callback, allowed=False)

    def test_resume_without_memory_dependencies_cannot_cross_character_ownership(self):
        self.start()
        self.provider.respond("Prior owner's private action-derived prose.")
        historical = StoryGenerationRequest.objects.get()
        self.session.refresh_from_db()
        self.assertEqual(self.session.resume_state["last_response_provenance"]["dependencies"], [])
        CharacterBio.objects.filter(character=self.character).update(account=self.other)
        NarrativeConsent.objects.create(account=self.other, character=self.character, opted_in=True)
        self.start("New owner's action")
        self.assertNotIn("Prior owner's private action-derived prose.", json.dumps(self.provider.messages[-1]))
        self.provider.respond("New owner's prose.")
        historical.refresh_from_db()
        self.assertEqual(
            (historical.status, historical.response), ("succeeded", "Prior owner's private action-derived prose.")
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.deterministic_outcome, {"success": True, "hunger_after": 2})

    def test_resume_without_memory_dependencies_remains_available_to_the_same_consented_owner(self):
        self.start()
        self.provider.respond("Current owner's authorized continuation.")
        self.start("Same owner's next action")
        self.assertIn("Current owner's authorized continuation.", json.dumps(self.provider.messages[-1]))
        self.provider.respond("Safe continuation.")
        self.assertEqual(self.errors, [])

    def test_completion_settles_waiter_and_late_prose_cannot_reopen_session(self):
        result = self.start()
        self.session.complete()
        self.assertTrue(result.called)
        self.provider.respond()
        self.assert_failed(StoryGenerationRequest.objects.get())
        self.assertEqual(self.session.status, "completed")

    def test_queued_closed_session_never_dispatches(self):
        queued = []
        self.start(scheduler=queued.append)
        StorySession.objects.filter(pk=self.session.pk).update(status="closed")
        queued[0]()
        self.assertEqual(self.provider.messages, [])
        self.assert_failed(StoryGenerationRequest.objects.get())

    def test_owner_transfer_rejects_even_if_new_owner_has_consent(self):
        for queued_dispatch in (True, False):
            with self.subTest(queued=queued_dispatch):
                queued = []
                self.start(scheduler=queued.append if queued_dispatch else None)
                CharacterBio.objects.filter(character=self.character).update(account=self.other)
                NarrativeConsent.objects.update_or_create(
                    account=self.other, character=self.character, defaults={"opted_in": True}
                )
                if queued_dispatch:
                    queued[0]()
                else:
                    self.provider.respond()
                self.assert_failed(StoryGenerationRequest.objects.latest("id"))
                CharacterBio.objects.filter(character=self.character).update(account=self.account)

    def test_changed_dispatch_context_rejects_response(self):
        self.start()
        StorySession.objects.filter(pk=self.session.pk).update(location="club")
        self.provider.respond()
        self.assert_failed(StoryGenerationRequest.objects.get())

    def test_deadline_cancels_provider_and_late_completion_is_ignored(self):
        result = self.start()
        self.provider.clock.advance(3)
        self.assertTrue(result.called)
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.provider.respond()
        self.assert_failed(StoryGenerationRequest.objects.get(), "timeout")
        self.assertEqual(len(self.errors), 1)

    def test_expired_queued_deadline_prevents_recovery_dispatch(self):
        self.start(scheduler=lambda _callback: None)
        request = StoryGenerationRequest.objects.get()
        StoryGenerationRequest.objects.filter(pk=request.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(services.recover_pending_requests(self.provider, lambda callback: callback()), 0)
        self.assertEqual(self.provider.messages, [])
        self.assert_failed(request, "timeout")

    def test_duplicate_pending_request_is_rejected_without_replacing_first(self):
        self.start()
        with self.assertRaisesRegex(RuntimeError, "pending"):
            self.start("second action")
        self.assertEqual(StoryGenerationRequest.objects.count(), 1)
        self.provider.respond()

    def test_admission_persists_action_and_duplicate_cannot_replace_it(self):
        self.start("first admitted action")
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "first admitted action")
        with self.assertRaises(RuntimeError):
            self.start("unaccepted second action")
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "first admitted action")
        self.provider.respond()
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "")

    def test_shutdown_settles_and_cancels_waiting_work(self):
        result = self.start()
        services.shutdown_pending_requests()
        self.assertTrue(result.called)
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.provider.respond()
        self.assert_failed(StoryGenerationRequest.objects.get(), "interrupted")

    def test_shutdown_of_losing_worker_preserves_foreign_claim(self):
        result = self.start(scheduler=lambda _callback: None)
        request = StoryGenerationRequest.objects.get()
        # A different worker has claimed the queued row without this worker
        # owning its transport. Local shutdown cannot revoke that claim.
        claim = services.claim_story_request(request.pk)
        self.assertIsNotNone(claim)
        services.shutdown_pending_requests()
        self.assertTrue(result.called)
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")
        self.assertEqual(request.dispatched_at, claim.dispatched_at)


class ChronicleRequestLifecycleTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="lifecycle-builder")
        self.staff.permissions.add("Builder")
        self.source = ChronicleEvent.objects.create(
            idempotency_key="lifecycle-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="Public meeting",
            summary="The court met.",
            status="published",
            visibility="public",
        )
        self.provider = ControlledProvider()

    def start(self, scheduler=None):
        with self.captureOnCommitCallbacks(execute=True):
            return generation.request_draft(
                self.staff,
                [self.source.pk],
                "recap",
                provider=self.provider,
                scheduler=scheduler or (lambda callback: callback()),
            )

    def test_deadline_fails_and_late_completion_cannot_create_draft(self):
        request = self.start()
        self.provider.clock.advance(3)
        request.refresh_from_db()
        self.assertEqual(request.status, "failed")
        self.assertEqual(request.error, "timeout")
        self.assertIsNotNone(request.deadline_at)
        self.assertTrue(self.provider.responses[0].cancel_requested)
        self.provider.respond(citations=[str(self.source.pk)])
        self.assertFalse(ChronicleEvent.objects.filter(ai_generated=True).exists())

    def test_expired_unsent_request_is_not_recovered(self):
        request = self.start(scheduler=lambda _callback: None)
        ChronicleGenerationRequest.objects.filter(pk=request.pk).update(
            deadline_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(generation.recover_pending_drafts(self.provider, lambda callback: callback()), 0)
        self.assertEqual(self.provider.messages, [])
        request.refresh_from_db()
        self.assertEqual(request.error, "timeout")

    def test_upstream_failure_stores_only_fixed_category(self):
        request = self.start()
        self.provider.responses[0].errback(RuntimeError("private prompt secret-do-not-store"))
        request.refresh_from_db()
        self.assertEqual(request.error, "upstream_failure")


class StoryRequestClaimConcurrencyTests(TransactionTestCase):
    def test_provider_calls_see_committed_claims_outside_atomic_blocks(self):
        account, _other, _character, session = story_fixture("committed-worker")
        provider = ControlledProvider()
        observed = []

        def observe():
            self.assertFalse(connection.in_atomic_block)

            def read_claim():
                try:
                    return StoryGenerationRequest.objects.get(session=session).dispatched_at
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as pool:
                observed.append(pool.submit(read_claim).result(timeout=5))

        provider.on_generate = observe
        result = services.generate_story(session, "admitted action", provider, lambda callback: callback())
        result.addErrback(lambda _failure: None)
        self.assertEqual(len(observed), 1)
        self.assertIsNotNone(observed[0])
        provider.respond()

        account.permissions.add("Builder")
        source = ChronicleEvent.objects.create(
            idempotency_key="committed-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="Public source",
            status="published",
            visibility="public",
        )
        provider.on_generate = lambda: self.assertFalse(connection.in_atomic_block)
        request = generation.request_draft(
            account, [source.pk], "recap", provider=provider, scheduler=lambda callback: callback()
        )
        self.assertIsNotNone(request.pk)
        provider.respond(citations=[str(source.pk)])

    def test_two_database_connections_claim_only_once(self):
        _account, _other, _character, session = story_fixture("claim-worker")
        request = StoryGenerationRequest.objects.create(session=session, action_text="private action")
        barrier = Barrier(2)

        def claim():
            try:
                barrier.wait(timeout=5)
                return services.claim_story_request(request.pk)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim), pool.submit(claim)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(result is not None for result in results), 1)
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")
        self.assertIsNotNone(request.dispatched_at)

    def test_two_database_connections_dispatch_chronicle_only_once(self):
        staff = get_user_model().objects.create_user(username="claim-builder")
        staff.permissions.add("Builder")
        source = ChronicleEvent.objects.create(
            idempotency_key="claim-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="Public source",
            status="published",
            visibility="public",
        )
        _sources, fingerprints = generation._source_context([str(source.pk)])
        request = ChronicleGenerationRequest.objects.create(
            requested_by=staff,
            mode="recap",
            source_ids=[str(source.pk)],
            source_fingerprints=fingerprints,
        )
        provider, barrier = ControlledProvider(), Barrier(2)

        def dispatch():
            try:
                barrier.wait(timeout=5)
                generation._dispatch(request.pk, provider)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(dispatch), pool.submit(dispatch)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(provider.messages), 1)
        provider.respond(citations=[str(source.pk)])
        request.refresh_from_db()
        self.assertEqual(request.status, "succeeded")


class LegacyStoryRequestMigrationTests(TransactionTestCase):
    def test_populated_legacy_pending_rows_fail_closed_without_losing_history(self):
        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("narrative", "0001_initial"), ("chronicle", "0002_chronicle_generation_request")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            account = old_apps.get_model("accounts", "AccountDB").objects.create(username="legacy-request-owner")
            character = old_apps.get_model("objects", "ObjectDB").objects.create(db_key="LegacyRequestPlayer")
            old_apps.get_model("narrative", "NarrativeConsent").objects.create(
                account_id=account.pk, character_id=character.pk, opted_in=True
            )
            session = old_apps.get_model("narrative", "StorySession").objects.create(
                character_id=character.pk,
                current_action="legacy private action",
                resume_state={"phase": "approach"},
                deterministic_outcome={"success": True, "hunger_after": 2},
            )
            old_request = old_apps.get_model("narrative", "StoryGenerationRequest")
            pending = old_request.objects.create(session_id=session.pk, action_text="legacy private action")
            second = old_request.objects.create(session_id=session.pk, action_text="other old action")
            succeeded = old_request.objects.create(
                session_id=session.pk, status="succeeded", response="Historic prose.", citations=["7"]
            )
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            current = executor.loader.project_state(final_targets).apps
            requests = current.get_model("narrative", "StoryGenerationRequest")
            for request_id in (pending.pk, second.pk):
                migrated = requests.objects.get(pk=request_id)
                self.assertEqual(
                    (migrated.status, migrated.error, migrated.action_text), ("failed", "legacy_dispatch_unknown", "")
                )
                self.assertIsNotNone(migrated.completed_at)
            historic = requests.objects.get(pk=succeeded.pk)
            self.assertEqual(
                (historic.status, historic.response, historic.citations), ("succeeded", "Historic prose.", ["7"])
            )
            preserved = current.get_model("narrative", "StorySession").objects.get(pk=session.pk)
            self.assertEqual(preserved.current_action, "")
            self.assertEqual(preserved.status, "active")
            self.assertEqual(preserved.resume_state, {"phase": "approach"})
            self.assertEqual(preserved.deterministic_outcome, {"success": True, "hunger_after": 2})
            self.assertTrue(current.get_model("narrative", "NarrativeConsent").objects.get().opted_in)
        finally:
            MigrationExecutor(connection).migrate(final_targets)
