"""
Comprehensive Tests for V5 Dice System

Test coverage for:
- DiceRollerTestCase: Core dice mechanics (dice_roller.py)
- RollResultTestCase: Result parsing and interpretation (roll_result.py)
- DisciplineRollerTestCase: Discipline power rolling (discipline_roller.py)
- RouseCheckerTestCase: Rouse checks and Hunger management (rouse_checker.py)
"""

import unittest
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from dice import dice_roller
from dice.dice_roller import (
    apply_willpower_reroll,
    get_success_threshold,
    roll_chance_die,
    roll_contested,
    roll_rouse_check,
    roll_v5_pool,
    validate_pool_params,
)
from dice.discipline_roller import (
    calculate_pool_from_traits,
    can_use_power,
    get_blood_potency_bonus,
    get_character_discipline_powers,
    parse_dice_pool,
    roll_discipline_power,
)
from dice.roll_result import RollResult
from dice.rouse_checker import (
    can_reroll_rouse,
    format_hunger_display,
    get_hunger_level,
    perform_rouse_check,
    set_hunger_level,
)


class DiceRollerTestCase(EvenniaTest):
    """Test core dice rolling mechanics."""

    def test_basic_roll(self):
        """Test basic dice pool rolling works."""
        result = roll_v5_pool(pool_size=5, hunger=0, difficulty=0)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, RollResult)
        self.assertEqual(len(result.regular_dice), 5)
        self.assertEqual(len(result.hunger_dice), 0)

        # Verify all dice are in valid range
        for die in result.regular_dice:
            self.assertGreaterEqual(die, 1)
            self.assertLessEqual(die, 10)

    def test_success_counting(self):
        """Test that 6-9 = 1 success each and 1-5 = none."""
        result = RollResult(
            regular_dice=[6, 7, 8, 9],
            hunger_dice=[],
            difficulty=0
        )

        self.assertEqual(result.total_successes, 4)

        # Test failures (1-5)
        result = RollResult(
            regular_dice=[1, 2, 3, 4, 5],  # 0 successes
            hunger_dice=[],
            difficulty=0
        )

        self.assertEqual(result.total_successes, 0)

    def test_hunger_dice_substitution(self):
        """Test that Hunger dice replace regular dice."""
        result = roll_v5_pool(pool_size=7, hunger=3, difficulty=0)

        self.assertEqual(len(result.regular_dice), 4)  # 7 - 3
        self.assertEqual(len(result.hunger_dice), 3)
        self.assertEqual(len(result.regular_dice) + len(result.hunger_dice), 7)

    def test_critical_detection(self):
        """Test that pair of 10s = critical (4 successes)."""
        result = RollResult(
            regular_dice=[10, 10, 5],  # Two 10s = critical
            hunger_dice=[],
            difficulty=0
        )

        self.assertTrue(result.is_critical)
        self.assertEqual(result.total_successes, 4)  # 2+2 from the tens

    def test_messy_critical(self):
        """Test that Hunger 10 in critical = messy."""
        result = RollResult(
            regular_dice=[10, 5],
            hunger_dice=[10, 3],  # Hunger 10 + regular 10 = messy critical
            difficulty=0
        )

        self.assertTrue(result.is_critical)
        self.assertTrue(result.is_messy_critical)
        self.assertEqual(result.result_type, 'messy_critical')

    def test_bestial_failure(self):
        """Test that only Hunger 1s on failure = bestial."""
        result = RollResult(
            regular_dice=[3, 4, 5],  # No 1s on regular dice
            hunger_dice=[1, 2],  # 1 on Hunger die
            difficulty=5  # Failure (0 successes < 5)
        )

        self.assertFalse(result.is_success)
        self.assertTrue(result.is_bestial_failure)
        self.assertEqual(result.result_type, 'bestial_failure')

    def test_chance_die(self):
        """Test that pool 0 or negative becomes 1 die."""
        result = roll_chance_die()

        self.assertIsNotNone(result)
        self.assertEqual(len(result.regular_dice), 1)
        self.assertEqual(len(result.hunger_dice), 0)

        # Verify die is in valid range
        self.assertGreaterEqual(result.regular_dice[0], 1)
        self.assertLessEqual(result.regular_dice[0], 10)

    def test_pool_validation(self):
        """Test that invalid parameters raise ValueError."""
        # Pool size < 1
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=0, hunger=0)

        # Hunger < 0
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=5, hunger=-1)

        # Hunger > 5
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=10, hunger=6)

        # Difficulty < 0
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=5, hunger=0, difficulty=-1)

    # F-016 family (Hunger dice), fixed in PR 5: roll_v5_pool raises when
    # Hunger exceeds the pool. QR p.4: Hunger dice replace regular dice
    # "without exceeding the total dice pool", so pool 3 at Hunger 5 rolls
    # three Hunger dice.
    @unittest.expectedFailure
    def test_hunger_above_pool_rolls_all_hunger_dice(self):
        result = roll_v5_pool(pool_size=3, hunger=5)
        self.assertEqual(len(result.regular_dice), 0)
        self.assertEqual(len(result.hunger_dice), 3)

    def test_willpower_reroll(self):
        """Re-roll up to 3 regular dice; Hunger dice are never re-rolled (QR p.3)."""
        # Create result with known failed dice
        original = RollResult(
            regular_dice=[1, 2, 3, 4, 5],  # 5 failed dice
            hunger_dice=[6],
            difficulty=0
        )

        # Reroll 3 failed dice
        new_result, rerolled_indices = apply_willpower_reroll(original, num_rerolls=3)

        self.assertEqual(len(rerolled_indices), 3)  # Should reroll 3 dice
        self.assertEqual(len(new_result.regular_dice), 5)  # Same number of regular dice
        self.assertEqual(new_result.hunger_dice, original.hunger_dice)  # Hunger dice unchanged

    def test_willpower_reroll_validation(self):
        """Test that invalid reroll counts raise ValueError."""
        original = RollResult(regular_dice=[1, 2, 3], hunger_dice=[], difficulty=0)

        # Too few rerolls
        with self.assertRaises(ValueError):
            apply_willpower_reroll(original, num_rerolls=0)

        # Too many rerolls
        with self.assertRaises(ValueError):
            apply_willpower_reroll(original, num_rerolls=4)

    def test_contested_roll(self):
        """The side with more successes wins by the difference."""
        # Roller 1: five dice, three successes. Roller 2: three dice, one success.
        dice = [8, 7, 6, 2, 3, 9, 1, 4]
        with patch('dice.dice_roller.randint', side_effect=dice):
            result = roll_contested(pool1=5, hunger1=0, pool2=3, hunger2=0)

        self.assertEqual(result['roller1_result'].total_successes, 3)
        self.assertEqual(result['roller2_result'].total_successes, 1)
        self.assertEqual(result['winner'], 1)
        self.assertEqual(result['margin'], 2)
        self.assertFalse(result['is_tie'])

    def test_rouse_check(self):
        """Test Rouse check returns proper structure."""
        result = roll_rouse_check()

        self.assertIn('roll', result)
        self.assertIn('success', result)
        self.assertIn('hunger_change', result)

        # Roll should be 1-10
        self.assertGreaterEqual(result['roll'], 1)
        self.assertLessEqual(result['roll'], 10)

        # Success should be True if 6+, False otherwise
        if result['roll'] >= 6:
            self.assertTrue(result['success'])
            self.assertEqual(result['hunger_change'], 0)
        else:
            self.assertFalse(result['success'])
            self.assertEqual(result['hunger_change'], 1)

    def test_validate_pool_params(self):
        """Test pool parameter validation and normalization."""
        # Normal case
        pool, hunger = validate_pool_params(5, 2)
        self.assertEqual(pool, 5)
        self.assertEqual(hunger, 2)

        # Negative pool becomes 0
        pool, hunger = validate_pool_params(-2, 1)
        self.assertEqual(pool, 0)

        # Negative hunger becomes 0
        pool, hunger = validate_pool_params(5, -1)
        self.assertEqual(hunger, 0)

        # Hunger > 5 clamped to 5
        pool, hunger = validate_pool_params(10, 7)
        self.assertEqual(hunger, 5)

        # Hunger > pool clamped to pool
        pool, hunger = validate_pool_params(3, 5)
        self.assertEqual(hunger, 3)

    def test_get_success_threshold(self):
        """Test success counting for individual die values."""
        # 1-5: 0 successes
        for value in range(1, 6):
            self.assertEqual(get_success_threshold(value), 0)

        # 6-9: 1 success
        for value in range(6, 10):
            self.assertEqual(get_success_threshold(value), 1)


class RollResultTestCase(EvenniaTest):
    """Test result parsing and interpretation."""

    def test_result_creation(self):
        """Test RollResult instantiates correctly."""
        result = RollResult(
            regular_dice=[6, 7, 8],
            hunger_dice=[9, 10],
            difficulty=3
        )

        self.assertEqual(result.regular_dice, [6, 7, 8])
        self.assertEqual(result.hunger_dice, [9, 10])
        self.assertEqual(result.difficulty, 3)
        self.assertEqual(result.all_dice, [6, 7, 8, 9, 10])

    def test_success_calculation(self):
        """Test total_successes computed correctly."""
        # Three 6-9s are 3 successes. The two 10s (one regular, one Hunger)
        # form a critical pair worth 4. Total 7.
        result = RollResult(
            regular_dice=[6, 7, 10],
            hunger_dice=[8, 10],
            difficulty=0
        )

        self.assertEqual(result.total_successes, 7)

    def test_critical_pairs(self):
        """Test detection of pairs of 10s."""
        # Two 10s = critical
        result = RollResult(
            regular_dice=[10, 10],
            hunger_dice=[],
            difficulty=0
        )
        self.assertTrue(result.is_critical)

        # One 10 = not critical
        result = RollResult(
            regular_dice=[10, 9],
            hunger_dice=[],
            difficulty=0
        )
        self.assertFalse(result.is_critical)

        # Three 10s = critical (multiple pairs)
        result = RollResult(
            regular_dice=[10, 10, 10],
            hunger_dice=[],
            difficulty=0
        )
        self.assertTrue(result.is_critical)

    def test_messy_critical_detection(self):
        """Test Hunger 10 in critical = messy."""
        # Regular 10 + Hunger 10 = messy critical
        result = RollResult(
            regular_dice=[10],
            hunger_dice=[10],
            difficulty=0
        )
        self.assertTrue(result.is_critical)
        self.assertTrue(result.is_messy_critical)

        # Two regular 10s = clean critical
        result = RollResult(
            regular_dice=[10, 10],
            hunger_dice=[],
            difficulty=0
        )
        self.assertTrue(result.is_critical)
        self.assertFalse(result.is_messy_critical)

    def test_bestial_failure_detection(self):
        """A failed roll with a Hunger 1 is bestial; a successful one is not (QR p.4)."""
        # Failure with Hunger 1, no regular 1s = bestial
        result = RollResult(
            regular_dice=[3, 4, 5],
            hunger_dice=[1, 2],
            difficulty=5
        )
        self.assertFalse(result.is_success)
        self.assertTrue(result.is_bestial_failure)

        # Success with Hunger 1s = NOT bestial
        result = RollResult(
            regular_dice=[10, 10],
            hunger_dice=[1, 1],
            difficulty=3
        )
        self.assertTrue(result.is_success)
        self.assertFalse(result.is_bestial_failure)

    def test_result_type_classification(self):
        """Test result_type properly classifies outcomes."""
        # Success
        result = RollResult(
            regular_dice=[6, 7, 8],
            hunger_dice=[],
            difficulty=2
        )
        self.assertEqual(result.result_type, 'success')

        # Failure
        result = RollResult(
            regular_dice=[1, 2, 3],
            hunger_dice=[],
            difficulty=2
        )
        self.assertEqual(result.result_type, 'failure')

        # Critical success
        result = RollResult(
            regular_dice=[10, 10],
            hunger_dice=[],
            difficulty=0
        )
        self.assertEqual(result.result_type, 'critical_success')

        # Messy critical
        result = RollResult(
            regular_dice=[10],
            hunger_dice=[10],
            difficulty=0
        )
        self.assertEqual(result.result_type, 'messy_critical')

        # Bestial failure
        result = RollResult(
            regular_dice=[3, 4],
            hunger_dice=[1, 2],
            difficulty=5
        )
        self.assertEqual(result.result_type, 'bestial_failure')

    def test_difficulty_pass_fail(self):
        """Test comparing successes to difficulty."""
        # Pass with exact successes
        result = RollResult(
            regular_dice=[6, 7, 8],  # 3 successes
            hunger_dice=[],
            difficulty=3
        )
        self.assertTrue(result.is_success)
        self.assertEqual(result.margin, 0)

        # Pass with margin
        result = RollResult(
            regular_dice=[10, 10],  # 4 successes
            hunger_dice=[],
            difficulty=2
        )
        self.assertTrue(result.is_success)
        self.assertEqual(result.margin, 2)

        # Fail
        result = RollResult(
            regular_dice=[6, 7],  # 2 successes
            hunger_dice=[],
            difficulty=5
        )
        self.assertFalse(result.is_success)
        self.assertEqual(result.margin, -3)

    def test_difficulty_zero(self):
        """Test difficulty 0 means any success wins."""
        # Any success wins
        result = RollResult(
            regular_dice=[6],  # 1 success
            hunger_dice=[],
            difficulty=0
        )
        self.assertTrue(result.is_success)

        # Zero successes fails
        result = RollResult(
            regular_dice=[1, 2, 3],
            hunger_dice=[],
            difficulty=0
        )
        self.assertFalse(result.is_success)


class V5CountingRulesTestCase(EvenniaTest):
    """V5 core rules for successes and bestial failures, on fixed dice.

    Each 6-9 or 10 is one success; each pair of 10s adds 2 more (a critical).
    A failed roll with any Hunger 1 is a bestial failure, whatever the regular
    dice show.
    """

    # F-016, fixed in PR 5: RollResult counts every 10 as 2 successes.
    @unittest.expectedFailure
    def test_lone_ten_is_one_success(self):
        result = RollResult(regular_dice=[10], hunger_dice=[], difficulty=0)
        self.assertEqual(result.total_successes, 1)
        self.assertFalse(result.is_critical)

    # F-016, fixed in PR 5: RollResult counts every 10 as 2 successes.
    @unittest.expectedFailure
    def test_three_tens_are_five_successes(self):
        result = RollResult(regular_dice=[10, 10, 10], hunger_dice=[], difficulty=0)
        self.assertEqual(result.total_successes, 5)

    # F-016, fixed in PR 5: RollResult suppresses the bestial failure when a
    # regular die also shows a 1.
    @unittest.expectedFailure
    def test_bestial_failure_with_regular_one(self):
        result = RollResult(regular_dice=[1, 3, 5], hunger_dice=[1, 2], difficulty=5)
        self.assertFalse(result.is_success)
        self.assertTrue(result.is_bestial_failure)

    def test_failure_without_hunger_one_is_not_bestial(self):
        result = RollResult(regular_dice=[2, 3], hunger_dice=[4, 5], difficulty=5)
        self.assertFalse(result.is_success)
        self.assertFalse(result.is_bestial_failure)


class DisciplineRollerTestCase(EvenniaTest):
    """Test discipline power rolling on a real character.

    Traits are written through the Character accessors and powers come from
    world.v5_data.DISCIPLINE_POWERS.
    """

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        self.char1.hunger = 1
        self.char1.set_trait("Strength", 4)
        self.char1.set_trait("Resolve", 3)
        self.char1.set_trait("Brawl", 3)
        self.char1.set_trait("Auspex", 2)
        self.char1.set_trait("Blood Sorcery", 2)
        self.char1.blood_potency = 2

        # Premonition: Auspex 2, free, "Resolve + Auspex".
        # Extinguish Vitae: Blood Sorcery 2, 1 Rouse, "Intelligence + Blood Sorcery".
        self.char1.learn_power("Premonition")
        self.char1.learn_power("Extinguish Vitae")

    def test_parse_dice_pool(self):
        """Test parsing 'Strength + Brawl' into ['Strength', 'Brawl']."""
        traits = parse_dice_pool("Strength + Brawl")
        self.assertEqual(traits, ['Strength', 'Brawl'])

        traits = parse_dice_pool("Resolve + Auspex")
        self.assertEqual(traits, ['Resolve', 'Auspex'])

        # Test with spaces
        traits = parse_dice_pool("  Strength  +  Brawl  ")
        self.assertEqual(traits, ['Strength', 'Brawl'])

    # F-095, fixed in PR 5: parse_dice_pool drops everything after the first
    # '/', so an alternative-attribute pool loses its skill.
    @unittest.expectedFailure
    def test_parse_dice_pool_alternative(self):
        """'A / B + C' takes the first option of the '/' group plus C."""
        traits = parse_dice_pool("Charisma / Manipulation + Intimidation")
        self.assertEqual(traits, ['Charisma', 'Intimidation'])

    def test_calculate_pool_from_traits(self):
        """Test summing character trait values."""
        total, breakdown = calculate_pool_from_traits(
            self.char1,
            ['Strength', 'Brawl']
        )

        self.assertEqual(total, 7)  # 4 + 3
        self.assertEqual(breakdown, {'Strength': 4, 'Brawl': 3})

    def test_blood_potency_bonus(self):
        """Test BP adds correct bonus dice."""
        for bp, bonus in ((1, 0), (2, 1), (4, 2), (6, 3), (8, 4), (10, 5)):
            self.char1.blood_potency = bp
            self.assertEqual(get_blood_potency_bonus(self.char1, "Auspex"), bonus, f"BP {bp}")

    def test_roll_discipline_power(self):
        """Test full integration with character."""
        result = roll_discipline_power(
            self.char1,
            "Premonition",
            difficulty=2,
            with_rouse=False  # Skip Rouse for deterministic test
        )

        self.assertIn('power', result)
        self.assertIn('dice_pool', result)
        self.assertIn('dice_pool_breakdown', result)
        self.assertIn('blood_potency_bonus', result)
        self.assertIn('roll_result', result)
        self.assertIn('success', result)

        self.assertEqual(result['power']['name'], "Premonition")
        self.assertIsInstance(result['roll_result'], RollResult)

        # Verify pool calculation: Resolve (3) + Auspex (2) + BP bonus (1) = 6
        self.assertEqual(result['dice_pool'], 6)
        self.assertEqual(result['blood_potency_bonus'], 1)

    def test_power_not_found(self):
        """Test raises ValueError for invalid power."""
        with self.assertRaises(ValueError) as context:
            roll_discipline_power(self.char1, "Nonexistent Power")

        self.assertIn("not found", str(context.exception).lower())

    def test_character_doesnt_know_power(self):
        """A real power the character hasn't learned is refused."""
        can_use, reason = can_use_power(self.char1, "Sense the Unseen")
        self.assertFalse(can_use)
        self.assertIn("don't know", reason.lower())

    def test_rouse_check_integration(self):
        """Test discipline roll includes Rouse check."""
        initial_hunger = self.char1.hunger

        # Mock rouse check to always fail
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 3, 'success': False, 'hunger_change': 1}

            result = roll_discipline_power(
                self.char1,
                "Extinguish Vitae",  # Has rouse cost
                difficulty=2,
                with_rouse=True
            )

            self.assertIsNotNone(result['rouse_result'])
            self.assertFalse(result['rouse_result']['success'])
            self.assertEqual(result['hunger_after'], initial_hunger + 1)

    def test_can_use_power(self):
        """Test checking if character can use a power."""
        # Character can use known power
        can_use, reason = can_use_power(self.char1, "Premonition")
        self.assertTrue(can_use)

        # Character doesn't know power
        can_use, reason = can_use_power(self.char1, "Heightened Senses")
        self.assertFalse(can_use)

    def test_get_character_discipline_powers(self):
        """Test retrieving character's discipline powers."""
        powers = get_character_discipline_powers(self.char1)

        self.assertEqual(len(powers), 2)
        power_names = [p['name'] for p in powers]
        self.assertIn("Premonition", power_names)
        self.assertIn("Extinguish Vitae", power_names)

        # Filter by discipline
        auspex_powers = get_character_discipline_powers(self.char1, "Auspex")
        self.assertEqual(len(auspex_powers), 1)
        self.assertEqual(auspex_powers[0]['name'], "Premonition")


class RouseCheckerTestCase(EvenniaTest):
    """Test Rouse checks and Hunger management."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        # Set initial Hunger
        self.char1.hunger = 2

    def test_rouse_check_success(self):
        """Test roll 6+ = no Hunger gain."""
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 8, 'success': True, 'hunger_change': 0}

            result = perform_rouse_check(self.char1, "Test", power_level=1)

            self.assertTrue(result['success'])
            self.assertEqual(result['hunger_change'], 0)
            self.assertEqual(result['hunger_after'], 2)  # No change
            self.assertEqual(self.char1.hunger, 2)

    def test_rouse_check_failure(self):
        """Test roll 1-5 = +1 Hunger."""
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 3, 'success': False, 'hunger_change': 1}

            result = perform_rouse_check(self.char1, "Test", power_level=1)

            self.assertFalse(result['success'])
            self.assertEqual(result['hunger_change'], 1)
            self.assertEqual(result['hunger_after'], 3)  # 2 + 1
            self.assertEqual(self.char1.hunger, 3)

    def test_hunger_at_max(self):
        """Stored Hunger never exceeds 5.

        This checks the storage bound only. It is not the rule for a Rouse at
        Hunger 5: QR p.4 forbids Rousing at Hunger 5 unless forced, and a
        failed forced Rouse provokes frenzy (p.13). PR 5 adds that refusal.
        """
        self.char1.hunger = 5

        result = perform_rouse_check(self.char1, "Test", power_level=1)

        self.assertEqual(result['hunger_before'], 5)
        self.assertEqual(result['hunger_after'], 5)
        self.assertEqual(result['hunger_change'], 0)
        self.assertEqual(self.char1.hunger, 5)

    def test_blood_potency_reroll_eligibility(self):
        """Test BP allows reroll for low-level powers."""
        self.char1.blood_potency = 3

        # BP 3 can reroll Level 1-2 powers
        self.assertTrue(can_reroll_rouse(self.char1, power_level=1))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=2))
        self.assertFalse(can_reroll_rouse(self.char1, power_level=3))

        # BP 6 can reroll Level 1-3 powers
        self.char1.blood_potency = 6

        self.assertTrue(can_reroll_rouse(self.char1, power_level=1))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=2))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=3))
        self.assertFalse(can_reroll_rouse(self.char1, power_level=4))

    def test_blood_potency_reroll_occurs(self):
        """Test failed roll gets rerolled automatically."""
        self.char1.blood_potency = 2  # Can reroll Level 1

        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            # First call fails, second succeeds
            mock_rouse.side_effect = [
                {'roll': 3, 'success': False, 'hunger_change': 1},  # Initial fail
                {'roll': 7, 'success': True, 'hunger_change': 0}    # Reroll success
            ]

            result = perform_rouse_check(self.char1, "Test", power_level=1)

            self.assertTrue(result['reroll_eligible'])
            self.assertTrue(result['reroll_used'])
            self.assertTrue(result['success'])  # Reroll succeeded
            self.assertEqual(result['roll'], 7)  # Shows reroll value
            self.assertEqual(self.char1.hunger, 2)  # No hunger gain

    def test_hunger_persistence(self):
        """Test Character.hunger is updated."""
        initial_hunger = self.char1.hunger

        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 2, 'success': False, 'hunger_change': 1}

            result = perform_rouse_check(self.char1, "Test")

            self.assertEqual(self.char1.hunger, initial_hunger + 1)
            self.assertEqual(result['hunger_after'], initial_hunger + 1)

    def test_get_hunger_level(self):
        """Test getting character's Hunger level."""
        self.char1.hunger = 3
        self.assertEqual(get_hunger_level(self.char1), 3)

        # Test clamping
        self.char1.hunger = 10
        self.assertEqual(get_hunger_level(self.char1), 5)  # Max 5

        self.char1.hunger = -1
        self.assertEqual(get_hunger_level(self.char1), 0)  # Min 0

    def test_set_hunger_level(self):
        """Test setting character's Hunger level."""
        result = set_hunger_level(self.char1, 4)
        self.assertEqual(result, 4)
        self.assertEqual(self.char1.hunger, 4)

        # Test clamping to max
        result = set_hunger_level(self.char1, 10)
        self.assertEqual(result, 5)
        self.assertEqual(self.char1.hunger, 5)

        # Test clamping to min
        result = set_hunger_level(self.char1, -2)
        self.assertEqual(result, 0)
        self.assertEqual(self.char1.hunger, 0)

    def test_format_hunger_display(self):
        """Test formatting Hunger for display."""
        self.char1.hunger = 3
        display = format_hunger_display(self.char1)

        self.assertIsInstance(display, str)
        self.assertIn("3/5", display)
        self.assertIn("■", display)  # Filled boxes
        self.assertIn("□", display)  # Empty boxes

    # Highest power level whose Rouse check BP lets you re-roll (V5 Blood
    # Potency table: "Level N and below"). Same in the 2018 printing (QR 2.0
    # p.14) and the errata'd table (Companion p.63, Players Guide p.248).
    REROLL_MAX_LEVEL = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}

    def assert_reroll_levels(self, bps):
        for bp in bps:
            self.char1.blood_potency = bp
            max_level = self.REROLL_MAX_LEVEL[bp]
            for level in range(1, 6):
                self.assertEqual(
                    can_reroll_rouse(self.char1, level), level <= max_level, f"BP {bp}, power level {level}"
                )

    def test_blood_potency_reroll_levels(self):
        self.assert_reroll_levels([0, 1, 2, 3, 4, 6, 8, 10])

    # F-022: can_reroll_rouse used to group BP 3-5, 6-7 and 8-9.
    def test_blood_potency_reroll_levels_odd_bp(self):
        self.assert_reroll_levels([5, 7, 9])


class PoolCapTestCase(EvenniaCommandTest):
    """Roll size and difficulty are capped at every entry point."""

    def _call_roll(self, args):
        """Run `roll <args>` and return (output, mock of roll_v5_pool)."""
        from dice.commands import CmdRoll

        real_roll = dice_roller.roll_v5_pool
        with patch("dice.commands.dice_roller.roll_v5_pool", side_effect=real_roll) as mock_roll:
            output = self.call(CmdRoll(), args)
        return output, mock_roll

    def _assert_roll_rejected(self, args, message):
        from dice.commands import CmdRoll

        with patch(
            "dice.commands.dice_roller.roll_v5_pool",
            side_effect=AssertionError("roll_v5_pool should not be called"),
        ):
            output = self.call(CmdRoll(), args)
        self.assertIn(message, output)

    def test_pool_cap(self):
        self._assert_roll_rejected("1000", f"cannot exceed {dice_roller.MAX_POOL}")
        with self.assertRaises(ValueError):
            roll_v5_pool(1000, 0)

    def test_pool_cap_boundary(self):
        self._assert_roll_rejected(str(dice_roller.MAX_POOL + 1), f"cannot exceed {dice_roller.MAX_POOL}")
        _, mock_roll = self._call_roll(str(dice_roller.MAX_POOL))
        mock_roll.assert_called_once_with(dice_roller.MAX_POOL, 0, 0)

        self.assertEqual(len(roll_v5_pool(dice_roller.MAX_POOL, 0).all_dice), dice_roller.MAX_POOL)
        with self.assertRaises(ValueError):
            roll_v5_pool(dice_roller.MAX_POOL + 1, 0)

    def test_difficulty_range(self):
        self._assert_roll_rejected(f"5 vs {dice_roller.MAX_DIFFICULTY + 1}", "Difficulty must be between")
        self._assert_roll_rejected("5 vs -1", "Difficulty must be between")
        _, mock_roll = self._call_roll(f"5 vs {dice_roller.MAX_DIFFICULTY}")
        mock_roll.assert_called_once_with(5, 0, dice_roller.MAX_DIFFICULTY)

        roll_v5_pool(5, 0, dice_roller.MAX_DIFFICULTY)
        with self.assertRaises(ValueError):
            roll_v5_pool(5, 0, dice_roller.MAX_DIFFICULTY + 1)
        with self.assertRaises(ValueError):
            roll_v5_pool(5, 0, -1)

    def test_v5_dice_roll_pool_cap(self):
        from world.v5_dice import roll_pool

        # Accepted at the limits.
        def dice_count(result):
            return len(result.normal_dice) + len(result.hunger_dice)

        self.assertEqual(dice_count(roll_pool(dice_roller.MAX_POOL)), dice_roller.MAX_POOL)
        self.assertEqual(dice_count(roll_pool(dice_roller.MAX_POOL - 3, willpower=True)), dice_roller.MAX_POOL)
        roll_pool(5, difficulty=dice_roller.MAX_DIFFICULTY)
        roll_pool(5, difficulty=dice_roller.MIN_DIFFICULTY)

        # Rejected past them. The Willpower bonus counts toward the cap.
        with self.assertRaises(ValueError):
            roll_pool(1000)
        with self.assertRaises(ValueError):
            roll_pool(dice_roller.MAX_POOL + 1)
        with self.assertRaises(ValueError):
            roll_pool(dice_roller.MAX_POOL - 2, willpower=True)
        with self.assertRaises(ValueError):
            roll_pool(5, difficulty=dice_roller.MAX_DIFFICULTY + 1)
        with self.assertRaises(ValueError):
            roll_pool(5, difficulty=-1)
