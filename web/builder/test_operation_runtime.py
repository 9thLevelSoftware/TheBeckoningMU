"""Durable builder claims, bounded callbacks and fail-closed restart fences."""

from collections import deque
from unittest import mock

from django.db import transaction
from evennia.accounts.models import AccountDB
from twisted.python.failure import Failure

from . import operation_runtime as runtime
from .models import BuilderOperationGuard, BuildProject
from .test_sandbox import SandboxTestBase


class StepClock:
    def __init__(self):
        self.callbacks = deque()

    def callLater(self, delay, callback):  # noqa: N802
        assert delay == 0
        self.callbacks.append(callback)

    def step(self):
        self.callbacks.popleft()()

    def drain(self):
        while self.callbacks:
            self.step()


class OperationRuntimeTests(SandboxTestBase):
    def setUp(self):
        self._reset_runtime()
        self.addCleanup(self._reset_runtime)
        super().setUp()
        self.project = self.approved_project()
        self.clock = StepClock()

    @staticmethod
    def _reset_runtime():
        runtime._recovered = False
        runtime._maintenance_hold = True
        runtime._fences = {}
        runtime._script_fences = {}
        runtime._connection_reservations = {}
        runtime._active_runner = None

    def claim(self, **kwargs):
        return runtime.claim_operation(
            self.project.pk, "build", self.owner, self.project.version,
            affected_ids=[self.plaza.pk], **kwargs,
        )

    def observe(self, operation, steps, compensate=None):
        outcome = []
        pending = runtime.run_steps(operation, steps, compensate, clock=self.clock)
        pending.addBoth(outcome.append)
        return pending, outcome

    def test_claim_and_replacement_callback_rollback_as_one_record_transaction(self):
        def callback(project):
            BuildProject.objects.filter(pk=project.pk).update(status="replacing")
            raise RuntimeError("root CAS refused")

        with self.assertRaisesRegex(RuntimeError, "root CAS refused"):
            self.claim(claim_callback=callback)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "approved")
        self.assertEqual(self.project.builder_operation, {})
        self.assertFalse(BuilderOperationGuard.objects.exclude(token="").exists())

    def test_global_claim_refuses_second_project_and_retains_first_token(self):
        operation = self.claim()
        other = self.approved_project()
        with self.assertRaisesRegex(runtime.OperationError, "Another builder operation"):
            runtime.claim_operation(other.pk, "build", self.owner, other.version)
        self.assertEqual(BuilderOperationGuard.objects.get(pk=1).token, operation.token)
        self.assertEqual(BuildProject.objects.get(pk=other.pk).builder_operation, {})

    def test_one_advance_per_callback_and_cancellation_waits_for_terminal_result(self):
        operation = self.claim()
        seen = []

        def steps():
            seen.append("first")
            yield
            seen.append("second")
            yield
            runtime.finish_operation(operation)
            return "terminal-result"

        pending, outcome = self.observe(operation, steps())
        self.assertEqual(seen, [])
        self.clock.step()
        self.assertEqual(seen, ["first"])
        pending.cancel()
        self.assertFalse(pending.called)
        self.assertEqual(outcome, [])
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))
        self.clock.step()
        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(outcome, [])
        self.clock.step()
        self.assertEqual(outcome, ["terminal-result"])
        self.assertFalse(runtime.object_is_fenced(self.plaza.pk))

    def test_mutation_authority_does_not_escape_callback_and_triggers_remain_suppressed(self):
        operation = self.claim()

        def steps():
            runtime.assert_mutation_allowed(self.plaza.pk)
            self.assertTrue(runtime.object_is_fenced(self.plaza.pk))
            yield
            runtime.finish_operation(operation)

        self.observe(operation, steps())
        self.clock.step()
        with self.assertRaises(runtime.OperationError):
            runtime.assert_mutation_allowed(self.plaza.pk)
        with self.assertRaises(runtime.OperationError):
            runtime.assert_mutation_allowed(None, target_ids=[self.plaza])
        runtime.assert_mutation_allowed(987654321)
        self.clock.drain()

    def test_stale_version_is_inert_and_never_runs_compensation(self):
        operation = self.claim()
        seen = []

        def steps():
            seen.append("first")
            yield
            seen.append("forbidden")

        def compensate(error):
            seen.append("forbidden compensation")
            yield

        _, outcome = self.observe(operation, steps(), compensate)
        self.clock.step()
        BuildProject.objects.filter(pk=self.project.pk).update(version=self.project.version + 1)
        self.clock.drain()
        self.assertEqual(seen, ["first"])
        self.assertIsInstance(outcome[0], Failure)
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))
        self.assertEqual(BuilderOperationGuard.objects.get(pk=1).token, operation.token)

    def test_revoked_persisted_authority_stops_forward_and_compensates_in_slices(self):
        operation = self.claim()
        seen = []

        def steps():
            seen.append("first")
            yield
            seen.append("forbidden")

        def compensate(error):
            seen.append("undo first")
            yield
            seen.append("undo second")
            runtime.finish_operation(operation, state="rolled_back")

        _, outcome = self.observe(operation, steps(), compensate)
        self.clock.step()
        AccountDB.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.clock.step()
        self.assertEqual(seen, ["first"])
        self.clock.step()
        self.assertEqual(seen, ["first", "undo first"])
        self.assertEqual(outcome, [])
        self.clock.step()
        self.assertEqual(seen, ["first", "undo first", "undo second"])
        self.assertIsInstance(outcome[0], Failure)
        self.assertIn("persisted active Builder", str(outcome[0].value))
        self.assertFalse(runtime.object_is_fenced(self.plaza.pk))

    def test_compensation_failure_retains_claim_and_original_error(self):
        operation = self.claim()

        def steps():
            raise RuntimeError("original failure")
            yield

        def compensate(error):
            yield
            raise RuntimeError("undo failed")

        _, outcome = self.observe(operation, steps(), compensate)
        self.clock.drain()
        self.assertEqual(str(outcome[0].value), "original failure")
        self.assertEqual(operation.envelope["state"], "failed")
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))

    def test_pending_creation_crash_survives_recovery_without_replay(self):
        operation = self.claim()
        runtime.creation_pending(operation, "room", "r-new", "typeclasses.rooms.Room")
        evidence = operation.envelope
        self._reset_runtime()
        self.assertFalse(runtime.recover_operation_fences())
        self.assertEqual(BuildProject.objects.get(pk=self.project.pk).builder_operation, evidence)
        self.assertTrue(runtime.object_is_fenced(987654321))
        with self.assertRaises(runtime.OperationError):
            runtime.assert_mutation_allowed(987654321)
        with self.assertRaises(runtime.OperationError):
            runtime.claim_operation(self.project.pk, "build", self.owner, self.project.version)

    def test_receipts_are_durable_and_extend_fence_before_next_step(self):
        from evennia.utils import create

        operation = self.claim()
        created = create.create_object("typeclasses.rooms.Room", key="New receipt room", nohome=True)
        runtime.creation_pending(operation, "room", "r-new", "typeclasses.rooms.Room")
        runtime.record_created(operation, created, "room", "r-new")
        envelope = BuildProject.objects.get(pk=self.project.pk).builder_operation
        self.assertIsNone(envelope["pending_creation"])
        self.assertEqual(envelope["receipts"][0]["object_id"], created.pk)
        self.assertEqual(envelope["receipts"][0]["typeclass"], "typeclasses.rooms.Room")
        self.assertEqual(envelope["receipts"][0]["expected_type"], "typeclasses.rooms.Room")
        self.assertIsNone(envelope["receipts"][0]["identity"]["db_account_id"])
        self._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        self.assertTrue(runtime.object_is_fenced(created.pk))
        self.assertFalse(runtime.object_is_fenced(987654321))

    def test_wrong_creation_type_cannot_clear_pending_marker(self):
        operation = self.claim()
        runtime.creation_pending(operation, "fixture", "f-new", "typeclasses.objects.Object")
        with self.assertRaisesRegex(runtime.OperationError, "matching typed identity"):
            runtime.record_created(operation, self.plaza, "fixture", "f-new")
        self.assertIsNotNone(operation.envelope["pending_creation"])
        self.assertEqual(operation.envelope["receipts"], [])

    def test_receipt_rejects_cross_namespace_pk_before_identity_lookup(self):
        from evennia.scripts.models import ScriptDB

        operation = self.claim()
        runtime.creation_pending(operation, "scripts", "r1:timer", "typeclasses.scripts.RoomTriggerScript")
        with mock.patch.object(ScriptDB.objects, "filter") as lookup:
            # ObjectDB and ScriptDB have independent sequences. An ObjectDB
            # instance cannot authorize a receipt for any equal-numbered timer.
            lookup.return_value.values.return_value.first.return_value = {
                "db_typeclass_path": "typeclasses.scripts.RoomTriggerScript", "db_obj_id": self.plaza.pk,
            }
            with self.assertRaisesRegex(runtime.OperationError, "identity namespace"):
                runtime.record_created(operation, self.plaza, "scripts", "r1:timer")
            lookup.assert_not_called()
        self.assertIsNotNone(operation.envelope["pending_creation"])
        self.assertEqual(operation.envelope["receipts"], [])

    def test_async_future_yield_fails_durably_instead_of_being_discarded(self):
        from concurrent.futures import Future

        operation = self.claim()
        continued = []

        def steps():
            yield Future()
            continued.append("unsafe continuation")
            runtime.finish_operation(operation)

        _, outcome = self.observe(operation, steps())
        self.clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(continued, [])
        self.assertEqual(operation.envelope["state"], "failed")
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))

    def test_directed_connection_reservation_preserves_other_room_traffic_and_recovers(self):
        # Keep the public plaza outside exact fences. Its named north slot is
        # reserved; occupants and every unrelated outgoing direction still work.
        operation = runtime.claim_operation(
            self.project.pk, "replacement", self.owner, self.project.version,
            connection_reservations=[{"room_id": self.plaza.pk, "names": ["north", "n"]}],
        )
        self.assertFalse(runtime.object_is_fenced(self.plaza.pk))
        runtime.assert_mutation_allowed(self.plaza.pk)
        runtime.assert_connection_allowed(self.plaza.pk, ["south", "s"])
        with self.assertRaises(runtime.OperationError):
            runtime.assert_connection_allowed(self.plaza.pk, ["North"])
        with self.assertRaises(runtime.OperationError):
            runtime.assert_connection_room_allowed(self.plaza.pk)
        with runtime.mutation_context(operation):
            runtime.assert_connection_allowed(self.plaza.pk, ["north"])
            runtime.assert_connection_room_allowed(self.plaza.pk)
        self._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        self.assertFalse(runtime.object_is_fenced(self.plaza.pk))
        with self.assertRaises(runtime.OperationError):
            runtime.assert_connection_allowed(self.plaza.pk, ["n"])
        with self.assertRaises(runtime.OperationError):
            runtime.assert_connection_room_allowed(self.plaza.pk)

    def test_malformed_and_orphaned_evidence_hold_globally(self):
        BuildProject.objects.filter(pk=self.project.pk).update(builder_operation={"token": "broken"})
        self.assertFalse(runtime.recover_operation_fences())
        self.assertTrue(runtime.object_is_fenced(987654321))
        BuildProject.objects.filter(pk=self.project.pk).update(builder_operation={})
        BuilderOperationGuard.objects.create(pk=1, token="orphan", project=self.project)
        self.assertFalse(runtime.recover_operation_fences())
        self.assertTrue(runtime.object_is_fenced(987654321))

    def test_post_publication_activation_failure_keeps_exact_fence_across_restart(self):
        operation = self.claim()

        def steps():
            BuildProject.objects.filter(pk=self.project.pk).update(status="live", version=self.project.version + 1)
            runtime.update_operation(operation, status="live", version=self.project.version + 1, phase="activation")
            yield
            raise RuntimeError("timer activation failed after publication")

        _, outcome = self.observe(operation, steps())
        self.clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        evidence = operation.envelope
        self.assertEqual(evidence["state"], "failed")
        self._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))
        self.assertFalse(runtime.object_is_fenced(987654321))
        self.assertEqual(BuildProject.objects.get(pk=self.project.pk).builder_operation, evidence)

    def test_real_nested_atomic_cannot_run_world_step(self):
        operation = self.claim()
        touched = []

        def steps():
            touched.append(True)
            yield

        with transaction.atomic(), self.assertRaisesRegex(runtime.OperationError, "inside a transaction"):
            runtime.drain_steps(operation, steps())
        self.assertEqual(touched, [])

    def test_sync_driver_preserves_generator_terminal_value(self):
        operation = self.claim()

        def steps():
            yield
            runtime.finish_operation(operation)
            return (True, "built")

        self.assertEqual(runtime.drain_steps(operation, steps()), (True, "built"))

    def test_return_without_terminal_record_fails_durably_and_retains_fence(self):
        operation = self.claim()

        def steps():
            yield
            return "premature"

        _, outcome = self.observe(operation, steps())
        self.clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(operation.envelope["state"], "failed")
        self.assertEqual(operation.envelope["phase"], "missing_terminal_record")
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))

    def test_terminal_evidence_read_outage_still_resolves_deferred(self):
        from django.db import OperationalError

        operation = self.claim()
        patcher = mock.patch.object(BuildProject.objects, "filter", side_effect=OperationalError("terminal read outage"))

        def steps():
            yield
            runtime.finish_operation(operation)
            patcher.start()
            return "finished before read outage"

        pending, outcome = self.observe(operation, steps())
        try:
            self.clock.drain()
        finally:
            patcher.stop()
        self.assertTrue(pending.called)
        self.assertIsInstance(outcome[0], Failure)
        self.assertIn("terminal read outage", str(outcome[0].value))
        self.assertIsNone(runtime._active_runner)
        self.assertEqual(BuildProject.objects.get(pk=self.project.pk).builder_operation["state"], "completed")

    def test_model_changes_to_claimed_project_are_refused_outside_step(self):
        operation = self.claim()
        self.project.name = "racing admin edit"
        with self.assertRaises(runtime.OperationError):
            self.project.save(update_fields=["name"])
        with self.assertRaises(runtime.OperationError):
            self.project.delete()
        with runtime.mutation_context(operation):
            self.project.name = "owned step edit"
            self.project.save(update_fields=["name"])

    def test_script_fences_have_separate_identity_namespace_and_recover(self):
        operation = self.claim(script_ids=[987654321])
        self.assertTrue(runtime.script_is_fenced(987654321))
        self.assertFalse(runtime.object_is_fenced(987654321))
        with self.assertRaises(runtime.OperationError):
            runtime.assert_script_mutation_allowed(987654321)
        with runtime.mutation_context(operation):
            runtime.assert_script_mutation_allowed(987654321)
            self.assertTrue(runtime.script_is_fenced(987654321))
        self._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        self.assertTrue(runtime.script_is_fenced(987654321))
        self.assertTrue(runtime.script_is_fenced(123456789, object_id=self.plaza.pk))

    def test_current_identity_and_custom_source_validator_are_rechecked(self):
        validate = mock.Mock()
        operation = self.claim(validate=validate)

        def steps():
            yield
            yield
            runtime.finish_operation(operation)

        self.observe(operation, steps())
        self.clock.step()
        self.assertEqual(validate.call_count, 1)
        changed = {**self.project.approved_map_data, "connection_direction": "south"}
        BuildProject.objects.filter(pk=self.project.pk).update(approved_map_data=changed)
        self.clock.drain()
        self.assertEqual(validate.call_count, 1)
        self.assertTrue(runtime.object_is_fenced(self.plaza.pk))
