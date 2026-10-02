"""
Command tests for the blood system: feed, bloodsurge and hunger.

Each test runs the real command through ``EvenniaCommandTest.call`` on a real
character in a real room. Only the dice are patched (``dice.dice_roller.randint``),
so the tests see the same data shapes the game does.

These tests check only behaviour the V5 core book and the current code agree
on. Rules the current code gets wrong are covered by expected-failure tests
tagged with their finding id, or are left to the PR that rebuilds them.
"""

import time
import unittest
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.blood import CmdBloodSurge, CmdFeed, CmdHunger
from commands.v5.utils import blood_utils
from dice import dice_roller

RANDINT = "dice.dice_roller.randint"


def fixed_dice(*values):
    """Patch the dice so they come up as ``values``, in order."""
    return patch(RANDINT, side_effect=list(values))


class BloodCommandTestBase(EvenniaCommandTest):
    """char1 in room1 with Strength 3 and Brawl 2 (a five-die feeding pool)."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        stats = self.char.db.stats
        stats["attributes"]["physical"]["strength"] = 3
        stats["skills"]["physical"]["brawl"] = 2


class CmdFeedTestCase(BloodCommandTestBase):
    """Tests for the feed command."""

    def test_feed_no_arguments(self):
        self.call(CmdFeed(), "", "Usage: feed")

    def test_feed_invalid_resonance(self):
        output = self.call(CmdFeed(), "mortal invalid_resonance")
        self.assertIn("Invalid resonance", output)

    def test_feed_requires_character(self):
        self.call(CmdFeed(), "mortal", "You must be in character", caller=self.account)

    def test_feed_rolls_with_character_hunger(self):
        """The feeding roll uses the character's Hunger as its Hunger dice (QR p.4).

        The pool and difficulty are not pinned: the book takes the pool from
        the predator type and the difficulty from the hunting ground (QR p.12),
        and PR 6 rebuilds both.
        """
        self.char.hunger = 4
        with (
            patch("dice.dice_roller.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll,
            patch(RANDINT, return_value=7),
        ):
            self.call(CmdFeed(), "mortal")
        roll.assert_called_once()
        self.assertEqual(roll.call_args.args[1], 4)

    def test_feed_success_reduces_hunger(self):
        self.char.hunger = 4
        with fixed_dice(7, 7, 7, 7, 7):
            output = self.call(CmdFeed(), "mortal")
        self.assertIn("Feeding successful", output)
        self.assertLess(blood_utils.get_hunger_level(self.char), 4)

    def test_feed_sets_resonance(self):
        self.char.hunger = 3
        with fixed_dice(7, 7, 7, 7, 7):
            output = self.call(CmdFeed(), "mortal choleric")
        resonance = blood_utils.get_resonance(self.char)
        self.assertEqual(resonance["type"], "Choleric")
        self.assertEqual(resonance["intensity"], 1)
        self.assertIn("Choleric", output)
        self.assertIn("Fleeting", output)

    def test_feed_failure_keeps_hunger(self):
        self.char.hunger = 3
        with fixed_dice(2, 2, 2, 2, 2):
            output = self.call(CmdFeed(), "mortal")
        self.assertIn("Feeding failed", output)
        self.assertEqual(blood_utils.get_hunger_level(self.char), 3)

    def test_feed_bestial_failure_keeps_hunger(self):
        """A failed feeding roll with a Hunger 1 is a bestial failure."""
        self.char.hunger = 3
        # Two regular dice, then three Hunger dice; one Hunger die shows 1.
        with fixed_dice(2, 3, 1, 2, 4):
            output = self.call(CmdFeed(), "mortal")
        self.assertIn("Bestial Failure", output)
        self.assertEqual(blood_utils.get_hunger_level(self.char), 3)

    def test_feed_success_is_announced_to_the_room(self):
        self.char.hunger = 3
        with patch.object(self.char2, "msg") as char2_msg, fixed_dice(7, 7, 7, 7, 7):
            self.call(CmdFeed(), "mortal")
        sent = " ".join(str(call) for call in char2_msg.call_args_list)
        self.assertIn("feeds", sent)


class CmdBloodSurgeTestCase(BloodCommandTestBase):
    """Tests for the bloodsurge command."""

    def test_bloodsurge_no_arguments(self):
        self.call(CmdBloodSurge(), "", "Usage: bloodsurge")

    def test_bloodsurge_requires_character(self):
        self.call(CmdBloodSurge(), "strength", "You must be in character", caller=self.account)

    # F-017, fixed in PR 5: activate_blood_surge calls
    # roll_rouse_check(character, reason=...), which takes no arguments, so
    # every bloodsurge raises TypeError.
    @unittest.expectedFailure
    def test_bloodsurge_costs_a_rouse_check(self):
        """A failed Rouse (die 1-5) raises Hunger by 1 and the surge activates."""
        self.char.hunger = 2
        with patch(RANDINT, return_value=3):
            output = self.call(CmdBloodSurge(), "strength")
        self.assertIn("Blood Surge activated", output)
        self.assertEqual(blood_utils.get_hunger_level(self.char), 3)


class CmdHungerTestCase(BloodCommandTestBase):
    """Tests for the hunger command."""

    def hunger_output(self, hunger):
        self.char.hunger = hunger
        return self.call(CmdHunger(), "")

    def test_hunger_requires_character(self):
        self.call(CmdHunger(), "", "You must be in character", caller=self.account)

    def test_hunger_basic_display(self):
        output = self.hunger_output(3)
        self.assertIn("Blood Status", output)
        self.assertIn("3/5", output)

    def test_hunger_shows_visual_indicator(self):
        output = self.hunger_output(2)
        self.assertIn("■■□□□", output)

    def test_hunger_level_messages(self):
        expected = {
            0: "well-fed",
            1: "minor cravings",
            2: "minor cravings",
            3: "moderate",
            4: "severe",
            5: "RAVENOUS",
        }
        for hunger, text in expected.items():
            with self.subTest(hunger=hunger):
                self.assertIn(text, self.hunger_output(hunger))

    def test_hunger_with_resonance_display(self):
        blood_utils.set_resonance(self.char, "Choleric", intensity=2)
        output = self.hunger_output(2)
        self.assertIn("Choleric", output)
        self.assertIn("Intense", output)

    def test_hunger_without_resonance(self):
        blood_utils.clear_resonance(self.char)
        output = self.hunger_output(2)
        self.assertNotIn("Resonance:", output)

    def test_hunger_with_blood_surge_display(self):
        self.char.ndb.blood_surge = {
            "trait": "Strength",
            "bonus": 3,
            "expires": time.time() + 1800,
        }
        output = self.hunger_output(2)
        self.assertIn("Blood Surge Active", output)
        self.assertIn("+3 dice to Strength", output)
        self.assertIn("minutes remaining", output)

    def test_hunger_without_blood_surge(self):
        self.char.ndb.blood_surge = None
        self.assertNotIn("Blood Surge Active", self.hunger_output(2))

    def test_hunger_expired_surge_not_shown(self):
        self.char.ndb.blood_surge = {
            "trait": "Strength",
            "bonus": 3,
            "expires": time.time() - 1,
        }
        self.assertNotIn("Blood Surge Active", self.hunger_output(2))

    def test_hunger_expired_resonance_not_shown(self):
        blood_utils.set_resonance(self.char, "Phlegmatic", intensity=1, duration=-1)
        self.assertNotIn("Phlegmatic", self.hunger_output(2))
