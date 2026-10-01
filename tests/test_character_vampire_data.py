"""
Tests for Character vampire data structure (Phase 6)

Tests the vampire data initialization, migration, and backward compatibility
with Phase 5 dice system.
"""

import unittest
from collections.abc import Mapping
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaTest

from dice.rouse_checker import perform_rouse_check
from typeclasses.characters import Character


class VampireDataInitializationTestCase(EvenniaTest):
    """Test vampire data structure initializes correctly on new characters."""

    def setUp(self):
        super().setUp()
        self.char = Character.objects.create(db_key="TestVampire")

    def test_vampire_dict_initialization(self):
        """Test vampire data structure initializes correctly."""
        self.assertIsNotNone(self.char.db.vampire)
        # Attributes come back as _SaverDict, a Mapping but not a dict.
        self.assertIsInstance(self.char.db.vampire, Mapping)

    def test_vampire_default_values(self):
        """Test vampire data has correct default values."""
        vampire = self.char.db.vampire
        self.assertIsNone(vampire['clan'])
        self.assertEqual(vampire['generation'], 13)
        self.assertEqual(vampire['blood_potency'], 0)
        self.assertEqual(vampire['hunger'], 1)
        self.assertEqual(vampire['humanity'], 7)
        self.assertIsNone(vampire['predator_type'])
        self.assertIsNone(vampire['current_resonance'])
        self.assertEqual(vampire['resonance_intensity'], 0)
        self.assertIsNone(vampire['bane'])
        self.assertIsNone(vampire['compulsion'])

    def test_fresh_character_hunger_is_one(self):
        """A new vampire starts at Hunger 1, read through the property."""
        self.assertEqual(self.char.hunger, 1)

    # F-014/F-063, fixed in PR 4: `hasattr(self.db, 'hunger')` is always true,
    # so a fresh character's legacy db.hunger is None, and the Rouse check
    # (which reads db.hunger) raises TypeError comparing None with an int.
    @unittest.expectedFailure
    def test_fresh_character_can_rouse(self):
        """A Rouse check on a brand-new character works and raises Hunger on 1-5."""
        with patch("dice.dice_roller.randint", return_value=3):
            result = perform_rouse_check(self.char, reason="test")
        self.assertFalse(result["success"])
        self.assertEqual(self.char.hunger, 2)


class HungerPropertyTestCase(EvenniaTest):
    """Test Hunger property getter/setter with dual storage."""

    def setUp(self):
        super().setUp()
        self.char = Character.objects.create(db_key="TestHungerChar")

    def test_hunger_getter(self):
        """Test hunger property retrieves from vampire dict."""
        self.char.db.vampire['hunger'] = 3
        self.assertEqual(self.char.hunger, 3)

    def test_hunger_setter(self):
        """Test hunger property sets both locations."""
        self.char.hunger = 3
        self.assertEqual(self.char.hunger, 3)
        self.assertEqual(self.char.db.vampire['hunger'], 3)
        self.assertEqual(self.char.db.hunger, 3)

    def test_hunger_clamping_min(self):
        """Test hunger property clamps to minimum 0."""
        self.char.hunger = -5
        self.assertEqual(self.char.hunger, 0)
        self.assertEqual(self.char.db.vampire['hunger'], 0)
        self.assertEqual(self.char.db.hunger, 0)

    def test_hunger_clamping_max(self):
        """Test hunger property clamps to maximum 5."""
        self.char.hunger = 10
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(self.char.db.vampire['hunger'], 5)
        self.assertEqual(self.char.db.hunger, 5)

    def test_hunger_property_without_vampire_dict(self):
        """Test hunger property falls back to legacy location if vampire dict missing."""
        # Simulate character without vampire dict (shouldn't happen but test resilience)
        self.char.db.vampire = None
        self.char.db.hunger = 2
        self.assertEqual(self.char.hunger, 2)


class VampireDataMigrationTestCase(EvenniaTest):
    """Test migrating old character data to new vampire structure."""

    def test_migrate_with_existing_hunger(self):
        """Test migrating character with existing Hunger value."""
        # Create character and simulate old format (only db.hunger, no db.vampire)
        char = Character.objects.create(db_key="OldCharacter")
        char.db.vampire = None  # Remove vampire dict
        char.db.hunger = 2  # Old format

        # Migrate
        char.migrate_vampire_data()

        # Check vampire dict was created with migrated Hunger
        self.assertIsNotNone(char.db.vampire)
        self.assertEqual(char.db.vampire['hunger'], 2)
        self.assertEqual(char.db.hunger, 2)

    # F-063, fixed in PR 4 (which deletes migrate_vampire_data): the
    # `hasattr(self.db, 'hunger')` guard is always true, so migration copies
    # the missing legacy Hunger (None) over the stored value.
    @unittest.expectedFailure
    def test_migrate_without_hunger(self):
        """Test migrating character without Hunger attribute."""
        # Create character without hunger attribute
        char = Character.objects.create(db_key="NoHungerCharacter")
        char.db.vampire = None
        if hasattr(char.db, 'hunger'):
            delattr(char.db, 'hunger')

        # Migrate
        char.migrate_vampire_data()

        # Check vampire dict was created with default Hunger
        self.assertIsNotNone(char.db.vampire)
        self.assertEqual(char.db.vampire['hunger'], 1)

    # F-063, fixed in PR 4 (which deletes migrate_vampire_data): the
    # `hasattr(self.db, 'hunger')` guard is always true, so migration copies
    # the missing legacy Hunger (None) over the stored value.
    @unittest.expectedFailure
    def test_migrate_preserves_existing_vampire_data(self):
        """Test migration doesn't overwrite existing vampire dict."""
        char = Character.objects.create(db_key="ExistingVampireChar")
        char.db.vampire = {
            "clan": "Ventrue",
            "generation": 10,
            "blood_potency": 3,
            "hunger": 2,
            "humanity": 6,
            "predator_type": "Alleycat",
            "current_resonance": "Choleric",
            "resonance_intensity": 2,
            "bane": "Must feed from specific prey",
            "compulsion": "Dominate",
        }

        # Migrate
        char.migrate_vampire_data()

        # Check vampire dict is unchanged
        self.assertEqual(char.db.vampire['clan'], "Ventrue")
        self.assertEqual(char.db.vampire['generation'], 10)
        self.assertEqual(char.db.vampire['blood_potency'], 3)
        self.assertEqual(char.db.vampire['hunger'], 2)

    def test_migrate_syncs_hunger_from_legacy(self):
        """Test migration syncs Hunger from legacy location if different."""
        char = Character.objects.create(db_key="SyncCharacter")
        char.db.vampire = {
            "clan": None,
            "generation": 13,
            "blood_potency": 0,
            "hunger": 1,  # Old value
            "humanity": 7,
            "predator_type": None,
            "current_resonance": None,
            "resonance_intensity": 0,
            "bane": None,
            "compulsion": None,
        }
        char.db.hunger = 3  # Updated value in legacy location

        # Migrate
        char.migrate_vampire_data()

        # Check Hunger was synced
        self.assertEqual(char.db.vampire['hunger'], 3)


class EdgeCaseTestCase(EvenniaTest):
    """Test edge cases and error conditions."""

    def test_hunger_incremental_operations(self):
        """Test incremental Hunger modifications work correctly."""
        char = Character.objects.create(db_key="IncrementalChar")
        char.hunger = 2

        # Increment
        char.hunger += 1
        self.assertEqual(char.hunger, 3)

        # Decrement
        char.hunger -= 1
        self.assertEqual(char.hunger, 2)

    def test_hunger_boundary_increments(self):
        """Test Hunger doesn't exceed boundaries when incremented."""
        char = Character.objects.create(db_key="BoundaryChar")

        # Test upper boundary
        char.hunger = 5
        char.hunger += 1  # Should clamp to 5
        self.assertEqual(char.hunger, 5)

        # Test lower boundary
        char.hunger = 0
        char.hunger -= 1  # Should clamp to 0
        self.assertEqual(char.hunger, 0)

    def test_invalid_hunger_values(self):
        """Test invalid Hunger values are clamped."""
        char = Character.objects.create(db_key="InvalidChar")

        test_cases = [
            (-100, 0),  # Way too low
            (-1, 0),    # Just below minimum
            (6, 5),     # Just above maximum
            (100, 5),   # Way too high
            (0, 0),     # Valid minimum
            (5, 5),     # Valid maximum
        ]

        for invalid, expected in test_cases:
            char.hunger = invalid
            self.assertEqual(char.hunger, expected,
                           f"hunger={invalid} should clamp to {expected}")

    def test_multiple_characters_independent(self):
        """Test multiple characters have independent vampire data."""
        char1 = Character.objects.create(db_key="Char1")
        char2 = Character.objects.create(db_key="Char2")

        char1.hunger = 2
        char1.db.vampire['clan'] = 'Ventrue'

        char2.hunger = 4
        char2.db.vampire['clan'] = 'Brujah'

        # Verify independence
        self.assertEqual(char1.hunger, 2)
        self.assertEqual(char2.hunger, 4)
        self.assertEqual(char1.db.vampire['clan'], 'Ventrue')
        self.assertEqual(char2.db.vampire['clan'], 'Brujah')
