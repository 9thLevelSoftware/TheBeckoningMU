"""Exercise production trigger-modal functions, with server-owned metadata."""

import json
import shutil
import subprocess
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse
from evennia.utils import create

from web.builder.trigger_actions import ACTION_PARAMETERS


class BuilderTriggerEditorTests(TestCase):
    def test_production_keyboard_activation(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required for editor acceptance")
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures" / "builder_keyboard.cjs"),
                str(root / "web" / "templates" / "builder" / "editor.html"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("builder keyboard contract OK", result.stdout)

    def test_production_modal_round_trips_typed_parameters(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required for editor acceptance")
        owner = create.create_account(
            "editor_contract", "editor@example.com", "testpassword123", permissions=["Builder"]
        )
        client = Client()
        client.force_login(owner)
        responses = []
        for parameters in ({"message": "   "}, {"message": "Cold", "unknown": True}):
            response = client.post(
                reverse("builder:save_project"),
                content_type="application/json",
                data=json.dumps(
                    {
                        "name": "Trigger draft",
                        "map_data": {
                            "rooms": {
                                "r1": {
                                    "name": "Hall",
                                    "triggers": [
                                        {
                                            "id": "t1",
                                            "type": "entry",
                                            "action": "send_message",
                                            "parameters": parameters,
                                        }
                                    ],
                                }
                            },
                            "exits": {},
                        },
                    }
                ),
            )
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertFalse(result["validation"]["is_valid"])
            self.assertTrue(result["validation"]["errors"])
            responses.append(result)
            from web.builder.models import BuildProject

            saved = BuildProject.objects.get(pk=result["id"])
            self.assertEqual(saved.map_data["rooms"]["r1"]["triggers"][0]["parameters"], parameters)
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures" / "trigger_editor.cjs"),
                str(root / "web" / "templates" / "builder" / "editor.html"),
            ],
            input=json.dumps({"actions": ACTION_PARAMETERS, "saveResponses": responses}),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("modal contract OK", result.stdout)
