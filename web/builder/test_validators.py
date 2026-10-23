"""
The strict build-map rules (F-091): object ids, enum fields, exit lock
allowlist and per-trigger rules, enforced at submit and at build.
"""

import copy
import json

from django.test import Client, TestCase
from django.urls import reverse
from evennia.utils import create

from web.builder.models import BuildProject
from web.builder.validators import entry_room_key, validate_build_map, validate_lock_string

GOOD_MAP = {
    "rooms": {
        "r1": {
            "name": "Hall",
            "description": "A hall.",
            "v5": {"location_type": "haven", "day_night": "always", "danger_level": "low", "hunting_modifier": 1},
        },
        "r2": {"name": "Annex", "description": "", "triggers": []},
    },
    "exits": {
        "e1": {"source": "r1", "target": "r2", "name": "east", "aliases": ["e"], "locks": "traverse:all()"},
    },
}


def _with(path, value):
    data = copy.deepcopy(GOOD_MAP)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


class LockAllowlistTests(TestCase):
    def test_allowed_locks(self):
        for lock in (
            "traverse:all()",
            "traverse:perm(Builder)",
            "view:tag(vip)",
            "traverse:tag(member, camarilla) or perm(Admin)",
            "traverse:not perm(Player);view:all()",
            "traverse:(perm(Builder) and tag(x)) or all()",
        ):
            self.assertIsNone(validate_lock_string(lock), lock)

    def test_refused_locks(self):
        for lock in (
            "puppet:all()",
            "delete:all()",
            "edit:perm(Builder)",
            "traverse:superuser()",
            "traverse:id(1)",
            "traverse:attr(vampire)",
            "traverse:all() and",
            "traverse:(all()",
            "traverse:all();traverse:perm(Admin)",
            "traverse",
            "traverse:perm(Builder);control:all()",
            "traverse:perm(Builder) __import__",
        ):
            self.assertIsNotNone(validate_lock_string(lock), lock)


class BuildMapTests(TestCase):
    def test_good_map_passes(self):
        self.assertEqual(validate_build_map(GOOD_MAP), [])

    def test_bad_maps_fail(self):
        cases = {
            "room id": {"rooms": {"r 1;drop": {"name": "x"}}, "exits": {}},
            "exit id": _with(["exits"], {"e/1": GOOD_MAP["exits"]["e1"]}),
            "no name": _with(["rooms", "r2", "name"], ""),
            "name type": _with(["rooms", "r2", "name"], ["x"]),
            "location_type": _with(["rooms", "r1", "v5", "location_type"], "space"),
            "day_night": _with(["rooms", "r1", "v5", "day_night"], "sometimes"),
            "danger": _with(["rooms", "r1", "v5", "danger_level"], 3),
            "hunting": _with(["rooms", "r1", "v5", "hunting_modifier"], 99),
            "haven": _with(["rooms", "r1", "v5", "haven_ratings"], {"security": "max"}),
            "exit target": _with(["exits", "e1", "target"], "r9"),
            "aliases": _with(["exits", "e1", "aliases"], "e"),
            "locks": _with(["exits", "e1", "locks"], "puppet:all()"),
            "trigger": _with(
                ["rooms", "r2", "triggers"],
                [
                    {
                        "id": "t1",
                        "type": "entry",
                        "action": "set_attribute",
                        "parameters": {"target": "character", "attr_name": "experience", "value": 1},
                    }
                ],
            ),
            "two entries": _with(["rooms", "r2", "is_entry"], True),
            "not an object": [],
        }
        cases["two entries"]["rooms"]["r1"]["is_entry"] = True
        for name, data in cases.items():
            self.assertTrue(validate_build_map(data), name)

    def test_entry_room(self):
        self.assertEqual(entry_room_key(GOOD_MAP), "r1")
        self.assertEqual(entry_room_key(_with(["rooms", "r2", "is_entry"], True)), "r2")


class SubmitRefusesUnbuildableMapTests(TestCase):
    def test_submit_400_for_a_disallowed_lock(self):
        owner = create.create_account("vowner", "v@example.com", "testpassword123", permissions=["Builder"])
        room = create.create_object("typeclasses.rooms.Room", key="Plaza", nohome=True)
        project = BuildProject.objects.create(
            user=owner, name="Area", map_data=_with(["exits", "e1", "locks"], "puppet:all()")
        )
        client = Client()
        client.force_login(owner)
        resp = client.post(
            reverse("builder:submit_project", args=[project.pk]),
            data=json.dumps({"connection_room_id": room.id, "connection_direction": "n"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("e1", resp.json()["error"])
        project.refresh_from_db()
        self.assertEqual(project.status, "draft")


MXP_PAYLOAD = "A cold crypt. |lcperm *mallory = Admin|ltthe old door|le"


def _trigger(**overrides):
    trigger = {"id": "t1", "type": "entry", "action": "send_message", "parameters": {"message": "Cold."}}
    trigger.update(overrides)
    return trigger


class MxpMarkupTests(TestCase):
    """R-1: builder text can't carry clickable command or URL links."""

    def test_every_text_field_refuses_mxp(self):
        cases = {
            "room desc": _with(["rooms", "r1", "description"], MXP_PAYLOAD),
            "room name": _with(["rooms", "r1", "name"], "|lclook|ltHall|le"),
            "exit name": _with(["exits", "e1", "name"], "|lceast|lteast|le"),
            "exit alias": _with(["exits", "e1", "aliases"], ["|luhttp://evil.example|ltgo|le"]),
            "exit desc": _with(["exits", "e1", "description"], MXP_PAYLOAD),
            "trigger message": _with(["rooms", "r2", "triggers"], [_trigger(parameters={"message": MXP_PAYLOAD})]),
            "set_attribute text": _with(
                ["rooms", "r2", "triggers"],
                [
                    _trigger(
                        action="set_attribute",
                        parameters={"target": "room", "attr_name": "sign", "value": MXP_PAYLOAD},
                    )
                ],
            ),
        }
        for name, data in cases.items():
            self.assertTrue(validate_build_map(data), name)
        # Colour codes are fine.
        self.assertEqual(validate_build_map(_with(["rooms", "r1", "description"], "A |rred|n door.")), [])

    def test_refused_at_submit_trigger_api_and_run(self):
        owner = create.create_account("mowner", "m@example.com", "testpassword123", permissions=["Builder"])
        plaza = create.create_object("typeclasses.rooms.Room", key="Plaza", nohome=True)
        project = BuildProject.objects.create(
            user=owner, name="Area", map_data=_with(["rooms", "r1", "description"], MXP_PAYLOAD)
        )
        client = Client()
        client.force_login(owner)
        resp = client.post(
            reverse("builder:submit_project", args=[project.pk]),
            data=json.dumps({"connection_room_id": plaza.id, "connection_direction": "n"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("link markup", resp.json()["error"])

        resp = client.post(
            reverse("builder:room_triggers", args=[project.pk, "r2"]),
            data=json.dumps(_trigger(parameters={"message": MXP_PAYLOAD})),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

        from unittest import mock

        from web.builder.trigger_engine import execute_triggers

        room = create.create_object("typeclasses.rooms.Room", key="Crypt", nohome=True)
        char = create.create_object("typeclasses.characters.Character", key="Nina", nohome=True)
        room.db.triggers = [_trigger(parameters={"message": MXP_PAYLOAD})]
        with mock.patch.object(char, "msg") as msg:
            self.assertEqual(execute_triggers(room, "entry", char), (0, 1))
        msg.assert_not_called()

    def test_build_strips_mxp_from_an_old_snapshot(self):
        from evennia.utils.text2html import parse_html

        from web.builder import sandbox_builder

        room = sandbox_builder._create_room(1, "r1", {"name": "|lclook|ltHall|le"})
        self.assertEqual(room.key, "lookHall")
        desc = sandbox_builder._room_attributes({"description": MXP_PAYLOAD + " ||lcx|ltpart"})[0][1]
        self.assertEqual(desc, "A cold crypt. perm *mallory = Adminthe old door xpart")
        self.assertNotIn("<a", parse_html(desc))
        exit_obj = sandbox_builder._create_exit(
            1, "e1", {"source": "r1", "target": "r1", "name": "door|le", "aliases": ["|lu"]}, {"r1": room}
        )
        self.assertEqual((exit_obj.key, exit_obj.aliases.all()), ("door", []))

    def test_link_split_across_fields_is_refused(self):
        """Evennia parses links over the whole message, so a link split across
        fields shown together must be caught token by token."""
        from evennia.utils.text2html import parse_html

        # The attack the per-field complete-link check missed: shown together,
        # this renders as a clickable command link.
        desc, name = "A crypt. |lcperm *mallory = Admin|ltthe old", "door|le"
        self.assertIn("perm *mallory = Admin", parse_html(f"{desc}\nExits: {name}"))
        self.assertIn("<a", parse_html(f"{desc}\nExits: {name}"))

        cases = {
            "desc + exit name": [
                (["rooms", "r1", "description"], desc),
                (["exits", "e1", "name"], name),
            ],
            "room name + desc": [
                (["rooms", "r1", "name"], "Hall |lclook"),
                (["rooms", "r1", "description"], "|ltclick|le"),
            ],
            "two exit names": [
                (["exits", "e1", "name"], "|lcperm *m = Admin|lteast"),
                (["exits", "e2", "name"], "west|le"),
            ],
            "escaped pipe": [(["rooms", "r1", "description"], "||lcperm *m = Admin||ltx||le")],
            "url token": [(["rooms", "r2", "description"], "see |luhttp://evil.example")],
            "lone end token in alias": [(["exits", "e1", "aliases"], ["e|le"])],
            "trigger message": [
                (["rooms", "r2", "triggers"], [_trigger(parameters={"message": "the old door|le"})]),
            ],
        }
        for label, edits in cases.items():
            data = copy.deepcopy(GOOD_MAP)
            data["exits"]["e2"] = {"source": "r2", "target": "r1", "name": "west"}
            for path, value in edits:
                node = data
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
            errors = validate_build_map(data)
            self.assertTrue(any("link markup" in e for e in errors), (label, errors))
        # Ordinary text and colour codes still pass.
        self.assertEqual(validate_build_map(_with(["rooms", "r1", "description"], "A |rred|n door. |/Lit.")), [])


class TriggerCapTests(TestCase):
    """R-4: triggers per room and timed triggers per project are capped."""

    def _timed(self, n, prefix="d"):
        return [_trigger(id=f"{prefix}{i}", type="timed", interval=60) for i in range(n)]

    def test_caps(self):
        self.assertEqual(validate_build_map(_with(["rooms", "r1", "triggers"], self._timed(10))), [])
        self.assertTrue(validate_build_map(_with(["rooms", "r1", "triggers"], self._timed(11))))
        data = {"rooms": {}, "exits": {}}
        for r in range(4):
            data["rooms"][f"r{r}"] = {"name": f"Room {r}", "triggers": self._timed(8, prefix=f"r{r}_")}
        errors = validate_build_map(data)
        self.assertTrue(any("timed triggers" in e for e in errors), errors)

    def test_minimum_interval_is_60(self):
        from web.builder.trigger_engine import validate_trigger

        self.assertFalse(validate_trigger(_trigger(type="timed", interval=59))[0])
        self.assertTrue(validate_trigger(_trigger(type="timed", interval=60))[0])

    def test_trigger_api_enforces_the_room_cap(self):
        owner = create.create_account("cowner", "c@example.com", "testpassword123", permissions=["Builder"])
        project = BuildProject.objects.create(
            user=owner,
            name="Area",
            map_data={"rooms": {"r1": {"name": "Hall", "triggers": self._timed(10)}}, "exits": {}},
        )
        client = Client()
        client.force_login(owner)
        resp = client.post(
            reverse("builder:room_triggers", args=[project.pk, "r1"]),
            data=json.dumps(_trigger(id="one_more")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at most 10", resp.json()["error"])
