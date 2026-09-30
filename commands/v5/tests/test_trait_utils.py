"""
Tests for Trait Utility Functions

Tests the trait_utils module that was fixed (BUG-002).
Validates that the internal bridge functions work correctly.
"""

import unittest
from unittest.mock import Mock
from commands.v5.utils import trait_utils


class TestTraitUtilsBridgeFunctions(unittest.TestCase):
    """Test the internal bridge functions (_db_get_trait, _db_set_trait)."""

    def setUp(self):
        """Create a mock character for testing."""
        self.character = Mock()
        self.character.db = Mock()
        self.character.db.stats = {
            'attributes': {
                'physical': {'strength': 3, 'dexterity': 2, 'stamina': 3},
                'social': {'charisma': 2, 'manipulation': 2, 'composure': 3},
                'mental': {'intelligence': 4, 'wits': 3, 'resolve': 3}
            },
            'skills': {
                'physical': {'athletics': 2, 'brawl': 3, 'drive': 0},
                'social': {'intimidation': 2, 'persuasion': 1, 'subterfuge': 0},
                'mental': {'academics': 3, 'investigation': 2, 'occult': 1}
            },
            'disciplines': {
                'potence': {'level': 2, 'powers': []},
                'fortitude': {'level': 1, 'powers': []}
            },
            'specialties': {}
        }
        self.character.db.advantages = {
            'backgrounds': {'herd': 2, 'resources': 3},
            'merits': {},
            'flaws': {}
        }

    def test_get_trait_attribute(self):
        """Test getting an attribute value."""
        value = trait_utils._db_get_trait(self.character, 'strength')
        self.assertEqual(value, 3, "Should get strength value")

        value2 = trait_utils._db_get_trait(self.character, 'intelligence')
        self.assertEqual(value2, 4, "Should get intelligence value")

    def test_get_trait_skill(self):
        """Test getting a skill value."""
        value = trait_utils._db_get_trait(self.character, 'brawl')
        self.assertEqual(value, 3, "Should get brawl value")

        value2 = trait_utils._db_get_trait(self.character, 'academics')
        self.assertEqual(value2, 3, "Should get academics value")

    def test_get_trait_discipline(self):
        """Test getting a discipline level."""
        value = trait_utils._db_get_trait(self.character, 'potence')
        self.assertEqual(value, 2, "Should get potence level")

    def test_get_trait_background(self):
        """Test getting a background value."""
        value = trait_utils._db_get_trait(self.character, 'herd')
        self.assertEqual(value, 2, "Should get herd value")

    def test_get_trait_not_found(self):
        """Test that unknown traits return 0."""
        value = trait_utils._db_get_trait(self.character, 'nonexistent_trait')
        self.assertEqual(value, 0, "Unknown trait should return 0")

    def test_set_trait_attribute(self):
        """Test setting an attribute value."""
        success = trait_utils._db_set_trait(self.character, 'strength', 4)
        self.assertTrue(success, "Should successfully set strength")
        self.assertEqual(self.character.db.stats['attributes']['physical']['strength'], 4)

    def test_set_trait_skill(self):
        """Test setting a skill value."""
        success = trait_utils._db_set_trait(self.character, 'brawl', 4)
        self.assertTrue(success, "Should successfully set brawl")
        self.assertEqual(self.character.db.stats['skills']['physical']['brawl'], 4)

    def test_set_trait_discipline(self):
        """Test setting a discipline level."""
        success = trait_utils._db_set_trait(self.character, 'potence', 3)
        self.assertTrue(success, "Should successfully set potence")
        self.assertEqual(self.character.db.stats['disciplines']['potence']['level'], 3)

    def test_set_trait_not_found(self):
        """Test that setting unknown trait returns False."""
        success = trait_utils._db_set_trait(self.character, 'nonexistent', 5)
        self.assertFalse(success, "Setting unknown trait should return False")


class TestGetTraitValue(unittest.TestCase):
    """Test the get_trait_value public function."""

    def setUp(self):
        """Create a mock character."""
        self.character = Mock()
        self.character.db = Mock()
        self.character.db.stats = {
            'attributes': {
                'physical': {'strength': 3},
            },
            'skills': {
                'physical': {'athletics': 2},
            },
            'disciplines': {},
            'specialties': {}
        }
        self.character.db.advantages = {'backgrounds': {'herd': 2}}

    def test_get_trait_with_category_hint(self):
        """Test getting trait with category hint."""
        value = trait_utils.get_trait_value(self.character, 'strength', category='attribute')
        self.assertEqual(value, 3)

    def test_get_trait_without_category(self):
        """Test getting trait without category hint (auto-detection)."""
        value = trait_utils.get_trait_value(self.character, 'strength')
        self.assertEqual(value, 3)


class TestGetDicePool(unittest.TestCase):
    """Test dice pool calculation."""

    def setUp(self):
        """Create a mock character."""
        self.character = Mock()
        self.character.db = Mock()
        self.character.db.stats = {
            'attributes': {
                'physical': {'strength': 3},
            },
            'skills': {
                'physical': {'brawl': 2},
            },
            'disciplines': {},
            'specialties': {}
        }

    def test_single_trait_pool(self):
        """Test dice pool with single trait."""
        pool = trait_utils.get_dice_pool(self.character, 'strength')
        self.assertEqual(pool, 3, "Should return strength value")

    def test_two_trait_pool(self):
        """Test dice pool with two traits (attribute + skill)."""
        pool = trait_utils.get_dice_pool(self.character, 'strength', 'brawl')
        self.assertEqual(pool, 5, "Should return strength + brawl (3+2=5)")

    def test_pool_with_specialty(self):
        """Test dice pool with specialty bonus."""
        pool = trait_utils.get_dice_pool(self.character, 'strength', 'brawl', specialty=True)
        self.assertEqual(pool, 6, "Should add +1 for specialty (3+2+1=6)")


if __name__ == '__main__':
    unittest.main()
