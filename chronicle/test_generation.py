import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from twisted.internet.defer import Deferred, fail

from . import generation
from .generation import recover_pending_drafts, request_draft
from .models import ChronicleEvent, ChronicleGenerationRequest
from .services import public_events, publish_event


class ChronicleGenerationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="draft-staff", password="test", is_staff=True)
        self.player = get_user_model().objects.create_user(username="draft-player", password="test")
        self.source = ChronicleEvent.objects.create(
            idempotency_key="generation-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="A public meeting",
            summary="The court gathered at midnight.",
            visibility="public",
            status="published",
        )
        self.sent = []
        self.responses = []

        test_case = self

        class Provider:
            def generate(self, messages):
                test_case.sent.append(messages)
                response = Deferred()
                test_case.responses.append(response)
                return response

        self.provider = Provider()

    def request(self, **kwargs):
        values = {
            "actor": self.staff,
            "source_ids": [str(self.source.pk)],
            "mode": "recap",
            "provider": self.provider,
            "scheduler": lambda callback: callback(),
        }
        values.update(kwargs)
        with self.captureOnCommitCallbacks(execute=True):
            return request_draft(**values)

    def respond(self, **kwargs):
        value = {"prose": "The court's midnight meeting is recalled.", "citations": [str(self.source.pk)]}
        value.update(kwargs)
        self.responses[-1].callback(json.dumps(value))

    def test_staff_required_even_with_stale_actor_permissions(self):
        with self.assertRaises(PermissionError):
            self.request(actor=self.player)
        get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False)
        with self.assertRaises(PermissionError):
            self.request()
        self.assertFalse(ChronicleGenerationRequest.objects.exists())
        self.assertEqual(len(self.sent), 0)

    def test_only_explicit_published_public_sources_are_accepted(self):
        for changes in (
            {"visibility": "participants"},
            {"visibility": "staff"},
            {"status": "draft"},
            {"status": "redacted"},
        ):
            with self.subTest(changes=changes):
                ChronicleEvent.objects.filter(pk=self.source.pk).update(
                    **{"visibility": "public", "status": "published", **changes}
                )
                with self.assertRaises(ValueError):
                    self.request()
        for ids in ([], list(range(1, 10)), ["bogus"], ["99999"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.request(source_ids=ids)
        self.assertEqual(len(self.sent), 0)

    @override_settings(NARRATIVE_AI=None)
    def test_disabled_provider_creates_no_request_and_staff_page_explains(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            self.request(provider=None)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("narrative_ops"))
        self.assertContains(response, "Narrative AI is not configured")
        self.assertFalse(ChronicleGenerationRequest.objects.exists())

    def test_success_stays_unpublished_with_attribution_and_all_source_links(self):
        second = ChronicleEvent.objects.create(
            idempotency_key="second",
            source_app="staff",
            source_type="scene",
            source_id="2",
            kind="scene.curated",
            title="A second public meeting",
            summary="The public meeting ended.",
            visibility="public",
            status="published",
        )
        request = self.request(source_ids=[self.source.pk, second.pk], mode="rumor")
        self.respond()  # Only one citation, but both supplied sources remain dependencies.
        request.refresh_from_db()
        event = request.draft_event
        self.assertEqual(request.status, "succeeded")
        self.assertEqual(event.status, "draft")
        self.assertTrue(event.ai_generated)
        self.assertCountEqual(event.source_events.all(), [self.source, second])
        self.assertEqual(request.citations, [str(self.source.pk)])
        self.assertFalse(public_events().filter(pk=event.pk).exists())
        self.assertNotIn(self.source.summary, json.dumps(request.source_fingerprints))
        publish_event(event.pk, self.staff)
        self.assertTrue(public_events().filter(pk=event.pk).exists())

    def test_invalid_json_contract_or_citations_never_create_draft(self):
        invalid = [
            "{not-json",
            {"prose": "Text", "citations": []},
            {"prose": "Text", "citations": ["999999"]},
            {"prose": "Text", "citations": [str(self.source.pk)] * 2},
            {"prose": "Text", "citations": [self.source.pk]},
            {"prose": "", "citations": [str(self.source.pk)]},
            {"prose": "Text", "citations": [str(self.source.pk)], "tools": []},
        ]
        for value in invalid:
            with self.subTest(case=str(type(value))):
                request = self.request()
                self.responses[-1].callback(value if isinstance(value, str) else json.dumps(value))
                request.refresh_from_db()
                self.assertEqual(request.status, "failed")
                self.assertIsNone(request.draft_event)
        self.assertEqual(ChronicleEvent.objects.count(), 1)

    def test_provider_errors_do_not_persist_secrets_or_prompt(self):
        class BrokenProvider:
            def generate(self, _messages):
                return fail(RuntimeError("secret=do-not-store full prompt"))

        request = self.request(provider=BrokenProvider())
        request.refresh_from_db()
        self.assertEqual(request.status, "failed")
        self.assertNotIn("do-not-store", request.error)
        self.assertIsNone(request.draft_event)

    def test_queued_permission_or_source_revocation_prevents_dispatch(self):
        for revoke in ("actor", "source"):
            with self.subTest(revoke=revoke):
                queued = []
                request = self.request(scheduler=queued.append)
                if revoke == "actor":
                    get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False)
                else:
                    ChronicleEvent.objects.filter(pk=self.source.pk).update(status="redacted")
                queued[0]()
                request.refresh_from_db()
                self.assertEqual(request.status, "failed")
                self.assertEqual(len(self.sent), 0)
                get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=True)

    def test_edit_during_prompt_assembly_prevents_dispatch(self):
        build_messages = generation._messages

        def edit_source(*args):
            messages = build_messages(*args)
            ChronicleEvent.objects.filter(pk=self.source.pk).update(summary="Changed source.")
            return messages

        with patch("chronicle.generation._messages", side_effect=edit_source):
            request = self.request()
        request.refresh_from_db()
        self.assertEqual(request.status, "failed")
        self.assertEqual(len(self.sent), 0)

    def test_inflight_uncited_source_changes_or_actor_revocation_reject_result(self):
        for change in ("source", "actor"):
            with self.subTest(change=change):
                request = self.request()
                if change == "source":
                    ChronicleEvent.objects.filter(pk=self.source.pk).update(summary="Edited source.")
                else:
                    get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False)
                self.respond()
                request.refresh_from_db()
                self.assertEqual(request.status, "failed")
                self.assertIsNone(request.draft_event)
                get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=True)

    def test_duplicate_submission_dispatch_and_callback_are_idempotent(self):
        key = uuid4()
        queued = []
        request = self.request(request_key=key, scheduler=queued.append)
        duplicate = self.request(request_key=key, scheduler=queued.append)
        self.assertEqual(request.pk, duplicate.pk)
        self.assertEqual(len(queued), 1)
        queued[0]()
        queued[0]()
        self.assertEqual(len(self.sent), 1)
        self.respond()
        generation._accept(request.pk, {"prose": "Duplicate", "citations": [str(self.source.pk)]})
        self.assertEqual(ChronicleEvent.objects.filter(ai_generated=True).count(), 1)
        with self.assertRaises(ValueError):
            self.request(request_key=key, mode="rumor")

    def test_recovery_resumes_unsent_and_fails_interrupted_without_retry(self):
        queued = []
        unsent = self.request(scheduler=queued.append)
        interrupted = self.request()
        self.assertEqual(recover_pending_drafts(self.provider, lambda callback: callback()), 1)
        interrupted.refresh_from_db()
        self.assertEqual(interrupted.status, "failed")
        self.assertEqual(len(self.sent), 2)
        self.respond()
        unsent.refresh_from_db()
        self.assertEqual(unsent.status, "succeeded")
        queued[0]()
        self.assertEqual(len(self.sent), 2)

    def test_recovery_rechecks_authorization_at_actual_dispatch(self):
        self.request(scheduler=lambda _callback: None)
        queued = []
        self.assertEqual(recover_pending_drafts(self.provider, queued.append), 1)
        get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False)
        queued[0]()
        self.assertEqual(len(self.sent), 0)
        self.assertEqual(ChronicleGenerationRequest.objects.get().status, "failed")

    def test_revoked_ancestor_rejects_generated_source_and_publication(self):
        request = self.request()
        self.respond()
        request.refresh_from_db()
        publish_event(request.draft_event_id, self.staff)
        followup = self.request(source_ids=[request.draft_event_id])
        ChronicleEvent.objects.filter(pk=self.source.pk).update(status="redacted")
        self.responses[-1].callback(json.dumps({"prose": "Followup", "citations": [str(request.draft_event_id)]}))
        followup.refresh_from_db()
        self.assertEqual(followup.status, "failed")
        with self.assertRaises(ValueError):
            self.request(source_ids=[request.draft_event_id])

    def test_source_revocation_after_generation_blocks_staff_publication(self):
        request = self.request()
        self.respond()
        request.refresh_from_db()
        ChronicleEvent.objects.filter(pk=self.source.pk).update(status="redacted")
        with self.assertRaises(ValueError):
            publish_event(request.draft_event_id, self.staff)
        request.draft_event.refresh_from_db()
        self.assertEqual(request.draft_event.status, "draft")

    def test_staff_form_permissions_post_only_and_full_review_flow(self):
        url = reverse("narrative_ops_generate")
        self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.player)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)
        with (
            patch("chronicle.generation.configured_provider", return_value=self.provider),
            patch("chronicle.generation.reactor.callFromThread", side_effect=lambda callback: callback()),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                url, {"mode": "recap", "source_ids": [self.source.pk], "request_key": str(uuid4())}
            )
        self.assertEqual(response.status_code, 302)
        self.respond()
        request = ChronicleGenerationRequest.objects.get()
        page = self.client.get(reverse("narrative_ops"), {"source": self.source.pk})
        self.assertContains(page, "AI-generated draft")
        self.assertContains(page, f"Review draft #{request.draft_event_id}")
        self.assertContains(page, self.source.summary)
        self.assertFalse(public_events().filter(pk=request.draft_event_id).exists())
        response = self.client.post(reverse("narrative_ops_action", args=(request.draft_event_id, "publish")))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(public_events().filter(pk=request.draft_event_id).exists())
