"""
V5 derived mechanics on real characters: Remorse and Stains, frenzy (with the
hunger frenzy test owed after a Rouse past Hunger 5), XP, combat, mending,
feeding and hunting, the mortal/vampire split, thin-blood alchemy, and the
player-to-player lockdown of +damage/+heal/+stain.

Expected values come from the V5 core book / Quick Reference 2.0 (cited per
test), not from the code. Only the dice are patched (``random.randint``,
which ``dice.dice_roller.randint`` wraps); every character is a real
Character. char1 is staff (Developer); char2 is a player.
"""

import time
from unittest.mock import patch

from evennia.utils import create
from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from commands.v5.combat import CmdAttack, CmdDamage, CmdHeal
from commands.v5.humanity import CmdFrenzy, CmdHumanity, CmdStain
from commands.v5.hunt import CmdHunt
from commands.v5.utils import background_utils, combat_utils, humanity_utils, thin_blood_utils, xp_utils
from commands.v5.xp import CmdSpend
from dice import dice_roller, discipline_roller
from dice.commands import CmdPower, CmdRouse
from typeclasses.characters import Character

RANDINT = "random.randint"


def dice(*values):
    """Patch the dice so they come up as ``values``, in order."""
    return patch(RANDINT, side_effect=list(values))


def all_dice(value):
    """Patch every die to show ``value``."""
    return patch(RANDINT, return_value=value)


def no_dice():
    return patch(RANDINT, side_effect=AssertionError("no dice should be rolled"))


def dice_count(roll):
    """Number of dice in a roll result."""
    return len(roll.regular_dice) + len(roll.hunger_dice)


def new_character(key="Fresh"):
    return create.create_object(Character, key=key)


# ---------------------------------------------------------------------------
# Remorse and Stains (QR p.3)
# ---------------------------------------------------------------------------


class RemorseTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1

    # F-039: Remorse rolls one die per unmarked Humanity box, minimum 1: at
    # Humanity 7 with 2 Stains that is 10 - 7 - 2 = 1 die.
    def test_remorse_rolls_unmarked_boxes(self):
        humanity_utils.set_humanity(self.char, 7)
        humanity_utils.add_stain(self.char, 2)
        with all_dice(6):
            result = humanity_utils.remorse_roll(self.char)
        self.assertEqual(dice_count(result["roll_result"]), 1)

    def test_minimum_one_die(self):
        humanity_utils.set_humanity(self.char, 9)
        humanity_utils.add_stain(self.char, 1)
        with all_dice(6):
            result = humanity_utils.remorse_roll(self.char)
        self.assertEqual(dice_count(result["roll_result"]), 1)

    def test_one_success_keeps_humanity_and_clears_stains(self):
        humanity_utils.set_humanity(self.char, 5)
        humanity_utils.add_stain(self.char, 3)  # 2 dice
        with dice(6, 2):
            result = humanity_utils.remorse_roll(self.char)
        self.assertTrue(result["success"])
        self.assertEqual((self.char.humanity, self.char.stains), (5, 0))

    def test_no_success_loses_one_humanity_and_clears_stains(self):
        humanity_utils.set_humanity(self.char, 5)
        humanity_utils.add_stain(self.char, 3)
        with all_dice(5):
            result = humanity_utils.remorse_roll(self.char)
        self.assertFalse(result["success"])
        self.assertEqual((self.char.humanity, self.char.stains), (4, 0))

    def test_remorse_rolls_no_hunger_dice(self):
        """A Humanity test never uses Hunger dice."""
        self.char.hunger = 3
        humanity_utils.set_humanity(self.char, 4)
        humanity_utils.add_stain(self.char, 1)  # 5 dice
        with all_dice(6):
            result = humanity_utils.remorse_roll(self.char)
        self.assertEqual(result["roll_result"].hunger_dice, [])
        self.assertEqual(dice_count(result["roll_result"]), 5)

    def test_stain_overflow_is_aggravated_willpower_damage(self):
        """H8 with 2 Stains + 1 new Stain overfills the tracker: 1 Aggravated Willpower damage."""
        humanity_utils.set_humanity(self.char, 8)
        humanity_utils.add_stain(self.char, 2)
        result = humanity_utils.add_stain(self.char, 1)
        self.assertEqual(result["overflow"], 1)
        self.assertEqual(self.char.stains, 2)
        self.assertEqual(self.char.damage["willpower"]["aggravated"], 1)

    def test_stains_within_the_tracker_cost_no_willpower(self):
        humanity_utils.set_humanity(self.char, 7)
        humanity_utils.add_stain(self.char, 3)
        self.assertEqual(self.char.stains, 3)
        self.assertEqual(self.char.damage["willpower"]["aggravated"], 0)


# ---------------------------------------------------------------------------
# Frenzy (QR p.4, p.13)
# ---------------------------------------------------------------------------


class FrenzyTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.char.set_trait("Composure", 4)
        self.char.set_trait("Resolve", 4)
        humanity_utils.set_humanity(self.char, 7)

    # F-041: the frenzy test is Willpower + Humanity / 3: 8 + 7 // 3 = 10 dice.
    def test_frenzy_pool_is_willpower_plus_third_humanity(self):
        self.char.hunger = 0
        with all_dice(6):
            result = humanity_utils.resist_frenzy(self.char, difficulty=3)
        self.assertEqual(dice_count(result["roll_result"]), 10)

    def test_frenzy_uses_current_willpower(self):
        self.char.set_damage("willpower", superficial=2)
        with all_dice(6):
            result = humanity_utils.resist_frenzy(self.char, difficulty=3)
        self.assertEqual(dice_count(result["roll_result"]), 8)

    def test_frenzy_rolls_no_hunger_dice(self):
        """A frenzy test is a Willpower test: no Hunger dice, so no bestial failure."""
        self.char.hunger = 4
        with all_dice(1):
            result = humanity_utils.resist_frenzy(self.char, difficulty=3, frenzy_type="hunger")
        self.assertEqual(result["roll_result"].hunger_dice, [])
        self.assertFalse(result["roll_result"].is_bestial_failure)

    def test_difficulty_is_the_provocation_not_hunger(self):
        """No Hunger modifier to the difficulty (the old code added Hunger // 2)."""
        self.char.hunger = 4
        with all_dice(6):
            result = humanity_utils.resist_frenzy(self.char, difficulty=2)
        self.assertEqual(result["roll_result"].difficulty, 2)

    def test_brujah_bane_subtracts_bane_severity_dice_from_fury(self):
        """Brujah: -Bane Severity dice to resist fury frenzy (BP 3: severity 3)."""
        self.char.clan = "Brujah"
        self.char.blood_potency = 3
        with all_dice(6):
            fury = humanity_utils.resist_frenzy(self.char, 3, "fury")
            terror = humanity_utils.resist_frenzy(self.char, 3, "terror")
        self.assertEqual(dice_count(fury["roll_result"]), 7)
        self.assertEqual(dice_count(terror["roll_result"]), 10)

    def test_provocations_come_from_the_book_table(self):
        hunger = humanity_utils.frenzy_provocations("hunger")
        self.assertEqual(hunger["provocations"]["Fail a Rouse check at Hunger 5"], 4)
        self.assertIsNone(humanity_utils.frenzy_provocations("boredom"))


class HungerFrenzyTests(EvenniaCommandTest):
    """A Rouse that can't be made at Hunger 5 calls for an immediate hunger frenzy
    test at Difficulty 4 (core p.211; the owner's multi-Rouse ruling)."""

    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.blood_potency = 0  # no Rouse re-rolls
        self.char.set_trait("Animalism", 1)
        self.char.learn_power("Bond Famulus")
        self.char.set_trait("Composure", 3)
        self.char.set_trait("Resolve", 3)

    def run_power(self, rouse_dice):
        self.char.hunger = 4
        with (
            patch.object(humanity_utils, "resist_frenzy", wraps=humanity_utils.resist_frenzy) as frenzy,
            dice(8, *rouse_dice, *[8] * 40),  # pool die, Rouse dice, then frenzy dice (all succeed)
        ):
            output = self.call(CmdPower(), "Bond Famulus", caller=self.char)
        return output, frenzy

    def test_each_failed_check_past_hunger_5_owes_a_test(self):
        """3-Rouse power at Hunger 4, all checks fail: 1 to reach 5, 2 more -> 2 tests."""
        output, frenzy = self.run_power([3, 3, 3])
        self.assertEqual(self.char.hunger, 5)
        self.assertTrue(self.char.ndb.last_roll["result"].is_success)  # the power resolved
        self.assertEqual(frenzy.call_count, 2)
        for call in frenzy.call_args_list:
            self.assertEqual(call.args[1:], (4, "hunger"))
        self.assertIsNone(self.char.db.pending_frenzy_test)
        self.assertIn("Hunger frenzy test", strip_ansi(output))

    def test_first_check_fails_then_one_more_fails(self):
        output, frenzy = self.run_power([3, 8, 3])
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(frenzy.call_count, 1)

    def test_no_test_when_only_the_first_check_fails(self):
        output, frenzy = self.run_power([3, 8, 8])
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(frenzy.call_count, 0)

    def test_a_failed_test_stops_the_rest(self):
        """Once a test fails the vampire is already in frenzy."""
        self.char.hunger = 4
        with (
            patch.object(humanity_utils, "resist_frenzy", wraps=humanity_utils.resist_frenzy) as frenzy,
            dice(8, 3, 3, 3, *[2] * 40),
        ):
            self.call(CmdPower(), "Bond Famulus", caller=self.char)
        self.assertEqual(frenzy.call_count, 1)

    def test_rising_at_hunger_5_is_rolled_and_a_pass_costs_nothing(self):
        """R-1: the forced Rouse is rolled; only a failure at Hunger 5 calls for the test."""
        self.char.hunger = 5
        with (
            patch.object(humanity_utils, "resist_frenzy", wraps=humanity_utils.resist_frenzy) as frenzy,
            all_dice(8),
        ):
            self.call(CmdRouse(), "/wake", caller=self.char)
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(frenzy.call_count, 0)
        self.assertIsNone(self.char.torpor)

    def test_failing_to_rise_at_hunger_5_is_a_frenzy_test_and_torpor(self):
        """QR p.13 (fail a Rouse at Hunger 5: hunger frenzy, Difficulty 4) and QR p.4 (torpor)."""
        self.char.hunger = 5
        with (
            patch.object(humanity_utils, "resist_frenzy", wraps=humanity_utils.resist_frenzy) as frenzy,
            dice(3, *[8] * 20),
        ):
            output = self.call(CmdRouse(), "/wake", caller=self.char)
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(frenzy.call_count, 1)
        self.assertEqual(frenzy.call_args.args[1], 4)
        self.assertIn("Hunger frenzy test", strip_ansi(output))
        self.assertIn("torpor", strip_ansi(output))
        self.assertIsNotNone(self.char.torpor)

    def test_rising_below_hunger_5_is_an_ordinary_rouse(self):
        self.char.hunger = 2
        with all_dice(3):
            self.call(CmdRouse(), "/wake", caller=self.char)
        self.assertEqual(self.char.hunger, 3)
        self.assertIsNone(self.char.db.pending_frenzy_test)

    def test_a_left_over_test_shows_and_is_rolled_by_frenzy_pending(self):
        from commands.v5.blood import CmdHunger
        from dice.rouse_checker import flag_hunger_frenzy

        flag_hunger_frenzy(self.char, "test", count=1)
        self.assertIn("owe a hunger frenzy test", strip_ansi(self.call(CmdHunger(), "", caller=self.char)))
        self.assertIn("+frenzy/pending", strip_ansi(self.call(CmdFrenzy(), "", caller=self.char)))
        with all_dice(8):
            output = self.call(CmdFrenzy(), "/pending", caller=self.char)
        self.assertIn("Hunger frenzy test", strip_ansi(output))
        self.assertIsNone(self.char.db.pending_frenzy_test)
        self.assertIn("don't owe", self.call(CmdFrenzy(), "/pending", caller=self.char))


# ---------------------------------------------------------------------------
# XP (QR p.1)
# ---------------------------------------------------------------------------


class XPCostTableTests(EvenniaTest):
    """One test per row of the QR p.1 Experience chart."""

    def setUp(self):
        super().setUp()
        self.char = new_character()
        self.char.db.experience["total_earned"] = 200
        self.char.clan = "Brujah"

    def spend(self, name, category, note=None):
        before = self.char.xp
        result = self.char.spend_xp(name, category, note)
        self.assertEqual(before - self.char.xp, result["cost"])
        return result["cost"]

    def test_attribute_new_level_x5(self):
        self.char.set_trait("Strength", 3)
        self.assertEqual(self.spend("Strength", "attribute"), 20)
        self.assertEqual(self.char.get_trait("Strength"), 4)

    def test_skill_new_level_x3(self):
        self.char.set_trait("Brawl", 2)
        self.assertEqual(self.spend("Brawl", "skill"), 9)
        self.assertEqual(self.char.get_trait("Brawl"), 3)

    def test_specialty_3(self):
        self.char.set_trait("Brawl", 1)
        self.assertEqual(self.spend("Brawl", "specialty", "Grappling"), 3)
        self.assertEqual(self.char.specialties["brawl"], ["Grappling"])

    def test_clan_discipline_new_level_x5(self):
        self.char.set_trait("Potence", 1)
        self.assertEqual(self.spend("Potence", "discipline"), 10)

    def test_other_discipline_new_level_x7(self):
        self.assertEqual(self.spend("Auspex", "discipline"), 7)

    # F-043: Caitiff disciplines cost new level x 6.
    def test_caitiff_discipline_cost(self):
        self.char.db.vampire["clan"] = "Caitiff"
        cost, new_rating, _in_clan = xp_utils.get_xp_cost_discipline(self.char, "potence")
        self.assertEqual(new_rating, 1)
        self.assertEqual(cost, 6)
        self.assertEqual(self.spend("Potence", "discipline"), 6)

    def test_ritual_level_x3(self):
        self.char.clan = "Tremere"
        self.char.set_trait("Blood Sorcery", 2)
        self.assertEqual(self.spend("Eyes of Babel", "ritual"), 6)
        self.assertEqual(self.char.known_rituals, ["Eyes of Babel"])

    def test_formula_level_x3(self):
        self.char.clan = "Thin-Blood"
        self.char.generation = 14
        self.char.blood_potency = 0
        self.char.set_trait("Thin-Blood Alchemy", 2)
        self.assertEqual(self.spend("Envelop", "formula"), 6)
        self.assertEqual(self.char.known_formulas, ["Envelop"])

    def test_advantage_3_per_dot(self):
        self.assertEqual(self.spend("Resources", "advantage"), 3)
        self.assertEqual(self.char.get_trait("Resources"), 1)
        # Beautiful is a 2-dot merit: 2 dots, 6 XP
        self.assertEqual(self.spend("Beautiful", "advantage"), 6)
        self.assertEqual(self.char.advantages["merits"]["Beautiful"], 2)
        self.assertEqual(self.spend("Allies", "advantage", "street gang"), 3)
        self.assertEqual(self.char.background_instances("Allies"), [{"dots": 1, "note": "street gang"}])

    def test_blood_potency_new_level_x10_up_to_generation_max(self):
        self.char.generation = 13  # max BP 3
        self.char.blood_potency = 1
        self.assertEqual(self.spend("", "bp"), 20)
        self.assertEqual(self.spend("", "bp"), 30)
        with self.assertRaisesRegex(ValueError, "can't rise above 3"):
            self.char.spend_xp("", "bp")
        self.assertEqual(self.char.blood_potency, 3)


class XPSpendTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.db.experience["total_earned"] = 50
        self.char.set_trait("Strength", 3)

    # F-005: an attribute can't be bought as a skill.
    def test_skill_spend_refuses_an_attribute(self):
        ok, message = xp_utils.spend_xp_on_skill(self.char, "strength")
        self.assertFalse(ok)
        self.assertIn("not one of the skills", message)
        self.assertEqual(self.char.xp, 50)
        self.assertEqual(self.char.get_trait("Strength"), 3)

    def test_spend_command_refuses_wrong_category_and_unknown_names(self):
        for args in ("skill strength", "discipline Fireball", "attribute brawl", "advantage Haunted"):
            with self.subTest(args=args):
                output = self.call(CmdSpend(), args, caller=self.char)
                self.assertIn("Nothing was spent", output)
        self.assertEqual(self.char.xp, 50)
        self.assertEqual(self.char.get_trait("Strength"), 3)

    def test_insufficient_xp_is_refused(self):
        self.char.db.experience["total_earned"] = 10
        output = self.call(CmdSpend(), "attribute strength", caller=self.char)
        self.assertIn("Insufficient XP", output)
        self.assertEqual((self.char.xp, self.char.get_trait("Strength")), (10, 3))

    def test_humanity_and_willpower_are_not_bought(self):
        for args in ("humanity", "willpower"):
            output = self.call(CmdSpend(), args, caller=self.char)
            self.assertIn("neither is bought", output)
        self.assertEqual(self.char.xp, 50)

    def test_spend_command_raises_and_logs(self):
        output = self.call(CmdSpend(), "attribute strength", caller=self.char)
        self.assertIn("Raised Strength to 4 for 20 XP", output)
        self.assertEqual((self.char.xp, self.char.get_trait("Strength")), (30, 4))
        entry = self.char.db.experience["log"][-1]
        self.assertEqual((entry["amount"], entry["balance"]), (-20, 30))

    def test_willpower_survives_an_attribute_raise(self):
        self.char.set_damage("willpower", superficial=1)
        before = self.char.willpower_max
        self.call(CmdSpend(), "attribute composure", caller=self.char)
        self.assertEqual(self.char.willpower_max, before + 1)
        self.assertEqual(self.char.damage["willpower"]["superficial"], 1)

    def test_learned_rituals_survive_a_discipline_change(self):
        self.char.learn_ritual_or_formula("ritual", "Blood Walk")
        self.char.set_trait("Blood Sorcery", 3)
        self.assertEqual(self.char.known_rituals, ["Blood Walk"])
        self.assertEqual(self.char.get_trait("Blood Sorcery"), 3)

    def test_ritual_above_the_discipline_rating_is_refused(self):
        self.char.set_trait("Blood Sorcery", 1)
        ok, message = xp_utils.spend_xp(self.char, "Eyes of Babel", "ritual")
        self.assertFalse(ok)
        self.assertEqual(self.char.xp, 50)


# ---------------------------------------------------------------------------
# Combat (core p.123-126; QR p.3)
# ---------------------------------------------------------------------------


class DamageTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.char.set_trait("Stamina", 1)  # 4 Health boxes

    def test_vampires_halve_superficial_damage_rounding_up(self):
        combat_utils.apply_damage(self.char, 3, "superficial")
        self.assertEqual(self.char.damage["health"]["superficial"], 2)

    def test_mortals_take_it_all(self):
        self.char.splat = "mortal"
        combat_utils.apply_damage(self.char, 3, "superficial")
        self.assertEqual(self.char.damage["health"]["superficial"], 3)

    def test_aggravated_is_not_halved(self):
        combat_utils.apply_damage(self.char, 3, "aggravated")
        self.assertEqual(self.char.damage["health"]["aggravated"], 3)

    def test_half_track_is_not_impaired(self):
        self.char.set_damage("health", superficial=2)
        self.assertFalse(combat_utils.is_impaired(self.char))
        self.assertEqual(combat_utils.get_impairment_penalty(self.char), 0)

    def test_full_superficial_track_is_impaired_not_torpor(self):
        result = combat_utils.apply_damage(self.char, 8, "superficial")
        self.assertEqual(self.char.damage["health"], {"superficial": 4, "aggravated": 0})
        self.assertTrue(result["impaired"])
        self.assertFalse(result["torpor"])
        self.assertEqual(combat_utils.get_impairment_penalty(self.char), -2)
        self.assertNotIn("torpor", strip_ansi(result["message"]))

    def test_superficial_on_a_full_track_becomes_aggravated(self):
        self.char.set_damage("health", superficial=4)
        combat_utils.apply_damage(self.char, 2, "superficial")  # halved to 1
        self.assertEqual(self.char.damage["health"], {"superficial": 3, "aggravated": 1})

    def test_torpor_is_judged_on_the_damage_after_the_hit(self):
        self.char.set_damage("health", aggravated=3)
        result = combat_utils.apply_damage(self.char, 1, "aggravated")
        self.assertTrue(result["torpor"])
        self.assertIn("torpor", strip_ansi(result["message"]))

    def test_no_lethal_damage_type(self):
        self.assertFalse(combat_utils.apply_damage(self.char, 2, "lethal")["success"])


class AttackTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.attacker, self.defender = self.char1, self.char2
        self.attacker.set_trait("Strength", 3)
        self.attacker.set_trait("Brawl", 2)  # 5 dice
        self.defender.set_trait("Dexterity", 2)
        self.defender.set_trait("Athletics", 1)  # 3 dice
        self.attacker.hunger = 0
        self.defender.hunger = 0

    def test_attack_is_contested_and_damage_is_margin_plus_weapon(self):
        # defender rolls first (2 successes), then the attacker (4 successes)
        with dice(8, 8, 2, 8, 8, 8, 8, 2):
            result = combat_utils.calculate_attack(self.attacker, self.defender, "Strength + Brawl", weapon=2)
        self.assertTrue(result["success"])
        self.assertEqual((result["margin"], result["damage"]), (2, 4))

    def test_attack_that_gets_fewer_successes_misses(self):
        with dice(8, 8, 8, 8, 2, 2, 2, 2):
            result = combat_utils.calculate_attack(self.attacker, self.defender, "Strength + Brawl", weapon=2)
        self.assertFalse(result["success"])
        self.assertEqual(result["damage"], 0)

    def test_a_tie_goes_to_the_attacker_for_1_plus_weapon(self):
        """R-2: a tie hits for 1 + weapon (Basic Rules, Conflict Pools)."""
        with dice(8, 2, 2, 8, 2, 2, 2, 2):
            result = combat_utils.calculate_attack(
                self.attacker, self.defender, "Strength + Brawl", weapon=1, defense_pool_desc="Dexterity + Athletics"
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["damage"], 2)

    def test_an_unarmed_tie_still_does_1(self):
        with dice(8, 2, 2, 8, 2, 2, 2, 2):
            result = combat_utils.calculate_attack(
                self.attacker, self.defender, "Strength + Brawl", defense_pool_desc="Dexterity + Athletics"
            )
        self.assertEqual(result["damage"], 1)

    def test_defender_rolls_their_best_standard_defense(self):
        """R-16/R-19: the defender's pool is chosen for them, not by the attacker."""
        self.defender.set_trait("Strength", 4)
        self.defender.set_trait("Brawl", 3)  # Strength + Brawl 7 beats Dexterity + Athletics 3
        self.assertEqual(combat_utils.best_defense_pool(self.defender, "Strength + Brawl"), "Strength + Brawl")
        # against a gun only a dodge works
        self.assertEqual(combat_utils.best_defense_pool(self.defender, "Dexterity + Firearms"), "Dexterity + Athletics")

    def test_player_cant_choose_the_defense_or_stack_traits(self):
        attacker = self.char2  # a player
        attacker.set_trait("Strength", 3)
        with no_dice():
            out = self.call(CmdAttack(), "Char=Strength + Brawl vs Occult", caller=attacker)
            self.assertIn("Only staff can choose", out)
            out = self.call(CmdAttack(), "Char=Strength + Brawl + Strength + Brawl", caller=attacker)
            self.assertIn("one Attribute plus one Skill", out)

    def test_fortitude_reduction_only_reduces_superficial(self):
        """R-6: Fortitude's damage reduction doesn't touch Aggravated damage."""
        self.defender.db.active_effects = [{"discipline": "Fortitude", "damage_reduction": 2}]
        combat_utils.apply_damage(self.defender, 2, "aggravated")
        self.assertEqual(self.defender.damage["health"]["aggravated"], 2)

    def test_attack_shows_and_rolls_the_same_pool(self):
        """F-042: an impaired attacker loses 2 dice from the pool shown and the pool rolled."""
        self.attacker.set_damage("health", superficial=self.attacker.health_max)
        with patch("commands.v5.utils.combat_utils.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll, all_dice(8):
            output = self.call(CmdAttack(), "Char2=Strength + Brawl", caller=self.attacker)
        self.assertEqual(roll.call_args_list[1].args[0], 3)  # attacker: 5 - 2
        self.assertIn("-2 (impaired)", strip_ansi(output))

    def test_mortal_defender_rolls_no_hunger_dice(self):
        self.defender.splat = "mortal"
        self.defender.hunger = 5
        with all_dice(1):
            result = combat_utils.calculate_attack(self.attacker, self.defender)
        self.assertEqual(result["defense_result"].hunger_dice, [])
        self.assertFalse(result["defense_result"].is_bestial_failure)


class LockdownTests(EvenniaCommandTest):
    """F-054 / A-030: +damage, +heal and +stain on someone else are staff only."""

    def setUp(self):
        super().setUp()
        self.player, self.staff = self.char2, self.char1

    def test_player_damage_on_another_is_refused(self):
        output = self.call(CmdDamage(), "Char=3", caller=self.player)
        self.assertIn("Only staff", output)
        self.assertEqual(self.staff.damage["health"]["superficial"], 0)

    def test_builder_damage_on_another_succeeds(self):
        self.call(CmdDamage(), "Char2=3", caller=self.staff)
        self.assertEqual(self.player.damage["health"]["superficial"], 2)  # 3 halved, rounded up

    def test_player_may_damage_themself(self):
        self.call(CmdDamage(), "2", caller=self.player)
        self.assertEqual(self.player.damage["health"]["superficial"], 1)

    def test_player_heal_on_another_is_refused(self):
        self.staff.set_damage("health", superficial=2)
        output = self.call(CmdHeal(), "Char=2", caller=self.player)
        self.assertIn("Only staff", output)
        self.assertEqual(self.staff.damage["health"]["superficial"], 2)

    def test_builder_heals_another(self):
        self.player.set_damage("health", aggravated=2)
        self.call(CmdHeal(), "Char2=1/aggravated", caller=self.staff)
        self.assertEqual(self.player.damage["health"]["aggravated"], 1)

    def test_player_stain_on_another_is_refused(self):
        output = self.call(CmdStain(), "Char=2", caller=self.player)
        self.assertIn("Only staff", output)
        self.assertEqual(self.staff.stains, 0)

    def test_builder_stains_another(self):
        self.call(CmdStain(), "Char2=2", caller=self.staff)
        self.assertEqual(self.player.stains, 2)

    def test_player_may_stain_themself(self):
        self.call(CmdStain(), "1", caller=self.player)
        self.assertEqual(self.player.stains, 1)


class MendTests(EvenniaCommandTest):
    """Mending: one Rouse check heals the BP mend amount of Superficial damage (QR p.13)."""

    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.blood_potency = 2  # mend 2
        self.char.set_trait("Stamina", 2)
        self.char.set_damage("health", superficial=3)

    def test_mend_heals_the_blood_potency_amount_for_one_rouse(self):
        self.char.hunger = 1
        with all_dice(8):
            self.call(CmdHeal(), "", caller=self.char)
        self.assertEqual(self.char.damage["health"]["superficial"], 1)
        self.assertEqual(self.char.hunger, 1)

    def test_failed_rouse_still_mends_and_raises_hunger(self):
        self.char.hunger = 1
        with all_dice(3):
            self.call(CmdHeal(), "", caller=self.char)
        self.assertEqual(self.char.damage["health"]["superficial"], 1)
        self.assertEqual(self.char.hunger, 2)

    def test_mending_with_a_refused_rouse_heals_nothing(self):
        self.char.hunger = 5
        with no_dice():
            output = self.call(CmdHeal(), "", caller=self.char)
        self.assertIn("cannot Rouse", output)
        self.assertEqual(self.char.damage["health"]["superficial"], 3)

    def test_mortals_dont_mend_with_blood(self):
        self.char.splat = "mortal"
        with no_dice():
            combat_utils.mend_superficial(self.char)
        self.assertEqual(self.char.damage["health"]["superficial"], 3)


# ---------------------------------------------------------------------------
# Mortal vs vampire (Character.splat)
# ---------------------------------------------------------------------------


class SplatTests(EvenniaTest):
    def test_player_characters_default_to_vampire(self):
        self.assertEqual(self.char1.splat, "vampire")
        self.assertEqual(self.char1.dice_hunger, self.char1.hunger)

    def test_invalid_splat_is_refused(self):
        with self.assertRaises(ValueError):
            self.char1.splat = "werewolf"

    def test_mortal_defender_of_a_contested_power_rolls_no_hunger_dice(self):
        user, npc = self.char1, self.char2
        user.set_trait("Presence", 3)
        user.learn_power("Dread Gaze")
        npc.splat = "mortal"
        npc.hunger = 5
        npc.set_trait("Composure", 3)
        npc.set_trait("Resolve", 2)
        with all_dice(1):
            result = discipline_roller.roll_discipline_power(user, "Dread Gaze", target=npc)
        defense = result["defense"]["roll_result"]
        self.assertEqual(defense.hunger_dice, [])
        self.assertEqual(len(defense.regular_dice), 5)
        self.assertFalse(defense.is_bestial_failure)

    def test_vampire_defender_still_rolls_hunger_dice(self):
        user, npc = self.char1, self.char2
        user.set_trait("Presence", 3)
        user.learn_power("Dread Gaze")
        npc.hunger = 2
        with all_dice(8):
            result = discipline_roller.roll_discipline_power(user, "Dread Gaze", target=npc)
        self.assertEqual(len(result["defense"]["roll_result"].hunger_dice), 2)


# ---------------------------------------------------------------------------
# Hunting and feeding (QR p.12; core p.307-308)
# ---------------------------------------------------------------------------


class HuntTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.predator_type = "Alleycat"
        self.char.set_trait("Strength", 3)
        self.char.set_trait("Brawl", 2)
        self.char.hunger = 4

    def test_hunt_rolls_the_predator_types_book_pool(self):
        with (
            patch("commands.v5.utils.hunting_utils.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll,
            all_dice(8),
        ):
            output = self.call(CmdHunt(), "downtown", caller=self.char)
        self.assertEqual(roll.call_args.args, (5, 4, 4))  # Strength 3 + Brawl 2, Hunger 4, Difficulty 4
        self.assertIn("Strength + Brawl", output)
        self.assertEqual(self.char.hunger, 2)  # a non-harmful drink slakes 2

    def test_no_hunt_at_the_hunger_floor(self):
        """R-13: at the no-kill floor +hunt rolls nothing and the resonance is kept."""
        self.char.hunger = 1
        from commands.v5.utils import blood_utils

        blood_utils.set_resonance(self.char, "Choleric", 2)
        with no_dice():
            out = self.call(CmdHunt(), "slum", caller=self.char)
        self.assertIn("without a kill", out)
        self.assertEqual(self.char.hunger, 1)
        self.assertEqual(self.char.resonance["type"], "Choleric")
        self.assertIsNone(self.char.last_hunt)

    def test_one_hunt_per_24_hours_even_after_a_failure(self):
        """R-12 (owner decision): one +hunt per 24 hours, success or failure."""
        with all_dice(2):
            self.call(CmdHunt(), "slum", caller=self.char)
        self.assertEqual(self.char.hunger, 4)
        with no_dice():
            out = self.call(CmdHunt(), "slum", caller=self.char)
        self.assertIn("already hunted", out)
        self.char.last_hunt = time.time() - 25 * 3600
        with all_dice(8):
            self.call(CmdHunt(), "slum", caller=self.char)
        self.assertEqual(self.char.hunger, 2)

    def test_staff_can_reset_the_hunt_timer(self):
        self.char.last_hunt = time.time()
        self.call(CmdHunt(), "/reset Char2", caller=self.char1)
        self.assertIsNone(self.char.last_hunt)

    def test_alternative_pool(self):
        """R-11: +hunt <ground>=alt rolls the type's alternative pool (Alleycat: Wits + Streetwise)."""
        self.char.set_trait("Wits", 2)
        self.char.set_trait("Streetwise", 3)
        with (
            patch("commands.v5.utils.hunting_utils.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll,
            all_dice(8),
        ):
            out = self.call(CmdHunt(), "downtown=alt", caller=self.char)
        self.assertEqual(roll.call_args.args[0], 5)
        self.assertIn("Wits + Streetwise", out)

    def test_failed_hunt_keeps_hunger(self):
        with all_dice(2):
            self.call(CmdHunt(), "wealthy", caller=self.char)
        self.assertEqual(self.char.hunger, 4)

    def test_blood_leech_has_no_hunting_roll(self):
        self.char.predator_type = "Blood Leech"
        with no_dice():
            output = self.call(CmdHunt(), "downtown", caller=self.char)
        self.assertIn("+hunt/staffed", output)
        self.assertEqual(self.char.hunger, 4)

    def test_no_predator_type_has_no_hunting_roll(self):
        self.char.predator_type = None
        with no_dice():
            output = self.call(CmdHunt(), "downtown", caller=self.char)
        self.assertIn("+hunt/staffed", output)

    def test_farmer_feeds_on_an_animal(self):
        self.char.predator_type = "Farmer"
        self.char.set_trait("Composure", 3)
        self.char.set_trait("Animal Ken", 2)
        with all_dice(8):
            self.call(CmdHunt(), "suburbs", caller=self.char)
        self.assertEqual(self.char.hunger, 3)  # an animal slakes 1
        self.assertIsNone(self.char.resonance)

    def test_unknown_ground_is_refused(self):
        with no_dice():
            output = self.call(CmdHunt(), "moon", caller=self.char)
        self.assertIn("Usage", output)


class HerdTests(EvenniaTest):
    def test_herd_slakes_up_to_its_dots_once_a_week(self):
        char = self.char1
        char.set_trait("Herd", 2)
        char.hunger = 5
        now = time.time()
        self.assertTrue(background_utils.use_herd_to_feed(char, now=now)["success"])
        self.assertEqual(char.hunger, 3)
        self.assertFalse(background_utils.use_herd_to_feed(char, now=now + 6 * 86400)["success"])
        self.assertEqual(char.hunger, 3)
        self.assertTrue(background_utils.use_herd_to_feed(char, now=now + 8 * 86400)["success"])
        self.assertEqual(char.hunger, 1)
        # and never below 1 without a kill
        self.assertFalse(background_utils.use_herd_to_feed(char, now=now + 16 * 86400)["success"])


# ---------------------------------------------------------------------------
# Touchstones (core p.172-173)
# ---------------------------------------------------------------------------


class TouchstoneTests(EvenniaCommandTest):
    def test_no_humanity_based_touchstone_cap(self):
        """The book ties Touchstones to Convictions; there is no Humanity / 2 cap."""
        char = self.char1
        humanity_utils.set_humanity(char, 4)  # the old cap would have been 2
        for text in ("Never kill", "Protect children", "Keep promises"):
            char.add_conviction(text)
        for index, name in enumerate(("Anna", "Ben", "Cleo")):
            result = humanity_utils.add_touchstone(char, name, "friend", index)
            self.assertTrue(result["success"], result["message"])
        self.assertEqual(len(char.touchstones), 3)
        self.assertNotIn("max", strip_ansi(self.call(CmdHumanity(), "", caller=char)).split("Touchstones:")[1][:10])


# ---------------------------------------------------------------------------
# Thin-blood alchemy (core p.282-288)
# ---------------------------------------------------------------------------


class AlchemyTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.char.clan = "Thin-Blood"
        self.char.generation = 14
        self.char.blood_potency = 0
        self.char.set_trait("Thin-Blood Alchemy", 1)
        self.char.set_trait("Stamina", 2)
        self.char.learn_ritual_or_formula("formula", "Far Reach")
        self.char.hunger = 2

    def test_distilling_rolls_the_method_pool_with_hunger_dice_then_rouses(self):
        with all_dice(3):  # a failed roll and a failed Rouse
            result = thin_blood_utils.craft_formula(self.char, "Far Reach", "athanor")
        roll = result["roll_result"]
        self.assertEqual(dice_count(roll), 3)  # Stamina 2 + Alchemy 1
        self.assertEqual(len(roll.hunger_dice), 2)  # the pre-Rouse Hunger
        self.assertEqual(self.char.hunger, 3)

    def test_a_successful_distillation_gives_a_dose_and_using_it_pays_its_rouse(self):
        with all_dice(8):
            self.assertTrue(thin_blood_utils.craft_formula(self.char, "Far Reach")["success"])
        self.assertEqual([dose["name"] for dose in self.char.db.crafted_formulae], ["Far Reach"])
        with all_dice(3):
            result = thin_blood_utils.use_alchemy(self.char, "Far Reach")
        self.assertTrue(result["success"])
        self.assertEqual(self.char.hunger, 3)  # Far Reach costs 1 Rouse
        self.assertEqual(self.char.db.crafted_formulae, [])

    def test_unknown_formula_is_refused_without_dice(self):
        with no_dice():
            result = thin_blood_utils.craft_formula(self.char, "Haze")
        self.assertFalse(result["success"])

    def test_no_distilling_at_hunger_5(self):
        self.char.hunger = 5
        with no_dice():
            result = thin_blood_utils.craft_formula(self.char, "Far Reach")
        self.assertIn("cannot Rouse", result["message"])


class TouchstoneConvictionTests(EvenniaCommandTest):
    def test_a_touchstone_needs_an_existing_conviction(self):
        """R-22: the conviction index must name one of the character's Convictions."""
        char = self.char1
        self.assertFalse(humanity_utils.add_touchstone(char, "Anna", "sister", 0)["success"])
        char.add_conviction("Never kill")
        self.assertFalse(humanity_utils.add_touchstone(char, "Anna", "sister", 1)["success"])
        out = self.call(CmdHumanity(), "/touchstone Anna=sister/1", caller=char)
        self.assertIn("Touchstone added", out)
        self.assertEqual(char.touchstones[0]["conviction_index"], 0)


# ---------------------------------------------------------------------------
# Review round 1 (reviews/pr-6.md)
# ---------------------------------------------------------------------------


class ThinBloodXPTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char = self.char2
        self.char.clan = "Thin-Blood"
        self.char.generation = 14
        self.char.blood_potency = 0
        self.char.db.experience["total_earned"] = 100

    def test_thin_bloods_cant_buy_vampire_disciplines(self):
        """R-3/R-14: only Thin-Blood Alchemy is bought with XP."""
        out = self.call(CmdSpend(), "discipline Dominate", caller=self.char)
        self.assertIn("Nothing was spent", out)
        self.assertEqual((self.char.xp, self.char.get_trait("Dominate")), (100, 0))

    def test_each_alchemy_dot_comes_with_a_formula(self):
        """R-4: buying an Alchemy dot needs, and grants, one formula (new level x 5)."""
        out = self.call(CmdSpend(), "discipline Thin-Blood Alchemy", caller=self.char)
        self.assertIn("Nothing was spent", out)
        out = self.call(CmdSpend(), "discipline Thin-Blood Alchemy = Envelop", caller=self.char)  # level 2
        self.assertIn("Nothing was spent", out)
        self.call(CmdSpend(), "discipline Thin-Blood Alchemy = Far Reach", caller=self.char)
        self.assertEqual(self.char.get_trait("Thin-Blood Alchemy"), 1)
        self.assertEqual(self.char.known_formulas, ["Far Reach"])
        self.assertEqual(self.char.xp, 95)

    def test_staff_teach_grants_a_formula(self):
        """R-9: the Thin-blood Alchemist merit's formula has a staff grant path."""
        from commands.v5.thinblood import CmdAlchemy

        out = self.call(CmdAlchemy(), "/teach Char2=Haze", caller=self.char2)
        self.assertIn("Only staff", out)
        self.call(CmdAlchemy(), "/teach Char2=Haze", caller=self.char1)
        self.assertEqual(self.char.known_formulas, ["Haze"])

    def test_players_cant_set_the_distillation_difficulty(self):
        """R-15: the difficulty is 3 unless staff set it."""
        from commands.v5.thinblood import CmdAlchemy

        self.char.set_trait("Thin-Blood Alchemy", 1)
        self.char.learn_ritual_or_formula("formula", "Far Reach")
        with no_dice():
            out = self.call(CmdAlchemy(), "/distill far reach vs 1", caller=self.char)
        self.assertIn("Only staff", out)
        self.assertFalse(self.char.db.crafted_formulae)


class DegenerationTests(EvenniaCommandTest):
    def test_full_humanity_tracker_impairs_rolls(self):
        """R-5: Stains filling the Humanity tracker: Impaired, -2 dice to all tests (QR p.3)."""
        from dice.commands import CmdRoll

        char = self.char2
        humanity_utils.set_humanity(char, 8)
        result = humanity_utils.add_stain(char, 2)
        self.assertIn("Impaired", result["message"])
        self.assertTrue(char.degenerating)
        char.hunger = 0
        with all_dice(8):
            self.call(CmdRoll(), "5", caller=char)
        self.assertEqual(len(char.ndb.last_roll["result"].regular_dice), 3)
        self.assertIn("Degeneration", strip_ansi(self.call(CmdHumanity(), "", caller=char)))


class GhoulPowerTests(EvenniaTest):
    def test_ghoul_power_rolls_no_hunger_dice_and_no_rouse(self):
        """R-8/R-18: only vampires roll Hunger dice or Rouse the Blood, on power too."""
        char = self.char2
        char.splat = "ghoul"
        char.hunger = 3
        char.set_trait("Animalism", 2)
        char.learn_power("Feral Whispers")
        with all_dice(1):
            result = discipline_roller.roll_discipline_power(char, "Feral Whispers")
        self.assertEqual(result["roll_result"].hunger_dice, [])
        self.assertFalse(result["roll_result"].is_bestial_failure)
        self.assertIsNone(result["rouse_result"])
        self.assertEqual(char.hunger, 3)
        self.assertIsNone(char.db.pending_frenzy_test)


class FeedingCarryTests(EvenniaTest):
    def test_bp_2_animal_blood_slakes_half_a_point_carried(self):
        """BP 2: animal and bagged blood slake half; the half point is carried."""
        from commands.v5.utils import hunting_utils

        char = self.char2
        char.blood_potency = 2
        char.hunger = 4
        hunting_utils.slake(char, "bag")
        self.assertEqual((char.hunger, char.slake_carry), (4, 0.5))
        hunting_utils.slake(char, "bag")
        self.assertEqual((char.hunger, char.slake_carry), (3, 0.0))
        hunting_utils.slake(char, "large animal")
        self.assertEqual(char.hunger, 2)

    def test_animal_succulence_adds_one_and_lowers_the_penalty(self):
        """BP 4 counts as BP 2 for animal blood and the animal gives 1 more: (1 + 1) / 2 = 1."""
        from commands.v5.utils import hunting_utils

        char = self.char2
        char.blood_potency = 4
        char.set_trait("Animalism", 2)
        char.learn_power("Animal Succulence")
        char.hunger = 4
        hunting_utils.slake(char, "animal")
        self.assertEqual(char.hunger, 3)


class HerdUseTests(EvenniaTest):
    def test_background_use_doesnt_reset_the_weekly_herd(self):
        """R-7: +background/use Herd records the weekly timer; it doesn't defeat it."""
        char = self.char2
        char.set_trait("Herd", 2)
        char.hunger = 4
        self.assertTrue(background_utils.use_background(char, "Herd", "a favour")["success"])
        self.assertFalse(background_utils.use_background(char, "Herd", "another")["success"])
        self.assertFalse(background_utils.use_herd_to_feed(char)["success"])
        background_utils.reset_background_uses(char)  # a new session keeps the week
        self.assertFalse(background_utils.use_herd_to_feed(char)["success"])
        self.assertEqual(char.hunger, 4)


class RemorseOncePerSessionTests(EvenniaCommandTest):
    def test_remorse_once_per_24_hours_but_staff_can_run_more(self):
        """R-17: one player Remorse test per 24 hours; staff can run another."""
        from commands.v5.humanity import CmdRemorse

        char = self.char2
        humanity_utils.add_stain(char, 1)
        with all_dice(8):
            self.call(CmdRemorse(), "", caller=char)
        humanity_utils.add_stain(char, 1)
        with no_dice():
            out = self.call(CmdRemorse(), "", caller=char)
        self.assertIn("made your Remorse test", out)
        self.assertEqual(char.stains, 1)
        with all_dice(8):
            self.call(CmdRemorse(), "Char2", caller=self.char1)
        self.assertEqual(char.stains, 0)
