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
        self.assertEqual(self.char.blood_potency, 1)  # QR p.3: 13th Generation starts at BP 1
        self.assertEqual(self.char.humanity, 7)
        self.assertEqual(self.char.stains, 0)
        self.assertEqual(self.char.xp, 0)

    def test_no_legacy_stores(self):
        for key in ("hunger", "blood_potency", "disciplines", "resonance", "willpower", "chargen", "effects"):
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


class WriterAccessorTests(EvenniaTest):
    """Writers for specialties, backgrounds, merits/flaws and humanity data."""

    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_a_skill_can_hold_several_specialties(self):
        # An Osiris can end up with two Performance specialties.
        self.char.set_trait("Performance", 2)
        self.assertTrue(self.char.add_specialty("performance", "Dance"))
        self.assertTrue(self.char.add_specialty("Performance", "Preaching"))
        self.assertFalse(self.char.add_specialty("Performance", "dance"))  # duplicate
        self.assertEqual(self.char.specialties, {"performance": ["Dance", "Preaching"]})
        self.assertTrue(self.char.remove_specialty("Performance", "DANCE"))
        self.assertEqual(self.char.specialties, {"performance": ["Preaching"]})

    def test_specialty_needs_a_rated_skill(self):
        with self.assertRaises(ValueError):
            self.char.add_specialty("Brawl", "Grappling")
        with self.assertRaises(WrongCategory):
            self.char.add_specialty("Strength", "Lifting")

    def test_instanced_backgrounds_hold_separate_instances(self):
        self.char.set_background_instance("Allies", "street gang", 2)
        self.char.set_background_instance("allies", "beat cop", 1)
        self.assertEqual(self.char.get_trait("Allies"), 3)
        self.assertEqual(
            self.char.background_instances("Allies"),
            [{"dots": 2, "note": "street gang"}, {"dots": 1, "note": "beat cop"}],
        )
        self.char.set_background_instance("Allies", "Street Gang", 0)
        self.assertEqual(self.char.background_instances("Allies"), [{"dots": 1, "note": "beat cop"}])
        with self.assertRaises(ValueError):
            self.char.set_trait("Allies", 2)
        with self.assertRaises(ValueError):
            self.char.set_background_instance("Herd", "cult", 2)

    def test_merits_and_flaws_are_validated(self):
        self.assertEqual(self.char.set_advantage("merits", "beautiful", 2), 2)
        self.assertEqual(self.char.advantages["merits"], {"Beautiful": 2})
        with self.assertRaises(ValueError):
            self.char.set_advantage("merits", "Beautiful", 3)
        with self.assertRaises(UnknownTrait):
            self.char.set_advantage("flaws", "Fireball", 1)
        self.char.set_advantage("merits", "Beautiful", 0)
        self.assertEqual(self.char.advantages["merits"], {})

    def test_convictions_and_touchstones(self):
        for text in ("Never kill", "Protect children", "Keep promises"):
            self.char.add_conviction(text)
        with self.assertRaises(ValueError):
            self.char.add_conviction("A fourth")
        self.char.add_touchstone("Anna", "sister", 0)
        self.assertEqual(self.char.touchstones[0]["name"], "Anna")
        self.assertEqual(self.char.remove_conviction(1), "Protect children")
        with self.assertRaises(IndexError):
            self.char.remove_touchstone(5)

    def test_bane_and_compulsion_follow_the_clan(self):
        self.assertIsNone(self.char.bane)
        self.char.clan = "brujah"
        self.assertEqual(self.char.bane, v5_data.CLANS["Brujah"]["bane"])
        self.assertEqual(self.char.compulsion, v5_data.CLANS["Brujah"]["compulsion"])
        self.assertNotIn("bane", self.char.db.vampire)


class ValidationTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_numbers_must_be_whole(self):
        for setter in (
            lambda: self.char.set_trait("Wits", 3.7),
            lambda: setattr(self.char, "hunger", True),
            lambda: setattr(self.char, "hunger", None),
            lambda: setattr(self.char, "blood_potency", "3"),
        ):
            with self.assertRaises(ValueError):
                setter()
        self.char.set_trait("Wits", 3.0)
        self.assertEqual(self.char.get_trait("wits"), 3)

    def test_generation_is_bounded(self):
        with self.assertRaises(ValueError):
            self.char.generation = 99
        with self.assertRaises(ValueError):
            self.char.generation = -2
        self.char.generation = 12
        self.assertEqual(self.char.generation, 12)

    def test_resonance_type_is_validated(self):
        with self.assertRaises(UnknownTrait):
            self.char.resonance = {"type": "Bogus", "intensity": 2}
        self.char.resonance = {"type": "sanguine", "intensity": 9}
        self.assertEqual((self.char.resonance["type"], self.char.resonance["intensity"]), ("Sanguine", 3))

    def test_damage_never_exceeds_a_shrunken_track(self):
        self.char.set_trait("Stamina", 4)
        self.char.set_damage("health", superficial=5, aggravated=2)
        self.char.set_trait("Stamina", 1)
        self.assertEqual(self.char.damage["health"], {"superficial": 2, "aggravated": 2})
        self.assertEqual(self.char.current_health, 0)


class DamagedStoreTests(EvenniaTest):
    """Accessors survive missing, partial or old-shape stores."""

    def setUp(self):
        super().setUp()
        self.char = new_character()

    def test_missing_vampire_store(self):
        self.char.db.vampire = None
        self.assertEqual(self.char.hunger, 1)
        self.char.hunger = 3
        self.assertEqual(self.char.db.vampire["hunger"], 3)
        self.assertEqual(self.char.db.vampire["humanity"], 7)

    def test_partial_stats_store(self):
        self.char.db.stats = {"attributes": {}}
        self.assertEqual(self.char.get_trait("strength"), 1)
        self.char.set_trait("strength", 3)
        self.char.set_trait("potence", 2)
        self.assertEqual((self.char.get_trait("strength"), self.char.get_trait("potence")), (3, 2))

    def test_bare_int_discipline_keeps_its_level(self):
        self.char.db.stats["disciplines"]["potence"] = 2  # old web-import shape
        self.char.learn_power("Lethal Body")
        self.assertEqual(self.char.get_trait("potence"), 2)
        self.assertIn("Lethal Body", self.char.known_powers)


class SpendRefusalTests(EvenniaTest):
    """+spend refuses names that aren't traits of that kind, without charging."""

    def setUp(self):
        super().setUp()
        self.char = new_character()
        self.char.db.experience["total_earned"] = 20

    def test_unknown_names_are_refused_for_free(self):
        from commands.v5.utils import xp_utils

        for spend, name in (
            (xp_utils.spend_xp_on_attribute, "fooo"),
            (xp_utils.spend_xp_on_skill, "brawll"),
            (xp_utils.spend_xp_on_discipline, "Fireball"),
        ):
            ok, message = spend(self.char, name)
            self.assertFalse(ok, name)
            self.assertIn("Unknown trait", message)
        self.assertEqual(self.char.xp, 20)

    def test_xp_is_earned_minus_spent(self):
        from commands.v5.utils import xp_utils

        ok, _ = xp_utils.spend_xp_on_skill(self.char, "Brawl")
        self.assertTrue(ok)
        self.assertEqual((self.char.xp_earned, self.char.xp_spent, self.char.xp), (20, 3, 17))
        self.assertNotIn("current", self.char.db.experience)
