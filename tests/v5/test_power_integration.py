"""Actual activation-to-consumer tests and shared pool impairment on real sheets."""

from unittest.mock import patch

from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.combat import CmdAttack
from commands.v5.utils import combat_utils, discipline_effects, discipline_utils, humanity_utils, hunting_utils
from dice import dice_roller, discipline_roller


class PowerCombatIntegrationTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.attacker, self.defender = self.char1, self.char2
        for char in (self.attacker, self.defender):
            char.blood_potency = 0
            char.hunger = 0
            char.set_trait("Strength", 3)
            char.set_trait("Dexterity", 3)
            char.set_trait("Brawl", 2)
            char.set_trait("Melee", 2)
            char.set_trait("Athletics", 2)
            char.set_trait("Firearms", 2)

    def activate(self, character, discipline, rating, power):
        character.set_trait(discipline, rating)
        character.learn_power(power)
        with patch("random.randint", return_value=8):
            result = discipline_utils.activate_discipline_power(character, discipline, power)
        self.assertTrue(result["success"])
        return result

    def attack(self, **kwargs):
        with patch("random.randint", return_value=8):
            return combat_utils.calculate_attack(self.attacker, self.defender, **kwargs)

    def test_fleetness_modifies_eligible_defense_before_best_pool_selection(self):
        self.defender.set_trait("Strength", 4)  # Brawl 6 beats the base dodge 5.
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        result = self.attack()
        self.assertEqual(result["defense_pool"], "Dexterity + Athletics")
        self.assertEqual(result["defense"]["pool"], 7)
        self.assertEqual(len(result["defense_result"].all_dice), 7)
        self.assertIn("Fleetness", result["defense"]["breakdown"])
        self.assertEqual(self.attack()["defense_pool"], "Strength + Brawl")

    def test_fleetness_is_once_per_turn_and_reactivation_does_not_reset_usage(self):
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        self.assertEqual(self.attack()["defense"]["pool"], 7)
        self.defender.attributes.reset_cache()  # Persisted use survives handler reload.
        self.assertEqual(self.attack()["defense"]["pool"], 5)
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        self.assertEqual(self.attack()["defense"]["pool"], 5)
        discipline_effects.tick_effects(self.defender)
        self.assertEqual(self.attack()["defense"]["pool"], 7)

    def test_ineligible_or_unchosen_defense_does_not_consume_fleetness(self):
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        result = self.attack(defense_pool_desc="Dexterity + Melee")
        self.assertEqual(result["defense"]["pool"], 5)
        self.defender.set_trait("Strength", 5)
        self.defender.set_trait("Brawl", 5)
        self.assertEqual(self.attack()["defense_pool"], "Strength + Brawl")
        self.defender.set_trait("Brawl", 2)
        self.defender.set_trait("Strength", 3)
        self.assertEqual(self.attack()["defense"]["pool"], 7)

    def test_fleetness_noncombat_dexterity_bonus_excludes_attacks_and_other_traits(self):
        self.activate(self.attacker, "Celerity", 2, "Fleetness")
        dexterity = combat_utils.get_combat_pool(self.attacker, "Dexterity + Athletics", context="noncombat")
        strength = combat_utils.get_combat_pool(self.attacker, "Strength + Athletics", context="noncombat")
        self.assertEqual((dexterity["pool"], strength["pool"]), (7, 5))
        result = self.attack(attack_pool_desc="Dexterity + Firearms")
        self.assertEqual(result["attack"]["pool"], 5)

    def test_prowess_adds_rating_to_brawl_and_melee_damage_once(self):
        self.activate(self.attacker, "Potence", 2, "Prowess")
        self.activate(self.attacker, "Potence", 2, "Prowess")
        for skill in ("Brawl", "Melee"):
            with self.subTest(skill=skill):
                result = self.attack(attack_pool_desc=f"Strength + {skill}", weapon=1)
                self.assertEqual((result["potence_bonus"], result["damage"]), (2, 4))
                self.assertEqual(result["attack"]["pool"], 5)
        result = self.attack(attack_pool_desc="Dexterity + Firearms", weapon=1)
        self.assertEqual((result["potence_bonus"], result["damage"]), (0, 2))

    def test_toughness_soaks_only_superficial_and_resilience_adds_health(self):
        baseline = self.defender.health_max
        self.activate(self.defender, "Fortitude", 2, "Resilience")
        self.activate(self.defender, "Fortitude", 2, "Resilience")
        self.assertEqual(self.defender.health_max, baseline + 2)
        self.activate(self.defender, "Fortitude", 2, "Toughness")
        result = combat_utils.apply_damage(self.defender, 4, "superficial", halve=False)
        self.assertEqual(result["marked"], 2)
        result = combat_utils.apply_damage(self.defender, 2, "aggravated")
        self.assertEqual(result["marked"], 2)
        effects = [e for e in self.defender.db.active_effects if e["power"] == "Resilience"]
        for effect in effects:
            discipline_effects.remove_effect(self.defender, effect["id"])
        self.assertEqual(self.defender.health_max, baseline)

    def test_resilience_and_draught_do_not_supply_invented_fixed_soak_or_defense(self):
        self.activate(self.defender, "Fortitude", 2, "Resilience")
        result = combat_utils.apply_damage(self.defender, 2, "superficial", halve=False)
        self.assertEqual(result["marked"], 2)
        self.activate(self.defender, "Celerity", 4, "Draught of Elegance")
        self.assertEqual(self.attack()["defense"]["pool"], 5)

    def test_attack_command_displays_the_same_modified_pools_it_rolls(self):
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        self.attacker.set_damage("health", superficial=self.attacker.health_max)
        with (
            patch("commands.v5.utils.combat_utils.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll,
            patch("random.randint", return_value=8),
        ):
            output = strip_ansi(self.call(CmdAttack(), "Char2=Strength + Brawl", caller=self.attacker))
        self.assertEqual([call.args[0] for call in roll.call_args_list], [7, 3])
        self.assertIn("Fleetness", output)
        self.assertIn("-2 (impaired)", output)

    def test_hunting_fleetness_applies_only_to_noncombat_dexterity_and_preserves_snapshot(self):
        self.activate(self.attacker, "Celerity", 2, "Fleetness")
        self.attacker.set_damage("health", superficial=self.attacker.health_max)
        self.attacker.set_trait("Stealth", 2)
        for index, (predator, expected, boosted) in enumerate((("Sandman", 5, True), ("Alleycat", 3, False))):
            with self.subTest(predator=predator):
                self.attacker.predator_type = predator
                self.attacker.hunger = 4
                with (
                    patch("commands.v5.utils.hunting_utils.roll_v5_pool", wraps=dice_roller.roll_v5_pool) as roll,
                    patch("random.randint", return_value=8),
                ):
                    result = hunting_utils.hunt(self.attacker, "downtown", now=1000000000 + index * 100000)
                self.assertEqual(roll.call_args.args[0], expected)
                self.assertEqual("Fleetness" in result["breakdown"], boosted)
                snapshot = hunting_utils.serialize_hunt_outcome(
                    dict(result, location="downtown", hunger_before=4, hunger_after=self.attacker.hunger)
                )
                self.assertEqual(snapshot["pool"]["rolled"], expected)
                self.assertIn("room_context", result)

    def test_invalid_attack_does_not_spend_fleetness_and_bad_bonus_values_are_ignored(self):
        self.activate(self.defender, "Celerity", 2, "Fleetness")
        failed = combat_utils.calculate_attack(self.attacker, self.defender, "Unknown Trait + Brawl")
        self.assertIsNotNone(failed["error"])
        self.assertEqual(self.attack()["defense"]["pool"], 7)
        self.defender.db.active_effects = [
            {
                "id": "malformed",
                "power": "Fleetness",
                "discipline": "Celerity",
                "duration": "scene",
                "parameters": {"dexterity_bonus": "99"},
            }
        ]
        discipline_effects.tick_effects(self.defender)
        self.assertEqual(self.attack()["defense"]["pool"], 5)


class DisciplineImpairmentTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.caster, self.target = self.char2, self.char1
        for char in (self.caster, self.target):
            char.blood_potency = 0
            char.hunger = 0

    def degenerate(self, character):
        humanity_utils.set_humanity(character, 9)
        humanity_utils.add_stain(character, 1)

    def defense(self, pool):
        with patch("random.randint", return_value=8):
            return discipline_roller._roll_defense(self.target, pool)

    def test_degenerating_social_resistance_has_four_dice_and_labelled_breakdown(self):
        self.target.set_trait("Composure", 3)
        self.target.set_trait("Resolve", 3)
        self.degenerate(self.target)
        result = self.defense("Composure + Resolve")
        self.assertEqual(result["dice_pool"], 4)
        self.assertEqual(len(result["roll_result"].all_dice), 4)
        self.assertEqual(result["dice_pool_breakdown"]["Degeneration (Humanity tracker full)"], -2)
        self.assertIn("Degeneration", strip_ansi(discipline_roller.format_defense(result)))

    def test_health_impaired_blink_rolls_three_with_displayed_penalty(self):
        self.caster.set_trait("Celerity", 3)
        self.caster.learn_power("Blink")
        self.caster.set_trait("Dexterity", 3)
        self.caster.set_trait("Athletics", 2)
        self.caster.set_damage("health", superficial=self.caster.health_max)
        with patch("random.randint", return_value=8):
            result = discipline_roller.roll_discipline_power(self.caster, "Blink")
        self.assertEqual(result["dice_pool"], 3)
        self.assertEqual(len(result["roll_result"].all_dice), 3)
        self.assertEqual(result["dice_pool_breakdown"]["Health impairment"], -2)
        self.assertIn("Health impairment: -2", strip_ansi(result["message"]))
        self.assertIn("Total: 3", strip_ansi(result["message"]))

    def test_physical_resistance_combines_health_and_degeneration_penalties(self):
        self.target.set_trait("Dexterity", 3)
        self.target.set_trait("Athletics", 3)
        self.target.set_damage("health", superficial=self.target.health_max)
        self.degenerate(self.target)
        result = self.defense("Dexterity + Athletics")
        self.assertEqual(result["dice_pool"], 2)
        self.assertEqual(result["dice_pool_breakdown"]["Health impairment"], -2)
        self.assertEqual(result["dice_pool_breakdown"]["Degeneration (Humanity tracker full)"], -2)

    def test_health_impairment_excludes_social_pools_and_healthy_control(self):
        self.target.set_trait("Composure", 3)
        self.target.set_trait("Resolve", 3)
        self.assertEqual(self.defense("Composure + Resolve")["dice_pool"], 6)
        self.target.set_damage("health", superficial=self.target.health_max)
        self.assertEqual(self.defense("Composure + Resolve")["dice_pool"], 6)
        result = combat_utils.get_combat_pool(self.target, "Composure + Resolve")
        self.assertEqual(result["pool"], 6)

    def test_mortal_and_ghoul_physical_resistance_impairment_has_no_hunger_dice(self):
        for splat in ("mortal", "ghoul"):
            with self.subTest(splat=splat):
                self.target.splat = splat
                self.target.hunger = 5
                self.target.set_trait("Dexterity", 3)
                self.target.set_trait("Athletics", 2)
                self.target.set_damage("health", superficial=self.target.health_max)
                result = self.defense("Dexterity + Athletics")
                self.assertEqual((result["dice_pool"], len(result["roll_result"].hunger_dice)), (3, 0))

    def test_fleetness_blink_keeps_other_bonuses_and_pool_floor_behavior(self):
        self.caster.set_trait("Celerity", 3)
        self.caster.learn_power("Fleetness")
        self.caster.learn_power("Blink")
        self.caster.set_trait("Dexterity", 3)
        self.caster.set_trait("Athletics", 2)
        with patch("random.randint", return_value=8):
            discipline_utils.activate_discipline_power(self.caster, "Celerity", "Fleetness")
        self.caster.set_damage("health", superficial=self.caster.health_max)
        with patch("random.randint", return_value=8):
            result = discipline_roller.roll_discipline_power(self.caster, "Blink")
        self.assertEqual(result["dice_pool"], 6)  # 5 + Fleetness 3 - Health 2.
        self.assertEqual(result["dice_pool_breakdown"]["Fleetness"], 3)
        self.caster.db.active_effects = []
        self.caster.set_trait("Athletics", 0)
        self.caster.set_trait("Dexterity", 1)
        self.degenerate(self.caster)
        with patch("random.randint", return_value=8):
            result = discipline_roller.roll_discipline_power(self.caster, "Blink")
        self.assertEqual(result["dice_pool"], 1)
