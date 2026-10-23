"""Actual CmdHunt, real dice/feeding, real loopback Twisted HTTP and persistence."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from evennia.utils.test_resources import EvenniaTest


class LocalHTTPCommandTests(SimpleTestCase):
    def test_command_to_http_preserves_mechanics_and_does_not_block(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tests/support/local_runtime.py"), "narrative"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"gate": "command-http"', result.stdout)
        self.assertIn('"passed": true', result.stdout)


class HuntingDiceIntegrationTests(EvenniaTest):
    def test_hunting_uses_authoritative_dice_flags_and_caps_hunger_dice_to_pool(self):
        from commands.v5.utils.hunting_utils import hunt

        for dice_values, hunger, expected in (
            ([8, 8, 8, 8], 2, (True, False, False)),
            ([10, 8, 8, 10], 2, (True, True, False)),
            ([1], 5, (False, False, True)),
        ):
            with self.subTest(dice=dice_values):
                character = self.char1
                character.predator_type = "Alleycat"
                character.hunger = hunger
                character.last_hunt = None
                character.set_trait("Strength", len(dice_values))
                character.set_trait("Brawl", 0)
                with (
                    patch("dice.dice_roller.randint", side_effect=dice_values) as dice,
                    patch("commands.v5.utils.hunting_utils.random.randint", return_value=100),
                    patch("commands.v5.utils.hunting_utils.random.choice", side_effect=lambda values: values[0]),
                ):
                    result = hunt(character, "downtown")
                self.assertEqual(dice.call_count, len(dice_values))
                roll = result["roll"]
                self.assertEqual((result["success"], roll.is_messy_critical, roll.is_bestial_failure), expected)
                self.assertEqual(len(roll.hunger_dice), min(hunger, len(dice_values)))
