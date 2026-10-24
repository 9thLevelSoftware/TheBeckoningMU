"""Builder review and publication boundaries for explicit room access policy."""

import copy
import json
import subprocess
from pathlib import Path

from django.urls import reverse
from evennia.objects.models import ObjectDB

from web.builder import promotion, sandbox_builder
from web.builder.models import BuildProject
from web.builder.test_sandbox import SandboxTestBase, area_map
from web.builder.validators import validate_build_map


def restricted_map(value=None):
    data = area_map()
    data["rooms"]["r1"]["v5"] = {"day_night": "restricted"}
    if value is not None:
        data["rooms"]["r1"]["v5"]["restricted_characters"] = value
    return data


class BuilderRoomPolicyTests(SandboxTestBase):
    def test_restricted_policy_requires_unique_positive_integer_principals(self):
        for invalid in (None, [], [0], [-1], [True], [1, 1], ["1"], "1, 2", list(range(1, 102))):
            self.assertTrue(validate_build_map(restricted_map(invalid)), invalid)
        self.assertEqual(validate_build_map(restricted_map([1, 22, 333])), [])
        self.assertEqual(validate_build_map(area_map()), [])

    def test_invalid_legacy_restricted_policy_is_saved_but_cannot_submit(self):
        client = self.client_for(self.owner)
        data = restricted_map("ambiguous legacy policy")
        response = self.post_json(client, reverse("builder:save_project"), {"name": "Legacy", "map_data": data})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["validation"]["is_valid"])
        project = BuildProject.objects.get(pk=response.json()["id"])
        self.assertEqual(project.map_data, data)
        response = self.post_json(
            client,
            reverse("builder:submit_project", args=[project.pk]),
            {"connection_room_id": self.plaza.pk, "connection_direction": "n"},
        )
        self.assertEqual(response.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.status, "draft")
        self.assertEqual(project.map_data, data)

    def test_build_serializes_the_exact_reviewed_restricted_policy(self):
        project = self.approved_project(map_data=restricted_map([11, 22]))
        sandbox_builder.build_unit(project.pk)
        project.refresh_from_db()
        room = ObjectDB.objects.get(pk=project.built_object_ids["rooms"]["r1"])
        self.assertEqual(list(room.db.restricted_characters), [11, 22])
        self.assertEqual(room.db.day_night, "restricted")

    def test_ambiguous_historical_snapshot_blocks_build_and_promotion(self):
        project = self.approved_project(map_data=restricted_map())
        with self.assertRaises(sandbox_builder.BuildError):
            sandbox_builder.build_unit(project.pk)
        project = self.built_project(map_data=restricted_map([11]))
        snapshot = copy.deepcopy(project.approved_map_data)
        snapshot["map_data"]["rooms"]["r1"]["v5"].pop("restricted_characters")
        BuildProject.objects.filter(pk=project.pk).update(approved_map_data=snapshot)
        before = ObjectDB.objects.count()
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_unit(project.pk)
        project.refresh_from_db()
        self.assertEqual(project.status, "built")
        self.assertEqual(ObjectDB.objects.count(), before)
        for obj in self.recorded_objects(project):
            self.assertTrue(obj.tags.has("sandbox"))

    def test_changed_built_policy_cannot_replace_reviewed_policy_at_promotion(self):
        project = self.built_project(map_data=restricted_map([11]))
        room = ObjectDB.objects.get(pk=project.built_object_ids["rooms"]["r1"])
        room.db.restricted_characters = [22]
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_unit(project.pk)
        self.assertTrue(room.tags.has("sandbox"))

    def test_editor_policy_control_round_trips_without_silently_repairing_legacy_data(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures" / "room_policy_editor.cjs"),
                str(root / "web" / "templates" / "builder" / "editor.html"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        client = self.client_for(self.owner)
        response = self.post_json(client, reverse("builder:save_project"), {"name": "Policy", "map_data": data})
        self.assertTrue(response.json()["validation"]["is_valid"], response.content)
        project = BuildProject.objects.get(pk=response.json()["id"])
        self.assertEqual(project.map_data["rooms"]["r1"]["v5"]["restricted_characters"], [12, 34])
        project.connection_room_id = self.plaza.pk
        project.connection_direction = "n"
        project.submit()
        review = self.client_for(self.builder2).get(reverse("builder:review_projects")).json()
        item = next(item for item in review["projects"] if item["id"] == project.pk)
        self.assertEqual(item["room_settings"]["r1"]["restricted_characters"], [12, 34])
        page = client.get(reverse("builder:edit_project", args=[project.pk]))
        self.assertContains(page, 'id="room-restricted-characters"')
        self.assertContains(page, "staff adjudication")
