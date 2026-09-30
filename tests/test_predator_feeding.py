"""
Tests for predator type feeding mechanics.
"""
from evennia.utils.test_resources import EvenniaTest
from commands.v5.utils.predator_utils import get_feeding_pool


class TestPredatorFeeding(EvenniaTest):
    """Test predator type bonuses for feeding."""

    def test_siren_gets_bonus_dice(self):
        """Siren predator type gets +2 dice"""
        self.char1.db.stats = {'predator_type': 'siren'}
        pool, bonus = get_feeding_pool(self.char1)
        self.assertEqual(pool, 'charisma+subterfuge')
        self.assertEqual(bonus, 2)

    def test_default_pool_without_predator_type(self):
        """Default pool is strength+brawl"""
        self.char1.db.stats = {}
        pool, bonus = get_feeding_pool(self.char1)
        self.assertEqual(pool, 'strength+brawl')
        self.assertEqual(bonus, 0)

    def test_alleycat_gets_bonus(self):
        """Alleycat predator type gets +1 die"""
        self.char1.db.stats = {'predator_type': 'Alleycat'}  # Test case insensitivity
        pool, bonus = get_feeding_pool(self.char1)
        self.assertEqual(pool, 'strength+brawl')
        self.assertEqual(bonus, 1)

    def test_osiris_gets_high_bonus(self):
        """Osiris predator type gets +2 dice"""
        self.char1.db.stats = {'predator_type': 'osiris'}
        pool, bonus = get_feeding_pool(self.char1)
        self.assertEqual(pool, 'charisma+performance')
        self.assertEqual(bonus, 2)

    def test_bagger_gets_no_bonus(self):
        """Bagger predator type gets no bonus dice"""
        self.char1.db.stats = {'predator_type': 'bagger'}
        pool, bonus = get_feeding_pool(self.char1)
        self.assertEqual(pool, 'intelligence+streetwise')
        self.assertEqual(bonus, 0)
