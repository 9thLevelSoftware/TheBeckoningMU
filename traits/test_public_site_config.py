import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from web.website.public_config import DEFAULT_CONFIG_PATH, public_game_origin, render_public_config


class PublicSiteConfigTests(SimpleTestCase):
    def test_https_and_explicit_loopback_origins_are_canonical(self):
        cases = {
            " https://Game.Example/ ": "https://game.example",
            "https://game.example:443/": "https://game.example",
            "https://game.example:8443/": "https://game.example:8443",
            "http://localhost:6665/": "http://localhost:6665",
            "http://127.0.0.1:80": "http://127.0.0.1",
            "http://[::1]:6665/": "http://[::1]:6665",
            "https://tést.example/": "https://xn--tst-bma.example",
            "": "",
            "   ": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(public_game_origin(raw), expected)

    def test_invalid_non_origin_and_unsafe_schemes_are_rejected(self):
        cases = [
            None,
            123,
            "game.example",
            "//game.example",
            "javascript:alert(1)",
            "ftp://game.example",
            "http://game.example",
            "http://localhost.evil.example",
            "http://127.0.0.2",
            "http://127.1",
            "https://user:password@game.example",
            "https://@game.example",
            "https://game.example/path",
            "https://game.example//",
            "https://game.example?",
            "https://game.example#",
            "https://game.example/?q=1",
            "https://game.example/#fragment",
            "https://game.example:invalid",
            "https://game.example:65536",
            "https://game.example:",
            "https://game.example\n",
            "https://game.example\\evil",
            "https://bad host.example",
            "https://game.example/</script><script>alert(1)</script>",
            "https://[::1",
            "https://999.999.999.999",
            "https://[::1]unexpected",
            "https://[::1%25zone]",
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                public_game_origin(raw)

    def test_rendered_assignment_contains_only_a_json_string(self):
        rendered = render_public_config("https://game.example:8443/")
        assignment = rendered.splitlines()[1]
        self.assertTrue(assignment.startswith("window.PUBLIC_GAME_BASE_URL = "))
        self.assertEqual(
            json.loads(assignment.removeprefix("window.PUBLIC_GAME_BASE_URL = ").removesuffix(";")),
            "https://game.example:8443",
        )
        self.assertNotIn("</script", rendered)
        self.assertIn('window.PUBLIC_GAME_BASE_URL = "";', render_public_config(""))

    @override_settings(PUBLIC_GAME_BASE_URL="https://game.example/")
    def test_management_command_uses_settings_and_only_explicit_output(self):
        placeholder = DEFAULT_CONFIG_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site-config.js"
            stdout = io.StringIO()
            call_command("build_public_site_config", output=output, stdout=stdout)
            self.assertIn('window.PUBLIC_GAME_BASE_URL = "https://game.example";', output.read_text(encoding="utf-8"))
            self.assertIn(str(output), stdout.getvalue())
            self.assertNotIn(b"\r\n", output.read_bytes())
        self.assertEqual(DEFAULT_CONFIG_PATH.read_bytes(), placeholder)

    @override_settings(PUBLIC_GAME_BASE_URL="")
    def test_empty_config_replaces_previous_origin_with_unavailable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site-config.js"
            output.write_text("previous public origin", encoding="utf-8")
            call_command("build_public_site_config", output=output, stdout=io.StringIO())
            self.assertIn('window.PUBLIC_GAME_BASE_URL = "";', output.read_text(encoding="utf-8"))

    @override_settings(PUBLIC_GAME_BASE_URL="https://game.example/private")
    def test_invalid_setting_never_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site-config.js"
            output.write_bytes(b"preserve existing deployment asset\n")
            with self.assertRaises(CommandError):
                call_command("build_public_site_config", output=output, stdout=io.StringIO())
            self.assertEqual(output.read_bytes(), b"preserve existing deployment asset\n")
            self.assertEqual(list(Path(directory).iterdir()), [output])
