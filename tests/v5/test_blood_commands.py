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
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.blood import CmdBloodSurge, CmdFeed, CmdHunger
from commands.v5.utils import blood_utils

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
    """`feed` records a feeding from a staff-run scene (QR p.12 sources).

    char1 is staff (Developer); char2 is the fed player character.
    """

    def feed(self, args):
        return self.call(CmdFeed(), args, caller=self.char1)

    def test_feed_no_arguments(self):
        self.call(CmdFeed(), "", "Usage: feed", caller=self.char1)

    def test_feed_is_staff_only(self):
        """F-085/A-032: the command is locked to Builders."""
        self.assertEqual(CmdFeed.locks, "cmd:perm(Builder)")

    def test_feed_invalid_resonance(self):
        output = self.feed("Char2=drink/invalid_resonance")
        self.assertIn("Invalid resonance", output)

    def test_feed_drink_slakes_two(self):
        self.char2.hunger = 4
        self.feed("Char2=drink")
        self.assertEqual(self.char2.hunger, 2)

    def test_feed_without_a_kill_stops_at_hunger_1(self):
        """A-012 / QR p.12: only draining and killing a human reaches Hunger 0."""
        self.char2.hunger = 2
        self.feed("Char2=harmful 4")
        self.assertEqual(self.char2.hunger, 1)
        self.feed("Char2=kill")
        self.assertEqual(self.char2.hunger, 0)

    def test_high_blood_potency_slakes_less_and_needs_a_kill_below_2(self):
        """BP 5: 1 less Hunger per human; must kill to go below 2."""
        self.char2.blood_potency = 5
        self.char2.hunger = 5
        self.feed("Char2=drink")
        self.assertEqual(self.char2.hunger, 4)
        self.feed("Char2=harmful 4")
        self.assertEqual(self.char2.hunger, 2)

    def test_animal_blood_slakes_nothing_above_bp_2(self):
        self.char2.blood_potency = 3
        self.char2.hunger = 3
        self.feed("Char2=large animal")
        self.assertEqual(self.char2.hunger, 3)

    def test_feed_sets_resonance(self):
        self.char2.hunger = 3
        output = self.feed("Char2=drink/choleric")
        resonance = blood_utils.get_resonance(self.char2)
        self.assertEqual(resonance["type"], "Choleric")
        self.assertEqual(resonance["intensity"], 1)
        self.assertIn("Choleric", output)
        self.assertIn("Fleeting", output)

    def test_feed_melancholy_sets_the_book_name(self):
        """'melancholy' (QR p.12) is accepted and stored as "Melancholy"."""
        self.char2.hunger = 3
        output = self.feed("Char2=sip/melancholy/2")
        self.assertEqual(blood_utils.get_resonance(self.char2)["type"], "Melancholy")
        self.assertIn("Intense", output)

    def test_feed_rejects_unknown_resonance_before_feeding(self):
        """An invalid resonance is refused before Hunger changes."""
        self.char2.hunger = 3
        output = self.feed("Char2=drink/melancholic")
        self.assertIn("Invalid resonance", output)
        self.assertEqual(self.char2.hunger, 3)
        self.assertIsNone(blood_utils.get_resonance(self.char2))


class FeedLockTestCase(EvenniaCommandTest):
    """A player typing `feed` gets no match: the command isn't available to them."""

    def test_player_feed_is_not_available(self):
        self.char2.hunger = 4
        with patch.object(self.char2, "msg") as msg:
            self.char2.execute_cmd("feed Char2=kill")
        sent = " ".join(str(call) for call in msg.call_args_list)
        self.assertIn("not available", sent)
        self.assertEqual(self.char2.hunger, 4)


class CmdBloodSurgeTestCase(BloodCommandTestBase):
    """Tests for the bloodsurge command."""

    def test_bloodsurge_no_arguments(self):
        self.call(CmdBloodSurge(), "", "Usage: bloodsurge")

    def test_bloodsurge_requires_character(self):
        self.call(CmdBloodSurge(), "strength", "You must be in character", caller=self.account)

    # F-017: bloodsurge makes one Rouse check, with the roll it surges. The
    # Hunger it costs is added after that roll (core pp.211-212).
    def test_bloodsurge_costs_a_rouse_check(self):
        """A failed surge Rouse raises Hunger by 1 after the surged roll."""
        from dice.commands import CmdRoll

        self.char.hunger = 2
        output = self.call(CmdBloodSurge(), "strength")
        self.assertIn("Blood Surge activated", output)
        self.assertEqual(blood_utils.get_hunger_level(self.char), 2)

        with patch(RANDINT, return_value=3):
            self.call(CmdRoll(), "3")
        self.assertEqual(len(self.char.ndb.last_roll["result"].hunger_dice), 2)
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
        self.char.db.blood_surge = {
            "trait": "Strength",
            "bonus": 3,
            "expires": time.time() + 1800,
        }
        output = self.hunger_output(2)
        self.assertIn("Blood Surge Active", output)
        self.assertIn("+3 dice to Strength", output)
        self.assertIn("minutes remaining", output)

    def test_hunger_without_blood_surge(self):
        blood_utils.deactivate_blood_surge(self.char)
        self.assertNotIn("Blood Surge Active", self.hunger_output(2))

    def test_hunger_expired_surge_not_shown(self):
        self.char.db.blood_surge = {
            "trait": "Strength",
            "bonus": 3,
            "expires": time.time() - 1,
        }
        self.assertNotIn("Blood Surge Active", self.hunger_output(2))

    def test_hunger_expired_resonance_not_shown(self):
        blood_utils.set_resonance(self.char, "Phlegmatic", intensity=1, duration=-1)
        self.assertNotIn("Phlegmatic", self.hunger_output(2))
