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
            "level": 1,
            "powers": ["Bond Famulus", "Sense the Beast"],
        }
        self.char.hunger = 2

    # F-038, fixed in PR 5: +power reads db.disciplines, which nothing
    # populates, and then calls roll_rouse_check(character, reason=...), which
    # takes no arguments, so every Rouse-costing power crashes.
    @unittest.expectedFailure
    def test_rouse_power_failed_rouse_raises_hunger(self):
        """A failed Rouse (die 1-5) on a Rouse power raises Hunger by 1."""
        with patch("dice.dice_roller.randint", return_value=3):
            result = discipline_utils.activate_discipline_power(self.char, "Animalism", "Bond Famulus")
        self.assertTrue(result["success"])
        self.assertEqual(self.char.hunger, 3)

    # F-038, fixed in PR 4: the power check reads db.disciplines, which is
    # None on a real character, so can_use_power raises AttributeError. PR 4
    # replaces every db.disciplines read.
    @unittest.expectedFailure
    def test_free_power_leaves_hunger_unchanged(self):
        """A power with no Rouse cost activates and leaves Hunger alone."""
        result = discipline_utils.activate_discipline_power(self.char, "Animalism", "Sense the Beast")
        self.assertTrue(result["success"])
        self.assertEqual(self.char.hunger, 2)
