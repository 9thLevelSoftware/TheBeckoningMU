"""
Tests for the Character vampire data structure.

Hunger lives only in db.vampire['hunger'], behind the clamped
Character.hunger property. There is no legacy top-level hunger Attribute and
no migration step.
"""

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

    # F-014/F-063: Rouse reads and writes Hunger through Character.hunger.
    def test_fresh_character_can_rouse(self):
        """A Rouse check on a brand-new character works and raises Hunger on 1-5."""
        with patch("dice.dice_roller.randint", return_value=3):
            result = perform_rouse_check(self.char, reason="test")
        self.assertFalse(result["success"])
        self.assertEqual(self.char.hunger, 2)


class HungerPropertyTestCase(EvenniaTest):
    """Hunger has one store, db.vampire['hunger'], behind Character.hunger."""

    def setUp(self):
        super().setUp()
        self.char = Character.objects.create(db_key="TestHungerChar")

    def test_no_legacy_hunger_attribute(self):
        """There is no top-level hunger Attribute, before or after a write."""
        self.assertFalse(self.char.attributes.has("hunger"))
        self.char.hunger = 3
        self.assertFalse(self.char.attributes.has("hunger"))

    def test_hunger_getter(self):
        """The property reads the vampire dict."""
        self.char.db.vampire['hunger'] = 3
        self.assertEqual(self.char.hunger, 3)

    def test_hunger_setter(self):
        """The property writes the vampire dict, and the write persists."""
        self.char.hunger = 3
        self.char.attributes.reset_cache()
        self.assertEqual(self.char.db.vampire['hunger'], 3)
        self.assertEqual(self.char.hunger, 3)

    def test_hunger_clamping_min(self):
        """Test hunger property clamps to minimum 0."""
        self.char.hunger = -5
        self.assertEqual(self.char.hunger, 0)
        self.assertEqual(self.char.db.vampire['hunger'], 0)

    def test_hunger_clamping_max(self):
        """Test hunger property clamps to maximum 5."""
        self.char.hunger = 10
        self.assertEqual(self.char.hunger, 5)
        self.assertEqual(self.char.db.vampire['hunger'], 5)

    def test_out_of_range_stored_value_is_clamped_on_read(self):
        self.char.db.vampire['hunger'] = 9
        self.assertEqual(self.char.hunger, 5)


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
