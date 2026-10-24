"""Real Evennia boundaries while a claimed builder operation yields."""

from collections import OrderedDict, defaultdict, deque
from unittest import mock

from django.db import transaction
from django.db.models.deletion import ProtectedError
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.utils import create

from . import operation_runtime as runtime
from . import test_operation_runtime as runtime_tests
from .test_sandbox import SandboxTestBase
from .trigger_engine import execute_trigger, execute_triggers


class OperationFenceTests(SandboxTestBase):
    def setUp(self):
        runtime_tests.OperationRuntimeTests._reset_runtime()
        self.addCleanup(runtime_tests.OperationRuntimeTests._reset_runtime)
        super().setUp()
        self.room = create.create_object("typeclasses.rooms.Room", key="Work area", nohome=True)
        self.outside = create.create_object("typeclasses.rooms.Room", key="Other area", nohome=True)
        self.item = create.create_object("typeclasses.objects.Object", key="Fixture", location=self.room)
        self.character = create.create_object(
            "typeclasses.characters.Character",
            key="Visitor",
            location=self.plaza,
            home=self.plaza,
        )
        self.exit = create.create_object(
            "typeclasses.exits.Exit",
            key="north",
            aliases=["n"],
            location=self.plaza,
            destination=self.room,
        )
        self.side_exit = create.create_object(
            "typeclasses.exits.Exit",
            key="east",
            aliases=["e"],
            location=self.plaza,
            destination=self.outside,
        )
        self.room.db.triggers = [
            {
                "id": "notice",
                "type": "timed",
                "interval": 60,
                "action": "set_attribute",
                "parameters": {"target": "room", "attr_name": "weather", "value": "rain"},
            }
        ]
        self.room.db.details = {"state": "original"}
        self.script = create.create_script(
            "typeclasses.scripts.RoomTriggerScript",
            obj=self.room,
            autostart=False,
        )
        self.script.db.trigger_id = "notice"
        self.project = self.approved_project()
        self.operation = None
        self.addCleanup(self._release)

    def _release(self):
        if self.operation:
            runtime.finish_operation(self.operation)
            self.operation = None

    def claim(self):
        self.operation = runtime.claim_operation(
            self.project.pk,
            "build",
            self.owner,
            self.project.version,
            affected_ids=[self.room.pk, self.item.pk, self.exit.pk],
            script_ids=[self.script.pk],
            connection_reservations=[{"room_id": self.plaza.pk, "names": ["north", "n"]}],
        )
        return self.operation

    def test_movement_with_and_without_hooks_and_exit_indirection_is_refused(self):
        self.claim()
        for destination, kwargs in ((self.room, {}), (self.room, {"move_hooks": False}), (self.exit, {})):
            with self.subTest(destination=destination, kwargs=kwargs):
                self.assertFalse(self.character.move_to(destination, quiet=True, **kwargs))
                self.assertEqual(self.character.location, self.plaza)
        self.assertFalse(self.exit.at_traverse(self.character, self.room))
        self.assertTrue(self.character.move_to(self.outside, quiet=True))

    def test_direct_links_and_dbrefs_refuse_before_mutating_shared_cache(self):
        self.claim()
        for field, value in (
            ("location", self.room),
            ("location", self.room.dbref),
            ("home", self.room),
            ("destination", self.room),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(runtime.OperationError):
                setattr(self.character, field, value)
        self.assertEqual(self.character.location, self.plaza)
        self.assertEqual(self.character.home, self.plaza)
        self.assertIsNone(self.character.destination)
        self.assertIn(self.character, self.plaza.contents)
        self.assertNotIn(self.character, self.room.contents)

    def test_direct_model_save_restores_cached_fields_and_preserves_rows(self):
        self.claim()
        self.item.db_location = self.outside
        self.item.db_key = "Unauthorized"
        with self.assertRaises(runtime.OperationError):
            self.item.save(update_fields=["db_location", "db_key"])
        self.assertEqual(self.item.location, self.room)
        self.assertEqual(self.item.key, "Fixture")
        self.assertEqual(
            ObjectDB.objects.filter(pk=self.item.pk).values_list("db_location_id", flat=True).get(), self.room.pk
        )
        self.assertIn(self.item, self.room.contents)

    def test_access_has_no_sandbox_owner_or_admin_bypass_and_appearance_is_hidden(self):
        self.room.tags.add("sandbox")
        self.room.tags.add(f"project_{self.project.pk}")
        self.character.account = self.owner
        self.claim()
        for actor in (self.character, self.admin):
            for access_type in ("traverse", "view", "search", "edit", "delete", "teleport_here"):
                with self.subTest(actor=actor, access=access_type):
                    self.assertFalse(self.room.access(actor, access_type, default=True))
        self.assertIn("temporarily unavailable", self.room.return_appearance(self.character))

    def test_delete_and_alias_clear_cannot_bypass_object_fences(self):
        aliases = self.exit.aliases
        self.assertEqual(aliases.all(), ["n"])
        self.claim()
        for action in (
            self.item.delete,
            aliases.clear,
            lambda: aliases.remove("n"),
            lambda: ObjectDB.objects.filter(pk=self.item.pk).delete(),
        ):
            with self.subTest(action=action), self.assertRaises(runtime.OperationError), transaction.atomic():
                action()
        self.assertTrue(ObjectDB.objects.filter(pk=self.item.pk).exists())
        aliases.reset_cache()
        self.assertEqual(aliases.all(), ["n"])

    def test_attributes_nested_saver_and_direct_relations_are_fenced(self):
        nested = self.room.db.details
        attribute = self.room.attributes.get("details", return_obj=True)
        self.claim()
        for action in (
            lambda: setattr(self.room.db, "details", {"state": "foreign"}),
            lambda: nested.__setitem__("state", "foreign"),
            lambda: self.room.attributes.remove("details"),
            lambda: self.room.db_attributes.remove(attribute),
            lambda: self.room.db_attributes.clear(),
        ):
            with self.subTest(action=action), self.assertRaises(runtime.OperationError), transaction.atomic():
                action()
            self.assertEqual(dict(self.room.db.details), {"state": "original"})

    def test_trigger_engine_and_timer_suppress_actions_even_in_owned_step(self):
        operation = self.claim()
        with runtime.mutation_context(operation):
            self.assertFalse(execute_trigger(self.room.db.triggers[0], self.room, None))
            self.assertEqual(execute_triggers(self.room, "timed", None), (0, 0))
            with mock.patch("web.builder.trigger_engine.execute_triggers") as execute:
                self.script.at_repeat()
                execute.assert_not_called()
        self.assertIsNone(self.room.db.weather)

    def test_owned_step_retains_original_setters_hooks_caches_and_expires_on_return(self):
        operation = self.claim()
        with runtime.mutation_context(operation):
            with mock.patch.object(self.room, "at_object_receive", wraps=self.room.at_object_receive) as received:
                self.assertTrue(self.character.move_to(self.room, quiet=True))
                received.assert_called_once()
            self.assertIn(self.character, self.room.contents)
            self.assertNotIn(self.character, self.plaza.contents)
            self.room.db.details = {"state": "reviewed"}
            self.exit.aliases.add("forward")
            self.item.key = "Reviewed fixture"
            self.assertTrue(self.character.move_to(self.plaza, quiet=True))
        with self.assertRaises(runtime.OperationError):
            self.item.key = "Foreign fixture"
        self.assertEqual(self.item.key, "Reviewed fixture")
        self.assertEqual(dict(self.room.db.details), {"state": "reviewed"})
        self._release()
        self.assertTrue(self.character.move_to(self.room, quiet=True))

    def test_directed_reservation_blocks_key_alias_and_initial_create_but_not_plaza_traffic(self):
        aliases = self.side_exit.aliases
        self.claim()
        for action in (
            lambda: setattr(self.side_exit, "key", "north"),
            lambda: aliases.add("n"),
            lambda: aliases.batch_add(("NORTH", "directions")),
        ):
            with self.subTest(action=action), self.assertRaises(runtime.OperationError), transaction.atomic():
                action()
        count = ObjectDB.objects.count()
        with self.assertRaises(runtime.OperationError):
            create.create_object(
                "evennia.objects.objects.DefaultExit",
                key="new passage",
                aliases=["n"],
                location=self.plaza,
                destination=self.outside,
            )
        self.assertEqual(ObjectDB.objects.count(), count)
        self.assertEqual(self.side_exit.key, "east")
        self.assertTrue(self.character.move_to(self.outside, quiet=True))
        self.assertTrue(self.character.move_to(self.plaza, quiet=True))
        self.plaza.db.weather = "clear"
        self.assertEqual(self.plaza.db.weather, "clear")

    def test_reserved_attachment_delete_and_structural_change_are_refused(self):
        self.claim()
        with self.assertRaises(runtime.OperationError):
            self.plaza.delete()
        self.plaza.db_destination = self.outside
        with self.assertRaises(runtime.OperationError):
            self.plaza.save(update_fields=["db_destination"])
        self.assertIsNone(self.plaza.destination)
        self.assertTrue(ObjectDB.objects.filter(pk=self.exit.pk).exists())

    def test_timer_mutation_and_project_bulk_delete_are_refused(self):
        self.claim()
        self.script.db_interval = 9
        with self.assertRaises(runtime.OperationError):
            self.script.save(update_fields=["db_interval"])
        with self.assertRaises(runtime.OperationError), transaction.atomic():
            self.script.delete()
        with self.assertRaises((runtime.OperationError, ProtectedError)), transaction.atomic():
            type(self.project).objects.filter(pk=self.project.pk).delete()

    def test_server_timer_restart_and_shutdown_preserve_held_evidence(self):
        self.script.db_is_active = True
        self.script.save(update_fields=["db_is_active"])
        self.script.db._paused_time = 10
        self.script.db._paused_callcount = 2
        self.script.db._manually_paused = False
        self.claim()
        runtime_tests.OperationRuntimeTests._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        ScriptDB.objects.update_scripts_after_server_start()
        self.assertIsNone(self.script.ndb._task)
        self.assertEqual(self.script.db._paused_time, 10)
        with mock.patch.object(self.script, "stop") as stop:
            self.script._step_callback()
            stop.assert_not_called()
        self.script._pause_task(auto_pause=True)
        self.assertEqual(self.script.db._paused_time, 10)
        with self.assertRaises(runtime.OperationError):
            self.script.db._paused_time = None

    def test_restart_reconstructs_world_and_direction_fences(self):
        self.claim()
        runtime_tests.OperationRuntimeTests._reset_runtime()
        self.assertTrue(runtime.recover_operation_fences())
        self.assertFalse(self.character.move_to(self.room, quiet=True))
        with self.assertRaises(runtime.OperationError), transaction.atomic():
            self.side_exit.aliases.add("north")
        with self.assertRaises(runtime.OperationError):
            self.room.db.details = {"state": "changed after restart"}

    def test_warmed_tag_and_permission_clear_are_fenced(self):
        self.item.tags.add("managed")
        self.item.permissions.add("Builder")
        tags, permissions = self.item.tags, self.item.permissions
        self.claim()
        for action in (tags.clear, permissions.clear):
            with self.subTest(action=action), self.assertRaises(runtime.OperationError):
                action()
        self.assertTrue(tags.has("managed"))
        self.assertTrue(permissions.has("Builder"))

    def test_global_world_hold_keeps_account_only_attributes_available_for_staff_login(self):
        self.owner.db.login_note = "before"
        runtime._maintenance_hold = True
        try:
            self.owner.db.login_note = "after"
            self.assertEqual(self.owner.db.login_note, "after")
            with self.assertRaises(runtime.OperationError):
                self.room.db.details = {"state": "blocked"}
        finally:
            runtime._maintenance_hold = False

    def test_held_nested_mutables_do_not_change_or_resurrect_refused_writes(self):
        initial = {
            "mapping": {"before": 1},
            "sequence": [1],
            "members": {1},
            "queue": deque([1]),
            "defaults": defaultdict(list, {"before": [1]}),
            "ordered": OrderedDict([("before", 1)]),
        }
        self.room.db.mutable = initial
        held = self.room.db.mutable
        self.claim()
        for action in (
            lambda: held["mapping"].update(blocked=2),
            lambda: held["sequence"].append(2),
            lambda: held["members"].add(2),
            lambda: held["queue"].append(2),
            lambda: held["defaults"]["blocked"],
            lambda: held["ordered"].update(blocked=2),
        ):
            with self.subTest(action=action):
                with self.assertRaises(runtime.OperationError):
                    action()
                self.assertEqual(held.deserialize(), initial)
                self.assertEqual(self.room.db.mutable.deserialize(), initial)
        self._release()
        held["mapping"]["allowed"] = 3
        self.assertEqual(held["queue"].pop(), 1)
        held["queue"].append(1)
        expected = {**initial, "mapping": {"before": 1, "allowed": 3}}
        self.assertEqual(self.room.db.mutable.deserialize(), expected)

    def test_script_tag_clear_and_shared_tag_save_respect_script_namespace(self):
        self.script.tags.add("timer-evidence")
        tags = self.script.tags
        tag = tags.get("timer-evidence", return_tagobj=True)
        self.claim()
        with self.assertRaises(runtime.OperationError):
            tags.clear()
        tag.db_key = "foreign"
        with self.assertRaises(runtime.OperationError):
            tag.save(update_fields=["db_key"])
        self.assertEqual(tag.db_key, "timer-evidence")
        self.assertTrue(tags.has("timer-evidence"))

    def test_warmed_lock_handler_refuses_before_changing_cached_authority(self):
        self.room.locks.add("traverse:none();view:none()")
        locks = self.room.locks
        before = locks.all()
        self.claim()
        for action in (
            lambda: locks.add("traverse:all()"),
            lambda: locks.remove("traverse"),
            lambda: locks.delete("view"),
            locks.clear,
            lambda: locks.replace("traverse:all()"),
            lambda: locks.append("traverse", "all()"),
        ):
            with self.subTest(action=action):
                with self.assertRaises(runtime.OperationError):
                    action()
                self.assertEqual(locks.all(), before)
        self.assertEqual(locks.validate("traverse:all()"), (True, None))
        self.owner.locks.add("operation-inspect:all()")
        self.assertIn("operation-inspect:all()", self.owner.locks.all())
        self._release()
        self.assertEqual(locks.all(), before)
        self.assertFalse(self.room.access(self.character, "traverse", default=True))
