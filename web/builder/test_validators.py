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
