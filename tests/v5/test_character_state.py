"""
The one character-state schema and its Character accessors (plan PR 4).

Every test runs on a real Character made with create_object, with no Mocks.
Only the dice are patched (dice.dice_roller.randint).
"""

import re
from unittest.mock import patch

from evennia.utils import create
from evennia.utils.ansi import strip_ansi
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from commands.v5.blood import CmdFeed
from commands.v5.sheet import CmdSheet
from commands.v5.utils import background_utils, blood_utils
from dice.commands import CmdRouse
from traits.models import CharacterBio
from typeclasses.characters import Character, UnknownTrait, WrongCategory
from world import v5_data

RANDINT = "dice.dice_roller.randint"


def new_character(key="Fresh"):
    return create.create_object(Character, key=key)


def sheet_value(sheet, label):
    """The number after "<label>:" and its dot leader on a rendered sheet."""
    match = re.search(rf"{label}:\.*\s*(\d+)", strip_ansi(sheet))
    return int(match.group(1)) if match else None


class FreshCharacterTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_fresh_character_vitals(self):
        self.assertEqual(self.char.hunger, 1)
        self.assertEqual(self.char.willpower_max, 2)  # Composure 1 + Resolve 1
        self.assertEqual(self.char.health_max, 4)  # Stamina 1 + 3
        self.assertEqual(self.char.current_health, 4)
        self.assertEqual(self.char.current_willpower, 2)
        self.assertEqual(self.char.blood_potency, 0)
        self.assertEqual(self.char.humanity, 7)
        self.assertEqual(self.char.stains, 0)
        self.assertEqual(self.char.xp, 0)

    def test_no_legacy_stores(self):
        for key in ("hunger", "blood_potency", "disciplines", "resonance", "willpower", "chargen"):
            self.assertFalse(self.char.attributes.has(key), key)
        self.assertNotIn("approved", self.char.db.stats)

    def test_derived_maximums_are_not_stored(self):
        self.char.set_trait("Stamina", 3)
        self.char.set_trait("Composure", 3)
        self.assertEqual(self.char.health_max, 6)
        self.assertEqual(self.char.willpower_max, 4)
        self.assertEqual(set(self.char.db.pools), {"health", "willpower"})

    def test_creation_does_not_overwrite_existing_stores(self):
        self.char.hunger = 4
        self.char.at_object_creation()
        self.assertEqual(self.char.hunger, 4)


class TraitAccessorTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_set_and_get_any_case(self):
        self.char.set_trait("Animal Ken", 2)
        self.assertEqual(self.char.get_trait("animal_ken"), 2)
        self.assertEqual(self.char.db.stats["skills"]["social"]["animal_ken"], 2)

    def test_discipline_shape(self):
        self.char.set_trait("blood sorcery", 3)
        self.assertEqual(self.char.db.stats["disciplines"]["blood_sorcery"], {"level": 3, "powers": []})
        self.assertEqual(self.char.discipline_levels, {"Blood Sorcery": 3})

    def test_background_lives_in_advantages(self):
        self.char.set_trait("Herd", 2)
        self.assertEqual(self.char.db.advantages["backgrounds"]["herd"], 2)

    def test_unknown_name_raises(self):
        with self.assertRaises(UnknownTrait):
            self.char.set_trait("brawll", 1)
        with self.assertRaises(UnknownTrait):
            self.char.get_trait("Fireball")

    def test_wrong_category_raises(self):
        with self.assertRaises(WrongCategory):
            self.char.get_trait("Strength", "skill")
        with self.assertRaises(WrongCategory):
            self.char.set_trait("Potence", 1, "skills")

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            self.char.set_trait("Strength", 0)
        with self.assertRaises(ValueError):
            self.char.set_trait("Brawl", 6)

    def test_writes_persist(self):
        self.char.set_trait("Strength", 4)
        self.char.attributes.reset_cache()
        self.assertEqual(self.char.get_trait("strength"), 4)

    def test_known_powers(self):
        self.char.set_trait("Animalism", 1)
        self.char.learn_power("sense the beast")
        self.assertEqual(self.char.known_powers, ["Sense the Beast"])
        with self.assertRaises(UnknownTrait):
            self.char.learn_power("Fireball")


class ScalarAccessorTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_clamps(self):
        self.char.hunger = 9
        self.char.blood_potency = 12
        self.char.humanity = -1
        self.char.stains = 11
        self.assertEqual((self.char.hunger, self.char.blood_potency), (5, 10))
        self.assertEqual((self.char.humanity, self.char.stains), (0, 10))

    def test_clan_and_predator_type_are_canonical(self):
        self.char.clan = "brujah"
        self.char.predator_type = "scene queen"
        self.assertEqual((self.char.clan, self.char.predator_type), ("Brujah", "Scene Queen"))
        with self.assertRaises(UnknownTrait):
            self.char.clan = "Fireball"

    def test_damage_drives_current_values(self):
        self.char.set_damage("health", superficial=1, aggravated=1)
        self.char.set_damage("willpower", superficial=1)
        self.assertEqual(self.char.current_health, 2)
        self.assertEqual(self.char.current_willpower, 1)
        self.assertEqual(self.char.damage["health"], {"superficial": 1, "aggravated": 1})

    def test_damage_is_clamped_to_the_track(self):
        self.char.set_damage("health", superficial=3, aggravated=9)
        self.assertEqual(self.char.damage["health"], {"superficial": 0, "aggravated": 4})

    def test_resonance_round_trip(self):
        blood_utils.set_resonance(self.char, "Choleric", intensity=2)
        self.assertEqual(self.char.resonance["type"], "Choleric")
        self.assertEqual(self.char.db.vampire["current_resonance"], "Choleric")
        blood_utils.clear_resonance(self.char)
        self.assertIsNone(self.char.resonance)

    def test_is_approved_reads_character_bio(self):
        self.assertFalse(self.char.is_approved)
        bio = CharacterBio.objects.create(character=self.char, status="submitted")
        self.assertFalse(self.char.is_approved)
        bio.status = "approved"
        bio.save()
        self.assertTrue(self.char.is_approved)


class HerdHungerTests(EvenniaTest):
    """F-066: a Herd hunger reduction is no longer reverted on the next read."""

    def test_herd_reduction_persists(self):
        char = new_character()
        char.set_trait("Herd", 2)
        char.hunger = 4
        result = background_utils.use_herd_to_feed(char)
        self.assertTrue(result["success"])
        char.attributes.reset_cache()
        self.assertEqual(char.hunger, 2)
        self.assertEqual(blood_utils.get_hunger_level(char), 2)


class SheetAndHungerAgreementTests(EvenniaCommandTest):
    """+sheet, rouse and feed all read and write the same Hunger."""

    def setUp(self):
        super().setUp()
        self.char = self.char1

    def sheet(self):
        return self.call(CmdSheet(), "")

    def test_set_trait_shows_on_sheet(self):
        self.char.set_trait("Strength", 4)
        self.char.set_trait("Brawl", 3)
        sheet = self.sheet()
        self.assertEqual(sheet_value(sheet, "Strength"), 4)
        self.assertEqual(sheet_value(sheet, "Brawl"), 3)

    def test_rouse_feed_and_sheet_agree_on_hunger(self):
        # A five-die feeding pool (Strength + Brawl), so Hunger 3 fits in it.
        self.char.set_trait("Strength", 3)
        self.char.set_trait("Brawl", 2)
        self.char.hunger = 2
        with patch(RANDINT, return_value=3):  # failed Rouse
            self.call(CmdRouse(), "")
        self.assertEqual(self.char.hunger, 3)
        self.assertEqual(sheet_value(self.sheet(), "Hunger"), 3)

        with patch(RANDINT, return_value=8):  # successful feeding roll
            self.call(CmdFeed(), "mortal")
        hunger_after_feed = self.char.hunger
        self.assertLess(hunger_after_feed, 3)
        self.assertEqual(blood_utils.get_hunger_level(self.char), hunger_after_feed)
        self.assertEqual(sheet_value(self.sheet(), "Hunger"), hunger_after_feed)


class RulesDataTests(EvenniaTest):
    """world/v5_data.py is the one rules-data source (KD-2)."""

    def test_every_discipline_has_powers(self):
        for name, data in v5_data.DISCIPLINES.items():
            self.assertTrue(data["powers"], name)
        self.assertTrue(v5_data.DISCIPLINES["Potence"]["powers"])

    def test_power_index_matches_disciplines(self):
        total = sum(len(p) for d in v5_data.DISCIPLINES.values() for p in d["powers"].values())
        self.assertEqual(len(v5_data.DISCIPLINE_POWERS), total)
        for power in v5_data.DISCIPLINE_POWERS.values():
            self.assertIn(power["discipline"], v5_data.DISCIPLINES)
            self.assertIn(power["level"], range(1, 6))
            if power.get("amalgam"):
                name, _, level = power["amalgam"].rpartition(" ")
                self.assertIn(name, v5_data.DISCIPLINES, power["name"])
                self.assertIn(int(level), range(1, 6))

    def test_registry_covers_every_trait(self):
        categories = [ref.category for ref in v5_data.TRAIT_REGISTRY.values()]
        self.assertEqual(categories.count("attributes"), 9)
        self.assertEqual(categories.count("skills"), 27)
        self.assertEqual(categories.count("disciplines"), len(v5_data.DISCIPLINES))
        self.assertEqual(categories.count("backgrounds"), len(v5_data.BACKGROUNDS))

    def test_merits_and_flaws_have_dot_ratings(self):
        self.assertTrue(v5_data.MERITS)
        self.assertTrue(v5_data.FLAWS)
        for table in (v5_data.MERITS, v5_data.FLAWS):
            for name, data in table.items():
                self.assertTrue(data["dots"], name)
                self.assertTrue(all(1 <= d <= 5 for d in data["dots"]), name)
