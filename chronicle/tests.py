from evennia.utils.test_resources import EvenniaTest

from boons.utils import accept_boon, dispute_boon, offer_boon, uphold_boon
from chronicle.models import ChronicleEvent
from chronicle.read_services import character_summary_for_account
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

    def test_upheld_boon_records_safe_chronicle_event(self):
        success, boon, _message = offer_boon(self.char1, self.char2, "minor", "private favor details")
        self.assertTrue(success)
        accept_boon(boon.pk, self.char2)
        dispute_boon(boon.pk, "private dispute reason", self.char1)

        with self.captureOnCommitCallbacks(execute=True):
            success, _message = uphold_boon(boon.pk, "private ruling reason")

        self.assertTrue(success)
        event = ChronicleEvent.objects.get(kind="boon.upheld", source_id=str(boon.pk))
        self.assertEqual(event.payload, {"boon_type": "minor"})
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PUBLIC)
        self.assertNotIn("private", event.summary)

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
        self.assertContains(response, event.title)
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

    def test_character_summary_uses_live_boon_totals(self):
        success, boon, _message = offer_boon(self.char1, self.char2, "minor", "A favor")
        self.assertTrue(success)
        accept_boon(boon.pk, self.char2)

        summary = character_summary_for_account(self.char1.account, self.char1.pk)

        self.assertEqual(summary["boons"], {"owed": 2, "held": 0, "net": -2})
