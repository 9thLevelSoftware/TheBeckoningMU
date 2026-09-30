"""
Unit tests for traits utility functions.

Tests the core trait manipulation API:
- Getting and setting character trait values
- Validating trait assignments
- Handling specialties and instanced traits
- Error cases and edge conditions
"""

from django.test import TestCase
from evennia.objects.models import ObjectDB
from traits.models import TraitCategory, Trait, CharacterTrait
from traits.utils import (
    get_character_trait_value,
    set_character_trait_value,
    validate_trait_for_character,
)


class TraitUtilsTestCase(TestCase):
    """Test cases for trait utility functions."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test categories
        self.attr_category = TraitCategory.objects.create(
            name="Test Attributes",
            code="test_attrs",
            sort_order=1
        )

        self.skill_category = TraitCategory.objects.create(
            name="Test Skills",
            code="test_skills",
            sort_order=2
        )

        # Create test traits
        self.strength = Trait.objects.create(
            name="Strength",
            category=self.attr_category,
            min_value=1,
            max_value=5,
            has_specialties=False,
            is_instanced=False
        )

        self.firearms = Trait.objects.create(
            name="Firearms",
            category=self.skill_category,
            min_value=0,
            max_value=5,
            has_specialties=True,
            is_instanced=False
        )

        # Create test character
        self.character = ObjectDB.objects.create(
            db_key="TestCharacter",
            db_typeclass_path="typeclasses.characters.Character"
        )

    def test_set_and_get_trait_value(self):
        """Test setting and getting a basic trait value."""
        # Set trait value
        success = set_character_trait_value(self.character, "Strength", 3)
        self.assertTrue(success)

        # Get trait value
        value = get_character_trait_value(self.character, "Strength")
        self.assertEqual(value, 3)

    def test_set_and_get_trait_with_specialty(self):
        """Test setting and getting a trait with specialty."""
        # Set skill with specialty
        success = set_character_trait_value(
            self.character,
            "Firearms",
            2,
            specialty="Pistols"
        )
        self.assertTrue(success)

        # Get skill value with specialty
        value = get_character_trait_value(
            self.character,
            "Firearms",
            specialty="Pistols"
        )
        self.assertEqual(value, 2)

        # Different specialty should return 0
        value = get_character_trait_value(
            self.character,
            "Firearms",
            specialty="Rifles"
        )
        self.assertEqual(value, 0)

    def test_validate_trait_valid_rating(self):
        """Test trait validation with valid rating."""
        is_valid, msg = validate_trait_for_character(
            self.character,
            "Strength",
            3
        )
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")

    def test_validate_trait_too_high(self):
        """Test trait validation with rating too high."""
        is_valid, msg = validate_trait_for_character(
            self.character,
            "Strength",
            10
        )
        self.assertFalse(is_valid)
        self.assertIn("maximum", msg.lower())

    def test_validate_trait_too_low(self):
        """Test trait validation with rating too low."""
        is_valid, msg = validate_trait_for_character(
            self.character,
            "Strength",
            0
        )
        self.assertFalse(is_valid)
        self.assertIn("minimum", msg.lower())

    def test_validate_trait_nonexistent(self):
        """Test trait validation with non-existent trait."""
        is_valid, msg = validate_trait_for_character(
            self.character,
            "NonExistentTrait",
            3
        )
        self.assertFalse(is_valid)
        self.assertIn("not found", msg.lower())

    def test_get_all_character_traits(self):
        """Test getting all character traits."""
        # Set multiple traits
        set_character_trait_value(self.character, "Strength", 3)
        set_character_trait_value(self.character, "Firearms", 2)

        # Get all traits via model query
        traits = CharacterTrait.objects.filter(character=self.character)
        self.assertEqual(traits.count(), 2)

        # Verify trait values
        trait_names = {ct.trait.name: ct.rating for ct in traits}
        self.assertEqual(trait_names["Strength"], 3)
        self.assertEqual(trait_names["Firearms"], 2)

    def test_get_trait_case_insensitive(self):
        """Test that trait lookup is case-insensitive."""
        # Set trait with standard casing
        set_character_trait_value(self.character, "Strength", 3)

        # Get with different casing
        value = get_character_trait_value(self.character, "strength")
        self.assertEqual(value, 3)

        value = get_character_trait_value(self.character, "STRENGTH")
        self.assertEqual(value, 3)

    def test_update_existing_trait(self):
        """Test updating an existing trait value."""
        # Set initial value
        set_character_trait_value(self.character, "Strength", 2)
        value = get_character_trait_value(self.character, "Strength")
        self.assertEqual(value, 2)

        # Update value
        set_character_trait_value(self.character, "Strength", 4)
        value = get_character_trait_value(self.character, "Strength")
        self.assertEqual(value, 4)

    def test_get_nonexistent_trait(self):
        """Test getting a trait the character doesn't have."""
        value = get_character_trait_value(self.character, "Strength")
        self.assertEqual(value, 0)  # Should return 0 for traits not set

    def test_multiple_specialties_same_skill(self):
        """Test that a character can have multiple specialties in same skill."""
        # Set different specialties
        set_character_trait_value(
            self.character,
            "Firearms",
            2,
            specialty="Pistols"
        )
        set_character_trait_value(
            self.character,
            "Firearms",
            3,
            specialty="Rifles"
        )

        # Verify both exist independently
        pistols = get_character_trait_value(
            self.character,
            "Firearms",
            specialty="Pistols"
        )
        rifles = get_character_trait_value(
            self.character,
            "Firearms",
            specialty="Rifles"
        )

        self.assertEqual(pistols, 2)
        self.assertEqual(rifles, 3)

    def test_skill_without_specialty(self):
        """Test setting a skill without specialty."""
        # Skills can be set without specialty
        success = set_character_trait_value(self.character, "Firearms", 2)
        self.assertTrue(success)

        value = get_character_trait_value(self.character, "Firearms")
        self.assertEqual(value, 2)

    def tearDown(self):
        """Clean up test data."""
        CharacterTrait.objects.all().delete()
        Trait.objects.all().delete()
        TraitCategory.objects.all().delete()
        ObjectDB.objects.filter(db_key="TestCharacter").delete()


class TraitModelTestCase(TestCase):
    """Test cases for trait models themselves."""

    def setUp(self):
        """Set up test fixtures."""
        self.category = TraitCategory.objects.create(
            name="Test Category",
            code="test_cat",
            sort_order=1
        )

    def test_trait_creation(self):
        """Test creating a trait."""
        trait = Trait.objects.create(
            name="Test Trait",
            category=self.category,
            min_value=0,
            max_value=5
        )
        self.assertEqual(trait.name, "Test Trait")
        self.assertEqual(trait.category, self.category)
        self.assertEqual(trait.min_value, 0)
        self.assertEqual(trait.max_value, 5)

    def test_trait_category_relationship(self):
        """Test that traits are properly linked to categories."""
        trait1 = Trait.objects.create(
            name="Trait 1",
            category=self.category,
            min_value=0,
            max_value=5
        )
        trait2 = Trait.objects.create(
            name="Trait 2",
            category=self.category,
            min_value=0,
            max_value=5
        )

        # Test reverse relationship
        category_traits = self.category.traits.all()
        self.assertEqual(category_traits.count(), 2)
        self.assertIn(trait1, category_traits)
        self.assertIn(trait2, category_traits)

    def test_trait_unique_name(self):
        """Test that trait names must be unique."""
        Trait.objects.create(
            name="Unique Trait",
            category=self.category
        )

        # Attempting to create another trait with same name should fail
        with self.assertRaises(Exception):
            Trait.objects.create(
                name="Unique Trait",
                category=self.category
            )

    def tearDown(self):
        """Clean up test data."""
        Trait.objects.all().delete()
        TraitCategory.objects.all().delete()
