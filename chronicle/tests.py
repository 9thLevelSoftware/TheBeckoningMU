from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from evennia.objects.models import ObjectDB
from evennia.typeclasses.attributes import Attribute
from evennia.utils.dbserialize import to_pickle
from evennia.utils.test_resources import EvenniaTest

from boons.utils import offer_boon
from chronicle.models import ChronicleEvent
from chronicle.read_services import character_chronicle_for_account, character_summary_for_account
from chronicle.services import (
    correct_event,
    participant_events,
    public_events,
    publish_event,
    record_event,
    redact_event,
)
from status.utils import set_earned_status


class ChronicleEventServiceTests(EvenniaTest):
    def record(
        self, *, key="event-1", title="A public scene", visibility=ChronicleEvent.Visibility.PUBLIC, participants=()
    ):
        with self.captureOnCommitCallbacks(execute=True):
            record_event(
                idempotency_key=key,
                source_app="test",
                source_type="TestRecord",
                source_id=key,
                kind="scene.curated",
                title=title,
                summary="A staff-curated event.",
                payload={},
                visibility=visibility,
                participants=participants,
            )
        return ChronicleEvent.objects.get(idempotency_key=key)

    def test_event_is_created_after_commit_and_duplicate_key_is_idempotent(self):
        with self.captureOnCommitCallbacks(execute=True):
            record_event(
                idempotency_key="same-transition",
                source_app="test",
                source_type="TestRecord",
                source_id="7",
                kind="scene.curated",
                title="First title",
                summary="First summary",
                payload={},
                visibility=ChronicleEvent.Visibility.PUBLIC,
            )
        with self.captureOnCommitCallbacks(execute=True):
            record_event(
                idempotency_key="same-transition",
                source_app="test",
                source_type="TestRecord",
                source_id="7",
                kind="scene.curated",
                title="Duplicate title",
                summary="Duplicate summary",
                payload={},
                visibility=ChronicleEvent.Visibility.PUBLIC,
            )

        self.assertEqual(ChronicleEvent.objects.count(), 1)
        self.assertEqual(ChronicleEvent.objects.get().title, "First title")
        self.assertEqual(ChronicleEvent.objects.get().status, ChronicleEvent.Status.DRAFT)

    def test_duplicate_delivery_cannot_expand_participants_or_sources(self):
        source = self.record(key="source")
        other_source = self.record(key="other-source")

        def deliver(participant, source_event):
            with self.captureOnCommitCallbacks(execute=True):
                record_event(
                    idempotency_key="private-transition",
                    source_app="test",
                    source_type="TestRecord",
                    source_id="1",
                    kind="scene.curated",
                    title="Private transition",
                    summary="Original participants only.",
                    payload={},
                    visibility=ChronicleEvent.Visibility.PARTICIPANTS,
                    participants=(participant,),
                    source_events=(source_event,),
                )

        deliver(self.char1, source)
        event = ChronicleEvent.objects.get(idempotency_key="private-transition")
        self.account.is_staff = True
        self.account.save(update_fields=["is_staff"])
        publish_event(event.pk, self.account)
        deliver(self.char2, other_source)

        self.assertCountEqual(event.participants.all(), [self.char1])
        self.assertCountEqual(event.source_events.all(), [source])
        self.assertFalse(participant_events(self.account2).filter(pk=event.pk).exists())

    def test_relation_failure_rolls_back_committed_event_creation(self):
        source = self.record(key="atomic-source")
        manager = ChronicleEvent.source_events.related_manager_cls
        with (
            patch.object(manager, "add", side_effect=RuntimeError("relation insertion failed")),
            self.assertRaisesMessage(RuntimeError, "relation insertion failed"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            record_event(
                idempotency_key="failed-relations",
                source_app="test",
                source_type="TestRecord",
                source_id="2",
                kind="scene.curated",
                title="Incomplete event",
                summary="Must roll back with its participants.",
                payload={},
                visibility=ChronicleEvent.Visibility.PARTICIPANTS,
                participants=(self.char1,),
                source_events=(source,),
            )

        self.assertFalse(ChronicleEvent.objects.filter(idempotency_key="failed-relations").exists())
        self.assertFalse(ChronicleEvent.participants.through.objects.exists())

    def test_participant_projection_is_account_scoped(self):
        event = self.record(
            key="private-event",
            visibility=ChronicleEvent.Visibility.PARTICIPANTS,
            participants=(self.char1,),
        )
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        publish_event(event.pk, staff)

        self.assertQuerySetEqual(participant_events(self.char1.account), [event])
        self.assertFalse(participant_events(self.char2.account).exists())
        self.assertFalse(public_events().filter(pk=event.pk).exists())

    def test_correction_replaces_public_projection_only_when_approved(self):
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        original = self.record(key="original")
        publish_event(original.pk, staff)

        correction = correct_event(
            original.pk,
            staff,
            title="Corrected scene",
            summary="Corrected summary.",
            payload={},
        )
        self.assertQuerySetEqual(public_events(), [original])

        publish_event(correction.pk, staff)
        original.refresh_from_db()
        self.assertEqual(original.status, ChronicleEvent.Status.SUPERSEDED)
        self.assertQuerySetEqual(public_events(), [correction])

    def test_redaction_clears_displayable_content_and_hides_event(self):
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        event = self.record(key="redacted")
        publish_event(event.pk, staff)

        redact_event(event.pk, staff)
        event.refresh_from_db()

        self.assertEqual(event.status, ChronicleEvent.Status.REDACTED)
        self.assertEqual((event.title, event.summary, event.payload), ("", "", {}))
        self.assertFalse(public_events().filter(pk=event.pk).exists())

    def test_payload_rejects_unapproved_fields(self):
        with self.assertRaises(ValueError):
            record_event(
                idempotency_key="unsafe-payload",
                source_app="test",
                source_type="TestRecord",
                source_id="8",
                kind="scene.curated",
                title="Unsafe",
                summary="Unsafe",
                payload={"private_note": "must not be copied"},
                visibility=ChronicleEvent.Visibility.PUBLIC,
            )

    def test_boon_offer_records_only_public_safe_fields(self):
        description = "private favor details"
        with self.captureOnCommitCallbacks(execute=True):
            success, boon, _message = offer_boon(self.char1, self.char2, "minor", description)

        self.assertTrue(success)
        event = ChronicleEvent.objects.get(kind="boon.offered", source_id=str(boon.pk))
        self.assertEqual(event.status, ChronicleEvent.Status.DRAFT)
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PUBLIC)
        self.assertEqual(event.payload, {"boon_type": "minor"})
        self.assertNotIn(description, event.summary)
        self.assertCountEqual(event.participants.all(), [self.char1, self.char2])

    def test_invalid_boon_offer_emits_no_event(self):
        with self.captureOnCommitCallbacks(execute=True):
            success, _boon, _message = offer_boon(self.char1, self.char2, "invalid", "private")

        self.assertFalse(success)
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_status_transition_records_participant_scoped_event(self):
        with self.captureOnCommitCallbacks(execute=True):
            status = set_earned_status(self.char1, 2, reason="private staff reason", changed_by=self.char1)

        event = ChronicleEvent.objects.get(kind="status.changed", source_id=str(status.pk))
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PARTICIPANTS)
        self.assertEqual(event.payload, {"old_value": 0, "new_value": 2})
        self.assertNotIn("private staff reason", event.summary)

    def test_player_api_enforces_auth_ownership_and_get_only(self):
        summary_url = f"/api/player/characters/{self.char1.pk}/summary/"
        other_summary_url = f"/api/player/characters/{self.char2.pk}/summary/"
        self.client.force_login(self.char1.account)

        self.assertEqual(self.client.get(summary_url).status_code, 200)
        self.assertEqual(self.client.get(other_summary_url).status_code, 404)
        self.assertEqual(self.client.post(summary_url).status_code, 405)

        self.client.logout()
        self.assertEqual(self.client.get("/api/player/chronicle/").status_code, 401)
        self.assertEqual(self.client.get("/api/player/chronicle/mine/").status_code, 401)

    def test_public_page_shows_only_staff_published_public_events(self):
        public_draft = self.record(key="public-draft")
        private_draft = self.record(
            title="Private scene",
            key="private-draft",
            visibility=ChronicleEvent.Visibility.PARTICIPANTS,
            participants=(self.char1,),
        )
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])

        response = self.client.get("/chronicle/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, public_draft.title)
        self.assertNotContains(response, private_draft.title)

        publish_event(public_draft.pk, staff)
        publish_event(private_draft.pk, staff)
        response = self.client.get("/chronicle/")
        self.assertContains(response, public_draft.title)
        self.assertNotContains(response, private_draft.title)

    def test_player_chronicle_api_excludes_other_accounts_events(self):
        own_event = self.record(
            key="own-event",
            title="My participant event",
            visibility=ChronicleEvent.Visibility.PARTICIPANTS,
            participants=(self.char1,),
        )
        other_event = self.record(
            key="other-event",
            title="Someone else's participant event",
            visibility=ChronicleEvent.Visibility.PARTICIPANTS,
            participants=(self.char2,),
        )
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        publish_event(own_event.pk, staff)
        publish_event(other_event.pk, staff)
        self.client.force_login(self.char1.account)

        response = self.client.get("/api/player/chronicle/mine/")

        self.assertEqual(response.status_code, 200)
        event_ids = {item["id"] for item in response.json()["events"]}
        self.assertIn(own_event.pk, event_ids)
        self.assertNotIn(other_event.pk, event_ids)

    def test_staff_console_requires_staff_and_publishes_via_post(self):
        event = self.record(key="staff-review")
        self.assertNotEqual(self.client.get("/staff/narrative-ops/").status_code, 200)

        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        response = self.client.get("/staff/narrative-ops/")
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/staff/narrative-ops/events/{event.pk}/publish/")
        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.status, ChronicleEvent.Status.PUBLISHED)

    def test_staff_console_corrects_and_redacts_events(self):
        event = self.record(key="staff-correction")
        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)

        self.client.post(f"/staff/narrative-ops/events/{event.pk}/publish/")
        response = self.client.post(
            f"/staff/narrative-ops/events/{event.pk}/correct/",
            {"title": "Corrected event", "summary": "Verified details.", "payload": "{}"},
        )
        self.assertEqual(response.status_code, 302)
        correction = ChronicleEvent.objects.get(supersedes=event)
        self.assertEqual(correction.status, ChronicleEvent.Status.DRAFT)
        self.assertIn(event, public_events())

        self.client.post(f"/staff/narrative-ops/events/{correction.pk}/publish/")
        event.refresh_from_db()
        self.assertEqual(event.status, ChronicleEvent.Status.SUPERSEDED)
        self.assertIn(correction, public_events())

        self.client.post(f"/staff/narrative-ops/events/{correction.pk}/redact/")
        correction.refresh_from_db()
        self.assertEqual(correction.status, ChronicleEvent.Status.REDACTED)
        self.assertFalse(public_events().filter(pk=correction.pk).exists())

    def test_staff_console_reviews_and_redacts_memory_facts(self):
        from evennia.objects.models import ObjectDB

        from narrative.models import MemoryFact, NarrativePersona

        npc = ObjectDB.objects.create(db_key="MemoryReviewNPC", db_typeclass_path="typeclasses.characters.Character")
        persona = NarrativePersona.objects.create(character=npc)
        event = self.record(key="memory-source")
        fact = MemoryFact.objects.create(
            persona=persona,
            text="A sourced memory awaiting review.",
            source_event=event,
            visibility=MemoryFact.Visibility.PUBLIC,
        )

        self.client.force_login(self.account)
        response = self.client.post(f"/staff/narrative-ops/memories/{fact.pk}/approve/")
        self.assertNotEqual(response.status_code, 200)
        fact.refresh_from_db()
        self.assertEqual(fact.status, MemoryFact.Status.DRAFT)

        staff = self.account
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        self.client.force_login(staff)
        response = self.client.get("/staff/narrative-ops/")
        self.assertContains(response, "A sourced memory awaiting review.")
        self.assertContains(response, f"Source Chronicle #{event.pk}")
        self.client.post(f"/staff/narrative-ops/memories/{fact.pk}/approve/")
        fact.refresh_from_db()
        self.assertEqual(fact.status, MemoryFact.Status.APPROVED)
        self.assertIsNotNone(fact.approved_at)

        self.client.post(f"/staff/narrative-ops/memories/{fact.pk}/redact/")
        fact.refresh_from_db()
        self.assertEqual(fact.status, MemoryFact.Status.REDACTED)
        self.assertEqual(fact.text, "")

    def test_boon_ledger_report_is_read_only(self):
        from boons.models import BoonLedger

        ledger = BoonLedger.objects.create(
            character=self.char1,
            total_debt_weight=99,
            net_weight=99,
        )
        expected = ledger.calculate_values()
        ledger.refresh_from_db()

        self.assertEqual(expected["total_debt_weight"], 0)
        self.assertEqual(ledger.total_debt_weight, 99)
        self.assertEqual(ledger.net_weight, 99)

    def test_staff_console_redacts_staff_origin_memory_without_retaining_note(self):
        from narrative.models import MemoryFact, NarrativePersona

        npc = ObjectDB.objects.create(db_key="StaffMemoryNPC", db_typeclass_path="typeclasses.characters.Character")
        fact = MemoryFact.objects.create(
            persona=NarrativePersona.objects.create(character=npc),
            text="Sensitive memory text.",
            staff_entry="Sensitive staff provenance.",
            visibility=MemoryFact.Visibility.STAFF,
        )
        self.account.is_staff = True
        self.account.save(update_fields=["is_staff"])
        self.client.force_login(self.account)

        response = self.client.post(f"/staff/narrative-ops/memories/{fact.pk}/redact/")

        self.assertEqual(response.status_code, 302)
        fact.refresh_from_db()
        self.assertEqual(fact.status, MemoryFact.Status.REDACTED)
        self.assertEqual(fact.text, "")
        self.assertEqual(fact.staff_entry, "[redacted staff entry]")
        self.assertIsNone(fact.source_event_id)
        self.assertNotContains(self.client.get("/staff/narrative-ops/"), "Sensitive staff provenance.")


class CharacterPersistenceProjectionTests(EvenniaTest):
    def test_summary_bypasses_cached_attributes_and_models_without_writing(self):
        from boons.models import BoonLedger
        from status.models import CamarillaPosition, CharacterStatus

        old_stats = {"attributes": {"physical": {"strength": 1}}}
        self.char1.db.stats = old_stats
        self.char1.db.vampire = {"hunger": 1}
        self.char1.db.pools = {"health": 3}
        self.char1.db.advantages = {"merits": ["Old merit"]}
        cached_attribute = self.char1.attributes.get("stats", return_obj=True)
        self.assertEqual(self.char1.db.stats, old_stats)
        old_name = self.char1.key
        position = CamarillaPosition.objects.create(name="Old position")
        status = CharacterStatus.objects.create(character=self.char1, earned_status=1, position=position)
        ledger = BoonLedger.objects.create(character=self.char1, total_debt_weight=1)

        # QuerySet.update represents another process: it changes persisted rows
        # without refreshing this process's idmapper or Attribute handler caches.
        updated = {
            "stats": {"attributes": {"physical": {"strength": 4}}, "specialties": {"stealth": ("Quiet", "Dark")}},
            "vampire": {"hunger": 3, "clan": "Ventrue"},
            "pools": {"health": 7, "damage": [1, 0]},
            "advantages": {"merits": ["New merit"], "backgrounds": {"allies": 2}},
        }
        for key, value in updated.items():
            attribute = self.char1.attributes.get(key, return_obj=True)
            Attribute.objects.filter(pk=attribute.pk).update(db_value=to_pickle(value))
        ObjectDB.objects.filter(pk=self.char1.pk).update(db_key="Current persisted name")
        CharacterStatus.objects.filter(pk=status.pk).update(earned_status=4, position_status=2, temporary_status=-1)
        CamarillaPosition.objects.filter(pk=position.pk).update(name="Current persisted position")
        BoonLedger.objects.filter(pk=ledger.pk).update(total_debt_weight=5, total_credit_weight=8, net_weight=3)

        with CaptureQueriesContext(connection) as queries:
            summary = character_summary_for_account(self.account, self.char1.pk)

        self.assertTrue(queries)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries))
        expected_stats = {**updated["stats"], "specialties": {"stealth": ["Quiet", "Dark"]}}
        self.assertEqual(summary["stats"], expected_stats)
        for key in ("vampire", "pools", "advantages"):
            self.assertEqual(summary[key], updated[key])
        self.assertEqual(summary["name"], "Current persisted name")
        self.assertEqual(summary["status"], {"earned": 4, "position": "Current persisted position", "total": 5})
        self.assertEqual(summary["boons"], {"owed": 5, "held": 8, "net": 3})
        self.assertEqual(self.char1.key, old_name)
        self.assertEqual(cached_attribute.value, old_stats)
        self.assertEqual(self.char1.db.stats, old_stats)
        self.assertEqual(status.earned_status, 1)
        self.assertEqual(position.name, "Old position")
        self.assertEqual(ledger.total_debt_weight, 1)

    def test_persisted_owner_transfer_denies_old_owner_and_reads_current_name(self):
        self.assertEqual(self.char1.account, self.account)
        self.assertIsNotNone(character_summary_for_account(self.account, self.char1.pk))
        ObjectDB.objects.filter(pk=self.char1.pk).update(db_account_id=self.account2.pk, db_key="Transferred name")

        self.assertEqual(self.char1.account, self.account)
        self.assertIsNone(character_summary_for_account(self.account, self.char1.pk))
        self.assertIsNone(character_chronicle_for_account(self.account, self.char1.pk))
        summary = character_summary_for_account(self.account2, self.char1.pk)
        self.assertEqual(summary["name"], "Transferred name")
        self.assertEqual(summary["id"], self.char1.pk)
        self.assertIsNotNone(character_chronicle_for_account(self.account2, self.char1.pk))

    def test_summary_uses_only_default_regular_attributes_and_plain_shapes(self):
        self.char1.db.stats = {"skills": {"stealth": 2}}
        self.char1.attributes.add("stats", {"private": "categorized"}, category="staff")
        self.char1.attributes.add("secret_staff_note", "Never projected")
        nick = Attribute.objects.create(
            db_key="stats", db_value=to_pickle({"private": "nick"}), db_model="objectdb", db_attrtype="nick"
        )
        self.char1.db_attributes.add(nick)

        summary = character_summary_for_account(self.account, self.char1.pk)

        self.assertEqual(summary["stats"], {"skills": {"stealth": 2}})
        self.assertNotIn("secret_staff_note", summary)
        self.assertEqual(set(summary), {"id", "name", "stats", "vampire", "pools", "advantages", "status", "boons"})

    def test_summary_rejects_embedded_object_and_session_references(self):
        for reference in (self.char2, ("__packed_session__", 1, 2)):
            with self.subTest(reference=type(reference).__name__):
                self.char1.db.stats = {"reference": reference}
                with self.assertRaisesMessage(TypeError, "Object and session references"):
                    character_summary_for_account(self.account, self.char1.pk)
