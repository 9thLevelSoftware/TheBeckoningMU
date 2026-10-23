"""Canonical chargen snapshots, gameplay compatibility, and rollback evidence."""

import copy
from unittest.mock import patch

from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaTest

from commands.v5.utils.trait_utils import get_trait_value
from traits.models import CharacterBio, CharacterPower, CharacterTrait, DisciplinePower, Trait, TraitCategory
from traits.utils import enhanced_import_character_from_json, export_character_to_json, set_character_trait_value
from typeclasses.characters import Character
from world.v5_data import ATTRIBUTES, SKILLS


class CharacterImportExportTests(EvenniaTest):
    character_typeclass = Character

    def setUp(self):
        super().setUp()
        categories = {
            code: TraitCategory.objects.create(name=code.title(), code=code)
            for code in ("attributes", "skills", "disciplines", "advantages", "flaws")
        }
        for code, definitions in (("attributes", ATTRIBUTES), ("skills", SKILLS)):
            for names in definitions.values():
                for name in names:
                    Trait.objects.create(
                        name=name,
                        category=categories[code],
                        min_value=int(code == "attributes"),
                        has_specialties=code == "skills",
                    )
        self.celerity = Trait.objects.create(
            name="Celerity", category=categories["disciplines"], splat_restriction="vampire"
        )
        Trait.objects.create(name="Potence", category=categories["disciplines"], splat_restriction="vampire")
        Trait.objects.create(name="Resources", category=categories["advantages"])
        Trait.objects.create(name="Allies", category=categories["advantages"], is_instanced=True, has_specialties=True)
        Trait.objects.create(name="Enemy", category=categories["flaws"], is_instanced=True)
        self.power = DisciplinePower.objects.create(
            name="Fleetness",
            discipline=self.celerity,
            level=2,
            description="A test power",
        )
        self.payload = {
            "name": "Snapshot Vampire",
            "splat": "vampire",
            "clan": "Brujah",
            "generation": 12,
            "concept": "Night courier",
            "sire": "Mara",
            "predator_type": "Alleycat",
            "predator_discipline": "Potence",
            "ambition": "Own a haven",
            "desire": "Find a friend",
            "background": "A local story",
            "disciplines": {"Celerity": 2, "Potence": 2},
            "advantages": {
                "Resources": {"value": 4},
                "Allies": {"value": 3, "instance": "Neighbors", "specialty": "Night watch"},
            },
            "flaws": {"Enemy": {"value": 1, "instance": "Hunters"}},
            "specialties": {"Firearms": {"Pistols": 1}},
            "discipline_powers": ["Fleetness"],
        }
        for names, ratings in (
            ([name for group in ATTRIBUTES.values() for name in group], [4, 3, 3, 3, 3, 2, 2, 2, 2]),
            (
                [name for group in SKILLS.values() for name in group],
                [3, 2, 2, 1, 1, 1, 1, 1, 1] + [1] * 9 + [1] * 5 + [0] * 4,
            ),
        ):
            self.payload.update(
                {name.lower().replace(" ", "_"): rating for name, rating in zip(names, ratings, strict=True)}
            )

    def _snapshot(self):
        return {
            "attributes": list(self.char1.db_attributes.order_by("pk").values()),
            "traits": list(CharacterTrait.objects.filter(character=self.char1).order_by("pk").values()),
            "powers": list(CharacterPower.objects.filter(character=self.char1).order_by("pk").values()),
            "bio": list(CharacterBio.objects.filter(character=self.char1).values()),
        }

    def test_import_populates_real_gameplay_schema_and_metadata(self):
        result = enhanced_import_character_from_json(self.char1, self.payload)
        self.assertTrue(result["success"], result)
        self.assertEqual(get_trait_value(self.char1, "Strength"), 4)
        self.assertEqual(get_trait_value(self.char1, "Animal Ken"), 1)
        self.assertEqual(get_trait_value(self.char1, "Celerity"), 2)
        self.assertEqual(self.char1.db.stats["disciplines"]["celerity"], {"level": 2, "powers": ["Fleetness"]})
        self.assertEqual(self.char1.db.advantages["backgrounds"]["allies_neighbors"], 3)
        self.assertEqual(self.char1.db.advantages["flaws"]["enemy_hunters"], 1)
        self.assertEqual(self.char1.db.vampire["clan"], "Brujah")
        self.assertEqual(self.char1.db.vampire["generation"], 12)
        self.assertEqual(self.char1.db.vampire["predator_type"], "Alleycat")
        self.assertEqual(self.char1.db.pools["health"], 6)
        self.assertEqual(self.char1.db.pools["willpower"], 4)

    def test_export_roundtrip_keeps_frontend_maps_structured_choices_and_powers(self):
        self.assertTrue(enhanced_import_character_from_json(self.char1, self.payload)["success"])
        exported = export_character_to_json(self.char1)
        self.assertEqual(exported["attributes"]["strength"], 4)
        self.assertEqual(exported["skills"]["animal_ken"], 1)
        self.assertEqual(exported["strength"], 4)
        self.assertEqual(exported["advantages"], self.payload["advantages"])
        self.assertEqual(exported["flaws"], self.payload["flaws"])
        self.assertEqual(exported["predator_discipline"], "Potence")
        self.assertEqual(exported["specialties"]["firearms"], {"Pistols": 1})
        result = enhanced_import_character_from_json(self.char2, exported)
        self.assertTrue(result["success"], result)
        self.assertEqual(export_character_to_json(self.char2), exported)

    def test_validation_only_uses_submitted_power_levels_and_writes_nothing(self):
        before = self._snapshot()
        result = enhanced_import_character_from_json(ObjectDB(), self.payload, validate_only=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.char1.db.stats["disciplines"], {})

    def test_shape_type_category_and_power_errors_write_nothing(self):
        invalid = [
            ("skills", []),
            ("disciplines", []),
            ("advantages", []),
            ("specialties", []),
            ("discipline_powers", "Fleetness"),
            ("clan", []),
            ("generation", True),
            ("strength", 3.0),
            ("animal_ken", True),
            ("advantages", {"Resources": {"value": 4}, "Celerity": {"value": 3}}),
            ("advantages", {"Resources": {"value": 4}, "Allies": {"value": 3, "instance": []}}),
            ("advantages", {"Resources": {"value": 7}}),
            ("discipline_powers", ["Unknown Power"]),
            ("specialties", {"Firearms": {"Pistols": True}}),
        ]
        before = self._snapshot()
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(self.payload)
                data[field] = value
                result = enhanced_import_character_from_json(self.char1, data)
                self.assertFalse(result["success"], result)
                self.assertTrue(result["validation_errors"])
                self.assertEqual(self._snapshot(), before)

    def test_power_requirements_do_not_use_existing_character_levels(self):
        self.power.level = 3
        self.power.save()
        set_character_trait_value(self.char1, "Celerity", 5)
        before = self._snapshot()
        result = enhanced_import_character_from_json(self.char1, self.payload, validate_only=True)
        self.assertFalse(result["success"])
        self.assertEqual(self._snapshot(), before)

    def test_conflicting_flat_and_export_maps_are_rejected(self):
        data = copy.deepcopy(self.payload)
        data["attributes"] = {"strength": 1}
        result = enhanced_import_character_from_json(self.char1, data)
        self.assertFalse(result["success"])
        self.assertIn("Conflicting values for strength", result["validation_errors"])

    def test_mid_write_failure_restores_rows_cached_attribute_and_new_attribute_cache(self):
        set_character_trait_value(self.char1, "Strength", 2)
        held = self.char1.attributes.get("stats", return_obj=True)
        held_before = copy.deepcopy(held.db_value)
        before = self._snapshot()
        original = set_character_trait_value
        calls = 0
        new_attribute = None

        def fail_after_first(*args, **kwargs):
            nonlocal calls, new_attribute
            calls += 1
            if calls == 2:
                self.char1.db.import_transient = "rolled back"
                new_attribute = self.char1.attributes.get("import_transient", return_obj=True)
                return False
            return original(*args, **kwargs)

        with patch("traits.utils.set_character_trait_value", side_effect=fail_after_first):
            result = enhanced_import_character_from_json(self.char1, self.payload)
        self.assertFalse(result["success"])
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(held.db_value, held_before)
        self.assertEqual(held.value["attributes"]["physical"]["strength"], 2)
        self.assertEqual(self.char1.db.stats["attributes"]["physical"]["strength"], 2)
        self.assertIsNone(self.char1.db.import_transient)
        self.assertNotIn(new_attribute.pk, type(new_attribute).__dbclass__.__instance_cache__)

    def test_snapshot_replaces_omitted_traits_and_zero_skills(self):
        self.assertTrue(enhanced_import_character_from_json(self.char1, self.payload)["success"])
        data = copy.deepcopy(self.payload)
        data["discipline_powers"] = []
        data["science"], data["academics"] = 1, 0
        data["advantages"] = {"Resources": {"value": 5}, "Allies": {"value": 2, "instance": "Neighbors"}}
        result = enhanced_import_character_from_json(self.char1, data)
        self.assertTrue(result["success"], result)
        self.assertEqual(get_trait_value(self.char1, "Academics"), 0)
        self.assertEqual(self.char1.db.stats["disciplines"]["celerity"]["powers"], [])
        self.assertFalse(CharacterPower.objects.filter(character=self.char1).exists())
        self.assertFalse(CharacterTrait.objects.filter(character=self.char1, trait__name="Academics").exists())
        self.assertEqual(
            export_character_to_json(self.char1)["advantages"]["Allies"], {"value": 2, "instance": "Neighbors"}
        )

    def test_multiple_instances_export_without_key_collision(self):
        data = copy.deepcopy(self.payload)
        data["advantages"]["Allies"] = [{"value": 1, "instance": "Neighbors"}, {"value": 2, "instance": "Coworkers"}]
        result = enhanced_import_character_from_json(self.char1, data)
        self.assertTrue(result["success"], result)
        exported = export_character_to_json(self.char1)
        self.assertEqual(exported["advantages"]["Allies"], data["advantages"]["Allies"])
        self.assertTrue(enhanced_import_character_from_json(self.char2, exported)["success"])

    def test_prepared_gameplay_snapshot_cannot_mutate_saved_power_lists(self):
        from traits.utils import _gameplay_stats

        self.char1.db.stats["disciplines"]["celerity"] = {"level": 2, "powers": ["Fleetness"]}
        snapshot = _gameplay_stats(self.char1)
        snapshot["disciplines"]["celerity"]["powers"].append("Uncommitted Power")
        self.assertEqual(list(self.char1.db.stats["disciplines"]["celerity"]["powers"]), ["Fleetness"])
