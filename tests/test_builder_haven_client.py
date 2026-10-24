"""Run production Haven room selection, input binding and save payload in Node."""

import shutil
import subprocess
import unittest
from pathlib import Path


class HavenEditorTests(unittest.TestCase):
    def test_production_haven_edit_save_and_room_switch(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required for Haven editor acceptance")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "node",
                str(root / "web/builder/fixtures/haven_editor.cjs"),
                str(root / "web/templates/builder/editor.html"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Haven edit/save/reload/room-switch contract OK", result.stdout)
