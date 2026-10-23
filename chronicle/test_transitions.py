"""Chronicle capture at authoritative domain transition boundaries."""

from unittest.mock import patch

from django.db import DatabaseError, transaction
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from bbs.commands import CmdBBSPost
from bbs.models import Board, Post
from boons.models import Boon
from boons.utils import (
    accept_boon,
    acknowledge_boon,
    call_in_boon,
    decline_boon,
    dispute_boon,
    fulfill_boon,
    offer_boon,
    uphold_boon,
)
from jobs.commands import CmdJobClaim, CmdJobCreate, CmdJobDone, CmdJobReopen, CmdJobSubmit
from jobs.models import Bucket, Job
from status.models import CamarillaPosition, CharacterStatus, StatusRequest
from status.utils import assign_position, get_character_status, modify_earned_status, remove_position, set_earned_status
from traits.models import CharacterBio
from web.builder import promotion, test_sandbox
from web.builder.models import BuildProject

from .models import ChronicleEvent


class JobTransitionCaptureTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.bucket = Bucket.objects.create(name="TransitionJobs", created_by=self.account)
        CharacterBio.objects.create(character=self.char1, account=self.account, status="approved")
        CharacterBio.objects.create(character=self.char2, account=self.account2, status="approved")

    def create_job(self, **kwargs):
        return Job.objects.create(
            bucket=self.bucket,
            title="Private job title",
            description="Private job description",
            creator=self.account,
            **kwargs,
        )

    def test_create_claim_complete_and_reopen_capture_only_safe_transition_fields(self):
        self.account2.permissions.add("Builder")
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobSubmit(), "TransitionJobs Private title = Private body")
        job = Job.objects.get(bucket=self.bucket)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobClaim(), str(job.sequence_number), caller=self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobDone(), str(job.sequence_number), caller=self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobReopen(), str(job.sequence_number))

        events = ChronicleEvent.objects.filter(source_app="jobs", source_id=str(job.pk)).order_by("created_at")
        self.assertEqual(
            list(events.values_list("kind", flat=True)), ["job.created", "job.claimed", "job.completed", "job.reopened"]
        )
        for event in events:
            self.assertEqual(event.status, ChronicleEvent.Status.DRAFT)
            self.assertEqual(set(event.payload), {"job_state", "job_priority"})
            self.assertNotIn("Private", event.summary)
            self.assertNotIn("Private", event.title)
        created, claimed, completed, reopened = events
        self.assertCountEqual(created.participants.all(), [self.char1])
        for event in (claimed, completed):
            self.assertCountEqual(event.participants.all(), [self.char1, self.char2])
            self.assertEqual(event.visibility, ChronicleEvent.Visibility.PARTICIPANTS)
        self.assertEqual(completed.payload["job_state"], "CLOSED")
        self.assertEqual(reopened.visibility, ChronicleEvent.Visibility.STAFF)
        job.refresh_from_db()
        self.assertEqual((job.status, job.completed), ("OPEN", False))

    def test_admin_creation_captures_one_private_draft(self):
        self.assertTrue(CmdJobCreate().access(self.char1, "cmd"))
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobCreate(), "TransitionJobs Private admin title = Private staff details")
        event = ChronicleEvent.objects.get(kind="job.created")
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PARTICIPANTS)
        self.assertCountEqual(event.participants.all(), [self.char1])
        self.assertNotIn("Private", str(event.payload))

    def test_job_participants_follow_application_ownership_not_current_puppeteer(self):
        self.char2.account = self.account
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobCreate(), "TransitionJobs Private admin title = Private staff details")
        event = ChronicleEvent.objects.get(kind="job.created")
        self.assertCountEqual(event.participants.all(), [self.char1])

    def test_rejected_claim_completion_and_reopen_emit_no_events(self):
        job = self.create_job()
        self.assertFalse(CmdJobCreate().access(self.char2, "cmd"))
        self.assertFalse(CmdJobReopen().access(self.char2, "cmd"))
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdJobDone(), str(job.sequence_number), caller=self.char2)
            self.call(CmdJobReopen(), str(job.sequence_number))
            self.call(CmdJobSubmit(), "MissingBucket Private title = body")
            job.players.add(self.account)
            self.call(CmdJobClaim(), str(job.sequence_number), caller=self.char2)
        self.assertFalse(ChronicleEvent.objects.exists())
        job.refresh_from_db()
        self.assertEqual((job.status, job.completed), ("OPEN", False))
        self.assertCountEqual(job.players.all(), [self.account])

    def test_failed_claim_save_rolls_back_assignment_and_emits_no_event(self):
        self.account2.permissions.add("Builder")
        self.assertTrue(CmdJobClaim().access(self.char2, "cmd"))
        job = self.create_job()
        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(Job, "save", side_effect=DatabaseError("job save failed")),
            self.assertRaisesMessage(DatabaseError, "job save failed"),
        ):
            self.call(CmdJobClaim(), job.ref, caller=self.char2)
        self.assertFalse(job.players.exists())
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_rolled_back_source_transitions_emit_no_events(self):
        job = self.create_job()
        for command in (CmdJobClaim(), CmdJobDone(), CmdJobReopen(), CmdJobSubmit()):
            if isinstance(command, CmdJobReopen):
                job.completed = True
                job.status = "CLOSED"
                job.save()
            arguments = (
                "TransitionJobs Rollback title = Rollback body"
                if isinstance(command, CmdJobSubmit)
                else str(job.sequence_number)
            )
            with (
                self.captureOnCommitCallbacks(execute=True),
                self.assertRaisesMessage(RuntimeError, "source rollback"),
                transaction.atomic(),
            ):
                self.call(command, arguments)
                raise RuntimeError("source rollback")
        self.assertEqual(Job.objects.count(), 1)
        self.assertFalse(job.players.exists())
        self.assertFalse(ChronicleEvent.objects.exists())


class BoonTransitionCaptureTests(EvenniaCommandTest):
    def test_offer_captures_metadata_after_witnesses_and_rejected_offer_emits_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(offer_boon(self.char1, self.char1, "minor", "Invalid")[0])
            self.assertFalse(ChronicleEvent.objects.exists())
            success, boon, _ = offer_boon(
                self.char1, self.char2, "major", "Private favour details", witnesses=[self.char1]
            )
        self.assertTrue(success)
        self.assertCountEqual(boon.witnesses.all(), [self.char1])
        event = ChronicleEvent.objects.get(kind="boon.offered")
        self.assertEqual(event.payload, {"boon_type": "major"})
        self.assertEqual(event.visibility, "public")
        self.assertEqual(event.occurred_at, boon.created_date)
        self.assertCountEqual(event.participants.all(), [self.char1, self.char2])
        self.assertNotIn("Private favour details", event.title + event.summary + str(event.payload))

    def test_decline_and_call_in_capture_only_successful_creditor_transitions(self):
        declined = Boon.objects.create(debtor=self.char1, creditor=self.char2, is_public=False)
        called = Boon.objects.create(debtor=self.char1, creditor=self.char2, status="accepted")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(decline_boon(declined.pk, "Private reason", self.char1)[0])
            self.assertFalse(call_in_boon(called.pk, "Private request", self.char1)[0])
        self.assertFalse(ChronicleEvent.objects.exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(decline_boon(declined.pk, "Private reason", self.char2)[0])
            self.assertFalse(decline_boon(declined.pk, "Again", self.char2)[0])
            self.assertTrue(call_in_boon(called.pk, "Private request", self.char2)[0])
            self.assertFalse(call_in_boon(called.pk, "Again", self.char2)[0])
        self.assertEqual(ChronicleEvent.objects.count(), 2)
        event = ChronicleEvent.objects.get(kind="boon.declined")
        self.assertEqual(event.visibility, "participants")
        self.assertEqual(event.payload, {"boon_type": "minor"})
        event = ChronicleEvent.objects.get(kind="boon.called_in")
        self.assertEqual(event.occurred_at, called.called_in_date)
        self.assertEqual(event.payload, {"boon_type": "minor"})
        self.assertNotIn("Private", event.summary + str(event.payload))

    def test_repeated_acknowledgement_retains_main_result_without_duplicate_event(self):
        boon = Boon.objects.create(debtor=self.char1, creditor=self.char2, is_public=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(acknowledge_boon(boon.pk, self.char1)[0])
            self.assertTrue(acknowledge_boon(boon.pk, self.char1)[0])
        event = ChronicleEvent.objects.get(kind="boon.acknowledged")
        self.assertEqual(event.visibility, "participants")
        self.assertEqual(event.actor, self.char1.account)
        self.assertEqual(event.payload, {"boon_type": "minor"})
        self.assertCountEqual(event.participants.all(), [self.char1, self.char2])

    def test_consent_and_two_party_fulfilment_capture_only_final_transitions(self):
        boon = Boon.objects.create(debtor=self.char1, creditor=self.char2, boon_type="minor", is_public=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(accept_boon(boon.pk, self.char1)[0])
            self.assertFalse(ChronicleEvent.objects.exists())
            self.assertTrue(accept_boon(boon.pk, self.char2)[0])
            self.assertFalse(accept_boon(boon.pk, self.char2)[0])
        accepted = ChronicleEvent.objects.get(kind="boon.accepted")
        self.assertEqual(accepted.visibility, "participants")
        self.assertCountEqual(accepted.participants.all(), [self.char1, self.char2])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(call_in_boon(boon.pk, "Private request", self.char2)[0])
            self.assertTrue(fulfill_boon(boon.pk, "Private confirmation", self.char1)[0])
        self.assertFalse(ChronicleEvent.objects.filter(kind="boon.fulfilled").exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(fulfill_boon(boon.pk, "Confirmed", self.char2)[0])
            self.assertFalse(fulfill_boon(boon.pk, "Again", self.char2)[0])
        event = ChronicleEvent.objects.get(kind="boon.fulfilled")
        self.assertEqual(event.payload, {"boon_type": "minor"})
        self.assertNotIn("Private", str(event.payload) + event.summary)

    def test_upheld_dispute_cannot_generate_second_dispute_event(self):
        boon = Boon.objects.create(debtor=self.char1, creditor=self.char2, status="accepted")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(dispute_boon(boon.pk, "Private objection", self.char2)[0])
            self.assertTrue(uphold_boon(boon.pk, "Stands", self.char1)[0])
            self.assertFalse(dispute_boon(boon.pk, "Again", self.char2)[0])
        self.assertEqual(ChronicleEvent.objects.filter(kind="boon.disputed").count(), 1)
        boon.refresh_from_db()
        self.assertEqual(boon.status, "accepted")


class BBSTransitionCaptureTests(EvenniaCommandTest):
    def post(self, board, *, switches=""):
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdBBSPost(), f"{switches}{board.name}=Public title/Raw private body must never be copied")

    def test_public_ic_post_captures_metadata_without_raw_body(self):
        board = Board.objects.create(name="PublicIC", is_ic=True)
        self.post(board)
        post = Post.objects.get(board=board)
        event = ChronicleEvent.objects.get(kind="bbs.posted")
        self.assertEqual(event.source_id, str(post.pk))
        self.assertEqual(event.status, ChronicleEvent.Status.DRAFT)
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PUBLIC)
        self.assertEqual(event.payload, {"board": board.name, "post_title": "Public title"})
        self.assertNotIn(post.body, str(event.payload) + event.title + event.summary)
        self.assertFalse(event.participants.exists())

    def test_private_ooc_and_flag_scoped_boards_are_excluded(self):
        self.char1.db.flags = {"eligible": True}
        for name, fields in (
            ("OOC", {"is_ic": False}),
            ("StaffIC", {"is_ic": True, "read_perm": "Builder"}),
            ("FlagIC", {"is_ic": True, "required_flags": "eligible"}),
        ):
            with self.subTest(board=name):
                board = Board.objects.create(name=name, **fields)
                self.post(board)
                self.assertTrue(Post.objects.filter(board=board).exists())
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_post_specific_read_restriction_is_excluded(self):
        board = Board.objects.create(name="RestrictedPost", is_ic=True)
        original_create = Post.objects.create

        def restricted_create(**kwargs):
            return original_create(**kwargs, read_perm="Builder")

        with patch.object(Post.objects, "create", side_effect=restricted_create):
            self.post(board)
        self.assertTrue(Post.objects.filter(board=board).exists())
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_denied_post_and_rolled_back_post_emit_no_events(self):
        board = Board.objects.create(name="DeniedIC", is_ic=True, write_perm="Developer")
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdBBSPost(), f"{board.name}=Title/Body", caller=self.char2)
        self.assertFalse(Post.objects.exists())
        board.write_perm = ""
        board.save()
        with (
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaisesMessage(RuntimeError, "post rollback"),
            transaction.atomic(),
        ):
            self.call(CmdBBSPost(), f"{board.name}=Title/Body")
            raise RuntimeError("post rollback")
        self.assertFalse(Post.objects.exists())
        self.assertFalse(ChronicleEvent.objects.exists())


class StatusTransitionCaptureTests(EvenniaCommandTest):
    def test_invalid_positions_requirements_and_noop_changes_emit_no_events(self):
        CharacterStatus.objects.create(character=self.char1)
        CamarillaPosition.objects.create(name="HighStatus", requires_status=3)
        CamarillaPosition.objects.create(name="ClanOnly", requires_clan="Tremere")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(assign_position(self.char1, "Missing")[0])
            self.assertFalse(assign_position(self.char1, "HighStatus")[0])
            self.assertFalse(assign_position(self.char1, "ClanOnly")[0])
            self.assertFalse(remove_position(self.char1)[0])
            set_earned_status(self.char1, 0)
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_failed_unique_assignment_restores_old_holder_and_emits_no_events(self):
        position = CamarillaPosition.objects.create(name="UniquePosition", is_unique=True, status_granted=2)
        old = CharacterStatus.objects.create(character=self.char1, position=position, position_status=2)
        new = CharacterStatus.objects.create(character=self.char2)
        original_save = CharacterStatus.save

        def fail_new_holder(instance, *args, **kwargs):
            if instance.pk == new.pk and instance.position_id == position.pk:
                raise DatabaseError("new holder failed")
            return original_save(instance, *args, **kwargs)

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(CharacterStatus, "save", new=fail_new_holder),
            self.assertRaisesMessage(DatabaseError, "new holder failed"),
        ):
            assign_position(self.char2, position.name, assigned_by=self.char1)
        persisted = CharacterStatus.objects.filter(pk=old.pk).values("position_id", "position_status").get()
        self.assertEqual(persisted, {"position_id": position.pk, "position_status": 2})
        self.assertFalse(CharacterStatus.objects.filter(pk=new.pk, position=position).exists())
        self.assertIs(get_character_status(self.char1), old)
        self.assertIs(get_character_status(self.char2), new)
        self.assertIs(old.position, position)
        self.assertEqual(old.position_status, 2)
        self.assertEqual(old.status_history, [])
        self.assertIsNone(new.position)
        self.assertEqual(new.position_status, 0)
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_failed_status_request_application_rolls_back_review_and_character_change(self):
        status = CharacterStatus.objects.create(character=self.char1, earned_status=1)
        request = StatusRequest.objects.create(character=self.char1, request_type="earned_status", requested_change=2)
        original_apply = StatusRequest._apply_change

        def failed_apply(instance, staff_member):
            original_apply(instance, staff_member)
            raise DatabaseError("status application failed")

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(StatusRequest, "_apply_change", new=failed_apply),
            self.assertRaisesMessage(DatabaseError, "status application failed"),
        ):
            request.approve(self.char2)
        self.assertEqual(StatusRequest.objects.filter(pk=request.pk).values_list("status", flat=True).get(), "pending")
        self.assertEqual(CharacterStatus.objects.filter(pk=status.pk).values_list("earned_status", flat=True).get(), 1)
        self.assertIs(StatusRequest.objects.get(pk=request.pk), request)
        self.assertIs(get_character_status(self.char1), status)
        self.assertEqual(request.status, "pending")
        self.assertIsNone(request.reviewed_by)
        self.assertIsNone(request.resolved_date)
        self.assertEqual(status.earned_status, 1)
        self.assertEqual(status.status_history, [])
        self.assertFalse(ChronicleEvent.objects.exists())

    def test_failed_approval_retry_applies_change_once_to_same_cached_objects(self):
        status = CharacterStatus.objects.create(character=self.char1, earned_status=1)
        request = StatusRequest.objects.create(character=self.char1, request_type="earned_status", requested_change=2)
        original_apply = StatusRequest._apply_change

        def failed_apply(instance, staff_member):
            original_apply(instance, staff_member)
            raise DatabaseError("approval interrupted after applying")

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(StatusRequest, "_apply_change", new=failed_apply),
            self.assertRaisesMessage(DatabaseError, "approval interrupted"),
        ):
            request.approve(self.char2)
        retry_request = StatusRequest.objects.get(pk=request.pk, status="pending")
        self.assertIs(retry_request, request)
        self.assertIs(get_character_status(self.char1), status)
        with self.captureOnCommitCallbacks(execute=True):
            retry_request.approve(self.char2)
        self.assertEqual(status.earned_status, 3)
        self.assertEqual(len(status.status_history), 1)
        self.assertEqual(request.status, "approved")
        event = ChronicleEvent.objects.get(kind="status.request_approved")
        self.assertEqual(event.payload, {"old_value": 1, "new_value": 3})
        self.assertEqual(CharacterStatus.objects.filter(pk=status.pk).values_list("earned_status", flat=True).get(), 3)

    def test_rolled_back_new_status_is_evicted_without_flushing_unrelated_instances(self):
        unrelated = CharacterStatus.objects.create(character=self.char2, earned_status=4)
        request = StatusRequest.objects.create(character=self.char1, request_type="earned_status", requested_change=2)
        created = []
        original_apply = StatusRequest._apply_change

        def failed_apply(instance, staff_member):
            original_apply(instance, staff_member)
            status = get_character_status(instance.character)
            created.append((status, status.pk))
            raise DatabaseError("new row interrupted")

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(StatusRequest, "_apply_change", new=failed_apply),
            self.assertRaisesMessage(DatabaseError, "new row interrupted"),
        ):
            request.approve(self.char2)
        rolled_back, old_id = created[0]
        self.assertFalse(CharacterStatus.objects.filter(character=self.char1).exists())
        self.assertIsNone(CharacterStatus.get_cached_instance(old_id))
        self.assertIsNone(rolled_back.pk)
        self.assertTrue(rolled_back._state.adding)
        self.assertIs(CharacterStatus.get_cached_instance(unrelated.pk), unrelated)
        self.assertEqual(unrelated.earned_status, 4)
        with self.captureOnCommitCallbacks(execute=True):
            request.approve(self.char2)
        current = get_character_status(self.char1)
        self.assertIsNot(current, rolled_back)
        self.assertEqual(current.earned_status, 2)
        self.assertEqual(len(current.status_history), 1)

    def test_nested_modify_failure_restores_cache_and_does_not_leak_tracker(self):
        status = CharacterStatus.objects.create(character=self.char1, earned_status=1)
        with (
            patch("chronicle.services.record_event", side_effect=RuntimeError("recording interrupted")),
            self.assertRaisesMessage(RuntimeError, "recording interrupted"),
        ):
            modify_earned_status(self.char1, 2)
        self.assertIs(get_character_status(self.char1), status)
        self.assertEqual(status.earned_status, 1)
        self.assertEqual(status.status_history, [])
        with self.captureOnCommitCallbacks(execute=True):
            set_earned_status(self.char1, 2)
        self.assertEqual(status.earned_status, 2)
        self.assertEqual(len(status.status_history), 1)
        self.assertEqual(ChronicleEvent.objects.get(kind="status.changed").payload, {"old_value": 1, "new_value": 2})


class BuilderTransitionCaptureTests(test_sandbox.SandboxTestBase):
    def setUp(self):
        super().setUp()
        self.project = self.built_project(map_data=test_sandbox.area_map(entry=2))
        self.record = self.project.built_object_ids.copy()
        self.room_ids = set(self.record["rooms"].values())
        self.objects = self.recorded_objects(self.project)
        self.objects_before = ObjectDB.objects.count()

    def promote(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return promotion.promote_project_to_live(self.project.pk, **kwargs)

    def assert_review_preserved(self):
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "built")
        self.assertEqual(self.project.built_object_ids, self.record)
        self.assertEqual(self.project.sandbox_room_id, self.record["entry"])
        self.assertIsNone(self.project.promoted_at)
        self.assertEqual(ObjectDB.objects.count(), self.objects_before)
        for obj in self.objects:
            self.assertTrue(obj.tags.has("sandbox"), obj)
            self.assertTrue(obj.tags.has(f"project_{self.project.pk}"), obj)
        self.assertFalse(ChronicleEvent.objects.filter(kind="builder.promoted").exists())

    def test_real_success_preserves_promoted_world_and_connects_reviewed_entry_room(self):
        success, result = self.promote()
        self.assertTrue(success, result)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "live")
        self.assertEqual(self.project.built_object_ids, {})
        self.assertIsNone(self.project.sandbox_room_id)
        self.assertEqual(ObjectDB.objects.filter(pk__in=self.room_ids).count(), 2)
        self.assertEqual(result["entry_room_id"], self.record["entry"])
        self.assertEqual(len(result["created_exits"]), 2)
        for obj in self.objects:
            self.assertFalse(obj.tags.has("sandbox"))
            self.assertFalse(obj.tags.has(f"project_{self.project.pk}"))
        for exit_data in result["created_exits"]:
            self.assertTrue(ObjectDB.objects.filter(pk=exit_data["id"]).exists())
        event = ChronicleEvent.objects.get(kind="builder.promoted")
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PUBLIC)
        self.assertEqual(event.status, ChronicleEvent.Status.DRAFT)
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.payload, {"project_name": self.project.name})
        self.assertEqual(
            event.idempotency_key,
            f"builder:{self.project.pk}:builder.promoted:{self.project.promoted_at.isoformat()}",
        )
        self.assertEqual(event.occurred_at, self.project.promoted_at)
        self.assertFalse(self.promote()[0])
        self.assertEqual(ChronicleEvent.objects.filter(kind="builder.promoted").count(), 1)

    def test_private_project_emits_staff_metadata_without_project_name(self):
        self.project.is_public = False
        self.project.save(update_fields=["is_public"])
        success, result = self.promote()
        self.assertTrue(success, result)
        event = ChronicleEvent.objects.get(kind="builder.promoted")
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.STAFF)
        self.assertEqual(event.payload, {})

    def test_connection_different_from_review_is_refused_without_success_event(self):
        success, result = self.promote(connection_room_id=self.plaza.pk, connection_direction="s")
        self.assertFalse(success)
        self.assertEqual(result["status"], 409)
        self.assertIn("reviewed", result["error"])
        self.assert_review_preserved()

    def test_partial_exit_failure_compensates_and_emits_no_success_event(self):
        calls = 0
        create_exit = promotion._create_connection_exit

        def fail_return_exit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("return exit failed")
            return create_exit(*args, **kwargs)

        with (
            patch.object(promotion, "_create_connection_exit", side_effect=fail_return_exit),
            self.assertLogs("web.builder.promotion", level="ERROR"),
        ):
            success, result = self.promote()
        self.assertFalse(success)
        self.assertIn("return exit failed", result["error"])
        self.assertEqual(calls, 2)
        self.assertEqual(self.plaza.contents, [])
        self.assert_review_preserved()

    def test_failed_status_finalization_restores_sandbox_and_emits_no_success(self):
        queryset_type = type(BuildProject.objects.all())
        original_update = queryset_type.update

        def fail_finalization(queryset, **kwargs):
            if queryset.model is BuildProject and kwargs.get("status") == "live":
                raise RuntimeError("state transition refused")
            return original_update(queryset, **kwargs)

        with (
            patch.object(queryset_type, "update", new=fail_finalization),
            self.assertLogs("web.builder.promotion", level="ERROR"),
        ):
            success, result = self.promote()
        self.assertFalse(success)
        self.assertIn("state transition refused", result["error"])
        self.assertEqual(self.plaza.contents, [])
        self.assert_review_preserved()

    def test_capture_failure_keeps_committed_live_world_and_does_not_run_compensation(self):
        with (
            patch("chronicle.services.record_event", side_effect=RuntimeError("capture unavailable")),
            self.assertLogs("web.builder.promotion", level="ERROR") as logs,
        ):
            success, result = self.promote()
        self.assertTrue(success, result)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "live")
        self.assertEqual(self.project.built_object_ids, {})
        self.assertEqual(len(result["created_exits"]), 2)
        for obj in self.objects:
            self.assertFalse(obj.tags.has("sandbox"))
            self.assertFalse(obj.tags.has(f"project_{self.project.pk}"))
        self.assertIn("Chronicle capture failed", logs.records[0].getMessage())
        self.assertFalse(ChronicleEvent.objects.filter(kind="builder.promoted").exists())
