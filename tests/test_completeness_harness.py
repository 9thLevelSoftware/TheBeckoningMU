"""Safety and false-positive guards for the optional local acceptance harness."""

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError

from tests.support.completeness_e2e import confirm_fixture_identity, loopback_ready, validate_game_steps


class CompletenessHarnessTests(unittest.TestCase):
    def test_readiness_ignores_proxy_configuration_and_refuses_redirects(self):
        class Endpoint(BaseHTTPRequestHandler):
            redirect = False

            def do_GET(self):  # noqa: N802
                self.send_response(302 if self.redirect else 200)
                if self.redirect:
                    self.send_header("Location", "https://remote.invalid/not-acceptance")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch("urllib.request.getproxies", side_effect=AssertionError("Unexpected proxy discovery")):
                self.assertTrue(loopback_ready(server.server_port))
                Endpoint.redirect = True
                with self.assertRaises(HTTPError):
                    loopback_ready(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_identity_requires_positive_account_and_puppet_confirmation(self):
        account = "Account AcceptancePlayerA (you are Out-of-Character)"
        session = "Character Sheet for: AcceptancePlayerA"
        confirm_fixture_identity("PlayerA", account, session)
        for wrong_account, wrong_session in (
            ("", session),
            (account, ""),
            (account.replace("PlayerA", "PlayerB"), session),
            (account, session.replace("PlayerA", "None")),
        ):
            with self.assertRaises(AssertionError):
                confirm_fixture_identity("PlayerA", wrong_account, wrong_session)

    def test_empty_assertions_or_unbounded_steps_cannot_emit_acceptance(self):
        validate_game_steps([{"command": "look", "contains": ["Limbo"]}])
        for step in (
            {"command": "look"},
            {"command": "look", "contains": [""]},
            {"command": "look", "contains": ["Limbo"], "timeout": 61},
            {"command": "look\nquit", "contains": ["Limbo"]},
        ):
            with self.assertRaises(ValueError):
                validate_game_steps([step])
