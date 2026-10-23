import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from twisted.internet.defer import Deferred, fail, succeed

from .models import (
    MemoryFact,
    NarrativeConsent,
    NarrativePersona,
    StoryGenerationRequest,
    StorySession,
)
from .services import active_consent, authorized_memory_context, configured_provider, generate_story, set_consent


class NarrativeStoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.account = user_model.objects.create_user(username="narrative-player", password="test")
        self.other_account = user_model.objects.create_user(username="other-player", password="test")
        self.character = ObjectDB.objects.create(
            db_key="NarrativePlayer", db_typeclass_path="typeclasses.characters.Character", db_account=self.account
        )
        self.other_character = ObjectDB.objects.create(
            db_key="OtherNarrativePlayer",
            db_typeclass_path="typeclasses.characters.Character",
            db_account=self.other_account,
        )
        self.npc = ObjectDB.objects.create(db_key="NarrativeNPC", db_typeclass_path="typeclasses.characters.Character")
        self.persona = NarrativePersona.objects.create(character=self.npc, profile="A reserved night-shift clerk.")
        self.session = StorySession.objects.create(
            character=self.character,
            persona=self.persona,
            location="street",
            deterministic_outcome={"hunting_success": True, "hunger_after": 2},
            resume_state={"phase": "approach"},
        )

    def test_consent_is_account_and_character_specific(self):
        NarrativeConsent.objects.create(account=self.other_account, character=self.character, opted_in=True)
        self.assertFalse(active_consent(self.session))
        with self.assertRaises(PermissionError):
            set_consent(self.other_account, self.character, True)
        self.assertFalse(active_consent(self.session))
        set_consent(self.account, self.character, True)
        self.assertTrue(active_consent(self.session))

    def test_opt_out_closes_active_story_and_expires_pending_player_text(self):
        consent = NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="Private action.")

        set_consent(self.account, self.character, False)

        consent.refresh_from_db()
        request.refresh_from_db()
        self.session.refresh_from_db()
        self.assertFalse(consent.opted_in)
        self.assertEqual(self.session.status, StorySession.Status.CLOSED)
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.action_text, "")

    @override_settings(
        NARRATIVE_AI={
            "endpoint": "http://provider.example/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-secret",
        }
    )
    def test_remote_cleartext_provider_is_disabled(self):
        self.assertIsNone(configured_provider())

    def test_malformed_provider_url_is_disabled(self):
        with override_settings(
            NARRATIVE_AI={
                "endpoint": "https://provider.example:invalid/v1/chat/completions",
                "model": "test-model",
                "api_key": "test-secret",
            }
        ):
            self.assertIsNone(configured_provider())

    def test_loopback_http_and_remote_https_providers_are_allowed(self):
        for endpoint in (
            "http://localhost:1234/v1/chat/completions",
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://[::1]:1234/v1/chat/completions",
            "https://provider.example/v1/chat/completions",
        ):
            with (
                self.subTest(endpoint=endpoint),
                override_settings(
                    NARRATIVE_AI={
                        "endpoint": endpoint,
                        "model": "test-model",
                        "api_key": "test-secret",
                    }
                ),
            ):
                self.assertIsNotNone(configured_provider())

    @override_settings(NARRATIVE_AI=None)
    def test_disabled_story_start_does_not_call_hunt_or_change_hunger(self):
        from commands.v5.hunt import CmdHunt
        from commands.v5.utils.blood_utils import get_hunger

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        caller = self.character
        caller.msg = Mock()
        hunger_before = get_hunger(caller)
        command = type("CommandStub", (), {"caller": caller, "args": "start street"})()
        with patch("commands.v5.hunt.hunt_prey") as hunt:
            CmdHunt._story_hunt(command)
        hunt.assert_not_called()
        self.assertEqual(get_hunger(caller), hunger_before)
        self.assertIn("not configured", str(caller.msg.call_args_list))

    @override_settings(
        NARRATIVE_AI={
            "endpoint": "http://localhost:1234/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-secret",
        }
    )
    def test_synchronous_generation_error_clears_session_action(self):
        from commands.v5.hunt import CmdHunt

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        caller = self.character
        caller.msg = Mock()
        command = type("CommandStub", (), {"caller": caller, "args": "x" * 2001})()
        CmdHunt._story_hunt(command)
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_action, "")
        self.assertTrue(any("limited to" in str(call) for call in caller.msg.call_args_list))

    def test_opt_out_prevents_provider_call_and_persists_no_request(self):
        class SpyProvider:
            calls = 0

            def generate(self, _messages):
                self.calls += 1
                return succeed('{"prose":"ignored","citations":[]}')

        provider = SpyProvider()
        with self.assertRaises(PermissionError):
            generate_story(self.session, "Approach the stranger.", provider, scheduler=lambda function: function())
        self.assertEqual(provider.calls, 0)
        self.assertFalse(StoryGenerationRequest.objects.exists())

    @override_settings(NARRATIVE_AI=None)
    def test_disabled_provider_sends_nothing_and_preserves_rules_outcome(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        before = dict(self.session.deterministic_outcome)
        with self.assertRaisesRegex(RuntimeError, "no story request was sent"):
            generate_story(self.session, "Continue.", scheduler=lambda function: function())
        self.session.refresh_from_db()
        self.assertEqual(self.session.deterministic_outcome, before)
        self.assertFalse(StoryGenerationRequest.objects.exists())

    def test_memory_context_is_scoped_approved_and_unexpired(self):
        def fact(text, **kwargs):
            return MemoryFact.objects.create(
                persona=self.persona, text=text, staff_entry="Staff-curated note.", **kwargs
            )

        fact("Publicly known detail", visibility=MemoryFact.Visibility.PUBLIC, status=MemoryFact.Status.APPROVED)
        fact(
            "This player's secret",
            visibility=MemoryFact.Visibility.PRIVATE,
            subject=self.character,
            status=MemoryFact.Status.APPROVED,
        )
        fact(
            "Other player's secret",
            visibility=MemoryFact.Visibility.PRIVATE,
            subject=self.other_character,
            status=MemoryFact.Status.APPROVED,
        )
        fact("Staff-only note", visibility=MemoryFact.Visibility.STAFF, status=MemoryFact.Status.APPROVED)
        fact("Unreviewed suggestion", visibility=MemoryFact.Visibility.PUBLIC, status=MemoryFact.Status.DRAFT)
        fact(
            "Expired detail",
            visibility=MemoryFact.Visibility.PUBLIC,
            status=MemoryFact.Status.APPROVED,
            expires_at=timezone.now(),
        )

        memory = authorized_memory_context(self.session)
        texts = {item["text"] for item in memory}
        self.assertEqual(texts, {"Publicly known detail", "This player's secret"})
        self.assertNotIn("Other player's secret", " ".join(item["text"] for item in memory))

    def test_persisted_request_keeps_deterministic_outcome_and_expires_action(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class StubProvider:
            def generate(self, messages):
                self.messages = messages
                return succeed(json.dumps({"prose": "A shadow passes beneath the streetlamp.", "citations": []}))

        provider = StubProvider()
        deferred = generate_story(
            self.session, "I watch from the doorway.", provider, scheduler=lambda function: function()
        )
        response = []
        deferred.addCallback(response.append)
        self.assertEqual(response[0], "A shadow passes beneath the streetlamp.")
        self.session.refresh_from_db()
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.SUCCEEDED)
        self.assertEqual(request.response, response[0])
        self.assertEqual(request.action_text, "")
        self.assertEqual(self.session.deterministic_outcome, {"hunting_success": True, "hunger_after": 2})
        self.assertIn("I watch from the doorway.", provider.messages[-1]["content"])

    def test_provider_error_is_persisted_without_secret_text(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class BrokenProvider:
            def generate(self, _messages):
                return fail(RuntimeError("provider secret=do-not-store"))

        deferred = generate_story(self.session, "Look around.", BrokenProvider(), scheduler=lambda function: function())
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertNotIn("do-not-store", request.error)
        self.assertEqual(request.action_text, "")

    def test_session_completion_expires_raw_action_text(self):
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="private action")
        self.session.complete()
        request.refresh_from_db()
        self.session.refresh_from_db()
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.action_text, "")
        self.assertEqual(self.session.current_action, "")
        self.assertEqual(self.session.status, StorySession.Status.COMPLETED)

    def test_untrusted_citation_rejects_provider_result(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class InvalidCitationProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "A voice calls.", "citations": ["not-authorized"]}))

        deferred = generate_story(
            self.session, "Listen.", InvalidCitationProvider(), scheduler=lambda function: function()
        )
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.response, "")
        self.assertEqual(request.action_text, "")

    def test_invalid_provider_json_is_persisted_as_failure(self):
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)

        class InvalidJSONProvider:
            def generate(self, _messages):
                return succeed("{not-json")

        deferred = generate_story(self.session, "Wait.", InvalidJSONProvider(), scheduler=lambda function: function())
        deferred.addErrback(lambda _failure: None)
        request = StoryGenerationRequest.objects.get(session=self.session)
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.response, "")
        self.assertEqual(request.action_text, "")

    def test_pending_request_recovers_and_persists_response(self):
        from .services import recover_pending_requests

        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        request = StoryGenerationRequest.objects.create(session=self.session, action_text="Resume me.")

        class RecoveryProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "The scene continues.", "citations": []}))

        self.assertEqual(recover_pending_requests(RecoveryProvider(), scheduler=lambda function: function()), 1)
        request.refresh_from_db()
        self.assertEqual(request.status, StoryGenerationRequest.Status.SUCCEEDED)
        self.assertEqual(request.response, "The scene continues.")


class NarrativePrivacyTests(TestCase):
    def setUp(self):
        NarrativeStoryTests.setUp(self)
        NarrativeConsent.objects.create(account=self.account, character=self.character, opted_in=True)
        self.messages = []
        self.responses = []
        self.provider = Mock(generate=self._generate)

    def _generate(self, messages):
        self.messages.append(messages)
        response = Deferred()
        self.responses.append(response)
        return response

    def _fact(self, **kwargs):
        return MemoryFact.objects.create(
            persona=self.persona,
            text="Sensitive approved detail.",
            staff_entry="Staff-curated source.",
            visibility=MemoryFact.Visibility.PUBLIC,
            status=MemoryFact.Status.APPROVED,
            **kwargs,
        )

    def _request(self, scheduler=None):
        result = generate_story(self.session, "Private player action.", self.provider, scheduler or (lambda fn: fn()))
        received = []
        result.addCallback(received.append)
        result.addErrback(lambda _failure: None)
        return received

    def _respond(self, prose="Derived sensitive prose."):
        self.responses[-1].callback(json.dumps({"prose": prose, "citations": []}))

    def test_queued_opt_out_never_sends_player_text(self):
        queued = []
        self._request(queued.append)
        set_consent(self.account, self.character, False)
        queued[0]()
        self.assertEqual(self.messages, [])
        request = StoryGenerationRequest.objects.get()
        self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
        self.assertEqual(request.error, "Consent withdrawn.")
        self.assertEqual(request.action_text, "")

    def test_queued_completion_never_sends_player_text(self):
        queued = []
        self._request(queued.append)
        self.session.complete()
        queued[0]()
        self.assertEqual(self.messages, [])

    def test_queued_terminal_request_is_not_sent_or_overwritten(self):
        queued = []
        self._request(queued.append)
        StoryGenerationRequest.objects.update(status=StoryGenerationRequest.Status.SUCCEEDED, response="Earlier result")
        queued[0]()
        self.assertEqual(self.messages, [])
        self.assertEqual(StoryGenerationRequest.objects.get().response, "Earlier result")

    def test_queued_request_retrieves_current_facts_at_dispatch(self):
        fact = self._fact()
        queued = []
        self._request(queued.append)
        fact.status = MemoryFact.Status.REDACTED
        fact.save(update_fields=("status",))
        queued[0]()
        self.assertNotIn("Sensitive approved detail.", self.messages[0][-1]["content"])
        self._respond()

    def test_queued_changed_owner_never_sends_player_text(self):
        queued = []
        self._request(queued.append)
        ObjectDB.objects.filter(pk=self.character.pk).update(db_account=self.other_account)
        queued[0]()
        self.assertEqual(self.messages, [])

    def test_inflight_terminal_request_cannot_succeed(self):
        received = self._request()
        StoryGenerationRequest.objects.update(status="failed", error="Canceled independently.", action_text="")
        self._respond()
        self.assertEqual(received, [])
        request = StoryGenerationRequest.objects.get()
        self.assertEqual(request.status, "failed")
        self.assertEqual(request.error, "Canceled independently.")

    def test_inflight_persona_edit_rejects_response(self):
        received = self._request()
        NarrativePersona.objects.filter(pk=self.persona.pk).update(profile="Changed profile.")
        self._respond()
        self.assertEqual(received, [])
        self.assertEqual(StoryGenerationRequest.objects.get().status, "failed")

    def test_recovery_queue_rechecks_opt_out_at_dispatch(self):
        from .services import recover_pending_requests

        StoryGenerationRequest.objects.create(session=self.session, action_text="Recovered private text.")
        queued = []
        self.assertEqual(recover_pending_requests(self.provider, queued.append), 1)
        set_consent(self.account, self.character, False)
        queued[0]()
        self.assertEqual(self.messages, [])

    def test_context_changes_during_message_build_never_reach_provider(self):
        from chronicle.models import ChronicleEvent

        from . import services

        event = ChronicleEvent.objects.create(
            idempotency_key="dispatch-source",
            source_app="staff",
            source_type="scene",
            source_id="dispatch",
            kind="scene.curated",
            title="Source",
            visibility="public",
            status="published",
        )
        fact = self._fact(source_event=event)
        build_messages = services._messages
        mutations = {
            "fact": lambda: MemoryFact.objects.filter(pk=fact.pk).update(status="redacted"),
            "source": lambda: ChronicleEvent.objects.filter(pk=event.pk).update(status="redacted"),
            "scene": lambda: StorySession.objects.filter(pk=self.session.pk).update(location="club"),
            "resume": lambda: StorySession.objects.filter(pk=self.session.pk).update(resume_state={"phase": "changed"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(context=name):

                def change_after_build(*args, mutate=mutate):
                    messages = build_messages(*args)
                    mutate()
                    return messages

                with patch("narrative.services._messages", side_effect=change_after_build):
                    self._request()
                self.assertEqual(self.messages, [])
                self.assertEqual(StoryGenerationRequest.objects.latest("id").status, "failed")

    def test_changed_inherited_fingerprint_cannot_be_replaced_by_new_snapshot(self):
        from . import services

        fact = self._fact()
        self._request()
        self._respond("Earlier derived prose.")
        resume_context = services._resume_context

        def change_after_resume(session):
            context = resume_context(session)
            MemoryFact.objects.filter(pk=fact.pk).update(text="Changed approved detail.")
            return context

        with patch("narrative.services._resume_context", side_effect=change_after_resume):
            received = self._request()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(received, [])
        self.assertEqual(StoryGenerationRequest.objects.latest("id").status, "failed")

    def test_uncited_inflight_fact_changes_reject_response(self):
        for changes in (
            {"status": MemoryFact.Status.REDACTED},
            {"expires_at": timezone.now()},
            {"text": "Edited fact."},
            {"staff_entry": "Changed provenance."},
            {"visibility": MemoryFact.Visibility.STAFF},
            {"visibility": MemoryFact.Visibility.PRIVATE, "subject_id": self.other_character.pk},
        ):
            with self.subTest(changes=changes):
                fact = self._fact()
                received = self._request()
                MemoryFact.objects.filter(pk=fact.pk).update(**changes)
                self._respond()
                self.assertEqual(received, [])
                request = StoryGenerationRequest.objects.latest("id")
                self.assertEqual(request.status, StoryGenerationRequest.Status.FAILED)
                self.assertEqual(request.response, "")

    def test_uncited_inflight_source_changes_reject_response(self):
        from chronicle.models import ChronicleEvent

        for field, value in (
            ("status", "redacted"),
            ("visibility", "staff"),
            ("summary", "Edited source."),
            ("payload", {"changed": True}),
            ("participants", None),
        ):
            with self.subTest(field=field):
                event = ChronicleEvent.objects.create(
                    idempotency_key=f"narrative-source-{field}",
                    source_app="staff",
                    source_type="scene",
                    source_id=field,
                    kind="scene.curated",
                    title="Source",
                    summary="Source text",
                    visibility="participants",
                    status="published",
                )
                event.participants.add(self.character)
                self._fact(source_event=event)
                received = self._request()
                if field == "participants":
                    event.participants.clear()
                else:
                    ChronicleEvent.objects.filter(pk=event.pk).update(**{field: value})
                self._respond()
                self.assertEqual(received, [])
                self.assertEqual(StoryGenerationRequest.objects.latest("id").status, "failed")

    def test_inflight_closed_or_terminal_request_cannot_succeed(self):
        received = self._request()
        self.session.complete()
        self._respond()
        self.assertEqual(received, [])
        self.assertEqual(StoryGenerationRequest.objects.get().error, "Session completed.")

    def test_legacy_resume_prose_is_omitted(self):
        self.session.resume_state["last_response"] = "Legacy sensitive prose."
        self.session.save(update_fields=("resume_state",))
        self._request()
        self.assertNotIn("Legacy sensitive prose.", self.messages[-1][-1]["content"])
        self._respond()

    def test_revoked_uncited_fact_invalidates_resume_prose(self):
        fact = self._fact()
        self._request()
        self._respond()
        MemoryFact.objects.filter(pk=fact.pk).update(status="redacted")
        self._request()
        self.assertNotIn("Derived sensitive prose.", self.messages[-1][-1]["content"])
        self.assertNotIn("Sensitive approved detail.", self.messages[-1][-1]["content"])
        self._respond("Safe continuation.")

    def test_transitive_resume_dependencies_survive_fact_retrieval_limit(self):
        original = self._fact()
        self._request()
        self._respond("First derived prose.")
        for _index in range(21):
            self._fact()
        self._request()
        self.assertIn("First derived prose.", self.messages[-1][-1]["content"])
        self._respond("Second derived prose.")
        MemoryFact.objects.filter(pk=original.pk).update(status="redacted")
        self._request()
        self.assertNotIn("Second derived prose.", self.messages[-1][-1]["content"])
        self._respond("Safe continuation.")

    def test_inflight_inherited_dependency_revocation_rejects_response(self):
        original = self._fact()
        self._request()
        self._respond("First derived prose.")
        for _index in range(21):
            self._fact()
        received = self._request()
        MemoryFact.objects.filter(pk=original.pk).update(status="redacted")
        self._respond()
        self.assertEqual(received, [])
        self.assertEqual(StoryGenerationRequest.objects.latest("id").status, "failed")


class NarrativeCommandDispatchTests(EvenniaCommandTest):
    def test_hunt_story_switch_runs_and_persists_a_normal_hunt(self):
        from commands.v5.hunt import CmdHunt

        class StubProvider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "A shadow moves.", "citations": []}))

        caller = self.char1
        caller.db.vampire = {"predator_type": "Alleycat", "hunger": 1}
        NarrativeConsent.objects.create(account=caller.account, character=caller, opted_in=True)
        outcome = {
            "hunting_success": True,
            "old_hunger": 1,
            "new_hunger": 2,
            "hunger_reduction": 1,
            "resonance": {"type": "sanguine"},
            "complications": [],
        }

        with (
            patch("narrative.services.configured_provider", return_value=StubProvider()),
            patch("narrative.services.reactor.callFromThread", side_effect=lambda callback: callback()),
            patch("commands.v5.hunt.get_predator_hunting_bonus", return_value={"bonus_dice": 1}),
            patch("commands.v5.hunt.hunt_prey", return_value=outcome) as hunt,
        ):
            output = self.call(
                CmdHunt(),
                "/story start street",
                cmdstring="+hunt",
                caller=caller,
            )

        self.assertEqual(hunt.call_count, 1, output)
        session = StorySession.objects.get(character=caller, status=StorySession.Status.ACTIVE)
        request = StoryGenerationRequest.objects.get(session=session)
        self.assertEqual(session.deterministic_outcome["hunger_after"], 2)
        self.assertEqual(request.response, "A shadow moves.")
        self.assertIn("[AI-generated narrative]", output)
