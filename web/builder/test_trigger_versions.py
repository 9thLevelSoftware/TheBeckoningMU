"""Trigger API writes must bind to the client-visible project version."""

import copy
import json

from django.urls import reverse

from web.builder.tests import BuilderGateTestBase, _map


class TriggerClientVersionTests(BuilderGateTestBase):
    def setUp(self):
        super().setUp()
        data = _map()
        self.trigger = {"id": "t1", "type": "entry", "action": "send_message", "parameters": {"message": "Cold"}}
        data["rooms"]["r1"]["triggers"] = [self.trigger]
        self.project = self.make_project(self.owner, map_data=data)
        self.owner_client = self.client_for(self.owner)
        self.url = reverse("builder:room_triggers", args=[self.project.pk, "r1"])
        self.delete_url = reverse("builder:room_trigger_detail", args=[self.project.pk, "r1", "t1"])

    def test_get_and_current_mutations_expose_incremented_versions(self):
        response = self.owner_client.get(self.url)
        self.assertEqual(response.json()["version"], 1)
        replacement = copy.deepcopy(self.trigger)
        replacement["parameters"]["message"] = "Fresh"
        response = self.post_json(self.owner_client, self.url, {**replacement, "version": 1})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["version"], 2)
        self.assertNotIn("version", response.json()["trigger"])
        response = self.owner_client.delete(
            self.delete_url, data=json.dumps({"version": 2}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["version"], 3)

    def test_stale_post_and_delete_preserve_the_newer_whole_map(self):
        seen = self.owner_client.get(self.url).json()["version"]
        data = copy.deepcopy(self.project.map_data)
        data["rooms"]["r1"]["triggers"][0]["parameters"]["message"] = "Newer"
        response = self.post_json(
            self.owner_client,
            reverse("builder:save_project"),
            {"id": self.project.pk, "version": seen, "name": "Newer draft", "map_data": data},
        )
        self.assertEqual(response.status_code, 200, response.content)
        response = self.post_json(self.owner_client, self.url, {**self.trigger, "version": seen})
        self.assertEqual(response.status_code, 409, response.content)
        response = self.owner_client.delete(
            self.delete_url, data=json.dumps({"version": seen}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.map_data, data)
        self.assertEqual(self.project.version, 2)

    def test_mutations_require_nonboolean_integer_client_version(self):
        for version in (None, True, "1"):
            response = self.post_json(self.owner_client, self.url, {**self.trigger, "version": version})
            self.assertEqual(response.status_code, 400, response.content)
            response = self.owner_client.delete(
                self.delete_url, data=json.dumps({"version": version}), content_type="application/json"
            )
            self.assertEqual(response.status_code, 400, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.version, 1)
        self.assertEqual(self.project.map_data["rooms"]["r1"]["triggers"], [self.trigger])
