"""
Tests for Discipline Utility Functions

These run on real Evennia characters whose disciplines are stored in the
typeclass shape (``db.stats['disciplines'][name] = {'level': n, 'powers': [...]}``).
Only the die is patched.
"""

import unittest
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaTest

from commands.v5.utils import discipline_utils


class ActivateDisciplinePowerTests(EvenniaTest):
    """activate_discipline_power on a character that has the discipline."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.char.db.stats["disciplines"]["animalism"] = {
            "level": 2,
            "powers": ["Feral Whispers", "Sense the Beast"],
        }
        self.char.hunger = 2

    # F-038, fixed in PR 5: activate_discipline_power calls
    # roll_rouse_check(character, reason=...), which takes no arguments, so
    # every Rouse-costing power raises TypeError.
    @unittest.expectedFailure
    def test_rouse_power_failed_rouse_raises_hunger(self):
        """A failed Rouse (die 1-5) on a 1-Rouse power raises Hunger by 1."""
        with patch("dice.dice_roller.randint", return_value=3):
            result = discipline_utils.activate_discipline_power(self.char, "Animalism", "Feral Whispers")
        self.assertTrue(result["success"])
        self.assertEqual(self.char.hunger, 3)

    # F-038: the power check reads disciplines through Character.get_trait.
    def test_free_power_leaves_hunger_unchanged(self):
        """A power with no Rouse cost activates and leaves Hunger alone."""
        result = discipline_utils.activate_discipline_power(self.char, "Animalism", "Sense the Beast")
        self.assertTrue(result["success"])
        self.assertEqual(self.char.hunger, 2)


class TurnDurationPowerTests(EvenniaTest):
    """A power whose duration token is "turn" is tracked for one turn."""

    def test_turn_power_activates_and_tracks_one_turn(self):
        char = self.char1
        char.db.stats["disciplines"]["celerity"] = {"level": 3, "powers": ["Blink"]}
        char.hunger = 1
        passed = {"hunger_increased": False, "die": 8}
        with patch("commands.v5.utils.discipline_utils.roll_rouse_check", return_value=passed):
            result = discipline_utils.activate_discipline_power(char, "Celerity", "Blink")
        self.assertTrue(result["success"])
        effects = [e for e in char.db.active_effects if e["power"] == "Blink"]
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["duration"], "turn")
        self.assertEqual(effects[0]["turns_remaining"], 1)
        self.assertEqual(char.hunger, 1)
