"""
Tests for Discipline Utility Functions

Tests the discipline_utils module, specifically the rouse_check
integration that was fixed (BUG-004, BUG-005).
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from commands.v5.utils import discipline_utils


class TestActivateDisciplinePowerRouseCheck(unittest.TestCase):
    """Test the rouse check integration in activate_discipline_power."""

    def setUp(self):
        """Create mock character and power."""
        self.character = Mock()
        self.character.db = Mock()
        self.character.db.vampire = {'blood_potency': 2, 'hunger': 2}
        self.character.db.disciplines = {'Potence': 2}
        self.character.db.resonance = None

    @patch('commands.v5.utils.discipline_utils.get_power_by_name')
    @patch('commands.v5.utils.discipline_utils.get_blood_potency')
    @patch('commands.v5.utils.discipline_utils.rouse_check')
    @patch('commands.v5.utils.discipline_utils.increase_hunger')
    @patch('commands.v5.utils.discipline_utils.check_resonance_bonus')
    @patch('commands.v5.utils.discipline_utils.get_power_duration')
    def test_rouse_check_success(
        self,
        mock_duration,
        mock_resonance,
        mock_increase_hunger,
        mock_rouse,
        mock_get_bp,
        mock_get_power
    ):
        """Test successful rouse check (no Hunger increase)."""
        # Setup mocks
        mock_get_power.return_value = (
            {
                'name': 'Test Power',
                'description': 'Test',
                'rouse': True,
                'dice_pool': 'Strength',
                'duration': 'instant'
            },
            1
        )
        mock_get_bp.return_value = 2
        mock_rouse.return_value = (True, 8)  # Success, rolled 8
        mock_resonance.return_value = None
        mock_duration.return_value = 'instant'

        # Execute
        result = discipline_utils.activate_discipline_power(
            self.character,
            'Potence',
            'Test Power'
        )

        # Verify
        self.assertTrue(result['success'], "Activation should succeed")
        self.assertIsNotNone(result['rouse_result'], "Should have rouse_result")
        self.assertTrue(result['rouse_result']['success'], "Rouse check should succeed")
        self.assertEqual(result['rouse_result']['die'], 8, "Should record die result")
        self.assertFalse(result['rouse_result']['hunger_increased'], "Hunger should not increase")

        # Verify rouse_check was called with blood_potency (not character object)
        mock_rouse.assert_called_once_with(2)

        # Verify increase_hunger was NOT called (success)
        mock_increase_hunger.assert_not_called()

    @patch('commands.v5.utils.discipline_utils.get_power_by_name')
    @patch('commands.v5.utils.discipline_utils.get_blood_potency')
    @patch('commands.v5.utils.discipline_utils.rouse_check')
    @patch('commands.v5.utils.discipline_utils.increase_hunger')
    def test_rouse_check_failure(
        self,
        mock_increase_hunger,
        mock_rouse,
        mock_get_bp,
        mock_get_power
    ):
        """Test failed rouse check (Hunger increases)."""
        # Setup mocks
        mock_get_power.return_value = (
            {
                'name': 'Test Power',
                'description': 'Test',
                'rouse': True,
                'dice_pool': 'Strength',
                'duration': 'instant'
            },
            1
        )
        mock_get_bp.return_value = 2
        mock_rouse.return_value = (False, 3)  # Failure, rolled 3
        mock_increase_hunger.return_value = 3  # New hunger level

        # Execute
        result = discipline_utils.activate_discipline_power(
            self.character,
            'Potence',
            'Test Power'
        )

        # Verify
        self.assertTrue(result['success'], "Activation still succeeds despite failed rouse")
        self.assertIsNotNone(result['rouse_result'], "Should have rouse_result")
        self.assertFalse(result['rouse_result']['success'], "Rouse check should fail")
        self.assertEqual(result['rouse_result']['die'], 3, "Should record die result")
        self.assertTrue(result['rouse_result']['hunger_increased'], "Hunger should increase")

        # Verify increase_hunger was called
        mock_increase_hunger.assert_called_once_with(self.character, 1)

        # Verify message mentions hunger increase
        self.assertIn('Hunger', result['message'], "Message should mention hunger")
        self.assertIn('3', result['message'], "Message should show new hunger level")

    @patch('commands.v5.utils.discipline_utils.get_power_by_name')
    @patch('commands.v5.utils.discipline_utils.check_resonance_bonus')
    @patch('commands.v5.utils.discipline_utils.get_power_duration')
    def test_no_rouse_check_for_non_rouse_powers(
        self,
        mock_duration,
        mock_resonance,
        mock_get_power
    ):
        """Test that powers with rouse:False don't trigger rouse checks."""
        # Setup mocks
        mock_get_power.return_value = (
            {
                'name': 'Free Power',
                'description': 'No cost',
                'rouse': False,  # No rouse check
                'dice_pool': 'Strength',
                'duration': 'instant'
            },
            1
        )
        mock_resonance.return_value = None
        mock_duration.return_value = 'instant'

        # Execute
        result = discipline_utils.activate_discipline_power(
            self.character,
            'Potence',
            'Free Power'
        )

        # Verify
        self.assertTrue(result['success'], "Activation should succeed")
        self.assertIsNone(result['rouse_result'], "Should have no rouse_result")


class TestGetBloodPotencyIntegration(unittest.TestCase):
    """Test that blood_potency is correctly retrieved for rouse checks."""

    @patch('commands.v5.utils.discipline_utils.get_blood_potency')
    def test_blood_potency_retrieved(self, mock_get_bp):
        """Verify get_blood_potency is called correctly."""
        from commands.v5.utils.blood_utils import get_blood_potency

        character = Mock()
        character.db = Mock()
        character.db.vampire = {'blood_potency': 5}

        bp = get_blood_potency(character)
        self.assertEqual(bp, 5, "Should retrieve blood potency from character")


if __name__ == '__main__':
    unittest.main()
