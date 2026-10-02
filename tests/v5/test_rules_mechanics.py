"""
V5 derived mechanics (Remorse, frenzy, XP) on real characters.

Expected values come from the V5 core book / Quick Reference, not from the
code. The tests below fail on the current code; each carries the finding id
and the PR that fixes it. That PR removes the marker.
"""

import unittest
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaTest

from commands.v5.utils import humanity_utils, xp_utils


def dice_count(roll):
    """Number of dice in a roll result, whichever dice engine produced it."""
    regular = getattr(roll, "regular_dice", None)
    if regular is None:
        regular = roll.normal_dice
    return len(regular) + len(roll.hunger_dice)


class RemorseTests(EvenniaTest):
    # F-039, fixed in PR 6: Remorse rolls Humanity dice and needs more
    # successes than Stains. V5 (QR p.3) rolls one die per unmarked Humanity
    # box, minimum 1: at Humanity 7 with 2 Stains that is 10 - 7 - 2 = 1 die.
    @unittest.expectedFailure
    def test_remorse_rolls_unmarked_boxes(self):
        char = self.char1
        humanity_utils.set_humanity(char, 7)
        humanity_utils.add_stain(char, 2)
        with patch("random.randint", return_value=6), patch("dice.dice_roller.randint", return_value=6):
            result = humanity_utils.remorse_roll(char)
        self.assertEqual(dice_count(result["roll_result"]), 1)


class FrenzyTests(EvenniaTest):
    # F-041, fixed in PR 6: resist_frenzy rolls current Willpower + Composure
    # (8 + 4 = 12 dice here). V5 (QR p.4) rolls Willpower + Humanity / 3:
    # Composure 4 + Resolve 4 gives Willpower 8, plus 7 // 3 = 2.
    @unittest.expectedFailure
    def test_frenzy_pool_is_willpower_plus_third_humanity(self):
        char = self.char1
        char.db.stats["attributes"]["social"]["composure"] = 4
        char.db.stats["attributes"]["mental"]["resolve"] = 4
        humanity_utils.set_humanity(char, 7)
        char.hunger = 0
        with patch("random.randint", return_value=6), patch("dice.dice_roller.randint", return_value=6):
            result = humanity_utils.resist_frenzy(char, difficulty=3)
        self.assertEqual(dice_count(result["roll_result"]), 10)


class XPSpendTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.char.db.experience["total_earned"] = 50
        self.char.db.stats["attributes"]["physical"]["strength"] = 3

    # F-005: the spend resolves the name through the trait registry, so an
    # attribute can no longer be bought at the skill price.
    def test_skill_spend_refuses_an_attribute(self):
        ok, message = xp_utils.spend_xp_on_skill(self.char, "strength")
        self.assertFalse(ok)
        self.assertIn("not one of the skills", message)
        self.assertEqual(self.char.xp, 50)
        self.assertEqual(self.char.db.stats["attributes"]["physical"]["strength"], 3)

    # F-043, fixed in PR 6: Caitiff disciplines cost new x 6 (QR p.1); the
    # code prices them as out-of-clan (new x 7).
    @unittest.expectedFailure
    def test_caitiff_discipline_cost(self):
        self.char.db.vampire["clan"] = "Caitiff"
        cost, new_rating, _in_clan = xp_utils.get_xp_cost_discipline(self.char, "potence")
        self.assertEqual(new_rating, 1)
        self.assertEqual(cost, 6)
