"""
The sandbox units (KD-6, KD-7): build, promote and cleanup run wholly on the
reactor, act only on the object ids recorded at build time, and undo
themselves with Evennia operations when they fail part-way.

Real test DB, real Evennia objects. Failure paths inject an exception
mid-unit and then check in-memory state (contents, tags, running Scripts) as
well as rows.
"""

import json
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.utils import create

from commands.builder.sandbox import CmdCleanupSandbox
from web import main_thread
from web.builder import promotion, sandbox_builder, sandbox_cleanup
from web.builder.models import BuildProject
from web.builder.promotion import promote_project_to_live
from web.builder.sandbox_bridge import create_sandbox_from_project
from web.builder.sandbox_cleanup import cleanup_sandbox_for_project


def area_map(n_rooms=2, timed_rooms=(), entry=None):
    """A line of rooms joined both ways; `timed_rooms` get a timed trigger."""
    rooms, exits = {}, {}
    for i in range(1, n_rooms + 1):
        room = {"name": f"Room {i}", "description": f"Room number {i}.", "v5": {"danger_level": "low"}}
        triggers = [
            {
                "id": "greet",
                "type": "entry",
                "action": "send_message",
                "parameters": {"message": f"You enter room {i}."},
            }
        ]
        if i in timed_rooms:
            triggers.append(
                {
                    "id": f"drip{i}",
                    "type": "timed",
                    "interval": 60,
                    "action": "emit_message",
                    "parameters": {"message": "Water drips."},
                }
            )
        room["triggers"] = triggers
        if entry == i:
            room["is_entry"] = True
        rooms[f"r{i}"] = room
    for i in range(1, n_rooms):
        exits[f"e{i}a"] = {"source": f"r{i}", "target": f"r{i + 1}", "name": "east", "aliases": ["e"]}
        exits[f"e{i}b"] = {
            "source": f"r{i + 1}",
            "target": f"r{i}",
            "name": "west",
            "aliases": ["w"],
            "locks": "traverse:all()",
        }
    return {"schema_version": 1, "rooms": rooms, "exits": exits, "objects": {}}


class SandboxTestBase(TestCase):
    def setUp(self):
        self.owner = create.create_account("sowner", "so@example.com", "testpassword123", permissions=["Builder"])
        self.builder2 = create.create_account("sb2", "sb2@example.com", "testpassword123", permissions=["Builder"])
        self.admin = create.create_account("sadmin", "sa@example.com", "testpassword123", permissions=["Admin"])
        self.plaza = create.create_object("typeclasses.rooms.Room", key="Plaza", nohome=True)
        # The test DB is rolled back after each test but in-memory Script
        # timers are not, and row ids are reused; only look at (and stop)
        # Script instances this test made.
        self._scripts_before = {id(script) for script in ScriptDB.get_all_cached_instances()}
        self.addCleanup(self._stop_new_timers)

    def _new_cached_scripts(self):
        return [s for s in ScriptDB.get_all_cached_instances() if id(s) not in self._scripts_before]

    def _stop_new_timers(self):
        for script in self._new_cached_scripts():
            task = script.ndb._task
            if task and task.running:
                task.stop()

    def approved_project(self, map_data=None, direction="n", room=None):
        """A project approved at a snapshot that connects to `room` (Plaza)."""
        map_data = map_data or area_map()
        room = room or self.plaza
        return BuildProject.objects.create(
            user=self.owner,
            name="Area",
            map_data=map_data,
            status="approved",
            reviewed_by=self.builder2,
            connection_room_id=room.id,
            connection_direction=direction,
            approved_map_data={
                "map_data": map_data,
                "connection_room_id": room.id,
                "connection_direction": direction,
            },
        )

    def built_project(self, **kwargs):
        project = self.approved_project(**kwargs)
        ok, result = create_sandbox_from_project(project.pk)
        self.assertTrue(ok, result)
        project.refresh_from_db()
        return project

    def recorded_objects(self, project):
        ids = [*project.built_object_ids["rooms"].values(), *project.built_object_ids["exits"].values()]
        return list(ObjectDB.objects.filter(pk__in=ids))

    def client_for(self, account):
        client = Client()
        client.force_login(account)
        return client

    def post_json(self, client, url, data=None):
        return client.post(url, data=json.dumps(data or {}), content_type="application/json")

    def assert_nothing_left(self, created_ids, objects_before, scripts_before):
        """No ObjectDB row, DB Script or running Script remains for these ids."""
        self.assertEqual(ObjectDB.objects.count(), objects_before)
        self.assertFalse(ObjectDB.objects.filter(pk__in=created_ids).exists())
        self.assertEqual(ScriptDB.objects.count(), scripts_before)
        self.assertFalse(ScriptDB.objects.filter(db_obj_id__in=created_ids).exists())
        running = [
            script
            for script in self._new_cached_scripts()
            if script.db_obj_id in created_ids and (script.db_is_active or _timer_running(script))
        ]
        self.assertEqual(running, [])


def _timer_running(script):
    """Is the Script's in-memory repeat timer running?"""
    task = script.ndb._task
    return bool(task and task.running)


class RecordingCreates:
    """Wrap the real create helpers, remembering every id they create."""

    def __init__(self, test, fail_exit_at=None, fail_script_at=None):
        self.ids = []
        self.exit_calls = 0
        self.script_calls = 0
        self.started_scripts = []
        real_room, real_exit = sandbox_builder._create_room, sandbox_builder._create_exit
        real_script = sandbox_builder.start_timed_trigger

        def room(*args, **kwargs):
            obj = real_room(*args, **kwargs)
            self.ids.append(obj.id)
            return obj

        def exit_(*args, **kwargs):
            self.exit_calls += 1
            if fail_exit_at and self.exit_calls == fail_exit_at:
                raise RuntimeError("injected exit failure")
            obj = real_exit(*args, **kwargs)
            self.ids.append(obj.id)
            return obj

        def script(*args, **kwargs):
            self.script_calls += 1
            if fail_script_at and self.script_calls == fail_script_at:
                raise RuntimeError("injected script failure")
            started = real_script(*args, **kwargs)
            self.started_scripts.append(started)
            return started

        test.enterContext(mock.patch.object(sandbox_builder, "_create_room", side_effect=room))
        test.enterContext(mock.patch.object(sandbox_builder, "_create_exit", side_effect=exit_))
        test.enterContext(mock.patch.object(sandbox_builder, "start_timed_trigger", side_effect=script))


class BuildUnitTests(SandboxTestBase):
    def test_build_creates_recorded_rooms_exits_and_scripts(self):
        project = self.built_project(map_data=area_map(3, timed_rooms=(2,), entry=2))
        record = project.built_object_ids
        self.assertEqual(project.status, "built")
        self.assertEqual(set(record["rooms"]), {"r1", "r2", "r3"})
        self.assertEqual(len(record["exits"]), 4)
        self.assertEqual(project.sandbox_room_id, record["rooms"]["r2"])
        self.assertEqual(record["entry"], record["rooms"]["r2"])
        # No container room: every created room is a room of the area.
        tagged = ObjectDB.objects.get_by_tag(f"project_{project.pk}")
        self.assertEqual({o.id for o in tagged}, {*record["rooms"].values(), *record["exits"].values()})
        for obj in tagged:
            self.assertTrue(obj.tags.has("sandbox"))
        # Exit locks and the timed Script are in place.
        west = ObjectDB.objects.get(pk=record["exits"]["e1b"])
        self.assertEqual(west.locks.get("traverse"), "traverse:all()")
        script = ScriptDB.objects.get(pk=record["scripts"][0])
        self.assertEqual(script.db_obj_id, record["rooms"]["r2"])
        self.assertTrue(script.db_is_active and _timer_running(script))
        self.assertEqual(script.db.trigger_id, "drip2")
        # Entry triggers stored through the build fire.
        from web.builder.trigger_engine import execute_triggers

        char = create.create_object("typeclasses.characters.Character", key="Nina", nohome=True)
        room2 = ObjectDB.objects.get(pk=record["rooms"]["r2"])
        with mock.patch.object(char, "msg") as msg:
            self.assertEqual(execute_triggers(room2, "entry", char), (1, 0))
        msg.assert_called_once_with("You enter room 2.")

    def test_injected_failure_mid_build_leaves_nothing(self):
        project = self.approved_project(map_data=area_map(4, timed_rooms=(1, 2)))
        objects_before, scripts_before = ObjectDB.objects.count(), ScriptDB.objects.count()
        recorder = RecordingCreates(self, fail_exit_at=3)
        with self.assertNoLogs("web.builder.sandbox_builder", level="ERROR"):
            ok, result = create_sandbox_from_project(project.pk)
        self.assertFalse(ok)
        self.assertIn("injected exit failure", result["error"])
        self.assertEqual(len(recorder.ids), 6)  # 4 rooms + 2 exits existed
        self.assertEqual(recorder.script_calls, 0)  # scripts start only after
        self.assert_nothing_left(recorder.ids, objects_before, scripts_before)
        self.assertEqual(self.plaza.contents, [])
        project.refresh_from_db()
        self.assertEqual((project.status, project.sandbox_room_id, project.built_object_ids), ("approved", None, {}))

    def test_injected_failure_starting_scripts_leaves_nothing(self):
        project = self.approved_project(map_data=area_map(3, timed_rooms=(1, 2, 3)))
        objects_before, scripts_before = ObjectDB.objects.count(), ScriptDB.objects.count()
        recorder = RecordingCreates(self, fail_script_at=2)
        with self.assertNoLogs("web.builder.sandbox_builder", level="ERROR"):
            ok, result = create_sandbox_from_project(project.pk)
        self.assertFalse(ok)
        self.assertIn("injected script failure", result["error"])
        self.assertEqual(len(recorder.started_scripts), 1)
        started = recorder.started_scripts[0]
        self.assertFalse(_timer_running(started))
        self.assert_nothing_left(recorder.ids, objects_before, scripts_before)
        project.refresh_from_db()
        self.assertEqual((project.status, project.built_object_ids), ("approved", {}))

    def test_lost_record_update_undoes_the_build(self):
        project = self.approved_project(map_data=area_map(2, timed_rooms=(1,)))
        objects_before, scripts_before = ObjectDB.objects.count(), ScriptDB.objects.count()
        recorder = RecordingCreates(self)
        real_start = sandbox_builder._start_timed_triggers

        def race(*args):
            real_start(*args)
            # Someone else builds first (or the project leaves 'approved').
            BuildProject.objects.filter(pk=project.pk).update(status="live")

        with mock.patch.object(sandbox_builder, "_start_timed_triggers", side_effect=race):
            ok, result = create_sandbox_from_project(project.pk)
        self.assertFalse(ok)
        self.assertIn("changed while it was being built", result["error"])
        self.assert_nothing_left(recorder.ids, objects_before, scripts_before)

    def test_refuses_unbuildable_snapshot(self):
        bad = area_map(2)
        bad["exits"]["e1a"]["locks"] = "puppet:all()"
        project = self.approved_project(map_data=bad)
        objects_before = ObjectDB.objects.count()
        ok, result = create_sandbox_from_project(project.pk)
        self.assertFalse(ok)
        self.assertIn("e1a", result["error"])
        self.assertEqual(ObjectDB.objects.count(), objects_before)

    def test_refuses_second_build(self):
        project = self.built_project()
        BuildProject.objects.filter(pk=project.pk).update(status="approved")
        ok, result = create_sandbox_from_project(project.pk)
        self.assertFalse(ok)
        self.assertIn("already exists", result["error"])

    def test_fifty_room_build_query_budget(self):
        # F-050 measured ~6,000 queries for 50 rooms / 98 exits; the budget
        # is half that.
        project = self.approved_project(map_data=area_map(50, timed_rooms=(1, 25, 50)))
        with CaptureQueriesContext(connection) as queries:
            ok, result = create_sandbox_from_project(project.pk)
        self.assertTrue(ok, result)
        self.assertEqual((result["room_count"], result["exit_count"]), (50, 98))
        print(f"\n50-room build: {len(queries)} queries")
        self.assertLessEqual(len(queries), 3000)


class ThreadDisciplineTests(SandboxTestBase):
    def test_build_runs_through_call_in_main_thread(self):
        project = self.approved_project()
        with mock.patch("web.builder.sandbox_bridge.call_in_main_thread", wraps=main_thread.call_in_main_thread) as spy:
            ok, _ = create_sandbox_from_project(project.pk)
        self.assertTrue(ok)
        self.assertEqual(spy.call_args.args, (sandbox_builder.build_unit, project.pk))

    def test_promote_and_cleanup_run_through_call_in_main_thread(self):
        project = self.built_project()
        with mock.patch(
            "web.builder.sandbox_cleanup.call_in_main_thread", wraps=main_thread.call_in_main_thread
        ) as spy:
            ok, _ = cleanup_sandbox_for_project(project.pk)
        self.assertTrue(ok)
        self.assertEqual(spy.call_args.args, (sandbox_cleanup.cleanup_unit, project.pk))

        project = self.built_project()
        with mock.patch("web.builder.promotion.call_in_main_thread", wraps=main_thread.call_in_main_thread) as spy:
            ok, result = promote_project_to_live(project.pk)
        self.assertTrue(ok, result)
        self.assertEqual(spy.call_args.args, (promotion.promote_unit, project.pk, None, None))

    def test_no_threading_event_wrappers_remain(self):
        import web.builder.sandbox_bridge as bridge

        for module in (bridge, promotion, sandbox_cleanup):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("run_in_main_thread", source.replace("call_in_main_thread", ""), module)
            self.assertNotIn("threading.Event", source, module)

    def test_build_view_end_to_end(self):
        project = self.approved_project()
        resp = self.post_json(self.client_for(self.owner), reverse("builder:build_sandbox", args=[project.pk]))
        self.assertEqual(resp.status_code, 200, resp.content)
        project.refresh_from_db()
        self.assertEqual(resp.json()["sandbox_id"], project.sandbox_room_id)


def _exits_of(room):
    return [obj for obj in room.contents if obj.destination]


class PromoteTests(SandboxTestBase):
    def promote(self, project, data=None, user=None):
        url = reverse("builder:promote_project", args=[project.pk])
        return self.post_json(self.client_for(user or self.owner), url, data)

    def test_build_promote_cleanup_happy_path(self):
        project = self.built_project(map_data=area_map(3, timed_rooms=(2,)))
        record = project.built_object_ids
        recorded = self.recorded_objects(project)
        entry = ObjectDB.objects.get(pk=record["entry"])

        resp = self.promote(project, {"connection_room_id": self.plaza.id, "connection_direction": "n"})
        self.assertEqual(resp.status_code, 200, resp.content)

        # The live room's new exit leads to the entry room, which has the
        # area's own exits plus the way back.
        north = [e for e in _exits_of(self.plaza) if e.key == "north"]
        self.assertEqual(len(north), 1)
        self.assertEqual(north[0].destination, entry)
        self.assertIn("n", north[0].aliases.all())
        entry_exits = {e.key: e.destination for e in _exits_of(entry)}
        self.assertEqual(entry_exits["south"], self.plaza)
        self.assertIn("east", entry_exits)
        # Nothing of the project is still a sandbox object.
        for obj in recorded:
            self.assertFalse(obj.tags.has("sandbox"), obj)
            self.assertFalse(obj.tags.has(f"project_{project.pk}"), obj)
        self.assertEqual(list(ObjectDB.objects.get_by_tag("sandbox")), [])
        project.refresh_from_db()
        self.assertEqual((project.status, project.built_object_ids, project.sandbox_room_id), ("live", {}, None))
        self.assertIsNotNone(project.promoted_at)
        # The timed trigger keeps running on the promoted room.
        script = ScriptDB.objects.get(pk=record["scripts"][0])
        self.assertTrue(_timer_running(script))

        # Cleanup afterwards deletes nothing live.
        objects_before = ObjectDB.objects.count()
        url = reverse("builder:cleanup_sandbox", args=[project.pk])
        self.assertEqual(self.post_json(self.client_for(self.owner), url).status_code, 400)
        with self.assertRaises(sandbox_cleanup.CleanupError):
            sandbox_cleanup.cleanup_unit(project.pk)
        self.assertEqual(ObjectDB.objects.count(), objects_before)

    def test_promote_without_a_body_uses_the_reviewed_connection(self):
        project = self.built_project(direction="e")
        resp = self.promote(project)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([e.key for e in _exits_of(self.plaza)], ["east"])

    def test_connection_different_from_snapshot_is_refused(self):
        project = self.built_project()
        other = create.create_object("typeclasses.rooms.Room", key="Docks", nohome=True)
        objects_before = ObjectDB.objects.count()
        for data in (
            {"connection_room_id": other.id, "connection_direction": "n"},
            {"connection_room_id": self.plaza.id, "connection_direction": "s"},
            {"connection_room_id": other.id},
        ):
            resp = self.promote(project, data)
            self.assertEqual(resp.status_code, 409, data)
        self.assertEqual(ObjectDB.objects.count(), objects_before)
        self.assertEqual(_exits_of(other), [])
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        for obj in self.recorded_objects(project):
            self.assertTrue(obj.tags.has("sandbox"))

    def test_direction_in_use_is_refused_by_alias_or_long_name(self):
        project = self.built_project()
        create.create_object(
            "typeclasses.exits.Exit", key="north", aliases=["n"], location=self.plaza, destination=self.plaza
        )
        resp = self.promote(project)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already has an exit", resp.json()["error"])

    def test_connection_room_gone_is_refused(self):
        project = self.built_project()
        self.plaza.delete()
        resp = self.promote(project)
        self.assertEqual(resp.status_code, 409)

    def test_injected_failure_after_first_connecting_exit(self):
        project = self.built_project()
        recorded = self.recorded_objects(project)
        objects_before = ObjectDB.objects.count()
        plaza_contents_before = list(self.plaza.contents)
        real = promotion._create_connection_exit
        calls = []

        def second_fails(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise RuntimeError("injected promotion failure")
            return real(*args, **kwargs)

        with (
            mock.patch.object(promotion, "_create_connection_exit", side_effect=second_fails),
            self.assertLogs("web.builder.promotion", level="ERROR") as logs,
        ):
            ok, result = promotion.promote_project_to_live(project.pk)
        # The failure is logged once; the undo itself raised nothing.
        self.assertEqual(len(logs.records), 1)
        self.assertNotIn("undo", logs.output[0])
        self.assertFalse(ok)
        self.assertIn("injected promotion failure", result["error"])
        self.assertEqual(len(calls), 2)
        # In memory: the live room's contents have no new exit, and the area
        # is still a sandbox.
        self.assertEqual(self.plaza.contents, plaza_contents_before)
        for obj in recorded:
            self.assertTrue(obj.tags.has("sandbox"), obj)
            self.assertTrue(obj.tags.has(f"project_{project.pk}"), obj)
        # In rows: no new object, project unchanged.
        self.assertEqual(ObjectDB.objects.count(), objects_before)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertTrue(project.built_object_ids)
        # And it can still be promoted afterwards.
        ok, result = promotion.promote_project_to_live(project.pk)
        self.assertTrue(ok, result)


class CleanupTests(SandboxTestBase):
    def cleanup_url(self, project):
        return reverse("builder:cleanup_sandbox", args=[project.pk])

    def make_player_character(self, location):
        account = create.create_account("splayer", "sp@example.com", "testpassword123")
        char = create.create_object("typeclasses.characters.Character", key="Vic", location=location, home=location)
        char.db_account = account
        char.save(update_fields=["db_account"])
        return char

    def forge(self, project, *objs):
        for obj in objs:
            obj.tags.add("sandbox")
            obj.tags.add(f"project_{project.pk}")

    def test_owner_cleanup_removes_only_recorded_objects(self):
        project = self.built_project(map_data=area_map(3, timed_rooms=(1, 3)))
        recorded_ids = [o.id for o in self.recorded_objects(project)]
        unrelated = create.create_object("typeclasses.rooms.Room", key="Unrelated", nohome=True)
        objects_before = ObjectDB.objects.count()

        resp = self.post_json(self.client_for(self.owner), self.cleanup_url(project))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["deleted"], {"rooms": 3, "exits": 4, "objects": 0})
        self.assert_nothing_left(recorded_ids, objects_before - len(recorded_ids), 0)
        self.assertTrue(ObjectDB.objects.filter(pk__in=[self.plaza.id, unrelated.id]).count() == 2)
        project.refresh_from_db()
        self.assertEqual((project.status, project.sandbox_room_id, project.built_object_ids), ("approved", None, {}))
        # The project record is kept, and it can be built again.
        ok, result = create_sandbox_from_project(project.pk)
        self.assertTrue(ok, result)

    def test_cleanup_route_permissions(self):
        project = self.built_project()
        self.assertEqual(self.post_json(self.client_for(self.builder2), self.cleanup_url(project)).status_code, 403)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertEqual(self.post_json(self.client_for(self.admin), self.cleanup_url(project)).status_code, 200)

    def test_forged_tags_survive_web_cleanup(self):
        project = self.built_project()
        player = self.make_player_character(self.plaza)
        self.forge(project, self.plaza, player)
        resp = self.post_json(self.client_for(self.owner), self.cleanup_url(project))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(ObjectDB.objects.filter(pk=self.plaza.id).exists())
        self.assertTrue(ObjectDB.objects.filter(pk=player.id).exists())
        self.assertEqual(player.location, self.plaza)

    def test_forged_tags_survive_in_game_cleanup(self):
        project = self.built_project()
        player = self.make_player_character(self.plaza)
        self.forge(project, self.plaza, player)
        builder_char = create.create_object("typeclasses.characters.Character", key="Bob", nohome=True)
        builder_char.db_account = self.owner
        builder_char.save(update_fields=["db_account"])
        cmd = CmdCleanupSandbox()
        cmd.caller = builder_char
        cmd.args = str(project.pk)
        with (
            mock.patch.object(builder_char, "msg") as msg,
            mock.patch("web.builder.sandbox_cleanup.call_in_main_thread", wraps=main_thread.call_in_main_thread) as spy,
        ):
            cmd.func()
        self.assertIn("Sandbox cleaned: 2 rooms, 2 exits deleted.", msg.call_args.args[0])
        self.assertEqual(spy.call_args.args, (sandbox_cleanup.cleanup_unit, project.pk))
        self.assertTrue(ObjectDB.objects.filter(pk__in=[self.plaza.id, player.id]).count() == 2)

    def test_forged_tags_survive_promotion_cleanup(self):
        project = self.built_project()
        player = self.make_player_character(self.plaza)
        # A second live room that also carries the forged tags.
        decoy = create.create_object("typeclasses.rooms.Room", key="Decoy", nohome=True)
        self.forge(project, decoy, player)
        with mock.patch.object(promotion, "delete_recorded", wraps=sandbox_cleanup.delete_recorded) as sweep:
            ok, result = promote_project_to_live(project.pk)
        self.assertTrue(ok, result)
        self.assertEqual(sweep.call_count, 1)
        self.assertEqual(sweep.call_args.args, ([], []))
        self.assertTrue(ObjectDB.objects.filter(pk__in=[decoy.id, player.id]).count() == 2)
        # Promotion didn't touch the forged objects' tags either.
        self.assertTrue(decoy.tags.has("sandbox"))

    def test_recorded_object_given_an_account_is_left_alone(self):
        project = self.built_project()
        record = project.built_object_ids
        odd_room = ObjectDB.objects.get(pk=record["rooms"]["r2"])
        odd_room.db_account = create.create_account("sodd", "sodd@example.com", "testpassword123")
        odd_room.save(update_fields=["db_account"])
        resp = self.post_json(self.client_for(self.owner), self.cleanup_url(project))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["skipped"], [odd_room.id])
        self.assertTrue(ObjectDB.objects.filter(pk=odd_room.id).exists())
        self.assertFalse(ObjectDB.objects.filter(pk=record["rooms"]["r1"]).exists())

    def test_occupied_sandbox_is_refused_and_untouched(self):
        project = self.built_project()
        entry = ObjectDB.objects.get(pk=project.sandbox_room_id)
        player = self.make_player_character(entry)
        objects_before = ObjectDB.objects.count()
        resp = self.post_json(self.client_for(self.owner), self.cleanup_url(project))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("still inside", resp.json()["error"])
        self.assertEqual(ObjectDB.objects.count(), objects_before)
        self.assertEqual(player.location, entry)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")

    def test_unrecorded_exit_into_sandbox_is_refused(self):
        project = self.built_project()
        entry = ObjectDB.objects.get(pk=project.sandbox_room_id)
        dug = create.create_object("typeclasses.exits.Exit", key="hatch", location=self.plaza, destination=entry)
        resp = self.post_json(self.client_for(self.owner), self.cleanup_url(project))
        self.assertEqual(resp.status_code, 409)
        self.assertIn(f"#{dug.id}", resp.json()["error"])
        self.assertTrue(ObjectDB.objects.filter(pk=dug.id).exists())
