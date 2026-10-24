"""Official OAuth client against an owned loopback HTTP runtime and temporary DB."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class LoopbackClientAuthorizationTests(SimpleTestCase):
    def test_official_sdk_oauth_discovery_authorization_refresh_and_read_permissions(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tests/support/oauth_runtime.py")],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(evidence["gate"], "loopback-sdk-oauth")
        self.assertTrue(evidence["passed"])
        self.assertNotEqual(evidence["pid"], os.getpid())
        self.assertEqual(evidence["accounts"], 2)
        self.assertEqual(evidence["negative_flows"], ["state", "issuer", "resource"])
        self.assertEqual(evidence["refreshes"], 2)
