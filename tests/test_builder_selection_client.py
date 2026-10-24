"""Production drag dirty-state and submission connection defaults."""

import shutil
import subprocess
import unittest
from pathlib import Path


class BuilderSelectionTests(unittest.TestCase):
    def test_selection_drag_and_submission_connection(self):
        self.assertIsNotNone(shutil.which("node"))
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "node",
                str(root / "web/builder/fixtures/selection_submit.cjs"),
                str(root / "web/templates/builder/editor.html"),
                str(root / "web/templates/builder/dashboard.html"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Room selection/drag and stored submit connection contract OK", result.stdout)
