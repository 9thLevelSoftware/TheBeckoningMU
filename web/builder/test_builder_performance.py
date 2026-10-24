"""Bound fresh replacement authority reads without weakening drift checks."""

from collections import deque
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from evennia.utils.idmapper.models import flush_cache

from web.builder import live_replacement, operation_runtime, promotion, sandbox_builder
from web.builder.models import BuildProject
from web.builder.revisions import fork_replacement
from web.builder.test_sandbox import SandboxTestBase, area_map


class ReplacementReadBudgetTests(SandboxTestBase):
    def setUp(self):
        self.reset_operation_runtime()
        self.addCleanup(self.reset_operation_runtime)
        self.addCleanup(flush_cache)
        super().setUp()

    @staticmethod
    def reset_operation_runtime():
        operation_runtime._recovered = False
        operation_runtime._maintenance_hold = True
        operation_runtime._fences = {}
        operation_runtime._script_fences = {}
        operation_runtime._connection_reservations = {}
        operation_runtime._active_runner = None

    class StepClock:
        def __init__(self):
            self.callbacks = deque()

        def callLater(self, delay, callback):  # noqa: N802 - Twisted clock protocol
            self.callbacks.append(callback)

        def step(self):
            self.callbacks.popleft()()

        def drain(self):
            steps = 0
            while self.callbacks:
                self.step()
                steps += 1
                if steps > 10000:
                    raise AssertionError("Operation did not reach terminal outcome")

    def observe(self, pending):
        outcome = []
        pending.addBoth(outcome.append)
        return outcome

    def source(self):
        data = area_map(20, timed_rooms=(1, 20))
        data["objects"] = {
            "f0": {"prototype_id": "wooden_chair", "prototype_revision": 1, "room_id": "r1"},
            "f1": {"prototype_id": "wooden_table", "prototype_revision": 1, "room_id": "r20"},
        }
        source = BuildProject.objects.create(
            user=self.owner,
            name="Fresh read budget",
            map_data=data,
            connection_room_id=self.plaza.pk,
            connection_direction="n",
        )
        source.submit()
        source.approve(self.builder2, source.version)
        sandbox_builder.build_unit(source.pk)
        promotion.promote_unit(source.pk)
        source.refresh_from_db()
        return source

    def candidate_with_exit_descriptions(self, source):
        candidate = fork_replacement(source.pk, self.owner, source.version)
        for exit_data in candidate.map_data["exits"].values():
            exit_data["description"] = "Reviewed new passage"
        candidate.map_data["rooms"]["r1"]["description"] = "Reviewed existing description"
        candidate.save(update_fields=["map_data"])
        candidate.submit()
        candidate.approve(self.builder2, candidate.version)
        return candidate

    def test_cooperative_build_yields_with_durable_receipts_and_waits_for_activation(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.models import ScriptDB
        from twisted.python.failure import Failure

        project = self.approved_project(area_map(3, timed_rooms=(1, 3)))
        clock = self.StepClock()
        pending = sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock)
        outcome = self.observe(pending)
        self.assertFalse(outcome)
        clock.step()
        project.refresh_from_db()
        self.assertEqual(len(project.builder_operation["receipts"]), 1)
        first_id = project.builder_operation["receipts"][0]["object_id"]
        self.assertTrue(operation_runtime.object_is_fenced(first_id))
        self.assertFalse(outcome)
        while project.builder_operation.get("phase") != "activation" and clock.callbacks:
            clock.step()
            project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertFalse(outcome)
        for script in ScriptDB.objects.filter(db_obj_id__in=project.built_object_ids["rooms"].values()):
            self.assertTrue(script.db._manually_paused)
        clock.drain()
        self.assertEqual(len(outcome), 1)
        self.assertNotIsInstance(outcome[0], Failure)
        self.assertEqual(outcome[0]["room_count"], 3)
        self.assertFalse(operation_runtime.object_is_fenced(ObjectDB.objects.get(pk=first_id)))
        project.refresh_from_db()
        self.assertEqual(project.builder_operation["state"], "completed")

    def test_cooperative_build_revocation_compensates_and_releases_fence(self):
        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB
        from twisted.python.failure import Failure

        project = self.approved_project(area_map(3))
        before = set(ObjectDB.objects.values_list("pk", flat=True))
        clock = self.StepClock()
        pending = sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock)
        outcome = self.observe(pending)
        clock.step()
        AccountDB.objects.filter(pk=self.owner.pk).update(is_active=False)
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(set(ObjectDB.objects.values_list("pk", flat=True)), before)
        project.refresh_from_db()
        self.assertEqual(project.status, "approved")
        self.assertEqual(project.builder_operation["state"], "rolled_back")
        operation_runtime.require_idle()

    def test_cooperative_build_activation_failure_keeps_published_sandbox_and_fence(self):
        from evennia.scripts.models import ScriptDB
        from twisted.python.failure import Failure

        project = self.approved_project(area_map(2, timed_rooms=(1,)))
        clock = self.StepClock()
        pending = sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock)
        outcome = self.observe(pending)
        while project.builder_operation.get("phase") != "activation" and clock.callbacks:
            clock.step()
            project.refresh_from_db()
        script = ScriptDB.objects.get(pk=project.built_object_ids["scripts"][0])
        with mock.patch.object(script, "unpause", side_effect=RuntimeError("activation failed")):
            clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertTrue(project.built_object_ids["rooms"])
        self.assertEqual(project.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(project.sandbox_room_id))

    def test_cooperative_replacement_retains_ids_and_terminal_result(self):
        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        clock = self.StepClock()
        pending = live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        outcome = self.observe(pending)
        clock.step()
        self.assertFalse(outcome)
        self.assertTrue(operation_runtime.object_is_fenced(source.live_manifest["rooms"]["r1"]["object_id"]))
        clock.drain()
        self.assertNotIsInstance(outcome[0], Failure, str(outcome[0]))
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(candidate.status, "live")
        self.assertEqual(
            candidate.live_manifest["rooms"],
            {
                key: {**entry, "provenance": candidate.live_manifest["rooms"][key]["provenance"]}
                for key, entry in source.live_manifest["rooms"].items()
            },
        )
        self.assertEqual(source.current_live_revision_id, candidate.pk)
        self.assertEqual(candidate.builder_operation["state"], "completed")

    def test_cooperative_replacement_raw_drift_is_preserved_and_fence_retained(self):
        from evennia.objects.models import ObjectDB
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle
        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        attr = room.attributes.get("desc", return_obj=True)
        clock = self.StepClock()
        pending = live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        outcome = self.observe(pending)
        clock.step()
        Attribute.objects.filter(pk=attr.pk).update(db_value=to_pickle("External persisted drift"))
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(
            Attribute.objects.filter(pk=attr.pk).values_list("db_value", flat=True).get(), "External persisted drift"
        )
        self.assertEqual(room.db.desc, "External persisted drift")
        source.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(source.status, "live")
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertEqual(candidate.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(room))

    def test_cooperative_replacement_prepublication_failure_restores_world_and_releases_fence(self):
        from evennia.objects.models import ObjectDB
        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        clock = self.StepClock()
        pending = live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        outcome = self.observe(pending)
        with mock.patch.object(
            live_replacement,
            "_checkpoint",
            side_effect=lambda phase: (
                (_ for _ in ()).throw(RuntimeError("injected apply failure")) if phase == "after_apply" else None
            ),
        ):
            clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(room.db.desc, "Room number 1.")
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(candidate.status, "approved")
        self.assertEqual(candidate.builder_operation["state"], "rolled_back")
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertIsNone(source.replacement_claim_id)
        operation_runtime.require_idle()

    def test_cooperative_replacement_activation_failure_keeps_published_lineage_fenced(self):
        from evennia.scripts.models import ScriptDB
        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        clock = self.StepClock()
        pending = live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        outcome = self.observe(pending)
        while candidate.builder_operation.get("phase") != "activation" and clock.callbacks:
            clock.step()
            candidate.refresh_from_db()
        self.assertEqual(candidate.status, "live")
        self.assertFalse(outcome)
        script = ScriptDB.objects.get(pk=next(iter(candidate.live_manifest["scripts"].values()))["script_id"])
        with mock.patch.object(script, "unpause", side_effect=RuntimeError("replacement activation failed")):
            clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        source.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(source.status, "superseded")
        self.assertEqual(source.current_live_revision_id, candidate.pk)
        self.assertEqual(candidate.status, "live")
        self.assertEqual(candidate.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(candidate.live_manifest["rooms"]["r1"]["object_id"]))

    def test_production_build_bridge_direct_reactor_call_waits_for_terminal_pair(self):
        from twisted.internet import defer

        from web.builder import sandbox_bridge

        project = self.approved_project(area_map(2))
        clock = self.StepClock()
        driver = sandbox_builder.build_deferred
        with (
            mock.patch("twisted.internet.reactor.running", True),
            mock.patch.object(sandbox_bridge, "build_deferred", side_effect=lambda *args: driver(*args, clock=clock)),
        ):
            pending = sandbox_bridge.create_sandbox_from_project(project.pk, self.owner, project.version)
        self.assertIsInstance(pending, defer.Deferred)
        outcome = self.observe(pending)
        self.assertFalse(outcome)
        clock.step()
        self.assertFalse(outcome)
        clock.drain()
        self.assertTrue(outcome[0][0], outcome)
        self.assertEqual(outcome[0][1]["room_count"], 2)

    def test_cooperative_build_raw_drift_preserves_staged_object_and_fence(self):
        from evennia.objects.models import ObjectDB
        from twisted.python.failure import Failure

        project = self.approved_project(area_map(2))
        clock = self.StepClock()
        pending = sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock)
        outcome = self.observe(pending)
        clock.step()
        project.refresh_from_db()
        first_id = project.builder_operation["receipts"][0]["object_id"]
        ObjectDB.objects.filter(pk=first_id).update(db_key="External staged rename")
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(
            ObjectDB.objects.filter(pk=first_id).values_list("db_key", flat=True).get(), "External staged rename"
        )
        project.refresh_from_db()
        self.assertEqual(project.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(first_id))
        self.assertEqual(project.status, "approved")

    def test_cooperative_full_id_turnover_has_typed_receipts_and_retains_retired_rows(self):
        from evennia.objects.models import ObjectDB
        from twisted.python.failure import Failure

        source = self.source()
        candidate = fork_replacement(source.pk, self.owner, source.version)
        data = candidate.map_data
        data["rooms"] = {"next_" + key: value for key, value in data["rooms"].items()}
        data["exits"] = {
            "next_" + key: {**value, "source": "next_" + value["source"], "target": "next_" + value["target"]}
            for key, value in data["exits"].items()
        }
        data["objects"] = {
            "next_" + key: {**value, "room_id": "next_" + value["room_id"]} for key, value in data["objects"].items()
        }
        candidate.save(update_fields=["map_data"])
        candidate.submit()
        candidate.approve(self.builder2, candidate.version)
        old_ids = {
            entry["object_id"]
            for kind in ("rooms", "exits", "fixtures")
            for entry in source.live_manifest[kind].values()
        }
        clock = self.StepClock()
        outcome = self.observe(
            live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        )
        clock.drain()
        self.assertNotIsInstance(outcome[0], Failure, str(outcome[0]))
        candidate.refresh_from_db()
        new_ids = {
            entry["object_id"]
            for kind in ("rooms", "exits", "fixtures")
            for entry in candidate.live_manifest[kind].values()
        }
        self.assertFalse(old_ids & new_ids)
        self.assertEqual(set(map(int, candidate.retired_manifest["objects"])), old_ids)
        self.assertEqual(set(ObjectDB.objects.filter(pk__in=old_ids).values_list("pk", flat=True)), old_ids)
        self.assertEqual(len(candidate.builder_operation["receipts"]), 62)
        self.assertTrue(all(receipt["typeclass"] for receipt in candidate.builder_operation["receipts"]))

    def test_running_build_refuses_http_mutation_cleanup_and_promotion(self):
        from django.urls import reverse

        from web.builder.promotion import PromotionError, promote_unit
        from web.builder.sandbox_cleanup import CleanupError, cleanup_unit

        project = self.approved_project(area_map(2))
        clock = self.StepClock()
        outcome = self.observe(sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock))
        clock.step()
        response = self.client_for(self.owner).post(
            reverse("builder:save_project"), data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 409)
        with self.assertRaisesRegex(CleanupError, "operation"):
            cleanup_unit(project.pk)
        with self.assertRaisesRegex(PromotionError, "operation"):
            promote_unit(project.pk)
        clock.drain()
        self.assertEqual(outcome[0]["room_count"], 2)

    def test_source_approved_snapshot_raw_drift_refuses_continuation_without_overwriting_drift(self):
        import copy

        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        clock = self.StepClock()
        outcome = self.observe(
            live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        )
        clock.step()
        changed = copy.deepcopy(source.approved_map_data)
        changed["map_data"]["rooms"]["r1"]["description"] = "External historical drift"
        BuildProject.objects.filter(pk=source.pk).update(approved_map_data=changed)
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        source.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(source.approved_map_data, changed)
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertEqual(candidate.status, "approved")
        self.assertEqual(candidate.builder_operation["state"], "rolled_back")

    def test_raw_foreign_ingress_during_replacement_keeps_restored_area_fenced(self):
        from evennia.objects.models import ObjectDB
        from evennia.utils import create
        from twisted.python.failure import Failure

        source = self.source()
        foreign = create.create_object("typeclasses.objects.Object", key="Foreign item", nohome=True)
        candidate = self.candidate_with_exit_descriptions(source)
        room_id = source.live_manifest["rooms"]["r1"]["object_id"]
        clock = self.StepClock()
        outcome = self.observe(
            live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        )
        clock.step()
        ObjectDB.objects.filter(pk=foreign.pk).update(db_location_id=room_id)
        with mock.patch.object(
            live_replacement,
            "_checkpoint",
            side_effect=lambda phase: (
                (_ for _ in ()).throw(RuntimeError("force compensation")) if phase == "after_apply" else None
            ),
        ):
            clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(ObjectDB.objects.filter(pk=foreign.pk).values_list("db_location_id", flat=True).get(), room_id)
        candidate.refresh_from_db()
        self.assertEqual(candidate.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(room_id))

    def test_cooperative_cross_object_monitor_runs_but_changed_reviewed_field_is_held_for_inspection(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER
        from twisted.python.failure import Failure

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        first = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        later = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r2"]["object_id"])
        watched = first.attributes.get("builder_revision", return_obj=True)
        monitored = MONITOR_HANDLER.at_update
        injected = []

        def change_later(attr, field):
            if attr is watched and field == "db_value" and not injected:
                injected.append(True)
                later.attributes.add("desc", "Normal monitor changed another reviewed object")
            return monitored(attr, field)

        clock = self.StepClock()
        outcome = self.observe(
            live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        )
        with mock.patch.object(MONITOR_HANDLER, "at_update", side_effect=change_later):
            clock.drain()
        self.assertTrue(injected)
        self.assertIsInstance(outcome[0], Failure)
        self.assertIn("inspection", str(outcome[0].value))
        self.assertEqual(later.db.desc, "Normal monitor changed another reviewed object")
        source.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(source.status, "live")
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertEqual(candidate.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(later))

    def test_published_build_late_foreign_contents_inside_exit_prevent_release(self):
        from evennia.objects.models import ObjectDB
        from evennia.utils import create
        from twisted.python.failure import Failure

        foreign = create.create_object("typeclasses.objects.Object", key="Late foreign item", nohome=True)
        project = self.approved_project(area_map(2))
        clock = self.StepClock()
        outcome = self.observe(sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock))
        while project.builder_operation.get("phase") != "activation" and clock.callbacks:
            clock.step()
            project.refresh_from_db()
        exit_id = next(iter(project.built_object_ids["exits"].values()))
        ObjectDB.objects.filter(pk=foreign.pk).update(db_location_id=exit_id)
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(ObjectDB.objects.filter(pk=foreign.pk).values_list("db_location_id", flat=True).get(), exit_id)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertEqual(project.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(exit_id))

    def test_published_build_late_foreign_script_on_exit_prevents_release(self):
        from evennia.scripts.models import ScriptDB
        from evennia.utils import create
        from twisted.python.failure import Failure

        foreign = create.create_script("typeclasses.scripts.Script", key="Foreign Script", autostart=False)
        project = self.approved_project(area_map(2))
        clock = self.StepClock()
        outcome = self.observe(sandbox_builder.build_deferred(project.pk, self.owner, project.version, clock=clock))
        while project.builder_operation.get("phase") != "activation" and clock.callbacks:
            clock.step()
            project.refresh_from_db()
        exit_id = next(iter(project.built_object_ids["exits"].values()))
        ScriptDB.objects.filter(pk=foreign.pk).update(db_obj_id=exit_id)
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(ScriptDB.objects.filter(pk=foreign.pk).values_list("db_obj_id", flat=True).get(), exit_id)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertEqual(project.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(exit_id))

    def test_foreign_ingress_into_a_retired_source_room_prevents_replacement_release(self):
        from evennia.objects.models import ObjectDB
        from evennia.utils import create
        from twisted.python.failure import Failure

        from .test_live_revisions import LiveRevisionTests

        source = LiveRevisionTests.source(self)
        candidate = LiveRevisionTests.candidate(self, source)
        old_room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r3"]["object_id"])
        foreign = create.create_object("typeclasses.objects.Object", key="Retired room foreign item", nohome=True)
        clock = self.StepClock()
        outcome = self.observe(
            live_replacement.replace_deferred(candidate.pk, self.owner, candidate.version, clock=clock)
        )
        while not old_room.attributes.has("builder_retired") and clock.callbacks:
            clock.step()
        self.assertTrue(old_room.attributes.has("builder_retired"))
        ObjectDB.objects.filter(pk=foreign.pk).update(db_location_id=old_room.pk)
        clock.drain()
        self.assertIsInstance(outcome[0], Failure)
        self.assertEqual(
            ObjectDB.objects.filter(pk=foreign.pk).values_list("db_location_id", flat=True).get(), old_room.pk
        )
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(source.current_live_revision_id, source.pk)
        self.assertEqual(candidate.builder_operation["state"], "failed")
        self.assertTrue(operation_runtime.object_is_fenced(old_room))

    def test_existing_attribute_uses_one_save_preserves_metadata_and_monitors(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER
        from evennia.typeclasses.attributes import Attribute

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        attr = room.attributes.get("desc", return_obj=True)
        attr.db_lock_storage = "attrread:false()"
        attr.save(update_fields=["db_lock_storage"])
        with (
            mock.patch.object(attr, "save", wraps=attr.save) as saved,
            mock.patch.object(MONITOR_HANDLER, "at_update", wraps=MONITOR_HANDLER.at_update) as monitored,
        ):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertEqual(saved.call_count, 1)
        self.assertEqual(room.db.desc, "Reviewed existing description")
        row = (
            Attribute.objects.filter(pk=attr.pk).values("db_key", "db_lock_storage", "db_category", "db_attrtype").get()
        )
        self.assertEqual(
            row, {"db_key": "desc", "db_lock_storage": "attrread:false()", "db_category": None, "db_attrtype": None}
        )
        self.assertEqual(
            [call.args[1] for call in monitored.call_args_list if call.args[0] is attr], ["db_value", "db_strvalue"]
        )

    def test_new_plain_attribute_rows_match_normal_handler_shape(self):
        from evennia.objects.models import ObjectDB

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        candidate.refresh_from_db()
        for entry in candidate.live_manifest["exits"].values():
            obj = ObjectDB.objects.get(pk=entry["object_id"])
            attr = obj.attributes.get("desc", return_obj=True)
            self.assertEqual(attr.value, "Reviewed new passage")
            self.assertEqual(
                (attr.db_model, attr.db_category, attr.db_attrtype, attr.db_strvalue, attr.db_lock_storage),
                ("objectdb", None, None, None, ""),
            )

    def test_new_attribute_link_failure_rolls_back_rows_and_compensates_then_retries(self):
        from django.db.models.query import QuerySet
        from evennia.objects.models import ObjectDB
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        original_ids = set(Attribute.objects.filter(db_model="objectdb").values_list("id", flat=True))
        bulk_create = QuerySet.bulk_create
        injected = []
        warmed = []

        def fail_links(queryset, rows, *args, **kwargs):
            if queryset.model is ObjectDB.db_attributes.through and not injected:
                self.assertGreater(
                    Attribute.objects.filter(
                        db_model="objectdb", db_key="desc", db_value=to_pickle("Reviewed new passage")
                    ).count(),
                    0,
                )
                warmed.append(
                    Attribute.objects.filter(
                        db_model="objectdb", db_key="desc", db_value=to_pickle("Reviewed new passage")
                    ).first()
                )
                injected.append(True)
                raise RuntimeError("injected Attribute link failure")
            return bulk_create(queryset, rows, *args, **kwargs)

        with (
            mock.patch.object(QuerySet, "bulk_create", new=fail_links),
            self.assertRaises(live_replacement.ReplacementError),
        ):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertTrue(injected)
        self.assertIsNot(Attribute.get_cached_instance(warmed[0].pk), warmed[0])
        self.assertEqual(set(Attribute.objects.filter(db_model="objectdb").values_list("id", flat=True)), original_ids)
        self.assertEqual(room.db.desc, "Room number 1.")
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(candidate.status, "approved")
        self.assertIsNone(source.replacement_claim_id)
        live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertEqual(room.db.desc, "Reviewed existing description")

    def test_new_attributes_are_visible_before_later_object_monitor_callbacks(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        first, second = list(source.live_manifest["exits"].values())[:2]
        first = ObjectDB.objects.get(pk=first["object_id"])
        second = ObjectDB.objects.get(pk=second["object_id"])
        watched = second.attributes.get("builder_revision", return_obj=True)
        monitored = MONITOR_HANDLER.at_update
        observed = []

        def check_order(attr, field):
            if attr is watched and field == "db_value":
                observed.append(first.db.desc)
            return monitored(attr, field)

        with mock.patch.object(MONITOR_HANDLER, "at_update", side_effect=check_order):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertEqual(observed, ["Reviewed new passage"])

    def test_later_owned_attribute_callback_changes_are_reconciled_without_duplicates(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        first = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        later = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r2"]["object_id"])
        exit_obj = ObjectDB.objects.get(pk=next(iter(source.live_manifest["exits"].values()))["object_id"])
        watched = first.attributes.get("builder_revision", return_obj=True)
        monitored = MONITOR_HANDLER.at_update
        injected = []

        def change_later(attr, field):
            if attr is watched and field == "db_value" and not injected:
                injected.append(True)
                later.attributes.add("desc", "Callback changed existing reviewed field")
                exit_obj.attributes.add("desc", "Callback created previously absent field")
            return monitored(attr, field)

        with mock.patch.object(MONITOR_HANDLER, "at_update", side_effect=change_later):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertTrue(injected)
        self.assertEqual(later.db.desc, "Room number 2.")
        self.assertEqual(exit_obj.db.desc, "Reviewed new passage")
        self.assertEqual(
            exit_obj.db_attributes.filter(db_key__iexact="desc", db_category=None, db_attrtype=None).count(), 1
        )
        candidate.refresh_from_db()
        live_replacement._inventory(candidate)

    def test_callback_changes_to_a_later_key_on_the_same_object_are_reconciled(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        first, later = [key for key in live_replacement.ROOM_KEYS if key in {"desc", "builder_revision"}]
        watched = room.attributes.get(first, return_obj=True)
        monitored = MONITOR_HANDLER.at_update
        injected = []

        def change_later_key(attr, field):
            if attr is watched and field == "db_value" and not injected:
                injected.append(True)
                room.attributes.add(later, "Callback mutated another key")
            return monitored(attr, field)

        with mock.patch.object(MONITOR_HANDLER, "at_update", side_effect=change_later_key):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertTrue(injected)
        self.assertEqual(room.db.desc, "Reviewed existing description")
        candidate.refresh_from_db()
        live_replacement._inventory(candidate)

    def test_timer_configuration_callback_changes_are_reconciled_before_resume(self):
        from evennia.objects.models import ObjectDB
        from evennia.scripts.monitorhandler import MONITOR_HANDLER

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        script = live_replacement._inventory(source)[2]["r1:drip1"]
        watched = room.attributes.get("builder_revision", return_obj=True)
        monitored = MONITOR_HANDLER.at_update
        injected = []

        def change_timer(attr, field):
            if attr is watched and field == "db_value" and not injected:
                injected.append(True)
                script.attributes.add("trigger_action", "Callback changed action")
                script.attributes.add("trigger_parameters", {"message": "Callback changed parameters"})
            return monitored(attr, field)

        with mock.patch.object(MONITOR_HANDLER, "at_update", side_effect=change_timer):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertTrue(injected)
        candidate.refresh_from_db()
        live_replacement._inventory(candidate)

    def test_shared_owned_attribute_refuses_without_mutating_either_owner(self):
        from evennia.objects.models import ObjectDB

        source = self.source()
        candidate = self.candidate_with_exit_descriptions(source)
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        attr = room.attributes.get("desc", return_obj=True)
        self.plaza.attributes.remove("desc")
        ObjectDB.db_attributes.through.objects.create(objectdb_id=self.plaza.pk, attribute_id=attr.pk)
        self.plaza.attributes.reset_cache()
        self.assertEqual(self.plaza.db.desc, "Room number 1.")
        with self.assertRaisesRegex(live_replacement.ReplacementError, "shared"):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        self.assertEqual(room.db.desc, "Room number 1.")
        self.assertEqual(self.plaza.db.desc, "Room number 1.")
        candidate.refresh_from_db()
        source.refresh_from_db()
        self.assertEqual(candidate.status, "approved")
        self.assertIsNone(source.replacement_claim_id)

    def test_exact_inventory_reads_are_bounded_for_present_and_absent_fields(self):
        source = self.source()
        with CaptureQueriesContext(connection) as queries:
            groups, connectors, scripts = live_replacement._inventory(source)
        self.assertEqual((len(groups["rooms"]), len(groups["exits"]), len(groups["fixtures"])), (20, 38, 2))
        self.assertEqual((len(connectors), len(scripts)), (2, 2))
        self.assertLessEqual(len(queries), 30, f"Inventory made {len(queries)} queries")

    def test_journal_reuses_fresh_inventory_without_per_field_queries(self):
        source = self.source()
        candidate = fork_replacement(source.pk, self.owner, source.version)
        candidate.submit()
        candidate.approve(self.builder2, candidate.version)
        before = BuildProject.objects.get(pk=source.pk).current_live_revision_id
        with (
            mock.patch.object(live_replacement, "_claim", side_effect=RuntimeError("before mutation")) as claim,
            CaptureQueriesContext(connection) as queries,
            self.assertRaisesRegex(RuntimeError, "before mutation"),
        ):
            live_replacement.replace_live_unit(candidate.pk, self.owner, candidate.version)
        claim.assert_called_once()
        journal = claim.call_args.args[3]
        self.assertEqual(len(journal["saved_objects"]), 62)
        self.assertEqual(len(journal["saved_scripts"]), 2)
        self.assertEqual(BuildProject.objects.get(pk=source.pk).current_live_revision_id, before)
        self.assertLessEqual(len(queries), 50, f"Preflight and journal made {len(queries)} queries")

    def test_unrelated_and_categorized_gameplay_values_are_not_deserialized(self):
        from evennia.objects.models import ObjectDB

        source = self.source()
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        sentinel = {"never_unpack_unrelated": True}
        room.db.scene_state = sentinel
        room.attributes.add("desc", sentinel, category="gameplay")
        room.db.trigger_action = sentinel  # Owned only on Scripts, not Rooms.
        fixture = ObjectDB.objects.get(pk=source.live_manifest["fixtures"]["f0"]["object_id"])
        fixture.db.haven_security = sentinel  # Owned only on Rooms.
        connector = ObjectDB.objects.get(pk=source.live_manifest["connection_exits"][0]["object_id"])
        connector.db.restricted_characters = sentinel
        script = live_replacement._inventory(source)[2]["r1:drip1"]
        script.db.builder_fixture = sentinel
        unpack = live_replacement.from_pickle

        def guarded(value):
            if value == sentinel:
                raise AssertionError("Unrelated gameplay value was deserialized")
            return unpack(value)

        with mock.patch.object(live_replacement, "from_pickle", side_effect=guarded):
            groups, _, _ = live_replacement._inventory(source)
        self.assertEqual(len(groups["rooms"]), 20)
        self.assertEqual(room.db.scene_state, sentinel)
        self.assertEqual(room.attributes.get("desc", category="gameplay"), sentinel)

    def test_case_insensitive_duplicate_owned_attribute_refuses_without_mutation(self):
        from evennia.objects.models import ObjectDB
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        source = self.source()
        room = ObjectDB.objects.get(pk=source.live_manifest["rooms"]["r1"]["object_id"])
        duplicate = Attribute.objects.create(
            db_key="DESC",
            db_value=to_pickle(room.db.desc),
            db_model="OBJECTDB",
            db_category=None,
            db_attrtype=None,
        )
        ObjectDB.db_attributes.through.objects.create(objectdb_id=room.pk, attribute_id=duplicate.pk)
        with self.assertRaisesRegex(live_replacement.ReplacementError, "ambiguous"):
            live_replacement._inventory(source)
        self.assertTrue(Attribute.objects.filter(pk=duplicate.pk).exists())
        source.refresh_from_db()
        self.assertEqual(source.status, "live")
        self.assertIsNone(source.replacement_claim_id)
