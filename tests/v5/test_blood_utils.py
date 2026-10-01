"""
Unit Tests for Blood System Utilities

Tests the blood_utils module functions for Hunger management, resonance tracking,
and Blood Surge mechanics.
"""

import time
import unittest
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaTest

from commands.v5.utils import blood_utils
from dice.rouse_checker import can_reroll_rouse


class HungerManagementTests(EvenniaTest):
    """Test Hunger level management functions."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_get_hunger_level_default(self):
        """Test getting default Hunger level when not set."""
        # Clear any existing hunger
        if hasattr(self.char.db, 'hunger'):
            del self.char.db.hunger

        hunger = blood_utils.get_hunger_level(self.char)
        self.assertEqual(hunger, 1, "Default Hunger should be 1")

    def test_get_hunger_level_set(self):
        """Test getting explicitly set Hunger level."""
        self.char.db.hunger = 3
        hunger = blood_utils.get_hunger_level(self.char)
        self.assertEqual(hunger, 3)

    def test_get_hunger_level_clamping(self):
        """Test Hunger level clamping on get."""
        # Test values within valid range
        self.char.db.hunger = 0
        self.assertEqual(blood_utils.get_hunger_level(self.char), 0)

        self.char.db.hunger = 5
        self.assertEqual(blood_utils.get_hunger_level(self.char), 5)

    def test_set_hunger_level_normal(self):
        """Test setting Hunger level within valid range."""
        new_hunger = blood_utils.set_hunger_level(self.char, 4)
        self.assertEqual(new_hunger, 4)
        self.assertEqual(self.char.db.hunger, 4)

    def test_set_hunger_level_clamps_upper(self):
        """Test Hunger level clamping at upper bound."""
        hunger = blood_utils.set_hunger_level(self.char, 10)
        self.assertEqual(hunger, 5, "Hunger should be clamped to 5")
        self.assertEqual(self.char.db.hunger, 5)

    def test_set_hunger_level_clamps_lower(self):
        """Test Hunger level clamping at lower bound."""
        hunger = blood_utils.set_hunger_level(self.char, -5)
        self.assertEqual(hunger, 0, "Hunger should be clamped to 0")
        self.assertEqual(self.char.db.hunger, 0)

    def test_reduce_hunger_normal(self):
        """Test reducing Hunger by specified amount."""
        self.char.db.hunger = 4
        new_hunger = blood_utils.reduce_hunger(self.char, 2)
        self.assertEqual(new_hunger, 2)
        self.assertEqual(self.char.db.hunger, 2)

    def test_reduce_hunger_default_amount(self):
        """Test reducing Hunger by default amount (1)."""
        self.char.db.hunger = 3
        new_hunger = blood_utils.reduce_hunger(self.char)
        self.assertEqual(new_hunger, 2)

    def test_reduce_hunger_clamps_to_zero(self):
        """Test Hunger reduction clamps to 0, not negative."""
        self.char.db.hunger = 1
        new_hunger = blood_utils.reduce_hunger(self.char, 5)
        self.assertEqual(new_hunger, 0, "Hunger should not go below 0")
        self.assertEqual(self.char.db.hunger, 0)

    def test_increase_hunger_normal(self):
        """Test increasing Hunger by specified amount."""
        self.char.db.hunger = 2
        new_hunger = blood_utils.increase_hunger(self.char, 1)['hunger_after']
        self.assertEqual(new_hunger, 3)
        self.assertEqual(self.char.db.hunger, 3)

    def test_increase_hunger_default_amount(self):
        """Test increasing Hunger by default amount (1)."""
        self.char.db.hunger = 2
        new_hunger = blood_utils.increase_hunger(self.char)['hunger_after']
        self.assertEqual(new_hunger, 3)

    def test_increase_hunger_clamps_to_five(self):
        """Test Hunger increase clamps to 5, not higher."""
        self.char.db.hunger = 4
        new_hunger = blood_utils.increase_hunger(self.char, 5)['hunger_after']
        self.assertEqual(new_hunger, 5, "Hunger should not exceed 5")
        self.assertEqual(self.char.db.hunger, 5)

    def test_hunger_edge_case_zero_to_five(self):
        """Test full range transition from 0 to 5."""
        self.char.db.hunger = 0
        for expected in range(1, 6):
            new_hunger = blood_utils.increase_hunger(self.char, 1)['hunger_after']
            self.assertEqual(new_hunger, expected)

    def test_hunger_edge_case_five_to_zero(self):
        """Test full range transition from 5 to 0."""
        self.char.db.hunger = 5
        for expected in range(4, -1, -1):
            new_hunger = blood_utils.reduce_hunger(self.char, 1)
            self.assertEqual(new_hunger, expected)


class HungerDisplayTests(EvenniaTest):
    """Test Hunger display formatting."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_format_hunger_display_zero(self):
        """Test Hunger display at level 0."""
        self.char.db.hunger = 0
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("0/5", display)
        self.assertIn("□□□□□", display)  # All empty boxes
        self.assertIn("|g", display)  # Green color

    def test_format_hunger_display_three(self):
        """Test Hunger display at level 3."""
        self.char.db.hunger = 3
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("3/5", display)
        self.assertIn("■■■", display)  # Three filled boxes
        self.assertIn("□□", display)   # Two empty boxes

    def test_format_hunger_display_five(self):
        """Test Hunger display at level 5 (max)."""
        self.char.db.hunger = 5
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("5/5", display)
        self.assertIn("■■■■■", display)  # All filled boxes
        self.assertIn("|r|h", display)  # Bright red color

    def test_format_hunger_display_color_coding(self):
        """Test color coding changes by Hunger level."""
        # Low Hunger (0-1) - Green
        self.char.db.hunger = 1
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("|g", display)

        # Moderate Hunger (2-3) - Yellow
        self.char.db.hunger = 2
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("|y", display)

        # High Hunger (4) - Red
        self.char.db.hunger = 4
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("|r", display)

        # Max Hunger (5) - Bright Red
        self.char.db.hunger = 5
        display = blood_utils.format_hunger_display(self.char)
        self.assertIn("|r|h", display)


class ResonanceManagementTests(EvenniaTest):
    """Test blood resonance tracking functions."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_set_resonance_choleric(self):
        """Test setting Choleric resonance."""
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=1)
        self.assertEqual(resonance['type'], 'Choleric')
        self.assertEqual(resonance['intensity'], 1)
        self.assertIn('expires', resonance)
        self.assertGreater(resonance['expires'], time.time())

    def test_set_resonance_all_types(self):
        """Test setting all resonance types."""
        types = ['Choleric', 'Melancholic', 'Phlegmatic', 'Sanguine']
        for res_type in types:
            resonance = blood_utils.set_resonance(self.char, res_type, intensity=1)
            self.assertEqual(resonance['type'], res_type)

    def test_set_resonance_intensity_levels(self):
        """Test setting different intensity levels."""
        # Fleeting (1)
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=1)
        self.assertEqual(resonance['intensity'], 1)

        # Intense (2)
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=2)
        self.assertEqual(resonance['intensity'], 2)

        # Acute (3)
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=3)
        self.assertEqual(resonance['intensity'], 3)

    def test_set_resonance_intensity_clamping(self):
        """Test resonance intensity clamping to 1-3."""
        # Below minimum
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=0)
        self.assertEqual(resonance['intensity'], 1)

        # Above maximum
        resonance = blood_utils.set_resonance(self.char, 'Choleric', intensity=10)
        self.assertEqual(resonance['intensity'], 3)

    def test_set_resonance_custom_duration(self):
        """Test setting resonance with custom duration."""
        duration = 7200  # 2 hours
        resonance = blood_utils.set_resonance(self.char, 'Sanguine', intensity=1, duration=duration)
        expected_expiration = time.time() + duration
        # Allow 1 second tolerance for test execution time
        self.assertAlmostEqual(resonance['expires'], expected_expiration, delta=1)

    def test_get_resonance_set(self):
        """Test getting set resonance."""
        blood_utils.set_resonance(self.char, 'Sanguine', intensity=2)
        resonance = blood_utils.get_resonance(self.char)
        self.assertIsNotNone(resonance)
        self.assertEqual(resonance['type'], 'Sanguine')
        self.assertEqual(resonance['intensity'], 2)

    def test_get_resonance_not_set(self):
        """Test getting resonance when none is set."""
        if hasattr(self.char.db, 'resonance'):
            del self.char.db.resonance
        resonance = blood_utils.get_resonance(self.char)
        self.assertIsNone(resonance)

    def test_clear_resonance(self):
        """Test clearing resonance."""
        blood_utils.set_resonance(self.char, 'Phlegmatic', intensity=1)
        self.assertIsNotNone(blood_utils.get_resonance(self.char))

        blood_utils.clear_resonance(self.char)
        resonance = blood_utils.get_resonance(self.char)
        self.assertIsNone(resonance)

    def test_resonance_replaces_previous(self):
        """Test that setting new resonance replaces previous."""
        blood_utils.set_resonance(self.char, 'Choleric', intensity=1)
        blood_utils.set_resonance(self.char, 'Melancholic', intensity=2)

        resonance = blood_utils.get_resonance(self.char)
        self.assertEqual(resonance['type'], 'Melancholic')
        self.assertEqual(resonance['intensity'], 2)


class ResonanceDisplayTests(EvenniaTest):
    """Test resonance display formatting."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_format_resonance_display_fleeting(self):
        """Test resonance display for fleeting intensity."""
        blood_utils.set_resonance(self.char, 'Choleric', intensity=1)
        display = blood_utils.format_resonance_display(self.char)
        self.assertIsNotNone(display)
        self.assertIn('Choleric', display)
        self.assertIn('Fleeting', display)

    def test_format_resonance_display_intense(self):
        """Test resonance display for intense intensity."""
        blood_utils.set_resonance(self.char, 'Melancholic', intensity=2)
        display = blood_utils.format_resonance_display(self.char)
        self.assertIn('Melancholic', display)
        self.assertIn('Intense', display)

    # F-096, fixed in PR 5: intensity 3 is labelled "Dyscrasia". In V5 the
    # third intensity is Acute; a Dyscrasia is something an Acute resonance
    # may carry.
    @unittest.expectedFailure
    def test_format_resonance_display_acute(self):
        """Test resonance display for acute intensity."""
        blood_utils.set_resonance(self.char, 'Phlegmatic', intensity=3)
        display = blood_utils.format_resonance_display(self.char)
        self.assertIn('Phlegmatic', display)
        self.assertIn('Acute', display)

    def test_format_resonance_display_none(self):
        """Test resonance display when no resonance set."""
        blood_utils.clear_resonance(self.char)
        display = blood_utils.format_resonance_display(self.char)
        self.assertIsNone(display)

    def test_format_resonance_display_expired(self):
        """Test resonance display returns None when expired."""
        # Set resonance with past expiration
        resonance = blood_utils.set_resonance(self.char, 'Sanguine', intensity=1, duration=0)
        self.char.db.resonance['expires'] = time.time() - 1  # Expired 1 second ago

        display = blood_utils.format_resonance_display(self.char)
        self.assertIsNone(display, "Expired resonance should not display")

        # Verify resonance was cleared
        self.assertIsNone(blood_utils.get_resonance(self.char))

    def test_format_resonance_display_color_coding(self):
        """Test color coding for different resonance types."""
        color_tests = [
            ('Choleric', '|r'),      # Red
            ('Melancholic', '|c'),    # Cyan
            ('Phlegmatic', '|g'),     # Green
            ('Sanguine', '|y')        # Yellow
        ]

        for res_type, expected_color in color_tests:
            blood_utils.set_resonance(self.char, res_type, intensity=1)
            display = blood_utils.format_resonance_display(self.char)
            self.assertIn(expected_color, display,
                         f"{res_type} should have color code {expected_color}")


class BloodSurgeManagementTests(EvenniaTest):
    """Test Blood Surge activation and management."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    # F-017, fixed in PR 5: activate_blood_surge calls
    # roll_rouse_check(character, reason=...), which takes no arguments, so
    # every Blood Surge raises TypeError.
    @unittest.expectedFailure
    def test_activate_blood_surge_rouses(self):
        """Blood Surge costs a Rouse check: a die of 1-5 raises Hunger by 1."""
        self.char.hunger = 2
        with patch('dice.dice_roller.randint', return_value=3):
            blood_utils.activate_blood_surge(self.char, 'attribute', 'Strength')
        self.assertEqual(self.char.hunger, 3)

    def test_get_blood_surge_active(self):
        """Test getting active Blood Surge status."""
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'trait_type': 'attribute',
            'bonus': 2,
            'expires': time.time() + 3600
        }

        surge = blood_utils.get_blood_surge(self.char)
        self.assertIsNotNone(surge)
        self.assertEqual(surge['trait'], 'Strength')
        self.assertEqual(surge['bonus'], 2)

    def test_get_blood_surge_not_active(self):
        """Test getting Blood Surge when not active."""
        if hasattr(self.char.ndb, 'blood_surge'):
            del self.char.ndb.blood_surge

        surge = blood_utils.get_blood_surge(self.char)
        self.assertIsNone(surge)

    def test_get_blood_surge_expired(self):
        """Test Blood Surge returns None when expired."""
        # Set surge with past expiration
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 3,
            'expires': time.time() - 1  # Expired 1 second ago
        }

        surge = blood_utils.get_blood_surge(self.char)
        self.assertIsNone(surge, "Expired Blood Surge should return None")

    def test_deactivate_blood_surge(self):
        """Test deactivating Blood Surge."""
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 2,
            'expires': time.time() + 3600
        }

        blood_utils.deactivate_blood_surge(self.char)
        surge = blood_utils.get_blood_surge(self.char)
        self.assertIsNone(surge)

    # F-022, fixed in PR 4/5: Blood Potency is read through
    # trait_utils.get_trait_value, which never looks at db.vampire, so it is
    # always 0 and Rouse re-rolls never apply.
    @unittest.expectedFailure
    def test_blood_potency_is_read_from_character(self):
        self.char.db.vampire['blood_potency'] = 3
        self.assertEqual(blood_utils.get_blood_potency(self.char), 3)
        self.assertTrue(can_reroll_rouse(self.char, 1))

    # F-022/F-093, fixed in PR 5: the surge bonus is "equal to Blood Potency"
    # and BP always reads 0. V5 core (p.216) gives the bonus from the Blood
    # Potency table. These rows are pending owner sign-off (design doc, "Rule
    # tables requiring owner sign-off").
    @unittest.expectedFailure
    def test_blood_surge_bonus_follows_bp_table(self):
        expected = {0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 4}
        for bp, bonus in expected.items():
            self.char.db.vampire['blood_potency'] = bp
            self.assertEqual(blood_utils.get_blood_potency_bonus(self.char), bonus, f"BP {bp}")

    def test_blood_surge_expiration_timing(self):
        """Test Blood Surge expires after approximately 1 hour."""
        expected_duration = 3600  # 1 hour in seconds

        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 2,
            'expires': time.time() + expected_duration
        }

        surge = blood_utils.get_blood_surge(self.char)
        self.assertIsNotNone(surge)

        # Check expiration is approximately 1 hour from now
        time_remaining = surge['expires'] - time.time()
        self.assertAlmostEqual(time_remaining, expected_duration, delta=1)


class EdgeCaseTests(EvenniaTest):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_multiple_hunger_operations_sequence(self):
        """Test sequence of Hunger operations."""
        self.char.db.hunger = 3

        # Increase then decrease
        blood_utils.increase_hunger(self.char, 2)  # 3 -> 5
        self.assertEqual(blood_utils.get_hunger_level(self.char), 5)

        blood_utils.reduce_hunger(self.char, 3)  # 5 -> 2
        self.assertEqual(blood_utils.get_hunger_level(self.char), 2)

        blood_utils.increase_hunger(self.char, 1)  # 2 -> 3
        self.assertEqual(blood_utils.get_hunger_level(self.char), 3)

    def test_resonance_overwrites_correctly(self):
        """Test that setting new resonance properly overwrites old."""
        # Set initial resonance
        blood_utils.set_resonance(self.char, 'Choleric', intensity=1, duration=1000)
        res1 = blood_utils.get_resonance(self.char)

        # Set new resonance
        blood_utils.set_resonance(self.char, 'Sanguine', intensity=3, duration=2000)
        res2 = blood_utils.get_resonance(self.char)

        # Verify only new resonance is present
        self.assertEqual(res2['type'], 'Sanguine')
        self.assertEqual(res2['intensity'], 3)
        self.assertNotEqual(res2['expires'], res1['expires'])
