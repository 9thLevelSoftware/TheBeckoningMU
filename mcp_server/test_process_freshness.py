"""SDK reads in a cached companion process observe separate-process writes."""

import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class SeparateProcessFreshnessTests(SimpleTestCase):
    def test_sdk_tools_refresh_persistence_and_enforce_transferred_ownership(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tests/support/local_runtime.py"), "mcp"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"gate": "mcp-process-freshness"', result.stdout)
        self.assertIn('"passed": true', result.stdout)
