"""Chronicle capture at authoritative domain transition boundaries."""

import threading
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import DatabaseError, transaction
from django.test import SimpleTestCase
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest

from bbs.commands import CmdBBSPost
from bbs.models import Board, Post
from jobs.commands import CmdJobClaim, CmdJobCreate, CmdJobDone, CmdJobReopen, CmdJobSubmit
from jobs.models import Bucket, Job
from status.models import CamarillaPosition, CharacterStatus, StatusRequest
from status.utils import assign_position, get_character_status, modify_earned_status, remove_position, set_earned_status
from web.builder.models import BuildProject
from web.builder.promotion import promote_project_to_live, run_in_main_thread
from web.builder.sandbox_builder import build_sandbox_area

from .models import ChronicleEvent


class JobTransitionCaptureTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.bucket = Bucket.objects.create(name="TransitionJobs", created_by=self.account)

    def create_job(self, **kwargs):
        return Job.objects.create(
            bucket=self.bucket,
            title="Private job title",
            description="Private job description",
            creator=self.account,
            **kwargs,
        )

    def test_create_claim_complete_and_reopen_capture_only_safe_transition_fields(self):
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
        job = self.create_job()
        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(Job, "save", side_effect=DatabaseError("job save failed")),
            self.assertRaisesMessage(DatabaseError, "job save failed"),
        ):
            self.call(CmdJobClaim(), str(job.sequence_number), caller=self.char2)
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

        def failed_apply(instance):
            original_apply(instance)
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

        def failed_apply(instance):
            original_apply(instance)
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

        def failed_apply(instance):
            original_apply(instance)
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


class BuilderTransitionCaptureTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.project = BuildProject.objects.create(user=self.account, name="Promoted area", status="built")
        built = build_sandbox_area(
            self.project.pk,
            {
                "rooms": {"first": {"name": "First live room"}, "second": {"name": "Second live room"}},
                "exits": {"path": {"source": "first", "target": "second", "name": "path"}},
            },
        )
        self.container_id = built["sandbox_room_id"]
        self.room_ids = set(built["room_map"].values())
        self.project.sandbox_room_id = self.container_id
        self.project.save(update_fields=["sandbox_room_id"])

    def promote(self):
        with (
            patch("web.builder.promotion.run_in_main_thread", side_effect=lambda callback: callback()),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return promote_project_to_live(self.project.pk, self.room2.pk, "n")

    def assert_review_preserved(self):
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "built")
        self.assertEqual(self.project.sandbox_room_id, self.container_id)
        self.assertIsNone(self.project.promoted_at)
        self.assertTrue(ObjectDB.objects.filter(pk=self.container_id).exists())
        self.assertFalse(ChronicleEvent.objects.filter(kind="builder.promoted").exists())

    def test_real_success_preserves_promoted_world_and_connects_actual_entry_room(self):
        success, result = self.promote()
        self.assertTrue(success, result)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "live")
        self.assertIsNone(self.project.sandbox_room_id)
        self.assertFalse(ObjectDB.objects.filter(pk=self.container_id).exists())
        self.assertEqual(ObjectDB.objects.filter(pk__in=self.room_ids).count(), 2)
        self.assertIn(result["entry_room_id"], self.room_ids)
        self.assertEqual(len(result["created_exits"]), 2)
        for exit_data in result["created_exits"]:
            self.assertTrue(ObjectDB.objects.filter(pk=exit_data["id"]).exists())
        event = ChronicleEvent.objects.get(kind="builder.promoted")
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.PUBLIC)
        self.assertEqual(event.status, ChronicleEvent.Status.DRAFT)
        self.assertEqual(event.payload, {"project_name": self.project.name})

    def test_private_project_emits_staff_metadata_without_project_name(self):
        self.project.is_public = False
        self.project.save(update_fields=["is_public"])
        success, result = self.promote()
        self.assertTrue(success, result)
        event = ChronicleEvent.objects.get(kind="builder.promoted")
        self.assertEqual(event.visibility, ChronicleEvent.Visibility.STAFF)
        self.assertEqual(event.payload, {})

    def test_invalid_connection_is_failure_without_success_event(self):
        with patch("web.builder.promotion.run_in_main_thread", side_effect=lambda callback: callback()):
            success, result = promote_project_to_live(self.project.pk, 99999999, "n")
        self.assertFalse(success)
        self.assertIn("not found", result["error"])
        self.assert_review_preserved()

    def test_partial_exit_failure_keeps_review_recovery_and_emits_no_success(self):
        calls = 0

        def fail_return_exit(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("return exit failed")
            return create_object(**kwargs)

        with patch("evennia.utils.create.create_object", side_effect=fail_return_exit):
            success, result = self.promote()
        self.assertFalse(success)
        self.assertTrue(result["recovery_required"])
        self.assertEqual(len(result["created_exits"]), 1)
        self.assertTrue(result["errors"])
        self.assert_review_preserved()

    def test_failed_status_finalization_does_not_delete_container_or_emit_success(self):
        with patch.object(BuildProject, "mark_live", side_effect=ValueError("state transition refused")):
            success, result = self.promote()
        self.assertFalse(success)
        self.assertTrue(result["recovery_required"])
        self.assert_review_preserved()


class PromotionDispatchTests(SimpleTestCase):
    def test_pending_finalization_with_populated_result_cannot_report_success(self):
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        callbacks = []
        failures = []

        def stalled_finalization():
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Test did not release finalization")
            raise RuntimeError("Finalization failed after the caller timed out")

        project = SimpleNamespace(
            status="built",
            sandbox_room_id=7,
            refresh_from_db=Mock(),
            mark_live=Mock(side_effect=stalled_finalization),
            save=Mock(),
        )

        def execute_callback():
            try:
                callbacks[0]()
            except BaseException as error:
                failures.append(error)

        # Construct the worker before replacing the promotion completion-event
        # factory; Thread itself owns a separate internal Event.
        worker = threading.Thread(target=execute_callback)

        def dispatch(callback):
            callbacks.append(callback)
            worker.start()

        def timeout_after_result_is_populated(timeout):
            self.assertTrue(started.wait(timeout=5), "Finalization did not start")
            return False

        with (
            patch("web.builder.models.BuildProject.objects.get", return_value=project),
            patch("web.builder.promotion.run_in_main_thread", side_effect=dispatch),
            patch("web.builder.promotion.threading.Event", return_value=completed),
            patch.object(completed, "wait", side_effect=timeout_after_result_is_populated),
            patch("web.builder.promotion.transaction.atomic", return_value=nullcontext()),
            patch("web.builder.promotion.logger.exception"),
            patch("web.builder.promotion._do_promotion_in_main_thread", return_value=(True, {"promoted_rooms": 2})),
            patch("chronicle.services.record_event") as record,
        ):
            try:
                success, result = promote_project_to_live(1, 2, "n")
                self.assertFalse(success)
                self.assertTrue(result["pending"])
                self.assertTrue(result["recovery_required"])
                self.assertFalse(completed.is_set())
                record.assert_not_called()
                project.save.assert_not_called()
            finally:
                release.set()
                worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(completed.is_set())

    def test_off_reactor_caller_queues_without_mutating_on_the_calling_thread(self):
        callback = Mock()
        with (
            patch("web.builder.promotion.isInIOThread", return_value=False),
            patch("web.builder.promotion.reactor.running", True),
            patch("web.builder.promotion.reactor.callFromThread") as dispatch,
        ):
            run_in_main_thread(callback)
        callback.assert_not_called()
        dispatch.assert_called_once_with(callback)

    def test_reactor_caller_executes_inline_without_queueing(self):
        callback = Mock()
        with (
            patch("web.builder.promotion.isInIOThread", return_value=True),
            patch("web.builder.promotion.reactor.callFromThread") as dispatch,
        ):
            run_in_main_thread(callback)
        callback.assert_called_once_with()
        dispatch.assert_not_called()

    def test_stopped_reactor_rejects_promotion_dispatch(self):
        callback = Mock()
        with (
            patch("web.builder.promotion.isInIOThread", return_value=False),
            patch("web.builder.promotion.reactor.running", False),
            patch("web.builder.promotion.reactor.callFromThread") as dispatch,
            self.assertRaisesMessage(RuntimeError, "game reactor is not running"),
        ):
            run_in_main_thread(callback)
        callback.assert_not_called()
        dispatch.assert_not_called()
