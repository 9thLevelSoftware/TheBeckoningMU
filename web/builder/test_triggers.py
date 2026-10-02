"""
Room triggers: dispatch through real `room.db` storage, the `set_attribute`
restriction, and the V5 conditions (F-049, F-083, F-086).
"""

import json
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse
from evennia.utils import create

from web.builder.models import BuildProject
from web.builder.trigger_engine import execute_triggers, validate_trigger
from web.builder.v5_conditions import CONDITION_TYPES, check_condition


def _trigger(**overrides):
    trigger = {
        "id": "t1",
        "type": "entry",
        "action": "send_message",
        "parameters": {"message": "The air is cold."},
        "enabled": True,
        "conditions": [],
    }
    trigger.update(overrides)
    return trigger


class TriggerDispatchTests(TestCase):
    def setUp(self):
        self.room = create.create_object("typeclasses.rooms.Room", key="Crypt", nohome=True)
        self.char = create.create_object("typeclasses.characters.Character", key="Nina", nohome=True)

    def test_trigger_stored_through_room_db_fires_on_entry(self):
        self.room.db.triggers = [_trigger()]
        # What Evennia hands back is a _SaverList of _SaverDicts, not list/dict.
        self.assertNotIsInstance(self.room.db.triggers, list)
        self.assertNotIsInstance(self.room.db.triggers[0], dict)
        with mock.patch.object(self.char, "msg") as msg:
            self.assertEqual(execute_triggers(self.room, "entry", self.char), (1, 0))
        msg.assert_called_once_with("The air is cold.")

    def test_entry_hook_runs_triggers_for_a_puppeted_character(self):
        self.room.db.triggers = [_trigger()]
        with (
            mock.patch.object(type(self.char), "has_account", new_callable=mock.PropertyMock, return_value=True),
            mock.patch.object(self.char, "msg") as msg,
        ):
            self.char.move_to(self.room, quiet=True)
        self.assertIn(mock.call("The air is cold."), msg.call_args_list)

    def test_conditions_stored_as_saver_types_are_evaluated(self):
        self.char.clan = "Brujah"
        self.room.db.triggers = [_trigger(conditions=[{"type": "character_clan", "parameters": {"clan": "brujah"}}])]
        with mock.patch.object(self.char, "msg"):
            self.assertEqual(execute_triggers(self.room, "entry", self.char), (1, 0))
        self.char.clan = "Ventrue"
        with mock.patch.object(self.char, "msg") as msg:
            self.assertEqual(execute_triggers(self.room, "entry", self.char), (0, 0))
        msg.assert_not_called()

    def test_timed_script_runs_its_trigger(self):
        from typeclasses.scripts import RoomTriggerScript

        self.room.db.triggers = [
            _trigger(id="tick", type="timed", interval=60, action="emit_message", parameters={"message": "Drip."})
        ]
        script = mock.Mock(spec=RoomTriggerScript)
        script.obj = self.room
        script.db.trigger_id = "tick"
        with mock.patch.object(self.room, "msg_contents") as emit:
            RoomTriggerScript.at_repeat(script)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.args[0], "Drip.")


class SetAttributeRestrictionTests(TestCase):
    def setUp(self):
        self.room = create.create_object("typeclasses.rooms.Room", key="Crypt", nohome=True)
        self.char = create.create_object("typeclasses.characters.Character", key="Nina", nohome=True)

    def _set(self, target, attr_name, value):
        return _trigger(
            action="set_attribute",
            parameters={"target": target, "attr_name": attr_name, "value": value},
        )

    def test_sheet_attributes_rejected_at_save(self):
        for name in ("experience", "vampire", "stats", "hunger", "advantages", "chargen"):
            ok, error = validate_trigger(self._set("character", name, 9999))
            self.assertFalse(ok, name)
            self.assertIn("trigger_flag_", error)

    def test_experience_rejected_at_run(self):
        before = self.char.attributes.get("experience")
        self.room.db.triggers = [self._set("character", "experience", {"total": 9999})]
        self.assertEqual(execute_triggers(self.room, "entry", self.char), (0, 1))
        self.room.db.triggers = [self._set("character", "experience", 9999)]
        self.assertEqual(execute_triggers(self.room, "entry", self.char), (0, 1))
        self.assertEqual(self.char.attributes.get("experience"), before)

    def test_trigger_flag_on_character_is_allowed(self):
        self.room.db.triggers = [self._set("character", "trigger_flag_saw_crypt", True)]
        self.assertEqual(execute_triggers(self.room, "entry", self.char), (1, 0))
        self.assertIs(self.char.attributes.get("trigger_flag_saw_crypt"), True)

    def test_non_primitive_values_and_room_trigger_list_rejected(self):
        self.assertFalse(validate_trigger(self._set("character", "trigger_flag_x", {"a": 1}))[0])
        self.assertFalse(validate_trigger(self._set("character", "trigger_flag_x", "x" * 201))[0])
        self.assertFalse(validate_trigger(self._set("room", "triggers", "[]"))[0])
        self.assertFalse(validate_trigger(self._set("room", "desc", "pwned"))[0])
        self.assertFalse(validate_trigger(self._set("account", "trigger_flag_x", 1))[0])
        self.assertTrue(validate_trigger(self._set("room", "lights_on", False))[0])

    def test_timed_character_write_never_lands_on_the_room(self):
        self.room.db.triggers = [
            {**self._set("character", "trigger_flag_x", 1), "id": "tick", "type": "timed", "interval": 60}
        ]
        self.assertEqual(execute_triggers(self.room, "timed", None, trigger_id="tick"), (0, 1))
        self.assertIsNone(self.room.attributes.get("trigger_flag_x"))

    def test_trigger_api_refuses_a_sheet_write(self):
        owner = create.create_account("tbuilder", "t@example.com", "testpassword123", permissions=["Builder"])
        project = BuildProject.objects.create(
            user=owner, name="Area", map_data={"rooms": {"r1": {"name": "Hall"}}, "exits": {}}
        )
        client = Client()
        client.force_login(owner)
        url = reverse("builder:room_triggers", args=[project.pk, "r1"])
        resp = client.post(
            url, data=json.dumps(self._set("character", "experience", 9999)), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        project.refresh_from_db()
        self.assertNotIn("triggers", project.map_data["rooms"]["r1"])


class ConditionTests(TestCase):
    def setUp(self):
        self.room = create.create_object("typeclasses.rooms.Room", key="Crypt", nohome=True)
        self.char = create.create_object("typeclasses.characters.Character", key="Nina", nohome=True)

    def test_clan_uses_accessor_and_matches_editor_values(self):
        self.char.clan = "Thin-Blood"
        self.assertTrue(check_condition("character_clan", {"clan": "thin_blood"}, character=self.char))
        self.assertTrue(check_condition("character_clan", {"clan": "Thin-Blood"}, character=self.char))
        self.assertFalse(check_condition("character_clan", {"clan": "Brujah"}, character=self.char))
        self.assertIn("Thin-Blood", CONDITION_TYPES["character_clan"]["parameters"]["clan"]["options"])

    def test_hunger_uses_accessor_and_accepts_editor_text(self):
        self.char.hunger = 3
        self.assertTrue(check_condition("character_hunger", {"operator": "gte", "value": "3"}, character=self.char))
        self.assertFalse(check_condition("character_hunger", {"operator": "gt", "value": 3}, character=self.char))

    def test_room_conditions_read_the_editor_values(self):
        self.room.db.location_type = "haven"
        self.room.db.danger_level = "high"
        self.assertTrue(check_condition("room_type", {"location_type": "haven"}, room=self.room))
        self.assertTrue(check_condition("room_danger", {"operator": "gte", "value": "3"}, room=self.room))
        self.assertFalse(check_condition("room_danger", {"operator": "eq", "value": 0}, room=self.room))
        options = CONDITION_TYPES["room_type"]["parameters"]["location_type"]["options"]
        self.assertEqual(set(options), {"haven", "elysium", "rack", "hostile", "neutral", "mortal", "supernatural"})

    def test_bad_parameters_are_logged_not_silent(self):
        with self.assertLogs("web.builder.v5_conditions", level="WARNING"):
            self.assertFalse(check_condition("room_danger", {"operator": "gte", "value": "lots"}, room=self.room))
        with self.assertLogs("web.builder.v5_conditions", level="WARNING"):
            self.assertFalse(check_condition("character_clan", {}, character=self.char))
