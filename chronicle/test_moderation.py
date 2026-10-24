"""Versioned correction moderation, using only disposable test databases."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from evennia.objects.models import ObjectDB
from twisted.internet.defer import Deferred, succeed

from narrative.models import MemoryFact, NarrativeConsent, NarrativePersona, StoryGenerationRequest, StorySession
from narrative.services import authorized_memory_context, generate_story
from traits.models import CharacterBio

from . import generation, services
from .models import ChronicleEvent


def moderation_fixture(prefix):
    staff = get_user_model().objects.create_user(username=f"{prefix}-builder", is_staff=False)
    staff.permissions.add("Builder")
    original = ChronicleEvent.objects.create(
        idempotency_key=f"{prefix}-original",
        source_app="staff",
        source_type="scene",
        source_id="1",
        kind="scene.curated",
        title="Original scene",
        summary="Original reviewed prose.",
        payload={},
        status="published",
        visibility="public",
    )
    return staff, original


class CorrectionDraftLifecycleTests(TestCase):
    def setUp(self):
        self.staff, self.original = moderation_fixture("moderation")

    def begin(self):
        return services.begin_correction(self.original.pk, self.staff)

    def test_compatibility_double_correction_returns_existing_without_overwrite(self):
        first = services.correct_event(
            self.original.pk, self.staff, title="First correction", summary="First correction prose.", payload={}
        )
        second = services.correct_event(
            self.original.pk, self.staff, title="Duplicate form title", summary="Duplicate form prose.", payload={}
        )
        self.assertEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual((first.title, first.summary), ("First correction", "First correction prose."))
        self.assertEqual(self.original.corrections.filter(status="draft").count(), 1)

    def test_double_begin_returns_one_active_draft(self):
        first, second = self.begin(), self.begin()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual((first.title, first.summary), (self.original.title, self.original.summary))
        self.assertEqual(first.supersedes_version, 1)

    def test_begin_authority_read_lock_is_reported_as_moderation_conflict(self):
        with (
            patch("chronicle.services._require_staff", side_effect=OperationalError("database is locked")),
            self.assertRaisesRegex(ValueError, "changed|reload|review"),
        ):
            self.begin()
        self.assertEqual(self.original.corrections.count(), 0)

    def test_edit_creates_replacement_and_preserves_immutable_history_and_links(self):
        participant = ObjectDB.objects.create(db_key="CorrectionParticipant")
        source = ChronicleEvent.objects.create(
            idempotency_key="correction-source",
            source_app="staff",
            source_type="scene",
            source_id="2",
            kind="scene.curated",
            title="Upstream source",
            status="published",
            visibility="public",
        )
        self.original.participants.add(participant)
        self.original.source_events.add(source)
        first = self.begin()
        replacement = services.revise_correction(
            first.pk, self.staff, 1, {"title": "Edited correction", "summary": "New prose.", "payload": {}}
        )
        first.refresh_from_db()
        self.assertEqual(
            (first.status, first.title, first.summary), ("discarded", "Original scene", "Original reviewed prose.")
        )
        self.assertEqual(first.discarded_by_id, self.staff.pk)
        self.assertIsNotNone(first.discarded_at)
        self.assertEqual(replacement.revision_of_id, first.pk)
        self.assertEqual(
            (replacement.status, replacement.version, replacement.title), ("draft", 2, "Edited correction")
        )
        self.assertCountEqual(replacement.participants.all(), [participant])
        self.assertCountEqual(replacement.source_events.all(), [source])
        self.original.refresh_from_db()
        self.assertEqual((self.original.status, self.original.summary), ("published", "Original reviewed prose."))

    def test_discard_allows_new_draft_without_losing_old_history(self):
        first = self.begin()
        services.discard_correction(first.pk, self.staff, 1)
        second = self.begin()
        first.refresh_from_db()
        self.assertEqual((first.status, first.summary), ("discarded", "Original reviewed prose."))
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.revision_of_id, first.pk)
        self.assertEqual(self.original.corrections.count(), 2)
        self.assertEqual(self.original.corrections.filter(status="draft").count(), 1)

    def test_stale_edit_and_publication_cannot_approve_replacement_text(self):
        first = self.begin()
        replacement = services.revise_correction(first.pk, self.staff, 1, {"summary": "Replacement requiring review."})
        with self.assertRaisesRegex(ValueError, "changed|reload|review"):
            services.revise_correction(first.pk, self.staff, 1, {"summary": "Stale overwrite."})
        with self.assertRaisesRegex(ValueError, "changed|reload|review"):
            services.publish_event(first.pk, self.staff, expected_version=1)
        with self.assertRaisesRegex(ValueError, "changed|reload|review"):
            services.publish_event(replacement.pk, self.staff, expected_version=1)
        replacement.refresh_from_db()
        self.assertEqual((replacement.status, replacement.summary), ("draft", "Replacement requiring review."))

    def test_publication_supersedes_only_expected_original_version(self):
        draft = self.begin()
        ChronicleEvent.objects.filter(pk=self.original.pk).update(version=2)
        with self.assertRaisesRegex(ValueError, "changed|reload|review"):
            services.publish_event(draft.pk, self.staff, expected_version=1)
        self.original.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual((self.original.status, draft.status), ("published", "draft"))

    def test_redacted_or_superseded_original_cannot_be_replaced_by_old_draft(self):
        for status in ("redacted", "superseded"):
            with self.subTest(status=status):
                draft = self.begin()
                ChronicleEvent.objects.filter(pk=self.original.pk).update(status=status)
                with self.assertRaisesRegex(ValueError, "changed|reload|review"):
                    services.publish_event(draft.pk, self.staff, expected_version=draft.version)
                draft.refresh_from_db()
                self.assertEqual(draft.status, "draft")
                services.discard_correction(draft.pk, self.staff, draft.version)
                ChronicleEvent.objects.filter(pk=self.original.pk).update(status="published")

    def test_reviewed_replacement_publishes_once_and_preserves_prior_history(self):
        first = self.begin()
        draft = services.revise_correction(first.pk, self.staff, 1, {"summary": "Reviewed revised prose."})
        published = services.publish_event(draft.pk, self.staff, expected_version=2)
        self.original.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(
            (self.original.status, published.status, first.status), ("superseded", "published", "discarded")
        )
        self.assertEqual(published.version, 3)
        with self.assertRaisesRegex(ValueError, "changed|reload|review"):
            services.publish_event(draft.pk, self.staff, expected_version=2)
        self.assertQuerySetEqual(services.public_events(), [published])

    def test_revision_rejects_scope_or_payload_expansion_and_keeps_active_draft(self):
        draft = self.begin()
        for changes in ({"visibility": "public"}, {"payload": {"private_note": "must not copy"}}, {"title": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                services.revise_correction(draft.pk, self.staff, 1, changes)
            draft.refresh_from_db()
            self.assertEqual((draft.status, draft.version), ("draft", 1))

    def test_builder_authority_is_reloaded_before_moderation(self):
        draft = self.begin()
        self.assertTrue(self.staff.permissions.has("Builder"))
        self.staff.db_tags.through.objects.filter(accountdb_id=self.staff.pk, tag__db_tagtype="permission").delete()
        for action in (
            lambda: self.begin(),
            lambda: services.revise_correction(draft.pk, self.staff, 1, {"summary": "Unauthorized"}),
            lambda: services.discard_correction(draft.pk, self.staff, 1),
            lambda: services.publish_event(draft.pk, self.staff, expected_version=1),
        ):
            with self.assertRaises(PermissionError):
                action()
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.version), ("draft", 1))


class CorrectionWebControlsTests(TestCase):
    def setUp(self):
        self.staff, self.original = moderation_fixture("moderation-web")
        self.client.force_login(self.staff)

    def test_begin_resume_edit_and_separate_publication_use_reviewed_versions(self):
        response = self.client.post(reverse("narrative_ops_action", args=(self.original.pk, "begin-correction")))
        self.assertEqual(response.status_code, 302)
        first = self.original.corrections.get(status="draft")
        self.assertIn(f"draft={first.pk}", response["Location"])
        review = self.client.get(reverse("narrative_ops"), {"draft": first.pk})
        self.assertContains(review, f"Correction draft #{first.pk}")
        self.assertContains(review, "version 1")
        self.assertContains(review, 'name="expected_version" value="1"')
        response = self.client.post(
            reverse("narrative_ops_correction_action", args=(first.pk, "revise")),
            {"expected_version": "1", "title": "Edited via web", "summary": "Needs fresh review.", "payload": "{}"},
        )
        self.assertEqual(response.status_code, 302)
        replacement = self.original.corrections.get(status="draft")
        self.assertNotEqual(first.pk, replacement.pk)
        self.assertIn(f"draft={replacement.pk}", response["Location"])
        self.assertEqual(
            self.client.post(
                reverse("narrative_ops_action", args=(first.pk, "publish")), {"expected_version": "1"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                reverse("narrative_ops_action", args=(replacement.pk, "publish")), {"expected_version": "1"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                reverse("narrative_ops_action", args=(replacement.pk, "publish")), {"expected_version": "2"}
            ).status_code,
            302,
        )
        replacement.refresh_from_db()
        self.assertEqual(replacement.status, "published")

    def test_discard_is_discoverable_and_history_can_be_resumed(self):
        draft = services.begin_correction(self.original.pk, self.staff)
        review = self.client.get(reverse("narrative_ops"), {"draft": draft.pk})
        self.assertContains(review, "Discard correction draft")
        self.assertContains(review, reverse("narrative_ops_correction_action", args=(draft.pk, "discard")))
        response = self.client.post(
            reverse("narrative_ops_correction_action", args=(draft.pk, "discard")), {"expected_version": "1"}
        )
        self.assertEqual(response.status_code, 302)
        history = self.client.get(reverse("narrative_ops"), {"source": self.original.pk})
        self.assertContains(history, "Correction history")
        self.assertContains(history, "discarded")
        self.assertContains(history, "Original reviewed prose.")
        self.assertContains(history, "Begin correction draft")

    def test_missing_revision_token_and_stale_discard_return_conflict(self):
        draft = services.begin_correction(self.original.pk, self.staff)
        url = reverse("narrative_ops_correction_action", args=(draft.pk, "discard"))
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertEqual(self.client.post(url, {"expected_version": "2"}).status_code, 409)
        self.assertEqual(self.client.get(url).status_code, 405)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")

    def test_non_builder_cannot_edit_or_discard_corrections(self):
        draft = services.begin_correction(self.original.pk, self.staff)
        player = get_user_model().objects.create_user(username="moderation-web-player", is_staff=True)
        self.client.force_login(player)
        for action in ("revise", "discard"):
            response = self.client.post(
                reverse("narrative_ops_correction_action", args=(draft.pk, action)),
                {"expected_version": "1", "title": "Denied", "summary": "Denied", "payload": "{}"},
            )
            self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.summary), ("draft", "Original reviewed prose."))

    def test_non_object_revision_payload_returns_400_without_changing_draft_or_history(self):
        draft = services.begin_correction(self.original.pk, self.staff)
        before = list(self.original.corrections.order_by("pk").values())
        url = reverse("narrative_ops_correction_action", args=(draft.pk, "revise"))
        for payload in ("[]", "null", "17", '"text"', "true"):
            with self.subTest(payload=payload):
                response = self.client.post(
                    url,
                    {
                        "expected_version": "1",
                        "title": "Unaccepted edit",
                        "summary": "Unaccepted prose.",
                        "payload": payload,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "JSON object", status_code=400)
                self.assertEqual(list(self.original.corrections.order_by("pk").values()), before)
                draft.refresh_from_db()
                self.assertEqual((draft.status, draft.version, draft.summary), ("draft", 1, "Original reviewed prose."))


class CorrectionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.staff, self.original = moderation_fixture("moderation-concurrent")

    def run_concurrently(self, *actions):
        barrier = Barrier(len(actions))

        def run(action):
            try:
                barrier.wait(timeout=5)
                try:
                    return action()
                except ValueError:
                    return None  # A clear moderation conflict is a supported losing result.
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(run, action) for action in actions]
            return [future.result(timeout=10) for future in futures]

    def test_concurrent_begin_returns_existing_or_clear_conflict_without_integrity_error(self):
        results = self.run_concurrently(
            lambda: services.begin_correction(self.original.pk, self.staff),
            lambda: services.begin_correction(self.original.pk, self.staff),
        )
        active = self.original.corrections.get(status="draft")
        self.assertTrue(any(result is not None for result in results))
        self.assertTrue(all(result is None or result.pk == active.pk for result in results))

    def test_concurrent_revisions_keep_one_active_replacement(self):
        first = services.begin_correction(self.original.pk, self.staff)
        results = self.run_concurrently(
            lambda: services.revise_correction(first.pk, self.staff, 1, {"title": "First replacement"}),
            lambda: services.revise_correction(first.pk, self.staff, 1, {"title": "Second replacement"}),
        )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.original.corrections.filter(status="draft").count(), 1)
        first.refresh_from_db()
        self.assertEqual((first.status, first.summary), ("discarded", "Original reviewed prose."))

    def test_publish_and_redact_cannot_resurrect_original_from_stale_snapshot(self):
        draft = services.begin_correction(self.original.pk, self.staff)
        results = self.run_concurrently(
            lambda: services.publish_event(draft.pk, self.staff, expected_version=1),
            lambda: services.redact_event(self.original.pk, self.staff, expected_version=1),
        )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.original.refresh_from_db()
        draft.refresh_from_db()
        if self.original.status == "redacted":
            self.assertEqual((draft.status, draft.title, draft.summary), ("redacted", "", ""))
        else:
            self.assertEqual((self.original.status, draft.status), ("superseded", "published"))


class CorrectionMigrationTests(TransactionTestCase):
    def test_existing_published_draft_and_redacted_correction_links_survive(self):
        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("chronicle", "0003_durable_dispatch_claims")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            events = old_apps.get_model("chronicle", "ChronicleEvent")
            rows = []
            for correction_status in ("published", "draft", "redacted"):
                original = events.objects.create(
                    idempotency_key=f"legacy-original-{correction_status}",
                    source_app="staff",
                    source_type="scene",
                    source_id=correction_status,
                    kind="scene.curated",
                    title="Historic original",
                    summary="Historic source prose.",
                    status="superseded" if correction_status == "published" else "published",
                )
                correction = events.objects.create(
                    idempotency_key=f"legacy-correction-{correction_status}",
                    source_app="staff",
                    source_type="scene",
                    source_id=correction_status,
                    kind="scene.curated",
                    title="Historic correction",
                    summary="Historic correction prose.",
                    status=correction_status,
                    supersedes_id=original.pk,
                )
                correction.source_events.add(original)
                rows.append((original.pk, correction.pk, correction_status))
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            current = executor.loader.project_state(final_targets).apps.get_model("chronicle", "ChronicleEvent")
            for original_id, correction_id, status in rows:
                correction = current.objects.get(pk=correction_id)
                self.assertEqual(
                    (correction.supersedes_id, correction.status, correction.summary),
                    (original_id, status, "Historic correction prose."),
                )
                self.assertEqual((correction.version, correction.supersedes_version), (1, 1))
                self.assertEqual(current.objects.get(pk=original_id).corrections.get().pk, correction_id)
                self.assertEqual(list(correction.source_events.values_list("pk", flat=True)), [original_id])
            with self.assertRaises(IntegrityError), transaction.atomic():
                current.objects.create(
                    idempotency_key="duplicate-legacy-active",
                    source_app="staff",
                    source_type="scene",
                    source_id="1",
                    kind="scene.curated",
                    supersedes_id=rows[1][0],
                    status="draft",
                )
        finally:
            MigrationExecutor(connection).migrate(final_targets)


class DependentWithdrawalTests(TestCase):
    def setUp(self):
        self.staff, self.a = moderation_fixture("withdrawal")
        self.owner = get_user_model().objects.create_user(username="withdrawal-player")
        self.other = get_user_model().objects.create_user(username="withdrawal-other")
        self.character = ObjectDB.objects.create(
            db_key="WithdrawalPlayer", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=self.character, account=self.owner)
        self.b = self.event("recap-b", sources=(self.a,))
        self.c = self.event("recap-c", sources=(self.b,))

    def event(self, key, *, sources=(), **changes):
        values = {
            "source_app": "staff",
            "source_type": "scene",
            "source_id": key,
            "kind": "scene.curated",
            "title": key,
            "summary": f"Sensitive prose for {key}.",
            "status": "published",
            "visibility": "public",
        }
        values.update(changes)
        event = ChronicleEvent.objects.create(idempotency_key="withdrawal-" + key, **values)
        event.source_events.set(sources)
        return event

    def test_redaction_withdraws_transitive_recaps_but_retains_their_prose(self):
        unrelated = self.event("unrelated")
        services.redact_event(self.a.pk, self.staff)
        for event in (self.b, self.c):
            event.refresh_from_db()
            self.assertEqual(event.status, "withdrawn")
            self.assertTrue(event.summary.startswith("Sensitive prose"))
            self.assertEqual(event.withdrawn_by_id, self.staff.pk)
            self.assertIsNotNone(event.withdrawn_at)
            self.assertTrue(event.withdrawal_reason)
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.title, self.a.summary, self.a.payload), ("redacted", "", "", {}))
        self.assertQuerySetEqual(services.public_events(), [unrelated])

    def test_shared_ancestors_and_cycles_are_bounded_and_withdraw_once(self):
        shared = self.event("shared", sources=(self.a, self.b))
        self.b.source_events.add(shared)
        self.assertFalse(services.event_available(self.b, "public"))
        report = services.withdraw_dependents([self.a.pk], self.staff, "source_redacted")
        self.assertCountEqual(report["withdrawn_ids"], [self.b.pk, self.c.pk, shared.pk])
        before = list(ChronicleEvent.objects.order_by("pk").values())
        repeated = services.withdraw_dependents([self.a.pk], self.staff, "source_redacted")
        self.assertEqual(repeated["withdrawn_ids"], [])
        self.assertEqual(list(ChronicleEvent.objects.order_by("pk").values()), before)

    def test_correction_publication_withdraws_old_derivatives_and_keeps_new_correction_available(self):
        correction = services.begin_correction(self.a.pk, self.staff)
        services.publish_event(correction.pk, self.staff, expected_version=correction.version)
        correction.refresh_from_db()
        self.assertTrue(services.event_available(correction, "public"))
        for event in (self.b, self.c):
            event.refresh_from_db()
            self.assertEqual(event.status, "withdrawn")
        ChronicleEvent.objects.filter(pk=self.a.pk).update(status="published")
        self.assertFalse(services.event_available(self.b, "public"))
        with self.assertRaises(ValueError):
            services.publish_event(self.b.pk, self.staff, expected_version=self.b.version)

    def test_generated_correction_inherits_sources_without_requiring_superseded_original_as_prompt(self):
        source = self.a

        class Provider:
            def generate(self, _messages):
                return succeed(json.dumps({"prose": "Generated retained recap.", "citations": [str(source.pk)]}))

        with self.captureOnCommitCallbacks(execute=True):
            request = generation.request_draft(
                self.staff, [self.a.pk], "recap", provider=Provider(), scheduler=lambda callback: callback()
            )
        request.refresh_from_db()
        services.publish_event(request.draft_event_id, self.staff)
        correction = services.begin_correction(request.draft_event_id, self.staff)
        services.publish_event(correction.pk, self.staff, expected_version=correction.version)
        self.assertTrue(services.event_available(correction, "public"))
        services.redact_event(self.a.pk, self.staff)
        correction.refresh_from_db()
        self.assertEqual((correction.status, correction.summary), ("withdrawn", "Generated retained recap."))

    def test_target_and_copied_revision_history_are_erased_while_derivative_prose_is_retained(self):
        first = services.begin_correction(self.a.pk, self.staff)
        replacement = services.revise_correction(
            first.pk, self.staff, first.version, {"summary": "Copied edited prose."}
        )
        services.redact_event(self.a.pk, self.staff)
        for event in (self.a, first, replacement):
            event.refresh_from_db()
            self.assertEqual((event.status, event.title, event.summary, event.payload), ("redacted", "", "", {}))
        self.assertEqual(replacement.revision_of_id, first.pk)
        self.b.refresh_from_db()
        self.assertEqual((self.b.status, self.b.summary), ("withdrawn", "Sensitive prose for recap-b."))

    def test_source_backed_memory_and_warmed_event_recheck_transitive_availability(self):
        npc = ObjectDB.objects.create(db_key="WithdrawalNPC", db_typeclass_path="typeclasses.characters.Character")
        persona = NarrativePersona.objects.create(character=npc)
        MemoryFact.objects.create(
            persona=persona,
            source_event=self.b,
            text="Source-backed sensitive memory.",
            status="approved",
            visibility="public",
        )
        session = StorySession.objects.create(character=self.character, persona=persona)
        self.assertEqual(len(authorized_memory_context(session)), 1)
        warmed = ChronicleEvent.objects.prefetch_related("source_events").get(pk=self.b.pk)
        ChronicleEvent.objects.filter(pk=self.a.pk).update(status="redacted")
        self.assertEqual(authorized_memory_context(session), [])
        self.assertFalse(services.event_available(warmed, "public"))
        self.assertFalse(services.public_events().filter(pk__in=[self.b.pk, self.c.pk]).exists())

    def test_inflight_generation_cannot_publish_after_source_withdrawal(self):
        pending = Deferred()

        class Provider:
            def generate(self, _messages):
                return pending

        with self.captureOnCommitCallbacks(execute=True):
            request = generation.request_draft(
                self.staff, [self.b.pk], "recap", provider=Provider(), scheduler=lambda callback: callback()
            )
        services.redact_event(self.a.pk, self.staff)
        pending.callback(json.dumps({"prose": "Late unsafe output", "citations": [str(self.b.pk)]}))
        request.refresh_from_db()
        self.assertEqual(request.status, "failed")
        self.assertIsNone(request.draft_event_id)

    def test_inflight_story_cannot_accept_memory_from_withdrawn_ancestor(self):
        npc = ObjectDB.objects.create(db_key="WithdrawalStoryNPC", db_typeclass_path="typeclasses.characters.Character")
        fact = MemoryFact.objects.create(
            persona=NarrativePersona.objects.create(character=npc),
            source_event=self.b,
            text="Private source-backed memory.",
            status="approved",
            visibility="public",
        )
        session = StorySession.objects.create(
            character=self.character, persona=fact.persona, deterministic_outcome={"hunger_after": 2}
        )
        NarrativeConsent.objects.create(account=self.owner, character=self.character, opted_in=True)
        pending = Deferred()

        class Provider:
            def generate(self, _messages):
                return pending

        result = generate_story(session, "Private action", Provider(), lambda callback: callback())
        errors = []
        result.addErrback(errors.append)
        services.redact_event(self.a.pk, self.staff)
        pending.callback(json.dumps({"prose": "Late unsafe story", "citations": [str(fact.pk)]}))
        self.assertEqual(len(errors), 1)
        request = StoryGenerationRequest.objects.get(session=session)
        self.assertEqual((request.status, request.response, request.action_text), ("failed", "", ""))
        session.refresh_from_db()
        self.assertEqual(session.deterministic_outcome, {"hunger_after": 2})

    def test_unknown_generated_lineage_private_sources_and_cycles_fail_closed(self):
        unknown = self.event("unknown-ai", ai_generated=True)
        private = self.event("staff-source", visibility="staff")
        cross_scope = self.event("cross-scope", sources=(private,))
        cyclic = self.event("self-cycle")
        cyclic.source_events.add(cyclic)
        for event in (unknown, cross_scope, cyclic):
            with self.subTest(event=event.pk):
                self.assertFalse(services.event_available(event, "public"))
                self.assertFalse(services.public_events().filter(pk=event.pk).exists())

    def test_withdrawn_review_queue_is_staff_only_and_does_not_offer_automatic_restore(self):
        services.redact_event(self.a.pk, self.staff)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("narrative_ops"))
        self.assertContains(response, "Withdrawn Chronicle review")
        self.assertContains(response, "Sensitive prose for recap-b.")
        self.assertContains(response, "new valid draft")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("narrative_ops")).status_code, 302)
        self.assertNotContains(self.client.get(reverse("chronicle_public")), "Sensitive prose for recap-b.")

    def test_generated_copy_cannot_drop_its_historical_provenance_requirement(self):
        unknown = self.event("unbound-generated-history", ai_generated=True, status="superseded", sources=(self.a,))
        copy = self.event("declassified-copy", supersedes=unknown, ai_generated=False, sources=(self.a,))
        self.assertFalse(services.event_available(copy, "public"))
        ChronicleEvent.objects.filter(pk=unknown.pk).update(status="published")
        copy.status, copy.supersedes_version = "draft", unknown.version
        copy.save(update_fields=("status", "supersedes_version"))
        with self.assertRaises(ValueError):
            services.publish_event(copy.pk, self.staff)
        copy.refresh_from_db()
        self.assertEqual(copy.status, "draft")


class WithdrawalLineageMigrationTests(TransactionTestCase):
    def test_manual_legacy_copy_with_redacted_original_is_withdrawn(self):
        before = [("chronicle", "0004_correction_draft_lifecycle")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            events = executor.loader.project_state(before).apps.get_model("chronicle", "ChronicleEvent")
            fields = {
                "source_app": "staff",
                "source_type": "scene",
                "source_id": "1",
                "kind": "scene.curated",
                "visibility": "public",
            }
            original = events.objects.create(
                idempotency_key="redacted-copy-original", status="redacted", title="", summary="", **fields
            )
            copy = events.objects.create(
                idempotency_key="redacted-copy",
                status="published",
                title="Copied title",
                summary="Retained legacy copy",
                supersedes_id=original.pk,
                **fields,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            current = executor.loader.project_state(final_targets).apps.get_model("chronicle", "ChronicleEvent")
            row = current.objects.get(pk=copy.pk)
            self.assertEqual(
                (row.status, row.summary, row.supersedes_id), ("withdrawn", "Retained legacy copy", original.pk)
            )
            self.assertEqual(row.withdrawal_reason, "legacy_source_unavailable")
        finally:
            MigrationExecutor(connection).migrate(final_targets)

    def test_manual_legacy_descendants_of_redacted_sources_are_withdrawn_idempotently(self):
        from importlib import import_module

        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("chronicle", "0004_correction_draft_lifecycle")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            events = executor.loader.project_state(before).apps.get_model("chronicle", "ChronicleEvent")

            def event(key, **changes):
                fields = {
                    "idempotency_key": key,
                    "source_app": "staff",
                    "source_type": "scene",
                    "source_id": key,
                    "kind": "scene.curated",
                    "title": key,
                    "summary": "Retained " + key,
                    "status": "published",
                    "visibility": "public",
                    "ai_generated": False,
                }
                fields.update(changes)
                return events.objects.create(**fields)

            source = event("manual-redacted-a", status="redacted", title="", summary="")
            b = event("manual-derived-b")
            b.source_events.add(source)
            c = event("manual-derived-c", status="draft")
            c.source_events.add(b)
            valid_original = event("manual-valid-original", status="superseded")
            valid_correction = event("manual-valid-correction", supersedes_id=valid_original.pk, supersedes_version=1)
            valid_correction.source_events.add(valid_original)
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            apps = executor.loader.project_state(final_targets).apps
            current = apps.get_model("chronicle", "ChronicleEvent")
            for pk, original_source in ((b.pk, source.pk), (c.pk, b.pk)):
                row = current.objects.get(pk=pk)
                self.assertEqual(row.status, "withdrawn")
                self.assertTrue(row.withdrawal_reason)
                self.assertIsNotNone(row.withdrawn_at)
                self.assertEqual(row.summary, "Retained " + row.idempotency_key)
                self.assertEqual(set(row.source_events.values_list("pk", flat=True)), {original_source})
            self.assertEqual(current.objects.get(pk=valid_correction.pk).status, "published")
            self.assertEqual(current.objects.get(pk=valid_original.pk).status, "superseded")
            snapshot = list(current.objects.order_by("pk").values())
            links = list(current.source_events.through.objects.order_by("pk").values())
            with connection.schema_editor() as schema:
                import_module("chronicle.migrations._lineage_repair").repair_lineage(apps, schema)
            self.assertEqual(list(current.objects.order_by("pk").values()), snapshot)
            self.assertEqual(list(current.source_events.through.objects.order_by("pk").values()), links)
        finally:
            MigrationExecutor(connection).migrate(final_targets)

    def test_legacy_correction_cannot_drop_generated_ancestor_proof(self):
        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("chronicle", "0004_correction_draft_lifecycle")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            events = executor.loader.project_state(before).apps.get_model("chronicle", "ChronicleEvent")
            fields = {
                "source_app": "legacy",
                "source_type": "scene",
                "source_id": "1",
                "kind": "scene.curated",
                "visibility": "public",
                "title": "Legacy generated history",
                "summary": "Preserved copy prose.",
            }
            original = events.objects.create(
                idempotency_key="legacy-no-proof", ai_generated=True, status="superseded", **fields
            )
            copy = events.objects.create(
                idempotency_key="legacy-dropped-flag",
                ai_generated=False,
                status="published",
                supersedes_id=original.pk,
                **fields,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            current = executor.loader.project_state(final_targets).apps.get_model("chronicle", "ChronicleEvent")
            row = current.objects.get(pk=copy.pk)
            self.assertEqual(
                (row.status, row.lineage_status, row.summary), ("withdrawn", "unknown", "Preserved copy prose.")
            )
            self.assertEqual(current.objects.get(pk=original.pk).status, "superseded")
        finally:
            MigrationExecutor(connection).migrate(final_targets)

    def test_populated_legacy_lineage_repair_is_idempotent_and_preserves_proofs_and_history(self):
        from importlib import import_module

        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("chronicle", "0004_correction_draft_lifecycle")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            old = executor.loader.project_state(before).apps
            events_model, requests_model = (
                old.get_model("chronicle", "ChronicleEvent"),
                old.get_model("chronicle", "ChronicleGenerationRequest"),
            )

            def event(key, **fields):
                values = {
                    "idempotency_key": key,
                    "source_app": "staff",
                    "source_type": "scene",
                    "source_id": key,
                    "kind": "scene.curated",
                    "visibility": "public",
                    "status": "published",
                    "title": key,
                    "summary": "Preserved " + key,
                }
                values.update(fields)
                return events_model.objects.create(**values)

            a = event("legacy-a")
            b = event("legacy-b", ai_generated=True, status="superseded")
            correction = event("legacy-b-correction", ai_generated=True, supersedes_id=b.pk, supersedes_version=1)
            request = requests_model.objects.create(
                mode="recap", status="succeeded", source_ids=[str(a.pk)], source_fingerprints={}, draft_event=b
            )
            erased = event("legacy-erased", status="redacted", title="", summary="")
            stale = event("legacy-stale", ai_generated=True)
            requests_model.objects.create(
                mode="recap",
                status="succeeded",
                source_ids=[str(erased.pk)],
                source_fingerprints={"old": "unchanged"},
                draft_event=stale,
            )
            unknown = event("legacy-unknown", ai_generated=True)
            ordinary = []
            for status in ("draft", "published", "redacted"):
                original = event("ordinary-" + status, status="superseded" if status == "published" else "published")
                copy = event("ordinary-copy-" + status, status=status, supersedes_id=original.pk, supersedes_version=1)
                copy.source_events.add(original)
                ordinary.append((original.pk, copy.pk, status))
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            apps = executor.loader.project_state(final_targets).apps
            current_model = apps.get_model("chronicle", "ChronicleEvent")
            for pk in (b.pk, correction.pk):
                self.assertEqual(
                    set(current_model.objects.get(pk=pk).source_events.values_list("pk", flat=True)), {a.pk}
                )
            self.assertEqual(current_model.objects.get(pk=b.pk).status, "superseded")
            for pk in (stale.pk, unknown.pk, correction.pk):
                row = current_model.objects.get(pk=pk)
                self.assertEqual(row.status, "withdrawn")
                self.assertTrue(row.summary.startswith("Preserved"))
            self.assertEqual(current_model.objects.get(pk=unknown.pk).lineage_status, "unknown")
            self.assertEqual(
                apps.get_model("chronicle", "ChronicleGenerationRequest")
                .objects.get(pk=request.pk)
                .source_fingerprints,
                {},
            )
            for original_id, copy_id, status in ordinary:
                row = current_model.objects.get(pk=copy_id)
                self.assertEqual(
                    (row.supersedes_id, row.status, row.summary),
                    (original_id, status, "Preserved ordinary-copy-" + status),
                )
            snapshot = list(current_model.objects.order_by("pk").values())
            proof_snapshot = list(
                apps.get_model("chronicle", "ChronicleGenerationRequest").objects.order_by("pk").values()
            )
            links = list(current_model.source_events.through.objects.order_by("pk").values())
            with connection.schema_editor() as schema:
                import_module("chronicle.migrations._lineage_repair").repair_lineage(apps, schema)
            self.assertEqual(list(current_model.objects.order_by("pk").values()), snapshot)
            self.assertEqual(list(current_model.source_events.through.objects.order_by("pk").values()), links)
            self.assertEqual(
                list(apps.get_model("chronicle", "ChronicleGenerationRequest").objects.order_by("pk").values()),
                proof_snapshot,
            )
        finally:
            MigrationExecutor(connection).migrate(final_targets)
