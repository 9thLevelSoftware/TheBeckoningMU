"""
Comprehensive Tests for V5 Dice System

Test coverage for:
- DiceRollerTestCase: Core dice mechanics (dice_roller.py)
- RollResultTestCase: Result parsing and interpretation (roll_result.py)
- DisciplineRollerTestCase: Discipline power rolling (discipline_roller.py)
- RouseCheckerTestCase: Rouse checks and Hunger management (rouse_checker.py)
"""

from unittest.mock import patch, MagicMock
from evennia.utils.test_resources import EvenniaTest
from dice import dice_roller, roll_result, discipline_roller, rouse_checker
from dice.dice_roller import (
    roll_v5_pool, roll_chance_die, roll_rouse_check, roll_contested,
    apply_willpower_reroll, validate_pool_params, get_success_threshold
)
from dice.roll_result import RollResult
from dice.discipline_roller import (
    roll_discipline_power, parse_dice_pool, calculate_pool_from_traits,
    get_blood_potency_bonus, can_use_power, get_character_discipline_powers
)
from dice.rouse_checker import (
    perform_rouse_check, can_reroll_rouse, get_hunger_level,
    set_hunger_level, format_hunger_display
)
from traits.models import (
    TraitCategory, Trait, DisciplinePower, CharacterTrait, CharacterPower
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
        """Test that 6-9 = 1 success, 10 = 2 successes."""
        # Create result with known dice values
        result = RollResult(
            regular_dice=[6, 7, 8, 9, 10],  # 1+1+1+1+2 = 6 successes
            hunger_dice=[],
            difficulty=0
        )

        self.assertEqual(result.total_successes, 6)

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

        # Test NOT bestial if regular die also shows 1
        result = RollResult(
            regular_dice=[1, 3, 5],  # Regular 1 present
            hunger_dice=[1, 2],  # Hunger 1 present
            difficulty=5  # Failure
        )

        self.assertFalse(result.is_success)
        self.assertFalse(result.is_bestial_failure)  # NOT bestial because regular 1 exists
        self.assertEqual(result.result_type, 'failure')

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

        # Hunger > pool_size
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=3, hunger=5)

        # Difficulty < 0
        with self.assertRaises(ValueError):
            roll_v5_pool(pool_size=5, hunger=0, difficulty=-1)

    def test_willpower_reroll(self):
        """Test reroll up to 3 failed regular dice."""
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

        # Test that rerolling with no failed dice works
        original = RollResult(
            regular_dice=[6, 7, 8, 9, 10],  # All successes
            hunger_dice=[],
            difficulty=0
        )

        new_result, rerolled_indices = apply_willpower_reroll(original, num_rerolls=3)
        self.assertEqual(len(rerolled_indices), 0)  # No dice to reroll
        self.assertEqual(new_result.regular_dice, original.regular_dice)  # Unchanged

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
        """Test two pools rolled, highest wins."""
        result = roll_contested(pool1=5, hunger1=2, pool2=7, hunger2=1)

        self.assertIn('roller1_result', result)
        self.assertIn('roller2_result', result)
        self.assertIn('winner', result)
        self.assertIn('margin', result)
        self.assertIn('is_tie', result)

        self.assertIsInstance(result['roller1_result'], RollResult)
        self.assertIsInstance(result['roller2_result'], RollResult)

        # Winner should be 1, 2, or None (tie)
        self.assertIn(result['winner'], [1, 2, None])

        # Margin should be non-negative
        self.assertGreaterEqual(result['margin'], 0)

        # is_tie should match winner being None
        self.assertEqual(result['is_tie'], result['winner'] is None)

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

        # 10: 2 successes
        self.assertEqual(get_success_threshold(10), 2)


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
        # 6-9 = 1 success each, 10 = 2 successes
        result = RollResult(
            regular_dice=[6, 7, 10],  # 1+1+2 = 4
            hunger_dice=[8, 10],  # 1+2 = 3
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
        """Test only Hunger 1s on failure = bestial."""
        # Failure with Hunger 1, no regular 1s = bestial
        result = RollResult(
            regular_dice=[3, 4, 5],
            hunger_dice=[1, 2],
            difficulty=5
        )
        self.assertFalse(result.is_success)
        self.assertTrue(result.is_bestial_failure)

        # Failure with Hunger 1 AND regular 1 = NOT bestial
        result = RollResult(
            regular_dice=[1, 3, 5],
            hunger_dice=[1, 2],
            difficulty=5
        )
        self.assertFalse(result.is_success)
        self.assertFalse(result.is_bestial_failure)

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

    def test_format_result(self):
        """Test result formatting produces string output."""
        result = RollResult(
            regular_dice=[6, 7, 8],
            hunger_dice=[9, 10],
            difficulty=3
        )

        formatted = result.format_result(show_details=True)
        self.assertIsInstance(formatted, str)
        self.assertGreater(len(formatted), 0)

        # Test without details
        formatted = result.format_result(show_details=False)
        self.assertIsInstance(formatted, str)
        self.assertGreater(len(formatted), 0)


class DisciplineRollerTestCase(EvenniaTest):
    """Test discipline power rolling."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        # Create trait categories
        self.attr_category = TraitCategory.objects.create(
            name="Attributes",
            code="attributes",
            sort_order=1
        )
        self.skill_category = TraitCategory.objects.create(
            name="Skills",
            code="skills",
            sort_order=2
        )
        self.discipline_category = TraitCategory.objects.create(
            name="Disciplines",
            code="disciplines",
            sort_order=3
        )

        # Create attributes
        self.strength = Trait.objects.create(
            name="Strength",
            category=self.attr_category,
            max_value=5
        )
        self.resolve = Trait.objects.create(
            name="Resolve",
            category=self.attr_category,
            max_value=5
        )

        # Create skills
        self.brawl = Trait.objects.create(
            name="Brawl",
            category=self.skill_category,
            max_value=5
        )

        # Create disciplines
        self.auspex = Trait.objects.create(
            name="Auspex",
            category=self.discipline_category,
            max_value=5
        )
        self.blood_sorcery = Trait.objects.create(
            name="Blood Sorcery",
            category=self.discipline_category,
            max_value=5
        )

        # Create Blood Potency
        self.blood_potency = Trait.objects.create(
            name="Blood Potency",
            category=self.attr_category,
            max_value=10
        )

        # Create discipline powers
        self.heightened_senses = DisciplinePower.objects.create(
            name="Heightened Senses",
            discipline=self.auspex,
            level=1,
            description="Sharpen your senses to supernatural levels.",
            dice_pool="Resolve + Auspex",
            cost="Free",
            duration="One scene"
        )

        self.corrosive_vitae = DisciplinePower.objects.create(
            name="Corrosive Vitae",
            discipline=self.blood_sorcery,
            level=2,
            description="Your blood becomes acidic.",
            dice_pool="Strength + Blood Sorcery",
            cost="One Rouse check",
            duration="One scene"
        )

        # Set up test character with traits
        self.char1.db.hunger = 1

        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.strength,
            rating=4
        )
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.resolve,
            rating=3
        )
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.brawl,
            rating=3
        )
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.auspex,
            rating=2
        )
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.blood_sorcery,
            rating=2
        )
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.blood_potency,
            rating=2
        )

        # Give character the powers
        CharacterPower.objects.create(
            character=self.char1,
            power=self.heightened_senses
        )
        CharacterPower.objects.create(
            character=self.char1,
            power=self.corrosive_vitae
        )

    def test_parse_dice_pool(self):
        """Test parsing 'Strength + Brawl' into ['Strength', 'Brawl']."""
        traits = parse_dice_pool("Strength + Brawl")
        self.assertEqual(traits, ['Strength', 'Brawl'])

        traits = parse_dice_pool("Resolve + Auspex")
        self.assertEqual(traits, ['Resolve', 'Auspex'])

        # Test with spaces
        traits = parse_dice_pool("  Strength  +  Brawl  ")
        self.assertEqual(traits, ['Strength', 'Brawl'])

        # Test with alternative (/)
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
        # BP 0-1: +0
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=1)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 0)

        # BP 2-3: +1
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=2)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 1)

        # BP 4-5: +2
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=4)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 2)

        # BP 6-7: +3
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=6)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 3)

        # BP 8-9: +4
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=8)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 4)

        # BP 10: +5
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=10)
        bonus = get_blood_potency_bonus(self.char1, "Auspex")
        self.assertEqual(bonus, 5)

    def test_roll_discipline_power(self):
        """Test full integration with character."""
        result = roll_discipline_power(
            self.char1,
            "Heightened Senses",
            difficulty=2,
            with_rouse=False  # Skip Rouse for deterministic test
        )

        self.assertIn('power', result)
        self.assertIn('dice_pool', result)
        self.assertIn('dice_pool_breakdown', result)
        self.assertIn('blood_potency_bonus', result)
        self.assertIn('roll_result', result)
        self.assertIn('success', result)

        self.assertEqual(result['power'].name, "Heightened Senses")
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
        """Test raises ValueError if character doesn't know power."""
        # Create a power the character doesn't know
        unknown_power = DisciplinePower.objects.create(
            name="Unknown Power",
            discipline=self.auspex,
            level=3,
            dice_pool="Resolve + Auspex",
            cost="One Rouse check"
        )

        can_use, reason = can_use_power(self.char1, "Unknown Power")
        self.assertFalse(can_use)
        self.assertIn("don't know", reason.lower())

    def test_rouse_check_integration(self):
        """Test discipline roll includes Rouse check."""
        initial_hunger = self.char1.db.hunger

        # Mock rouse check to always fail
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 3, 'success': False, 'hunger_change': 1}

            result = roll_discipline_power(
                self.char1,
                "Corrosive Vitae",  # Has rouse cost
                difficulty=2,
                with_rouse=True
            )

            self.assertIsNotNone(result['rouse_result'])
            self.assertFalse(result['rouse_result']['success'])
            self.assertEqual(result['hunger_after'], initial_hunger + 1)

    def test_can_use_power(self):
        """Test checking if character can use a power."""
        # Character can use known power
        can_use, reason = can_use_power(self.char1, "Heightened Senses")
        self.assertTrue(can_use)

        # Character doesn't know power
        unknown_power = DisciplinePower.objects.create(
            name="Test Unknown",
            discipline=self.auspex,
            level=1,
            dice_pool="Resolve + Auspex"
        )
        can_use, reason = can_use_power(self.char1, "Test Unknown")
        self.assertFalse(can_use)

    def test_get_character_discipline_powers(self):
        """Test retrieving character's discipline powers."""
        powers = get_character_discipline_powers(self.char1)

        self.assertEqual(len(powers), 2)
        power_names = [p['name'] for p in powers]
        self.assertIn("Heightened Senses", power_names)
        self.assertIn("Corrosive Vitae", power_names)

        # Filter by discipline
        auspex_powers = get_character_discipline_powers(self.char1, "Auspex")
        self.assertEqual(len(auspex_powers), 1)
        self.assertEqual(auspex_powers[0]['name'], "Heightened Senses")


class RouseCheckerTestCase(EvenniaTest):
    """Test Rouse checks and Hunger management."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        # Create Blood Potency trait
        attr_category = TraitCategory.objects.create(
            name="Attributes",
            code="attributes"
        )
        self.blood_potency = Trait.objects.create(
            name="Blood Potency",
            category=attr_category,
            max_value=10
        )

        # Set initial Hunger
        self.char1.db.hunger = 2

    def test_rouse_check_success(self):
        """Test roll 6+ = no Hunger gain."""
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 8, 'success': True, 'hunger_change': 0}

            result = perform_rouse_check(self.char1, "Test", power_level=1)

            self.assertTrue(result['success'])
            self.assertEqual(result['hunger_change'], 0)
            self.assertEqual(result['hunger_after'], 2)  # No change
            self.assertEqual(self.char1.db.hunger, 2)

    def test_rouse_check_failure(self):
        """Test roll 1-5 = +1 Hunger."""
        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 3, 'success': False, 'hunger_change': 1}

            result = perform_rouse_check(self.char1, "Test", power_level=1)

            self.assertFalse(result['success'])
            self.assertEqual(result['hunger_change'], 1)
            self.assertEqual(result['hunger_after'], 3)  # 2 + 1
            self.assertEqual(self.char1.db.hunger, 3)

    def test_hunger_at_max(self):
        """Test Hunger 5 cannot increase."""
        self.char1.db.hunger = 5

        result = perform_rouse_check(self.char1, "Test", power_level=1)

        self.assertEqual(result['hunger_before'], 5)
        self.assertEqual(result['hunger_after'], 5)
        self.assertEqual(result['hunger_change'], 0)
        self.assertEqual(self.char1.db.hunger, 5)

    def test_blood_potency_reroll_eligibility(self):
        """Test BP allows reroll for low-level powers."""
        # Create BP trait
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.blood_potency,
            rating=3
        )

        # BP 3 can reroll Level 1-2 powers
        self.assertTrue(can_reroll_rouse(self.char1, power_level=1))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=2))
        self.assertFalse(can_reroll_rouse(self.char1, power_level=3))

        # BP 6 can reroll Level 1-3 powers
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=6)

        self.assertTrue(can_reroll_rouse(self.char1, power_level=1))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=2))
        self.assertTrue(can_reroll_rouse(self.char1, power_level=3))
        self.assertFalse(can_reroll_rouse(self.char1, power_level=4))

    def test_blood_potency_reroll_occurs(self):
        """Test failed roll gets rerolled automatically."""
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.blood_potency,
            rating=2  # Can reroll Level 1
        )

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
            self.assertEqual(self.char1.db.hunger, 2)  # No hunger gain

    def test_hunger_persistence(self):
        """Test character.db.hunger updated correctly."""
        initial_hunger = self.char1.db.hunger

        with patch('dice.rouse_checker.base_rouse_check') as mock_rouse:
            mock_rouse.return_value = {'roll': 2, 'success': False, 'hunger_change': 1}

            result = perform_rouse_check(self.char1, "Test")

            self.assertEqual(self.char1.db.hunger, initial_hunger + 1)
            self.assertEqual(result['hunger_after'], initial_hunger + 1)

    def test_get_hunger_level(self):
        """Test getting character's Hunger level."""
        self.char1.db.hunger = 3
        self.assertEqual(get_hunger_level(self.char1), 3)

        # Test clamping
        self.char1.db.hunger = 10
        self.assertEqual(get_hunger_level(self.char1), 5)  # Max 5

        self.char1.db.hunger = -1
        self.assertEqual(get_hunger_level(self.char1), 0)  # Min 0

    def test_set_hunger_level(self):
        """Test setting character's Hunger level."""
        result = set_hunger_level(self.char1, 4)
        self.assertEqual(result, 4)
        self.assertEqual(self.char1.db.hunger, 4)

        # Test clamping to max
        result = set_hunger_level(self.char1, 10)
        self.assertEqual(result, 5)
        self.assertEqual(self.char1.db.hunger, 5)

        # Test clamping to min
        result = set_hunger_level(self.char1, -2)
        self.assertEqual(result, 0)
        self.assertEqual(self.char1.db.hunger, 0)

    def test_format_hunger_display(self):
        """Test formatting Hunger for display."""
        self.char1.db.hunger = 3
        display = format_hunger_display(self.char1)

        self.assertIsInstance(display, str)
        self.assertIn("3/5", display)
        self.assertIn("■", display)  # Filled boxes
        self.assertIn("□", display)  # Empty boxes

    def test_blood_potency_reroll_levels(self):
        """Test all BP levels for reroll eligibility."""
        CharacterTrait.objects.create(
            character=self.char1,
            trait=self.blood_potency,
            rating=0
        )

        # BP 0: No rerolls
        for level in range(1, 6):
            self.assertFalse(can_reroll_rouse(self.char1, level))

        # BP 1-2: Level 1 only
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=2)

        self.assertTrue(can_reroll_rouse(self.char1, 1))
        self.assertFalse(can_reroll_rouse(self.char1, 2))

        # BP 3-5: Levels 1-2
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=5)

        self.assertTrue(can_reroll_rouse(self.char1, 1))
        self.assertTrue(can_reroll_rouse(self.char1, 2))
        self.assertFalse(can_reroll_rouse(self.char1, 3))

        # BP 6-7: Levels 1-3
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=7)

        self.assertTrue(can_reroll_rouse(self.char1, 1))
        self.assertTrue(can_reroll_rouse(self.char1, 2))
        self.assertTrue(can_reroll_rouse(self.char1, 3))
        self.assertFalse(can_reroll_rouse(self.char1, 4))

        # BP 8-9: Levels 1-4
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=9)

        self.assertTrue(can_reroll_rouse(self.char1, 1))
        self.assertTrue(can_reroll_rouse(self.char1, 2))
        self.assertTrue(can_reroll_rouse(self.char1, 3))
        self.assertTrue(can_reroll_rouse(self.char1, 4))
        self.assertFalse(can_reroll_rouse(self.char1, 5))

        # BP 10: All levels
        CharacterTrait.objects.filter(
            character=self.char1,
            trait=self.blood_potency
        ).update(rating=10)

        for level in range(1, 6):
            self.assertTrue(can_reroll_rouse(self.char1, level))
