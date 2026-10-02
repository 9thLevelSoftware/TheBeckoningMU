"""
The V5 roll core against the core rules: dice, Rouse, Blood Surge, powers,
Willpower re-rolls and resonance dice.

Expected values come from the rules (V5 Quick Reference 2.0 p.3-4, p.12 and
the Blood Potency table in world/v5_data.py), not from the code. Only the
dice are patched, through ``random.randint``; every character is a real,
freshly created Character.
"""

from unittest.mock import patch

from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from commands.v5.blood import CmdBloodSurge
from commands.v5.hunt import CmdHunt
from commands.v5.utils import blood_utils
from dice.commands import LAST_ROLL_WINDOW, CmdPower, CmdRoll, CmdRouse
from dice.dice_roller import MAX_POOL, roll_v5_pool
from dice.roll_result import RollResult

RANDINT = "random.randint"


def dice(*values):
    """Patch the dice so they come up as ``values``, in order."""
    return patch(RANDINT, side_effect=list(values))


def all_dice(value):
    """Patch every die to show ``value``."""
    return patch(RANDINT, return_value=value)


class CountingTableTests(EvenniaTest):
    """RollResult on fixed dice (QR p.4)."""

    # (regular dice, Hunger dice, difficulty) -> (successes, success, critical, messy, bestial)
    TABLE = [
        (([10], [], 0), (1, True, False, False, False)),
        (([10, 10], [], 0), (4, True, True, False, False)),
        (([10, 10, 10], [], 0), (5, True, True, False, False)),
        (([10, 10, 10, 10], [], 0), (8, True, True, False, False)),
        (([10, 7, 2], [], 0), (2, True, False, False, False)),
        (([10], [10], 0), (4, True, True, True, False)),
        (([10, 10], [10], 0), (5, True, True, True, False)),
        (([1], [1], 1), (0, False, False, False, True)),
        (([1, 3], [1, 2], 3), (0, False, False, False, True)),
        (([], [4, 5], 1), (0, False, False, False, False)),
        (([10, 10], [], 5), (4, False, False, False, False)),
        (([10], [10], 5), (4, False, False, False, False)),
        (([10], [1, 10], 6), (4, False, False, False, True)),
        (([6, 7, 8], [], 3), (3, True, False, False, False)),
        (([1, 2], [], 0), (0, False, False, False, False)),
    ]

    def test_counting_table(self):
        for (regular, hunger, difficulty), expected in self.TABLE:
            with self.subTest(regular=regular, hunger=hunger, difficulty=difficulty):
                result = RollResult(regular, hunger, difficulty)
                self.assertEqual(
                    (
                        result.total_successes,
                        result.is_success,
                        result.is_critical,
                        result.is_messy_critical,
                        result.is_bestial_failure,
                    ),
                    expected,
                )

    def test_pool_rolls_patched_dice(self):
        """roll_v5_pool takes its dice from random.randint: regular first, then Hunger."""
        with dice(10, 7, 10):
            result = roll_v5_pool(3, hunger=1)
        self.assertEqual(result.regular_dice, [10, 7])
        self.assertEqual(result.hunger_dice, [10])
        self.assertTrue(result.is_messy_critical)

    def test_hunger_above_pool_makes_every_die_a_hunger_die(self):
        """Pool 3 at Hunger 5 rolls three Hunger dice (QR p.4)."""
        with all_dice(6):
            result = roll_v5_pool(3, hunger=5)
        self.assertEqual(result.regular_dice, [])
        self.assertEqual(len(result.hunger_dice), 3)


class RollCommandTests(EvenniaCommandTest):
    """`roll` on fresh characters. char2's account has no staff permission."""

    def test_roll_uses_the_characters_hunger(self):
        self.char2.hunger = 3
        with all_dice(7):
            self.call(CmdRoll(), "5", caller=self.char2)
        result = self.char2.ndb.last_roll["result"]
        self.assertEqual(len(result.hunger_dice), 3)
        self.assertEqual(len(result.regular_dice), 2)

    def test_player_cannot_set_hunger(self):
        self.char2.hunger = 3
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRoll(), "5 0", caller=self.char2)
        self.assertIn("Only staff can set the Hunger dice", output)

    def test_player_cannot_roll_mortal(self):
        self.char2.hunger = 3
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRoll(), "/mortal 5", caller=self.char2)
        self.assertIn("Only staff can set the Hunger dice", output)

    def test_staff_can_set_hunger(self):
        self.char1.hunger = 3
        with all_dice(7):
            self.call(CmdRoll(), "5 0")
        self.assertEqual(self.char1.ndb.last_roll["result"].hunger_dice, [])

    def test_messy_critical_adds_no_stain(self):
        """A messy critical is the Storyteller's complication, not a Stain (F-040)."""
        self.char2.hunger = 1
        with all_dice(10):
            output = self.call(CmdRoll(), "2", caller=self.char2)
        self.assertIn("MESSY CRITICAL", output)
        self.assertIn("Storyteller decides the complication", output)
        self.assertEqual(self.char2.stains, 0)


class WillpowerRerollTests(EvenniaCommandTest):
    """roll/willpower re-rolls the regular dice the player chose (QR p.3)."""

    def setUp(self):
        super().setUp()
        self.char2.hunger = 1
        self.char2.set_trait("Composure", 2)
        self.char2.set_trait("Resolve", 2)  # Willpower 4

    def test_rerolls_exactly_the_chosen_dice_including_a_ten(self):
        # Four regular dice, then one Hunger die.
        with dice(10, 2, 2, 7, 1):
            self.call(CmdRoll(), "5 vs 4", caller=self.char2)
        with dice(8, 9):
            output = self.call(CmdRoll(), "/willpower 10 2", caller=self.char2)

        result = self.char2.ndb.last_roll["result"]
        self.assertEqual(result.regular_dice, [8, 9, 2, 7])
        self.assertEqual(result.hunger_dice, [1])
        self.assertIn("Willpower Re-roll", output)
        self.assertEqual(self.char2.damage["willpower"]["superficial"], 1)
        self.assertEqual(self.char2.current_willpower, 3)

    def test_hunger_dice_cannot_be_chosen(self):
        with dice(3, 3, 3, 3, 1):
            self.call(CmdRoll(), "5", caller=self.char2)
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRoll(), "/willpower 1", caller=self.char2)
        self.assertIn("No regular die showing 1", output)
        self.assertEqual(self.char2.damage["willpower"]["superficial"], 0)

    def test_only_once_per_roll(self):
        with all_dice(3):
            self.call(CmdRoll(), "3", caller=self.char2)
            self.call(CmdRoll(), "/willpower 3", caller=self.char2)
            output = self.call(CmdRoll(), "/willpower 3", caller=self.char2)
        self.assertIn("already spent Willpower", output)
        self.assertEqual(self.char2.damage["willpower"]["superficial"], 1)

    def test_no_willpower_left(self):
        self.char2.set_damage("willpower", superficial=4)
        with all_dice(3):
            self.call(CmdRoll(), "3", caller=self.char2)
            output = self.call(CmdRoll(), "/willpower 3", caller=self.char2)
        self.assertIn("no Willpower left", output)


class RouseCommandTests(EvenniaCommandTest):
    def test_failed_rouse_raises_hunger(self):
        self.char2.hunger = 2
        with all_dice(3):
            self.call(CmdRouse(), "", caller=self.char2)
        self.assertEqual(self.char2.hunger, 3)

    def test_rouse_refused_at_hunger_5(self):
        self.char2.hunger = 5
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRouse(), "", caller=self.char2)
        self.assertIn("cannot Rouse the Blood", output)
        self.assertEqual(self.char2.hunger, 5)


class BloodSurgeTests(EvenniaCommandTest):
    """bloodsurge: the BP table's surge dice on the next roll; its Rouse is made with that roll."""

    def setUp(self):
        super().setUp()
        self.char2.hunger = 1
        self.char2.blood_potency = 1  # surge +2

    def test_surge_rouse_comes_after_the_surged_roll(self):
        """Hunger dice use the pre-Rouse Hunger; the surge's Hunger is added after (core pp.211-212)."""
        output = self.call(CmdBloodSurge(), "strength", caller=self.char2)
        self.assertIn("Blood Surge activated", output)
        self.assertEqual(self.char2.hunger, 1)

        with all_dice(3):
            output = self.call(CmdRoll(), "3", caller=self.char2)
        result = self.char2.ndb.last_roll["result"]
        self.assertEqual(len(result.all_dice), 5)
        self.assertEqual(len(result.hunger_dice), 1)
        self.assertIn("Blood Surge", strip_ansi(output))
        self.assertEqual(self.char2.hunger, 2)

        with all_dice(7):
            self.call(CmdRoll(), "3", caller=self.char2)
        self.assertEqual(len(self.char2.ndb.last_roll["result"].all_dice), 3)

    def test_surge_refused_at_hunger_5(self):
        self.char2.hunger = 5
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdBloodSurge(), "strength", caller=self.char2)
        self.assertIn("cannot Rouse the Blood", output)
        self.assertIsNone(blood_utils.get_blood_surge(self.char2))

    def test_one_surge_at_a_time(self):
        self.call(CmdBloodSurge(), "strength", caller=self.char2)
        output = self.call(CmdBloodSurge(), "dexterity", caller=self.char2)
        self.assertIn("already have a Blood Surge", output)
        self.assertEqual(blood_utils.get_blood_surge(self.char2)["trait"], "Strength")

    def test_surge_is_kept_when_the_roll_errors(self):
        """A pool pushed over MAX_POOL by the surge is refused and the surge stays ready."""
        self.call(CmdBloodSurge(), "strength", caller=self.char2)
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRoll(), str(MAX_POOL), caller=self.char2)
        self.assertIn("cannot exceed", output)
        self.assertIn("Blood Surge", output)
        self.assertIsNotNone(blood_utils.get_blood_surge(self.char2))
        self.assertEqual(self.char2.hunger, 1)

    def test_staff_npc_roll_keeps_the_surge(self):
        self.char1.blood_potency = 1
        self.char1.hunger = 1
        self.call(CmdBloodSurge(), "strength")
        with all_dice(7):
            self.call(CmdRoll(), "3 0")
        self.assertEqual(len(self.char1.ndb.last_roll["result"].all_dice), 3)
        self.assertIsNotNone(blood_utils.get_blood_surge(self.char1))

    def test_surge_waits_while_at_hunger_5(self):
        self.call(CmdBloodSurge(), "strength", caller=self.char2)
        self.char2.hunger = 5
        with all_dice(7):
            output = self.call(CmdRoll(), "3", caller=self.char2)
        self.assertEqual(len(self.char2.ndb.last_roll["result"].all_dice), 3)
        self.assertIn("can't be used at Hunger 5", output)
        self.assertIsNotNone(blood_utils.get_blood_surge(self.char2))


class PowerCommandTests(EvenniaCommandTest):
    """`power` (alias +power) on a fresh character that learns its powers."""

    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.hunger = 1
        self.char.blood_potency = 0  # no Rouse re-rolls, no power bonus, surge +1
        self.char.set_trait("Animalism", 1)
        self.char.set_trait("Presence", 3)
        self.char.set_trait("Manipulation", 3)
        self.char.set_trait("Celerity", 2)
        for name in ("Bond Famulus", "Sense the Beast", "Awe", "Dread Gaze", "Fleetness"):
            self.char.learn_power(name)

    def effects(self, power="Dread Gaze"):
        return [e for e in self.char.db.active_effects or [] if e["power"] == power]

    def test_unknown_power_is_refused_without_hunger_change(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Fireball", caller=self.char)
        self.assertIn("not found", output)
        self.assertEqual(self.char.hunger, 1)

    def test_unlearned_power_is_refused(self):
        self.char.set_trait("Auspex", 1)
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Sense the Unseen", caller=self.char)
        self.assertIn("don't know", output)
        self.assertEqual(self.char.hunger, 1)

    def test_power_refused_at_hunger_5(self):
        self.char.hunger = 5
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Dread Gaze", caller=self.char)
        self.assertIn("cannot Rouse the Blood", output)
        self.assertEqual(self.char.hunger, 5)

    def test_every_rouse_check_is_made(self):
        """Bond Famulus costs three Rouse checks: three failures raise Hunger by 3."""
        # Charisma 1 + Animal Ken 0 = 1 die (a Hunger die at Hunger 1), then 3 Rouse dice.
        with all_dice(3):
            self.call(CmdPower(), "Bond Famulus", caller=self.char)
        self.assertEqual(self.char.hunger, 4)

    def test_multi_rouse_past_hunger_5_rolls_every_check_and_owes_a_frenzy_test(self):
        """At Hunger 4 a 3-Rouse power still works; Hunger stops at 5 and a frenzy test is owed."""
        self.char.hunger = 4
        # pool die, then all three Rouse dice, then the owed frenzy tests' dice
        with dice(8, 3, 3, 3, *[8] * 20):
            output = self.call(CmdPower(), "Bond Famulus", caller=self.char)
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(strip_ansi(output).count("Rouse Check (Bond Famulus)"), 3)
        self.assertIn("hunger frenzy", output)
        # PR 6: the owed test is rolled at once and the record cleared
        self.assertIn("Hunger frenzy test", strip_ansi(output))
        self.assertIsNone(self.char.db.pending_frenzy_test)
        self.assertTrue(self.char.ndb.last_roll["result"].is_success)

    def test_no_frenzy_test_when_hunger_stays_within_5(self):
        self.char.hunger = 2
        with all_dice(3):
            self.call(CmdPower(), "Bond Famulus", caller=self.char)
        self.assertEqual(self.char.hunger, 5)
        self.assertIsNone(self.char.db.pending_frenzy_test)

    def test_roll_uses_pre_rouse_hunger(self):
        """The pool is rolled with the Hunger from before the power's Rouse (core pp.211-212)."""
        # Dread Gaze: Charisma 1 + Presence 3 = 4 dice, 1 Hunger die; then 1 Rouse.
        with all_dice(3):
            self.call(CmdPower(), "Dread Gaze", caller=self.char)
        result = self.char.ndb.last_roll["result"]
        self.assertEqual(len(result.hunger_dice), 1)
        self.assertEqual(self.char.hunger, 2)

    def test_failed_roll_starts_no_effect_but_pays_the_rouse(self):
        with all_dice(3):
            self.call(CmdPower(), "Dread Gaze = Char", caller=self.char)
        self.assertFalse(self.effects())
        self.assertEqual(self.char.hunger, 2)

    def test_successful_contested_roll_starts_the_effect(self):
        with all_dice(8):
            self.call(CmdPower(), "Dread Gaze = Char", caller=self.char)
        self.assertTrue(self.effects())

    def test_uncontested_power_starts_no_effect_and_claims_no_success(self):
        with patch.object(self.char1, "msg") as room_msg, all_dice(8):
            output = self.call(CmdPower(), "Dread Gaze", caller=self.char)
        self.assertIn("Uncontested", output)
        self.assertFalse(self.effects())
        sent = " ".join(str(call) for call in room_msg.call_args_list)
        self.assertIn("uncontested", sent)
        self.assertNotIn("Success", sent)

    def test_messy_critical_power_adds_no_stain(self):
        """Plan (d): no automatic Stain on a messy critical, for powers too."""
        with all_dice(10):
            output = self.call(CmdPower(), "Dread Gaze", caller=self.char)
        self.assertIn("MESSY CRITICAL", output)
        self.assertEqual(self.char.stains, 0)

    def test_free_power_costs_no_rouse(self):
        # Sense the Beast: Resolve 1 + Animalism 1 = 2 dice, free.
        with all_dice(3):
            self.call(CmdPower(), "Sense the Beast", caller=self.char)
        self.assertEqual(self.char.hunger, 1)

    def test_power_without_a_pool_is_used_without_a_roll(self):
        """Fleetness has no dice pool: it costs its Rouse and rolls nothing else."""
        with dice(3):
            output = self.call(CmdPower(), "Fleetness", caller=self.char)
        self.assertIn("No roll needed", output)
        self.assertEqual(self.char.hunger, 2)

    def test_rouse_reroll_at_the_power_level(self):
        """BP 3 re-rolls Rouse checks for level 1-2 powers: Fleetness (level 2) gets one."""
        self.char.blood_potency = 3
        with dice(3, 7):
            output = self.call(CmdPower(), "Fleetness", caller=self.char)
        self.assertIn("Blood Potency re-roll", output)
        self.assertEqual(self.char.hunger, 1)

    def test_no_rouse_reroll_above_the_power_level(self):
        """BP 2 re-rolls level 1 powers only: Fleetness (level 2) gets none."""
        self.char.blood_potency = 2
        with dice(3):
            self.call(CmdPower(), "Fleetness", caller=self.char)
        self.assertEqual(self.char.hunger, 2)

    def test_plus_power_discipline_slash_power(self):
        with all_dice(7):
            output = self.call(CmdPower(), "animalism/sense the beast", caller=self.char, cmdstring="+power")
        self.assertIn("Sense the Beast", output)

    def test_plus_power_with_the_wrong_discipline_is_refused(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "animalism/dread gaze", caller=self.char, cmdstring="+power")
        self.assertIn("is a Presence power", output)
        self.assertEqual(self.char.hunger, 1)

    def test_player_cannot_skip_rouse(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "/norouse Dread Gaze", caller=self.char)
        self.assertIn("Only staff", output)
        self.assertEqual(self.char.hunger, 1)

    def test_contested_power_rolls_against_the_defender(self):
        """Awe (Manipulation + Presence) vs the target's Composure + Intelligence."""
        # Defender char1: 2 dice (one Hunger) -> [7, 2] = 1 success.
        # User: Manipulation 3 + Presence 3 = 6 dice -> 2 successes, beating 1.
        with dice(7, 2, 8, 8, 1, 1, 1, 1):
            self.call(CmdPower(), "Awe = Char", caller=self.char)
        self.assertTrue(self.char.ndb.last_roll["result"].is_success)

    def test_contested_tie_goes_to_the_acting_character(self):
        with dice(7, 2, 8, 1, 1, 1, 1, 1):
            self.call(CmdPower(), "Awe = Char", caller=self.char)
        self.assertTrue(self.char.ndb.last_roll["result"].is_success)

    def test_contested_no_successes_is_not_a_win(self):
        with all_dice(2):
            self.call(CmdPower(), "Awe = Char", caller=self.char)
        self.assertFalse(self.char.ndb.last_roll["result"].is_success)

    def test_target_is_told_and_defender_roll_is_not_shown_as_yours(self):
        # Defender: [10] + Hunger [10] = 4 successes (a messy critical of theirs).
        # User: 4 dice of 2 -> fails; Rouse die 7.
        with patch.object(self.char1, "msg") as target_msg, dice(10, 10, 2, 2, 2, 2, 7):
            output = self.call(CmdPower(), "Dread Gaze = Char", caller=self.char)
        self.assertIn("Char resists", output)
        self.assertNotIn("MESSY CRITICAL", output)
        self.assertNotIn("2 dice", output)  # the defender's pool size isn't revealed
        sent = strip_ansi(" ".join(str(call) for call in target_msg.call_args_list))
        self.assertIn("uses Dread Gaze on you", sent)
        self.assertIn("You resist it", sent)

    def test_target_and_difficulty_together_are_refused(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Dread Gaze vs 3 = Char", caller=self.char)
        self.assertIn("not both", output)

    def test_object_cannot_be_the_defender(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Awe = Obj", caller=self.char)
        self.assertIn("can't resist a power", output)
        self.assertEqual(self.char.hunger, 1)

    def test_target_for_an_uncontested_power_is_refused(self):
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdPower(), "Bond Famulus = Char", caller=self.char)
        self.assertIn("isn't resisted", output)

    def test_blood_surge_adds_to_a_power_roll(self):
        """A readied surge goes on a power roll too; its Rouse is settled after the roll."""
        self.call(CmdBloodSurge(), "charisma", caller=self.char)  # BP 0: +1 die
        with all_dice(3):
            output = self.call(CmdPower(), "Dread Gaze", caller=self.char)
        result = self.char.ndb.last_roll["result"]
        self.assertEqual(len(result.all_dice), 5)
        self.assertEqual(len(result.hunger_dice), 1)
        self.assertIn("Blood Surge", output)
        self.assertEqual(self.char.hunger, 3)  # power Rouse + surge Rouse, both failed
        self.assertIsNone(blood_utils.get_blood_surge(self.char))


class PowerWillpowerTests(EvenniaCommandTest):
    """A Willpower re-roll of a power roll re-resolves the power (QR p.3)."""

    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.hunger = 1
        self.char.blood_potency = 0
        self.char.set_trait("Presence", 3)
        self.char.learn_power("Dread Gaze")

    def effects(self):
        return [e for e in self.char.db.active_effects or [] if e["power"] == "Dread Gaze"]

    def test_reroll_into_success_starts_the_effect(self):
        # Defender [2] + Hunger [2] = 0 -> difficulty 1. User [2, 2, 2] + Hunger [2]; Rouse 7.
        with dice(2, 2, 2, 2, 2, 2, 7):
            self.call(CmdPower(), "Dread Gaze = Char", caller=self.char)
        self.assertFalse(self.effects())
        with dice(8):
            output = self.call(CmdRoll(), "/willpower 2", caller=self.char)
        self.assertIn("now succeeds", output)
        self.assertTrue(self.effects())

    def test_reroll_into_failure_ends_the_effect(self):
        with dice(2, 2, 8, 2, 2, 2, 7):
            self.call(CmdPower(), "Dread Gaze = Char", caller=self.char)
        self.assertTrue(self.effects())
        with dice(2):
            output = self.call(CmdRoll(), "/willpower 8", caller=self.char)
        self.assertIn("now fails", output)
        self.assertFalse(self.effects())


class LastRollTests(EvenniaCommandTest):
    """roll/willpower reaches only a fresh last roll (QR p.3)."""

    def setUp(self):
        super().setUp()
        self.char2.hunger = 1
        self.char2.set_trait("Celerity", 2)
        self.char2.learn_power("Fleetness")

    def test_old_roll_cannot_be_rerolled(self):
        with all_dice(3):
            self.call(CmdRoll(), "3", caller=self.char2)
        self.char2.ndb.last_roll["time"] -= LAST_ROLL_WINDOW + 1
        with patch(RANDINT, side_effect=AssertionError("no dice should be rolled")):
            output = self.call(CmdRoll(), "/willpower 3", caller=self.char2)
        self.assertIn("too old", output)
        self.assertEqual(self.char2.damage["willpower"]["superficial"], 0)

    def test_power_without_a_roll_clears_the_last_roll(self):
        with all_dice(3):
            self.call(CmdRoll(), "3", caller=self.char2)
            self.call(CmdPower(), "Fleetness", caller=self.char2)
            output = self.call(CmdRoll(), "/willpower 3", caller=self.char2)
        self.assertIn("no roll to re-roll", output)


class ResonanceDiceTests(EvenniaTest):
    """Resonance dice follow world.v5_data.RESONANCE_INTENSITIES (core p.226-231)."""

    def test_intensity_dice(self):
        for intensity, expected in ((1, 0), (2, 1), (3, 1)):
            with self.subTest(intensity=intensity):
                blood_utils.set_resonance(self.char1, "Melancholy", intensity=intensity)
                self.assertEqual(blood_utils.get_resonance_bonus(self.char1, "Fortitude"), expected)
                self.assertEqual(blood_utils.get_resonance_bonus(self.char1, "Potence"), 0)

    def test_melancholy_is_the_stored_name(self):
        """QR p.12 spells the humour "Melancholy"."""
        blood_utils.set_resonance(self.char1, "Melancholy", intensity=2)
        self.assertEqual(self.char1.resonance["type"], "Melancholy")
        self.assertEqual(self.char1.db.vampire["current_resonance"], "Melancholy")


class HuntCommandTests(EvenniaCommandTest):
    def test_hunt_runs_without_import_error(self):
        """+hunt used to import a class that doesn't exist (F-044)."""
        self.char2.hunger = 3
        with all_dice(7):
            output = self.call(CmdHunt(), "street", caller=self.char2)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("ImportError", output)
