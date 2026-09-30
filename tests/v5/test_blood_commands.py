"""
Integration Tests for Blood System Commands

Tests the feed, bloodsurge, and hunger commands with full integration
of dice rolling, Hunger management, and resonance tracking.
"""

import time
from unittest.mock import Mock, patch, MagicMock, call
from evennia.utils.test_resources import EvenniaTest
from commands.v5.blood import CmdFeed, CmdBloodSurge, CmdHunger
from commands.v5.utils import blood_utils


class CmdFeedTestCase(EvenniaTest):
    """Integration tests for the feed command."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.cmd = CmdFeed()
        self.cmd.caller = self.char
        self.cmd.cmdstring = "feed"
        self.cmd.switches = []

        # Create a mock location for the character
        self.char.location = Mock()
        self.char.location.msg_contents = Mock()

    def test_feed_no_arguments(self):
        """Test feed command with no arguments shows usage."""
        self.cmd.args = ""
        self.cmd.func()

        # Check for usage message
        self.assertTrue(self.char.msg.called)
        message = self.char.msg.call_args[0][0]
        self.assertIn("Usage", message)

    def test_feed_invalid_resonance(self):
        """Test feed command with invalid resonance type."""
        self.cmd.args = "mortal invalid_resonance"
        self.cmd.func()

        # Check for error message
        self.assertTrue(self.char.msg.called)
        message = self.char.msg.call_args[0][0]
        self.assertIn("Invalid resonance", message.lower())

    def test_feed_valid_resonances(self):
        """Test feed command accepts all valid resonance types."""
        valid_resonances = ['choleric', 'melancholic', 'phlegmatic', 'sanguine']

        for resonance in valid_resonances:
            with patch('dice.dice_roller.roll_v5_pool') as mock_roll:
                with patch('traits.utils.get_character_trait_value', return_value=3):
                    # Mock successful roll
                    mock_result = Mock()
                    mock_result.is_success = True
                    mock_result.is_messy_critical = False
                    mock_result.is_bestial_failure = False
                    mock_result.total_successes = 3
                    mock_result.format_result = Mock(return_value="Roll details")
                    mock_roll.return_value = mock_result

                    self.char.db.hunger = 3
                    self.cmd.args = f"mortal {resonance}"
                    self.cmd.func()

                    # Verify no error message about invalid resonance
                    message = self.char.msg.call_args[0][0]
                    self.assertNotIn("Invalid resonance", message.lower())

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_success_reduces_hunger(self, mock_trait, mock_roll):
        """Test successful feeding reduces Hunger."""
        # Mock traits (Strength + Brawl = 5 dice)
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        # Mock successful roll with 3 successes
        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 3
        mock_result.format_result = Mock(return_value="Roll: 3 successes")
        mock_roll.return_value = mock_result

        # Set initial hunger
        initial_hunger = 4
        self.char.db.hunger = initial_hunger

        # Execute command
        self.cmd.args = "mortal"
        self.cmd.func()

        # Verify hunger was reduced
        final_hunger = blood_utils.get_hunger_level(self.char)
        self.assertLess(final_hunger, initial_hunger,
                       "Hunger should be reduced after successful feeding")

        # Verify success message
        message = self.char.msg.call_args[0][0]
        self.assertIn("Feeding successful", message)
        self.assertIn("Hunger reduced", message)

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_reduction_scales_with_successes(self, mock_trait, mock_roll):
        """Test Hunger reduction scales with number of successes."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        test_cases = [
            (2, 1),  # 2 successes = 1 Hunger reduced (minimum)
            (3, 1),  # 3 successes = 1 Hunger reduced
            (4, 2),  # 4 successes = 2 Hunger reduced
            (6, 3),  # 6 successes = 3 Hunger reduced (maximum)
            (10, 3), # 10+ successes = 3 Hunger reduced (capped)
        ]

        for successes, expected_reduction in test_cases:
            mock_result = Mock()
            mock_result.is_success = True
            mock_result.is_messy_critical = False
            mock_result.is_bestial_failure = False
            mock_result.total_successes = successes
            mock_result.format_result = Mock(return_value=f"Roll: {successes} successes")
            mock_roll.return_value = mock_result

            self.char.db.hunger = 5  # Reset to max
            self.cmd.args = "mortal"
            self.cmd.func()

            actual_reduction = 5 - blood_utils.get_hunger_level(self.char)
            self.assertEqual(actual_reduction, expected_reduction,
                           f"{successes} successes should reduce Hunger by {expected_reduction}")

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_sets_resonance(self, mock_trait, mock_roll):
        """Test feeding with resonance sets it correctly."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 3
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        self.char.db.hunger = 3
        self.cmd.args = "mortal choleric"
        self.cmd.func()

        # Verify resonance was set
        resonance = blood_utils.get_resonance(self.char)
        self.assertIsNotNone(resonance)
        self.assertEqual(resonance['type'], 'Choleric')
        self.assertEqual(resonance['intensity'], 1)  # Default fleeting

        # Verify resonance in message
        message = self.char.msg.call_args[0][0]
        self.assertIn("Choleric", message)
        self.assertIn("Fleeting", message)

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_messy_critical(self, mock_trait, mock_roll):
        """Test feeding with Messy Critical still reduces Hunger but has consequences."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = True
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 4
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        initial_hunger = 4
        self.char.db.hunger = initial_hunger

        self.cmd.args = "mortal"
        self.cmd.func()

        # Hunger should still be reduced
        final_hunger = blood_utils.get_hunger_level(self.char)
        self.assertLess(final_hunger, initial_hunger)

        # Should mention Messy Critical
        message = self.char.msg.call_args[0][0]
        self.assertIn("Messy Critical", message)
        self.assertIn("successful", message.lower())

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_bestial_failure(self, mock_trait, mock_roll):
        """Test feeding with Bestial Failure does not reduce Hunger."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = False
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = True
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        initial_hunger = 3
        self.char.db.hunger = initial_hunger

        self.cmd.args = "mortal"
        self.cmd.func()

        # Hunger should NOT be reduced
        final_hunger = blood_utils.get_hunger_level(self.char)
        self.assertEqual(final_hunger, initial_hunger,
                        "Bestial Failure should not reduce Hunger")

        # Should mention Bestial Failure and Beast
        message = self.char.msg.call_args[0][0]
        self.assertIn("Bestial Failure", message)
        self.assertIn("Beast", message)

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_regular_failure(self, mock_trait, mock_roll):
        """Test feeding with regular failure does not reduce Hunger."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = False
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        initial_hunger = 3
        self.char.db.hunger = initial_hunger

        self.cmd.args = "mortal"
        self.cmd.func()

        # Hunger should NOT be reduced
        final_hunger = blood_utils.get_hunger_level(self.char)
        self.assertEqual(final_hunger, initial_hunger,
                        "Regular failure should not reduce Hunger")

        # Should mention failure
        message = self.char.msg.call_args[0][0]
        self.assertIn("failed", message.lower())

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_broadcasts_to_room(self, mock_trait, mock_roll):
        """Test feeding broadcasts message to room."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 3
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        self.char.db.hunger = 3
        self.cmd.args = "mortal"
        self.cmd.func()

        # Verify room broadcast
        self.char.location.msg_contents.assert_called_once()
        call_args = self.char.location.msg_contents.call_args

        # Check message content and exclusion
        message = call_args[0][0]
        self.assertIn("feeds", message.lower())
        self.assertEqual(call_args[1]['exclude'], [self.char])

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_uses_hunger_dice(self, mock_trait, mock_roll):
        """Test feeding uses current Hunger for dice roll."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 3
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        self.char.db.hunger = 4
        self.cmd.args = "mortal"
        self.cmd.func()

        # Verify roll was called with correct parameters
        mock_roll.assert_called_once()
        call_args = mock_roll.call_args

        # Should use dice pool of 5 (Strength 3 + Brawl 2)
        self.assertEqual(call_args[0][0], 5)
        # Should use Hunger of 4
        self.assertEqual(call_args[0][1], 4)

    @patch('dice.dice_roller.roll_v5_pool')
    @patch('traits.utils.get_character_trait_value')
    def test_feed_cannot_reduce_below_zero(self, mock_trait, mock_roll):
        """Test feeding at low Hunger doesn't go negative."""
        mock_trait.side_effect = lambda char, trait: {
            'Strength': 3,
            'Brawl': 2
        }.get(trait, 0)

        # Mock massive success
        mock_result = Mock()
        mock_result.is_success = True
        mock_result.is_messy_critical = False
        mock_result.is_bestial_failure = False
        mock_result.total_successes = 10  # Would reduce by 3
        mock_result.format_result = Mock(return_value="Roll details")
        mock_roll.return_value = mock_result

        # Start at Hunger 1
        self.char.db.hunger = 1
        self.cmd.args = "mortal"
        self.cmd.func()

        # Should be at 0, not negative
        final_hunger = blood_utils.get_hunger_level(self.char)
        self.assertEqual(final_hunger, 0, "Hunger should not go below 0")


class CmdBloodSurgeTestCase(EvenniaTest):
    """Integration tests for the bloodsurge command."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.cmd = CmdBloodSurge()
        self.cmd.caller = self.char
        self.cmd.cmdstring = "bloodsurge"

    def test_bloodsurge_no_arguments(self):
        """Test bloodsurge command with no arguments shows usage."""
        self.cmd.args = ""
        self.cmd.func()

        self.assertTrue(self.char.msg.called)
        message = self.char.msg.call_args[0][0]
        self.assertIn("Usage", message)

    @patch('commands.v5.utils.blood_utils.activate_blood_surge')
    def test_bloodsurge_success(self, mock_activate):
        """Test successful Blood Surge activation."""
        mock_activate.return_value = {
            'success': True,
            'bonus': 3,
            'trait': 'Strength',
            'expires': time.time() + 3600,
            'rouse_result': {
                'message': 'Rouse check passed'
            }
        }

        self.cmd.args = "strength"
        self.cmd.func()

        # Verify activation was called
        mock_activate.assert_called_once()
        call_args = mock_activate.call_args
        self.assertEqual(call_args[0][0], self.char)
        self.assertEqual(call_args[0][2], 'Strength')

        # Verify success message
        message = self.char.msg.call_args[0][0]
        self.assertIn("Blood Surge activated", message)
        self.assertIn("Strength", message)
        self.assertIn("+3", message)

    @patch('commands.v5.utils.blood_utils.activate_blood_surge')
    def test_bloodsurge_capitalizes_trait_name(self, mock_activate):
        """Test Blood Surge capitalizes trait name."""
        mock_activate.return_value = {
            'success': True,
            'bonus': 2,
            'trait': 'Brawl',
            'expires': time.time() + 3600,
            'rouse_result': {
                'message': 'Rouse check passed'
            }
        }

        # Use lowercase input
        self.cmd.args = "brawl"
        self.cmd.func()

        # Should capitalize before calling activate
        call_args = mock_activate.call_args
        self.assertEqual(call_args[0][2], 'Brawl')

    @patch('commands.v5.utils.blood_utils.activate_blood_surge')
    def test_bloodsurge_shows_rouse_result(self, mock_activate):
        """Test Blood Surge displays Rouse check result."""
        mock_activate.return_value = {
            'success': True,
            'bonus': 2,
            'trait': 'Dexterity',
            'expires': time.time() + 3600,
            'rouse_result': {
                'message': 'Rouse check: No Hunger increase'
            }
        }

        self.cmd.args = "dexterity"
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("Rouse check", message)

    @patch('commands.v5.utils.blood_utils.activate_blood_surge')
    def test_bloodsurge_shows_duration(self, mock_activate):
        """Test Blood Surge displays duration information."""
        mock_activate.return_value = {
            'success': True,
            'bonus': 3,
            'trait': 'Strength',
            'expires': time.time() + 3600,
            'rouse_result': {
                'message': 'Rouse check passed'
            }
        }

        self.cmd.args = "strength"
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("1 hour", message.lower())

    @patch('traits.utils.get_character_trait_value')
    @patch('dice.rouse_checker.perform_rouse_check')
    def test_bloodsurge_performs_rouse_check(self, mock_rouse, mock_trait):
        """Test Blood Surge actually performs Rouse check."""
        mock_trait.return_value = 2
        mock_rouse.return_value = {
            'success': True,
            'hunger_after': 3,
            'message': 'Rouse check performed'
        }

        self.char.db.hunger = 2
        self.cmd.args = "strength"
        self.cmd.func()

        # Verify Rouse check was called
        mock_rouse.assert_called_once()

    @patch('traits.utils.get_character_trait_value')
    @patch('dice.rouse_checker.perform_rouse_check')
    def test_bloodsurge_bonus_equals_blood_potency(self, mock_rouse, mock_trait):
        """Test Blood Surge bonus equals Blood Potency value."""
        test_bp_values = [0, 1, 2, 3, 4, 5]

        for bp in test_bp_values:
            mock_trait.return_value = bp
            mock_rouse.return_value = {
                'success': True,
                'hunger_after': 2,
                'message': 'Rouse check passed'
            }

            self.cmd.args = "strength"
            self.cmd.func()

            message = self.char.msg.call_args[0][0]
            self.assertIn(f"+{bp}", message,
                         f"Should show +{bp} dice for BP {bp}")


class CmdHungerTestCase(EvenniaTest):
    """Integration tests for the hunger command."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        self.cmd = CmdHunger()
        self.cmd.caller = self.char
        self.cmd.cmdstring = "hunger"

    def test_hunger_basic_display(self):
        """Test hunger command displays basic status."""
        self.char.db.hunger = 3

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("Blood Status", message)
        self.assertIn("Hunger", message)
        self.assertIn("3/5", message)

    def test_hunger_shows_visual_indicator(self):
        """Test hunger command shows visual Hunger bar."""
        self.char.db.hunger = 2

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("■", message)  # Filled boxes
        self.assertIn("□", message)  # Empty boxes

    def test_hunger_level_zero_message(self):
        """Test hunger command message at Hunger 0."""
        self.char.db.hunger = 0

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("well-fed", message.lower())
        self.assertIn("sated", message.lower())

    def test_hunger_level_low_message(self):
        """Test hunger command message at Hunger 1-2."""
        for hunger in [1, 2]:
            self.char.db.hunger = hunger

            self.cmd.args = ""
            self.cmd.func()

            message = self.char.msg.call_args[0][0]
            self.assertIn("minor cravings", message.lower())

    def test_hunger_level_moderate_message(self):
        """Test hunger command message at Hunger 3."""
        self.char.db.hunger = 3

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("moderate", message.lower())

    def test_hunger_level_high_message(self):
        """Test hunger command message at Hunger 4."""
        self.char.db.hunger = 4

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("severe", message.lower())
        self.assertIn("Beast", message)

    def test_hunger_level_max_message(self):
        """Test hunger command message at Hunger 5."""
        self.char.db.hunger = 5

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("RAVENOUS", message)
        self.assertIn("cannot use", message.lower())

    def test_hunger_with_resonance_display(self):
        """Test hunger command displays active resonance."""
        self.char.db.hunger = 2
        blood_utils.set_resonance(self.char, 'Choleric', intensity=2)

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("Choleric", message)
        self.assertIn("Intense", message)

    def test_hunger_with_blood_surge_display(self):
        """Test hunger command displays active Blood Surge."""
        self.char.db.hunger = 2
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 3,
            'expires': time.time() + 3600
        }

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("Blood Surge Active", message)
        self.assertIn("Strength", message)
        self.assertIn("+3", message)

    def test_hunger_with_both_resonance_and_surge(self):
        """Test hunger command displays both resonance and Blood Surge."""
        self.char.db.hunger = 3
        blood_utils.set_resonance(self.char, 'Sanguine', intensity=1)
        self.char.ndb.blood_surge = {
            'trait': 'Dexterity',
            'bonus': 2,
            'expires': time.time() + 3600
        }

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        # Should show both
        self.assertIn("Sanguine", message)
        self.assertIn("Blood Surge Active", message)
        self.assertIn("Dexterity", message)

    def test_hunger_without_resonance(self):
        """Test hunger command without resonance doesn't show resonance section."""
        self.char.db.hunger = 2
        blood_utils.clear_resonance(self.char)

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        # Should still work but not show resonance-specific terms
        self.assertIn("Blood Status", message)
        self.assertIn("Hunger", message)

    def test_hunger_without_blood_surge(self):
        """Test hunger command without Blood Surge doesn't show surge section."""
        self.char.db.hunger = 2
        if hasattr(self.char.ndb, 'blood_surge'):
            del self.char.ndb.blood_surge

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        # Should still work but not show Blood Surge
        self.assertIn("Blood Status", message)
        self.assertNotIn("Blood Surge Active", message)

    def test_hunger_shows_remaining_surge_time(self):
        """Test hunger command shows remaining time for Blood Surge."""
        self.char.db.hunger = 2
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 3,
            'expires': time.time() + 1800  # 30 minutes
        }

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertIn("minutes remaining", message.lower())

    def test_hunger_expired_surge_not_shown(self):
        """Test hunger command doesn't show expired Blood Surge."""
        self.char.db.hunger = 2
        self.char.ndb.blood_surge = {
            'trait': 'Strength',
            'bonus': 3,
            'expires': time.time() - 1  # Expired 1 second ago
        }

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        self.assertNotIn("Blood Surge Active", message)

    def test_hunger_expired_resonance_not_shown(self):
        """Test hunger command doesn't show expired resonance."""
        self.char.db.hunger = 2
        resonance = blood_utils.set_resonance(self.char, 'Phlegmatic', intensity=1)
        # Manually expire it
        self.char.db.resonance['expires'] = time.time() - 1

        self.cmd.args = ""
        self.cmd.func()

        message = self.char.msg.call_args[0][0]
        # Expired resonance should not appear
        # (Note: format_resonance_display clears expired resonance)
        self.assertNotIn("Phlegmatic", message)


class CommandPermissionsTests(EvenniaTest):
    """Test command permissions and access control."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def test_feed_requires_character(self):
        """Test feed command validates caller is a Character."""
        cmd = CmdFeed()
        cmd.caller = Mock()  # Not a Character
        cmd.caller.msg = Mock()
        cmd.args = "mortal"

        with patch('evennia.utils.utils.inherits_from', return_value=False):
            cmd.func()

            message = cmd.caller.msg.call_args[0][0]
            self.assertIn("must be in character", message.lower())

    def test_bloodsurge_requires_character(self):
        """Test bloodsurge command validates caller is a Character."""
        cmd = CmdBloodSurge()
        cmd.caller = Mock()  # Not a Character
        cmd.caller.msg = Mock()
        cmd.args = "strength"

        with patch('evennia.utils.utils.inherits_from', return_value=False):
            cmd.func()

            message = cmd.caller.msg.call_args[0][0]
            self.assertIn("must be in character", message.lower())

    def test_hunger_requires_character(self):
        """Test hunger command validates caller is a Character."""
        cmd = CmdHunger()
        cmd.caller = Mock()  # Not a Character
        cmd.caller.msg = Mock()
        cmd.args = ""

        with patch('evennia.utils.utils.inherits_from', return_value=False):
            cmd.func()

            message = cmd.caller.msg.call_args[0][0]
            self.assertIn("must be in character", message.lower())
