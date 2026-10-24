"""Production in-page dialog and asynchronous editor continuation contract."""

import shutil
import subprocess
import unittest
from pathlib import Path


class PageDialogTests(unittest.TestCase):
    def test_production_dialog_and_confirmation_continuations(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required for dialog acceptance")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "node",
                str(root / "web/builder/fixtures/page_dialogs.cjs"),
                str(root / "web/static/builder/page-dialogs.js"),
                *[
                    str(root / "web/templates" / path)
                    for path in (
                        "builder/editor.html",
                        "builder/dashboard.html",
                        "builder/review.html",
                        "character_approval.html",
                    )
                ],
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("page dialogs and async continuation contract OK", result.stdout)
