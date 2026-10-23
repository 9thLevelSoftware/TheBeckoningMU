"""
Tests for Trait Utility Functions

These run on a real Evennia character, so they see the real Attribute
storage (``_SaverDict``) and the shape ``Character.at_object_creation``
initializes, rather than plain dicts on a Mock.
"""

from evennia.utils.test_resources import EvenniaTest

from commands.v5.utils import trait_utils


class TraitUtilsTestBase(EvenniaTest):
    """A real character with a few traits written into the typeclass shape."""

    def setUp(self):
        super().setUp()
        self.char = self.char1
        stats = self.char.db.stats
        stats["attributes"]["physical"]["strength"] = 3
        stats["attributes"]["mental"]["intelligence"] = 4
        stats["skills"]["physical"]["brawl"] = 2
        stats["skills"]["mental"]["academics"] = 3
        stats["disciplines"]["potence"] = {"level": 2, "powers": []}
        self.char.db.advantages["backgrounds"]["herd"] = 2

    def reload_stats(self):
        """Read stats back from the database, bypassing the Attribute cache."""
        self.char.attributes.reset_cache()
        return self.char.db.stats


class TestTraitUtilsBridgeFunctions(TraitUtilsTestBase):
    """Test the internal bridge functions (_db_get_trait, _db_set_trait)."""

    def test_get_trait_attribute(self):
        self.assertEqual(trait_utils._db_get_trait(self.char, "strength"), 3)
        self.assertEqual(trait_utils._db_get_trait(self.char, "intelligence"), 4)

    def test_get_trait_skill(self):
        self.assertEqual(trait_utils._db_get_trait(self.char, "brawl"), 2)
        self.assertEqual(trait_utils._db_get_trait(self.char, "academics"), 3)

    def test_get_trait_discipline(self):
        self.assertEqual(trait_utils._db_get_trait(self.char, "potence"), 2)

    def test_get_trait_background(self):
        self.assertEqual(trait_utils._db_get_trait(self.char, "herd"), 2)

    def test_get_trait_not_found(self):
        self.assertEqual(trait_utils._db_get_trait(self.char, "nonexistent_trait"), 0)

    def test_set_trait_attribute_persists(self):
        self.assertTrue(trait_utils._db_set_trait(self.char, "strength", 4))
        self.assertEqual(self.reload_stats()["attributes"]["physical"]["strength"], 4)

    def test_set_trait_skill_persists(self):
        self.assertTrue(trait_utils._db_set_trait(self.char, "brawl", 4))
        self.assertEqual(self.reload_stats()["skills"]["physical"]["brawl"], 4)

    def test_set_trait_discipline_persists(self):
        self.assertTrue(trait_utils._db_set_trait(self.char, "potence", 3))
        self.assertEqual(self.reload_stats()["disciplines"]["potence"]["level"], 3)

    def test_set_trait_not_found(self):
        self.assertFalse(trait_utils._db_set_trait(self.char, "nonexistent", 5))


class TestGetTraitValue(TraitUtilsTestBase):
    """Test the get_trait_value public function."""

    def test_get_trait_with_category_hint(self):
        self.assertEqual(trait_utils.get_trait_value(self.char, "strength", category="attribute"), 3)

    def test_get_trait_without_category(self):
        self.assertEqual(trait_utils.get_trait_value(self.char, "strength"), 3)


class TestGetDicePool(TraitUtilsTestBase):
    """Test dice pool calculation."""

    def test_single_trait_pool(self):
        self.assertEqual(trait_utils.get_dice_pool(self.char, "strength"), 3)

    def test_two_trait_pool(self):
        self.assertEqual(trait_utils.get_dice_pool(self.char, "strength", "brawl"), 5)

    def test_pool_with_specialty(self):
        self.assertEqual(trait_utils.get_dice_pool(self.char, "strength", "brawl", specialty=True), 6)
