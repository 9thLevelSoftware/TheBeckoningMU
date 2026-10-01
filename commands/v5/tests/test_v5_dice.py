"""
Tests for the world.v5_dice engine (DiceResult, roll_pool).

This engine still serves +attack, +remorse, +frenzy and alchemy until PR 5
deletes it, so its V5-correct behaviour stays covered here. Wrong-rule tests
were removed: rouse_check (dead code), "Hunger [4,5] with no 1s is bestial",
and the non-V5 Willpower +3 dice.
"""

import unittest

from world.v5_dice import DiceResult, roll_pool


class TestDiceResult(unittest.TestCase):
    """Test the DiceResult class for correct V5 mechanics."""

    def test_success_calculation(self):
        """Test that successes are counted correctly (6+ on any die)."""
        # Dice: 1,2,3,4,5,6,7,8,9,10
        result = DiceResult(
            normal_dice=[1, 2, 3, 4, 5],  # 1 success (5 doesn't count, 6+ only)
            hunger_dice=[6, 7, 8, 9, 10],  # 5 successes
            difficulty=3,
        )
        self.assertEqual(result.normal_successes, 0, "Dice below 6 should not count as successes")
        self.assertEqual(result.hunger_successes, 5, "All dice 6+ should count")
        self.assertEqual(result.successes, 5, "Total successes should be 5")

    def test_critical_pairs(self):
        """Test that critical pairs are calculated correctly."""
        # Two 10s = 1 critical pair
        result = DiceResult(normal_dice=[10, 10, 5, 3], hunger_dice=[], difficulty=0)
        self.assertEqual(result.criticals, 1, "Two 10s should form 1 critical pair")

        # Four 10s = 2 critical pairs
        result2 = DiceResult(normal_dice=[10, 10], hunger_dice=[10, 10], difficulty=0)
        self.assertEqual(result2.criticals, 2, "Four 10s should form 2 critical pairs")

    def test_messy_critical(self):
        """Test that Messy Criticals are detected (Hunger die in a critical pair)."""
        # Messy: Hunger die with 10 in a critical pair
        result = DiceResult(normal_dice=[10, 5], hunger_dice=[10, 3], difficulty=0)
        self.assertTrue(result.is_messy, "Should be Messy Critical (Hunger die in critical pair)")
        self.assertEqual(result.criticals, 1, "Should have 1 critical pair")

        # Not messy: No Hunger dice
        result2 = DiceResult(normal_dice=[10, 10, 5], hunger_dice=[], difficulty=0)
        self.assertFalse(result2.is_messy, "Should NOT be Messy (no Hunger dice)")

    def test_not_bestial(self):
        """A roll with successes, or with no Hunger dice, is not a bestial failure."""
        # Not bestial: Has successes
        result2 = DiceResult(normal_dice=[6, 2, 3], hunger_dice=[4, 5], difficulty=0)
        self.assertFalse(result2.is_bestial, "Should NOT be Bestial (has successes)")

        # Not bestial: No Hunger dice
        result3 = DiceResult(normal_dice=[1, 2, 3], hunger_dice=[], difficulty=0)
        self.assertFalse(result3.is_bestial, "Should NOT be Bestial (no Hunger dice)")

    def test_margin_calculation(self):
        """Test that margin is calculated correctly (total successes - difficulty)."""
        # 3 successes, difficulty 2 = margin +1
        result = DiceResult(normal_dice=[6, 7, 8, 2, 3], hunger_dice=[], difficulty=2)
        self.assertEqual(result.successes, 3, "Should have 3 successes")
        self.assertEqual(result.margin, 1, "Margin should be 3 - 2 = 1")
        self.assertTrue(result.is_success(), "Should be a success (margin >= 0)")

        # 2 successes, difficulty 3 = margin -1 (failure)
        result2 = DiceResult(normal_dice=[6, 7, 2, 3], hunger_dice=[], difficulty=3)
        self.assertEqual(result2.successes, 2, "Should have 2 successes")
        self.assertEqual(result2.margin, -1, "Margin should be 2 - 3 = -1")
        self.assertFalse(result2.is_success(), "Should be a failure (margin < 0)")

    def test_critical_bonus_to_margin(self):
        """Test that critical pairs add +2 successes each to margin."""
        # 1 critical pair (2x10) = 2 successes + 2 bonus = 4 total
        result = DiceResult(normal_dice=[10, 10, 3], hunger_dice=[], difficulty=3)
        # Criticals: 1 pair
        # Base successes: 2 (the two 10s)
        # Critical bonus: +2 (1 pair * 2)
        # Total successes with crits: 4
        # Margin: 4 - 3 = 1
        self.assertEqual(result.criticals, 1)
        self.assertEqual(result.successes, 2, "Base successes (counting the 10s)")
        self.assertEqual(result.margin, 1, "Margin should include critical bonus: (2+2)-3=1")


class TestRollPool(unittest.TestCase):
    """Test the roll_pool function."""

    def test_hunger_dice_replace_normal(self):
        """Test that Hunger dice REPLACE normal dice (not add to pool)."""
        # Pool of 5, Hunger 2 = 3 normal + 2 hunger dice
        result = roll_pool(pool=5, hunger=2, difficulty=0)
        self.assertEqual(len(result.normal_dice), 3, "Should have 3 normal dice")
        self.assertEqual(len(result.hunger_dice), 2, "Should have 2 Hunger dice")
        total_dice = len(result.normal_dice) + len(result.hunger_dice)
        self.assertEqual(total_dice, 5, "Total dice should equal pool size")

    def test_hunger_capped_at_pool_size(self):
        """Test that Hunger dice cannot exceed pool size."""
        # Pool of 3, Hunger 5 = 0 normal + 3 hunger dice (capped)
        result = roll_pool(pool=3, hunger=5, difficulty=0)
        self.assertEqual(len(result.normal_dice), 0, "Should have 0 normal dice")
        self.assertEqual(len(result.hunger_dice), 3, "Hunger dice capped at pool size")


if __name__ == "__main__":
    unittest.main()
