"""Builder curation through real forms and durable record transitions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from evennia.objects.models import ObjectDB

from chronicle.models import ChronicleEvent
from chronicle.services import redact_event
from traits.models import CharacterBio

from .models import MemoryFact, NarrativePersona, StorySession
from .services import authorized_memory_context


class CurationFixture:
    def setUp(self):
        self.builder = get_user_model().objects.create_user(username="curation-builder", is_staff=False)
        self.builder.permissions.add("Builder")
        self.flag_only = get_user_model().objects.create_user(username="curation-flag-only", is_staff=True)
        self.owner = get_user_model().objects.create_user(username="curation-owner")
        self.character = ObjectDB.objects.create(
            db_key="Curation Player", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=self.character, account=self.owner)
        self.npc = ObjectDB.objects.create(db_key="Curation NPC", db_typeclass_path="typeclasses.characters.Character")
        self.persona = NarrativePersona.objects.create(character=self.npc, profile="A reserved NPC.")
        self.session = StorySession.objects.create(character=self.character, persona=self.persona)
        self.source = ChronicleEvent.objects.create(
            idempotency_key="curation-source",
            source_app="staff",
            source_type="scene",
            source_id="1",
            kind="scene.curated",
            title="Public source",
            summary="Reviewed source.",
            visibility="public",
            status="published",
        )
        self.client.force_login(self.builder)

    def fact(self, **changes):
        from .curation import create_memory_fact

        values = {
            "persona_id": self.persona.pk,
            "subject_id": self.character.pk,
            "text": "Staff-authored private detail.",
            "source_event_id": None,
            "staff_entry": "Sensitive staff provenance.",
            "visibility": "private",
            "expires_at": None,
        }
        values.update(changes)
        return create_memory_fact(self.builder, **values)


class PersonaCurationTests(CurationFixture, TestCase):
    def test_account_bearing_npc_and_later_player_ownership_fail_closed(self):
        from .curation import register_persona, update_persona

        account_npc = ObjectDB.objects.create(
            db_key="Account-bearing NPC", db_typeclass_path="typeclasses.characters.Character", db_account=self.owner
        )
        with self.assertRaises(ValueError):
            register_persona(account_npc, self.builder, "Must not register")
        CharacterBio.objects.create(character=self.npc, account=self.owner)
        with self.assertRaises(ValueError):
            update_persona(self.persona.pk, self.builder, 1, "Must not update a player persona")
        self.persona.refresh_from_db()
        self.assertEqual((self.persona.version, self.persona.profile), (1, "A reserved NPC."))
        self.assertEqual(authorized_memory_context(self.session), [])

    def test_builder_without_django_staff_registers_and_edits_through_rendered_forms(self):
        npc = ObjectDB.objects.create(db_key="New searchable NPC", db_typeclass_path="typeclasses.characters.Character")
        page = self.client.get(reverse("narrative_ops_personas"), {"q": "New searchable"})
        self.assertContains(page, "Register persona")
        self.assertContains(page, npc.db_key)
        response = self.client.post(
            reverse("narrative_ops_personas"), {"character_id": npc.pk, "profile": "New public profile."}
        )
        self.assertEqual(response.status_code, 302)
        persona = NarrativePersona.objects.get(character=npc)
        self.assertEqual((persona.registered_by_id, persona.version), (self.builder.pk, 1))
        edit = self.client.get(reverse("narrative_ops_persona_edit", args=(persona.pk,)))
        self.assertContains(edit, 'name="expected_version"')
        response = self.client.post(
            reverse("narrative_ops_persona_edit", args=(persona.pk,)),
            {"expected_version": 1, "profile": "Reviewed revised profile."},
        )
        self.assertEqual(response.status_code, 302)
        persona.refresh_from_db()
        self.assertEqual(
            (persona.profile, persona.version, persona.updated_by_id), ("Reviewed revised profile.", 2, self.builder.pk)
        )

    def test_registration_refuses_player_characters_noncharacters_and_unpersisted_objects(self):
        from .curation import register_persona

        room = ObjectDB.objects.create(db_key="Not an NPC", db_typeclass_path="typeclasses.rooms.Room")
        unsaved = ObjectDB(db_key="Unsaved", db_typeclass_path="typeclasses.characters.Character")
        for character in (self.character, room, unsaved):
            with self.subTest(character=character.db_key), self.assertRaises(ValueError):
                register_persona(character, self.builder, "Public profile")
        self.assertEqual(NarrativePersona.objects.count(), 1)

    def test_stale_profile_edits_and_revoked_builder_authority_do_not_overwrite(self):
        from .curation import update_persona

        updated = update_persona(self.persona.pk, self.builder, 1, "First reviewed update.")
        with self.assertRaises(ValueError):
            update_persona(self.persona.pk, self.builder, 1, "Stale overwrite.")
        self.builder.db_tags.through.objects.filter(accountdb_id=self.builder.pk, tag__db_tagtype="permission").delete()
        with self.assertRaises(PermissionError):
            update_persona(self.persona.pk, self.builder, updated.version, "Revoked overwrite.")
        self.persona.refresh_from_db()
        self.assertEqual(self.persona.profile, "First reviewed update.")

    def test_personas_and_registration_candidates_remain_searchable_beyond_first_page(self):
        for index in range(25):
            npc = ObjectDB.objects.create(
                db_key=f"Older NPC {index:02}", db_typeclass_path="typeclasses.characters.Character"
            )
            NarrativePersona.objects.create(character=npc, profile=f"Profile {index}")
        listing = self.client.get(reverse("narrative_ops_personas"))
        self.assertContains(listing, "Next")
        page = self.client.get(reverse("narrative_ops_personas"), {"q": "Older NPC 00"})
        self.assertContains(page, "Older NPC 00")
        self.assertContains(page, "Edit profile")

    def test_persona_pages_require_current_builder_authority_not_django_staff_flag(self):
        for user in (None, self.owner, self.flag_only):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in (
                reverse("narrative_ops_personas"),
                reverse("narrative_ops_persona_edit", args=(self.persona.pk,)),
            ):
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 302)
                    self.assertEqual(
                        self.client.post(url, {"profile": "Unauthorized", "expected_version": 1}).status_code, 302
                    )
        self.persona.refresh_from_db()
        self.assertEqual(self.persona.profile, "A reserved NPC.")


class MemoryCurationTests(CurationFixture, TestCase):
    def test_private_source_authority_is_bound_to_the_exact_subject(self):
        from .curation import approve_memory_fact, revise_memory_fact

        ChronicleEvent.objects.filter(pk=self.source.pk).update(visibility="participants")
        self.source.participants.add(self.character)
        fact = self.fact(source_event_id=self.source.pk)
        fact = approve_memory_fact(fact.pk, self.builder, fact.version)
        other = get_user_model().objects.create_user(username="private-source-other")
        character = ObjectDB.objects.create(
            db_key="Other source subject", db_typeclass_path="typeclasses.characters.Character"
        )
        CharacterBio.objects.create(character=character, account=other)
        with self.assertRaises(ValueError):
            revise_memory_fact(fact.pk, self.builder, fact.version, {"subject_id": character.pk})
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.subject_id), ("approved", self.character.pk))

    def test_approved_revision_revokes_inflight_and_resumed_prose_without_erasing_success_history(self):
        from .curation import approve_memory_fact, revise_memory_fact
        from .models import NarrativeConsent, StoryGenerationRequest
        from .services import generate_story
        from .test_request_lifecycle import ControlledProvider

        fact = self.fact()
        fact = approve_memory_fact(fact.pk, self.builder, fact.version)
        NarrativeConsent.objects.create(account=self.owner, character=self.character, opted_in=True)
        provider = ControlledProvider()
        first = generate_story(self.session, "First action", provider, lambda callback: callback())
        first.addErrback(lambda failure: self.fail(str(failure.value)))
        provider.respond("Derived private success.", citations=[str(fact.pk)])
        historical = StoryGenerationRequest.objects.get()
        waiting = generate_story(self.session, "Pending action", provider, lambda callback: callback())
        errors = []
        waiting.addErrback(errors.append)
        revise_memory_fact(fact.pk, self.builder, fact.version, {"text": "Replacement requiring new approval"})
        provider.respond("Late stale success.", citations=[str(fact.pk)])
        self.assertEqual(len(errors), 1)
        next_request = generate_story(self.session, "Safe action", provider, lambda callback: callback())
        next_request.addErrback(lambda failure: self.fail(str(failure.value)))
        self.assertNotIn("Derived private success.", str(provider.messages[-1]))
        self.assertNotIn(fact.text, str(provider.messages[-1]))
        provider.respond("Safe continuation.")
        historical.refresh_from_db()
        self.assertEqual((historical.status, historical.response), ("succeeded", "Derived private success."))

    def test_create_review_and_approve_private_fact_through_real_forms(self):
        page = self.client.get(reverse("narrative_ops_memories"))
        self.assertContains(page, "Create memory draft")
        response = self.client.post(
            reverse("narrative_ops_memories"),
            {
                "persona_id": self.persona.pk,
                "subject_id": self.character.pk,
                "text": "Manual curated detail.",
                "staff_entry": "Reviewed by staff.",
                "visibility": "private",
            },
        )
        self.assertEqual(response.status_code, 302)
        fact = MemoryFact.objects.get()
        self.assertEqual((fact.status, fact.created_by_id), ("draft", self.builder.pk))
        self.assertEqual(authorized_memory_context(self.session), [])
        edit = self.client.get(reverse("narrative_ops_memory_edit", args=(fact.pk,)))
        self.assertContains(edit, "Reviewed by staff.")
        self.assertContains(edit, "Approve memory fact")
        self.assertEqual(
            self.client.post(
                reverse("narrative_ops_memory_action", args=(fact.pk, "approve")), {"expected_version": fact.version}
            ).status_code,
            302,
        )
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.approved_by_id), ("approved", self.builder.pk))
        self.assertIsNotNone(fact.approved_at)
        self.assertEqual(authorized_memory_context(self.session), [{"id": str(fact.pk), "text": fact.text}])

    def test_approved_edit_creates_review_draft_and_revokes_previous_eligibility(self):
        from .curation import approve_memory_fact, revise_memory_fact

        fact = self.fact()
        fact = approve_memory_fact(fact.pk, self.builder, fact.version)
        original_text = fact.text
        draft = revise_memory_fact(fact.pk, self.builder, fact.version, {"text": "Revised detail requires review."})
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.text), ("withdrawn", original_text))
        self.assertEqual((draft.status, draft.revision_of_id, draft.revision_root_id), ("draft", fact.pk, fact.pk))
        self.assertEqual(authorized_memory_context(self.session), [])
        self.assertNotEqual(draft.pk, fact.pk)
        approve_memory_fact(draft.pk, self.builder, draft.version)
        self.assertEqual(authorized_memory_context(self.session), [{"id": str(draft.pk), "text": draft.text}])

    def test_redaction_clears_text_and_sensitive_provenance_across_revision_family(self):
        from .curation import approve_memory_fact, redact_memory_fact, revise_memory_fact

        original = self.fact()
        original = approve_memory_fact(original.pk, self.builder, original.version)
        draft = revise_memory_fact(
            original.pk,
            self.builder,
            original.version,
            {"text": "Changed private text", "staff_entry": "Changed private staff provenance"},
        )
        self.assertEqual(
            self.client.post(
                reverse("narrative_ops_memory_action", args=(draft.pk, "redact")), {"expected_version": draft.version}
            ).status_code,
            302,
        )
        for fact in (original, draft):
            fact.refresh_from_db()
            self.assertEqual((fact.status, fact.text, fact.staff_entry), ("redacted", "", ""))
            self.assertEqual(fact.redacted_by_id, self.builder.pk)
            self.assertIsNotNone(fact.redacted_at)
        self.assertEqual(original.approved_by_id, self.builder.pk)
        self.assertEqual(draft.revision_of_id, original.pk)
        with self.assertRaises(ValueError):
            revise_memory_fact(draft.pk, self.builder, draft.version, {"text": "Must not restore"})
        self.assertEqual(redact_memory_fact(draft.pk, self.builder, draft.version).status, "redacted")

    def test_scope_provenance_subject_and_expiry_validation(self):
        room = ObjectDB.objects.create(db_key="Invalid private subject", db_typeclass_path="typeclasses.rooms.Room")
        for changes in (
            {"subject_id": None},
            {"subject_id": room.pk},
            {"staff_entry": " ", "source_event_id": None},
            {"text": " "},
            {"expires_at": timezone.now() - timedelta(seconds=1)},
            {"visibility": "unrecognized"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fact(**changes)
        self.assertFalse(MemoryFact.objects.exists())

    def test_source_backed_public_fact_cannot_use_private_or_unavailable_ancestry(self):
        for change in ({"visibility": "participants"}, {"status": "redacted"}):
            ChronicleEvent.objects.filter(pk=self.source.pk).update(
                **{"visibility": "public", "status": "published", **change}
            )
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.fact(source_event_id=self.source.pk, visibility="public", subject_id=None)
        self.assertFalse(MemoryFact.objects.exists())

    def test_source_withdrawal_and_expiry_prevent_approval_without_mutation(self):
        from .curation import approve_memory_fact

        fact = self.fact(source_event_id=self.source.pk)
        redact_event(self.source.pk, self.builder)
        with self.assertRaises(ValueError):
            approve_memory_fact(fact.pk, self.builder, fact.version)
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.version, fact.approved_by_id), ("draft", 1, None))
        expired = self.fact(expires_at=timezone.now() + timedelta(hours=1))
        MemoryFact.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            approve_memory_fact(expired.pk, self.builder, expired.version)

    def test_stale_approval_revision_and_redaction_cannot_replace_later_review(self):
        from .curation import approve_memory_fact, redact_memory_fact, revise_memory_fact

        fact = self.fact()
        approved = approve_memory_fact(fact.pk, self.builder, 1)
        for action in (
            lambda: approve_memory_fact(fact.pk, self.builder, 1),
            lambda: revise_memory_fact(fact.pk, self.builder, 1, {"text": "stale"}),
            lambda: redact_memory_fact(fact.pk, self.builder, 1),
        ):
            with self.assertRaises(ValueError):
                action()
        approved.refresh_from_db()
        self.assertEqual(approved.status, "approved")

    def test_all_memory_states_search_pagination_and_direct_review_remain_discoverable(self):
        from .curation import approve_memory_fact, revise_memory_fact

        oldest = self.fact(text="Searchable oldest fact")
        oldest = approve_memory_fact(oldest.pk, self.builder, oldest.version)
        draft = revise_memory_fact(oldest.pk, self.builder, oldest.version, {"text": "Replacement awaiting review"})
        for index in range(25):
            self.fact(text=f"Later fact {index}")
        self.assertContains(self.client.get(reverse("narrative_ops_memories")), "Next")
        page = self.client.get(reverse("narrative_ops_memories"), {"q": "Searchable oldest", "status": "withdrawn"})
        self.assertContains(page, "Searchable oldest fact")
        self.assertContains(page, reverse("narrative_ops_memory_edit", args=(oldest.pk,)))
        self.assertContains(
            self.client.get(reverse("narrative_ops_memory_edit", args=(draft.pk,))), "Replacement awaiting review"
        )

    def test_unavailable_source_approved_facts_are_discoverable_in_withdrawn_review(self):
        from .curation import approve_memory_fact

        fact = self.fact(source_event_id=self.source.pk)
        fact = approve_memory_fact(fact.pk, self.builder, fact.version)
        redact_event(self.source.pk, self.builder)
        page = self.client.get(reverse("narrative_ops_memories"), {"status": "withdrawn"})
        self.assertContains(page, reverse("narrative_ops_memory_edit", args=(fact.pk,)))
        self.assertContains(page, "source unavailable")

    def test_memory_pages_actions_csrf_and_safe_method_boundaries(self):
        fact = self.fact()
        url = reverse("narrative_ops_memory_edit", args=(fact.pk,))
        for user in (self.owner, self.flag_only):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url, {"expected_version": 1, "text": "Unauthorized"}).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.builder)
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url, {"expected_version": 1, "text": "No token"}).status_code, 403)
        self.client.force_login(self.builder)
        self.assertEqual(
            self.client.get(reverse("narrative_ops_memory_action", args=(fact.pk, "approve"))).status_code, 405
        )
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.version), ("draft", 1))


class CurationAdminTests(CurationFixture, TestCase):
    def test_admin_is_read_only_and_cannot_bypass_review_or_redaction(self):
        from django.contrib.admin.sites import AdminSite

        from .admin import MemoryFactAdmin, NarrativePersonaAdmin

        fact = self.fact()
        request = RequestFactory().post("/admin/")
        request.user = self.builder
        for model, admin_class, record in (
            (MemoryFact, MemoryFactAdmin, fact),
            (NarrativePersona, NarrativePersonaAdmin, self.persona),
        ):
            managed = admin_class(model, AdminSite())
            self.assertTrue(managed.has_view_permission(request, record))
            self.assertFalse(managed.has_change_permission(request, record))
            self.assertFalse(managed.has_add_permission(request))
            self.assertFalse(managed.has_delete_permission(request, record))
            self.assertIn("version", managed.get_readonly_fields(request, record))
            self.assertIn("Story Operations", str(managed.curation_link(record)))
            with self.assertRaises(PermissionDenied):
                managed.save_model(request, record, None, True)
            request.user = self.flag_only
            self.assertFalse(managed.has_view_permission(request, record))
            request.user = self.builder
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.text), ("draft", "Staff-authored private detail."))

    def test_crafted_admin_status_post_is_denied_and_preserves_complete_record(self):
        fact = self.fact()
        admin = get_user_model().objects.create_user(username="curation-admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        snapshot = MemoryFact.objects.values().get(pk=fact.pk)
        response = self.client.post(
            reverse("admin:narrative_memoryfact_change", args=(fact.pk,)),
            {"status": "redacted", "text": "Uncleared private text", "_save": "Save"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(MemoryFact.objects.values().get(pk=fact.pk), snapshot)


class CurationConcurrencyTests(CurationFixture, TransactionTestCase):
    def compete(self, operation):
        from .curation import CurationConflictError

        barrier = Barrier(2)
        actor_id = self.builder.pk

        def worker():
            connections.close_all()
            try:
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                return operation(actor)
            except CurationConflictError:
                return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _index: worker(), range(2)))

    def test_competing_approved_edits_create_one_review_draft(self):
        from .curation import approve_memory_fact, revise_memory_fact

        fact = self.fact()
        fact = approve_memory_fact(fact.pk, self.builder, fact.version)
        results = self.compete(
            lambda actor: revise_memory_fact(fact.pk, actor, fact.version, {"text": "Concurrent reviewed replacement"})
        )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(MemoryFact.objects.filter(revision_root_id=fact.pk, status="draft").count(), 1)
        fact.refresh_from_db()
        self.assertEqual((fact.status, fact.text), ("withdrawn", "Staff-authored private detail."))

    def test_competing_approval_and_redaction_use_expected_version(self):
        from .curation import CurationConflictError, approve_memory_fact, redact_memory_fact

        fact = self.fact()
        barrier = Barrier(2)

        def operation(action):
            connections.close_all()
            try:
                actor = get_user_model().objects.get(pk=self.builder.pk)
                barrier.wait(timeout=10)
                return action(fact.pk, actor, 1)
            except CurationConflictError:
                return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(operation, (approve_memory_fact, redact_memory_fact)))
        self.assertEqual(sum(result is not None for result in results), 1)
        fact.refresh_from_db()
        if fact.status == "redacted":
            self.assertEqual((fact.text, fact.staff_entry), ("", ""))
        else:
            self.assertEqual((fact.status, fact.version), ("approved", 2))


class CurationMigrationTests(TransactionTestCase):
    def test_legacy_audit_is_preserved_redacted_text_erased_and_new_constraints_enforced(self):
        from importlib import import_module

        database = str(connection.settings_dict["NAME"])
        self.assertTrue("memorydb" in database or "test_" in database or database == ":memory:")
        before = [("narrative", "0002_durable_dispatch_claims")]
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            old = executor.loader.project_state(before).apps
            objects = old.get_model("objects", "ObjectDB")
            npc = objects.objects.create(db_key="Legacy NPC", db_typeclass_path="typeclasses.characters.Character")
            personas = old.get_model("narrative", "NarrativePersona")
            persona = personas.objects.create(character_id=npc.pk, profile="Legacy public profile")
            facts = old.get_model("narrative", "MemoryFact")
            reviewed_at = timezone.now() - timedelta(days=2)
            approved = facts.objects.create(
                persona_id=persona.pk,
                subject_id=npc.pk,
                text="Preserved approved text",
                staff_entry="Preserved staff provenance",
                visibility="private",
                status="approved",
                approved_at=reviewed_at,
            )
            erased = facts.objects.create(
                persona_id=persona.pk,
                subject_id=npc.pk,
                text="Legacy uncleared secret",
                staff_entry="Legacy sensitive provenance",
                visibility="private",
                status="redacted",
                approved_at=reviewed_at,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(final_targets)
            apps = executor.loader.project_state(final_targets).apps
            current = apps.get_model("narrative", "MemoryFact")
            approved_row, erased_row = current.objects.get(pk=approved.pk), current.objects.get(pk=erased.pk)
            self.assertEqual(
                (approved_row.status, approved_row.text, approved_row.staff_entry, approved_row.approved_at),
                ("approved", "Preserved approved text", "Preserved staff provenance", reviewed_at),
            )
            self.assertEqual(
                (
                    approved_row.version,
                    approved_row.created_by_id,
                    approved_row.approved_by_id,
                    approved_row.revision_of_id,
                ),
                (1, None, None, None),
            )
            self.assertEqual(
                (erased_row.status, erased_row.text, erased_row.staff_entry, erased_row.approved_at),
                ("redacted", "", "", reviewed_at),
            )
            snapshot = list(current.objects.order_by("pk").values())
            with connection.schema_editor() as schema:
                import_module("narrative.migrations.0003_versioned_manual_curation").clear_legacy_redacted_text(
                    apps, schema
                )
            self.assertEqual(list(current.objects.order_by("pk").values()), snapshot)
            fields = {
                "persona_id": persona.pk,
                "subject_id": npc.pk,
                "visibility": "private",
                "text": "Draft",
                "staff_entry": "Staff proof",
            }
            current.objects.create(revision_root_id=approved.pk, revision_of_id=approved.pk, **fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                current.objects.create(revision_root_id=approved.pk, revision_of_id=approved.pk, **fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                current.objects.create(**{**fields, "staff_entry": "", "status": "approved"})
        finally:
            MigrationExecutor(connection).migrate(final_targets)


class PersistedCurationAuthorityTests(CurationFixture, TestCase):
    def snapshot(self):
        return (
            list(NarrativePersona.objects.order_by("pk").values()),
            list(MemoryFact.objects.order_by("pk").values()),
        )

    def test_warmed_superuser_refuses_curation_after_persisted_quelling_without_mutating_rows(self):
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        from .curation import (
            approve_memory_fact,
            create_memory_fact,
            redact_memory_fact,
            register_persona,
            update_persona,
        )

        fact = self.fact()
        actor = get_user_model().objects.create_user(username="warmed-quell-superuser", is_superuser=True)
        actor.permissions.clear()
        actor.attributes.add("_quell", False)
        self.assertFalse(actor.attributes.get("_quell"))
        self.assertTrue(actor.check_permstring("Builder"))
        attribute_id = (
            actor.db_attributes.through.objects.filter(accountdb_id=actor.pk, attribute__db_key="_quell")
            .values_list("attribute_id", flat=True)
            .get()
        )
        Attribute.objects.filter(pk=attribute_id).update(db_value=to_pickle(True))
        npc = ObjectDB.objects.create(
            db_key="Quelled registration target", db_typeclass_path="typeclasses.characters.Character"
        )
        before = self.snapshot()
        actions = [
            lambda: register_persona(npc, actor, "Unauthorized profile"),
            lambda: update_persona(self.persona.pk, actor, 1, "Unauthorized update"),
            lambda: create_memory_fact(
                actor,
                persona_id=self.persona.pk,
                subject_id=self.character.pk,
                text="Unauthorized fact",
                staff_entry="Staff proof",
                visibility="private",
            ),
            lambda: approve_memory_fact(fact.pk, actor, 1),
            lambda: redact_memory_fact(fact.pk, actor, 1),
        ]
        for action in actions:
            with self.subTest(action=action), self.assertRaises(PermissionError):
                action()
        self.assertEqual(self.snapshot(), before)

    def test_quelled_superuser_with_explicit_current_builder_tag_keeps_normal_builder_authority(self):
        from .curation import update_persona

        actor = get_user_model().objects.create_user(username="quelled-explicit-builder", is_superuser=True)
        actor.permissions.add("Builder")
        actor.attributes.add("_quell", True)
        updated = update_persona(self.persona.pk, actor, 1, "Explicit Builder reviewed profile")
        self.assertEqual(updated.updated_by_id, actor.pk)
        self.assertTrue(get_user_model().objects.filter(pk=actor.pk).values_list("is_superuser", flat=True).get())

    def drift_personas(self, field, value):
        from .curation import approve_memory_fact

        fact = self.fact()
        approve_memory_fact(fact.pk, self.builder, fact.version)
        self.assertEqual(len(authorized_memory_context(self.session)), 1)
        candidate = ObjectDB.objects.create(
            db_key="Warmed drift candidate", db_typeclass_path="typeclasses.characters.Character"
        )
        self.assertTrue(candidate.is_typeclass("typeclasses.characters.Character", exact=False))
        self.assertIsNone(candidate.db_account)
        self.assertTrue(self.npc.is_typeclass("typeclasses.characters.Character", exact=False))
        self.assertIsNone(self.npc.db_account)
        ObjectDB.objects.filter(pk__in=(candidate.pk, self.npc.pk)).update(**{field: value})
        return candidate

    def refuse_drift(self, candidate):
        from .curation import register_persona, update_persona

        before = self.snapshot()
        with self.assertRaises(ValueError):
            register_persona(candidate, self.builder, "Must refuse persisted drift")
        with self.assertRaises(ValueError):
            update_persona(self.persona.pk, self.builder, 1, "Must refuse persisted drift")
        self.assertEqual(authorized_memory_context(self.session), [])
        self.assertEqual(self.snapshot(), before)

    def test_warmed_personas_refuse_persisted_account_binding_drift(self):
        self.refuse_drift(self.drift_personas("db_account_id", self.owner.pk))

    def test_warmed_personas_refuse_persisted_noncharacter_typeclass_drift(self):
        self.refuse_drift(self.drift_personas("db_typeclass_path", "typeclasses.rooms.Room"))

    def test_warmed_private_subject_typeclass_drift_refuses_draft_creation(self):
        self.assertTrue(self.character.is_typeclass("typeclasses.characters.Character", exact=False))
        ObjectDB.objects.filter(pk=self.character.pk).update(db_typeclass_path="typeclasses.rooms.Room")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.fact()
        self.assertEqual(self.snapshot(), before)

    def test_warmed_private_subject_typeclass_drift_refuses_approval_and_context(self):
        from .curation import approve_memory_fact

        fact = self.fact()
        self.assertTrue(self.character.is_typeclass("typeclasses.characters.Character", exact=False))
        ObjectDB.objects.filter(pk=self.character.pk).update(db_typeclass_path="typeclasses.rooms.Room")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            approve_memory_fact(fact.pk, self.builder, 1)
        self.assertEqual(self.snapshot(), before)
        # A legacy approved fact cannot use a now non-Character scene subject.
        MemoryFact.objects.filter(pk=fact.pk).update(status="approved")
        self.assertEqual(authorized_memory_context(self.session), [])
