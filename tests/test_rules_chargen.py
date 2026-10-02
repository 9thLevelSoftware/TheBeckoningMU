"""
world.rules_chargen: the submission schema, the V5 creation validator and the
writer. Rules are the V5 core book's (QR p.2-3), read from world/v5_data.py.
"""

from unittest import mock

from django.test import SimpleTestCase
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from tests.chargen_fixtures import ancilla_payload, legal_payload, thin_blood_payload, zero_skills
from world import v5_data
from world.rules_chargen import (
    SubmissionError,
    apply_chargen,
    build_sheet,
    parse_submission,
    skill_distribution,
    validate_v5_creation,
)


def errors_for(payload):
    """Shape errors, or else rule errors, for a payload."""
    try:
        sub = parse_submission(payload)
    except SubmissionError as err:
        return err.errors
    return validate_v5_creation(sub)


def assert_rejected(test, payload, fragment):
    errors = errors_for(payload)
    test.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")


def skills_with(distribution):
    """A skills map following {rating: count}, filling skills in fixture order."""
    skills = zero_skills()
    names = [s for s in skills if s not in ("academics", "craft", "performance", "science")]
    for rating, count in sorted(distribution.items(), reverse=True):
        for _ in range(count):
            skills[names.pop(0)] = rating
    return skills


class ShapeTests(SimpleTestCase):
    def test_legal_payload_parses_and_validates(self):
        self.assertEqual(errors_for(legal_payload()), [])

    def test_non_object_bodies_are_rejected(self):
        for body in ([], "x", 3, None):
            with self.assertRaises(SubmissionError):
                parse_submission(body)

    def test_unknown_top_level_key(self):
        payload = legal_payload()
        payload["approved"] = True
        assert_rejected(self, payload, "Unknown key(s): approved")

    def test_smuggled_dict_in_an_item_is_rejected(self):
        """F-056: extra keys inside an advantage must not slip through."""
        payload = legal_payload()
        payload["advantages"][0]["value"] = {"dots": 5, "stats": {"strength": 5}}
        assert_rejected(self, payload, "unknown key(s) value")

    def test_unknown_inner_keys_are_rejected(self):
        payload = legal_payload()
        payload["attributes"]["luck"] = 3
        assert_rejected(self, payload, "attributes: unknown key 'luck'")
        payload = legal_payload()
        payload["specialties"][0]["dots"] = 2
        assert_rejected(self, payload, "unknown key(s) dots")
        payload = legal_payload(disciplines={"Potence": 2, "Presence": 1, "Celerity": 1, "Oblivion": 1})
        assert_rejected(self, payload, "unknown discipline 'Oblivion'")

    def test_missing_keys(self):
        payload = legal_payload()
        del payload["skills"]["brawl"]
        assert_rejected(self, payload, "skills: missing Brawl")
        payload = legal_payload()
        del payload["age"]
        assert_rejected(self, payload, "Missing key(s): age")

    def test_wrong_types(self):
        payload = legal_payload()
        payload["attributes"]["strength"] = "4"
        assert_rejected(self, payload, "Strength must be a whole number")
        payload = legal_payload()
        payload["attributes"]["strength"] = True
        assert_rejected(self, payload, "Strength must be a whole number")
        assert_rejected(self, legal_payload(generation="13"), "generation: must be a whole number")

    def test_background_is_capped(self):
        assert_rejected(self, legal_payload(background="x" * 10001), "background: at most 10000")
        self.assertEqual(errors_for(legal_payload(background="x" * 10000)), [])


class IdentityTests(SimpleTestCase):
    def test_name_rules(self):
        for name in ("X", "Bob|r", "9Lives", "Robert'); DROP", "A" * 31):
            assert_rejected(self, legal_payload(name=name), "Name:")
        for name in ("Jo", "Mary-Kate O'Neil"):
            self.assertEqual(errors_for(legal_payload(name=name)), [], name)

    def test_clan_must_be_a_core_clan(self):
        for clan in ("Lasombra", "Banu Haqim", "Ministry"):
            assert_rejected(self, legal_payload(clan=clan), f"Clan: '{clan}' is not available")

    def test_predator_type_must_be_known(self):
        assert_rejected(self, legal_payload(predator_type="Vegan"), "'Vegan' is not a predator type")

    def test_generation_must_fit_the_age(self):
        assert_rejected(self, legal_payload(generation=11), "Generation: a Neonate is of generation 12, 13")
        assert_rejected(self, legal_payload(age="Elder"), "Age: choose one of")

    def test_thin_bloods_and_childer_take_no_predator_type(self):
        assert_rejected(self, thin_blood_payload(predator_type="Alleycat"), "take no predator type")
        childer = legal_payload(age="Childer", predator_type=None)
        childer["specialties"] = [{"skill": "brawl", "name": "Boxing"}]
        childer["disciplines"] = {"Potence": 2, "Presence": 1}
        childer["discipline_powers"] = ["Lethal Body", "Prowess", "Awe"]
        self.assertEqual(errors_for(childer), [])
        # Owner decision: Childer may take a predator type, but needn't.
        self.assertEqual(errors_for(legal_payload(age="Childer")), [])

    def test_other_clans_need_a_predator_type(self):
        assert_rejected(self, legal_payload(predator_type=None), "Predator type: choose one")

    def test_thin_blood_generation(self):
        assert_rejected(self, legal_payload(age="Childer", generation=14, predator_type=None), "are thin-bloods")
        assert_rejected(self, thin_blood_payload(generation=13), "thin-bloods are of the 14th-16th")


class AttributeAndSkillTests(SimpleTestCase):
    def test_attribute_spread(self):
        payload = legal_payload()
        # 4/4/3/3/2/2/2/1/1 is not the V5 spread.
        payload["attributes"].update({"dexterity": 4, "stamina": 3, "wits": 1})
        assert_rejected(self, payload, "Attributes: rate them 4/3/3/3/2/2/2/2/1")

    def test_v20_payload_is_rejected(self):
        """The old form's 7/5/3 attributes and 13/9/5 skills are not V5 creation."""
        attributes = {
            "strength": 4, "dexterity": 3, "stamina": 3,  # +7
            "charisma": 3, "manipulation": 3, "composure": 2,  # +5
            "intelligence": 2, "wits": 2, "resolve": 2,  # +3
        }  # fmt: skip
        skills = zero_skills()
        skills.update({"athletics": 3, "brawl": 3, "drive": 3, "firearms": 2, "melee": 2})  # 13
        skills.update({"insight": 3, "intimidation": 2, "persuasion": 2, "streetwise": 2})  # 9
        skills.update({"awareness": 1, "finance": 1, "investigation": 1, "medicine": 1, "occult": 1})  # 5
        errors = errors_for(legal_payload(attributes=attributes, skills=skills))
        self.assertTrue(any(e.startswith("Attributes:") for e in errors), errors)
        self.assertTrue(any(e.startswith("Skills:") for e in errors), errors)

    def test_each_skill_distribution_is_accepted(self):
        for name, distribution in v5_data.CREATION_SKILL_DISTRIBUTIONS.items():
            skills = skills_with(distribution)
            self.assertEqual(skill_distribution(skills), name)
            payload = legal_payload(skills=skills, specialties=[
                {"skill": "athletics", "name": "Running"},
                {"skill": "brawl", "name": "Grappling"},
            ])  # fmt: skip
            self.assertEqual(errors_for(payload), [], name)

    def test_a_broken_distribution_is_rejected(self):
        payload = legal_payload()
        payload["skills"]["survival"] = 1  # eight 1s with Balanced's 3s and 2s
        assert_rejected(self, payload, "Skills: use one distribution")


class SpecialtyTests(SimpleTestCase):
    def test_specialty_needs_a_rated_skill(self):
        payload = legal_payload()
        payload["specialties"][1] = {"skill": "finance", "name": "Banking"}
        assert_rejected(self, payload, "Finance (Banking) needs at least one dot in Finance")

    def test_free_specialty_for_rated_academics(self):
        payload = legal_payload()
        payload["skills"].update(occult=0, academics=1)
        assert_rejected(self, payload, "Specialties: take 3")
        payload["specialties"].append({"skill": "brawl", "name": "Kicks"})
        assert_rejected(self, payload, "Specialties: take one free specialty in each")
        payload["specialties"][-1] = {"skill": "academics", "name": "History"}
        self.assertEqual(errors_for(payload), [])

    def test_predator_specialty_is_required(self):
        payload = legal_payload()
        payload["specialties"][0] = {"skill": "brawl", "name": "Kicks"}
        assert_rejected(self, payload, "Alleycat gives one of Intimidation (Stickups), Brawl (Grappling)")

    def test_placeholder_specialties_take_any_name(self):
        payload = legal_payload(predator_type="Scene Queen", disciplines={"Potence": 2, "Presence": 2})
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Awe", "Lingering Kiss"]
        payload["skills"].update(etiquette=1, occult=0)
        payload["specialties"] = [
            {"skill": "etiquette", "name": "Goth clubs"},
            {"skill": "brawl", "name": "Boxing"},
        ]
        payload["flaws"].append({"name": "Disliked", "dots": 1, "source": "predator"})
        self.assertEqual(errors_for(payload), [])

    def test_duplicate_specialty(self):
        payload = legal_payload()
        payload["specialties"][1] = {"skill": "intimidation", "name": "stickups"}
        assert_rejected(self, payload, "is listed twice")


class DisciplineTests(SimpleTestCase):
    def test_out_of_clan_discipline(self):
        payload = legal_payload(disciplines={"Auspex": 2, "Presence": 1, "Celerity": 1})
        payload["discipline_powers"] = ["Heightened Senses", "Premonition", "Awe", "Rapid Reflexes"]
        assert_rejected(
            self, payload, "Disciplines: 2 dots in one and 1 in another of two of Celerity, Potence, Presence"
        )

    def test_predator_dot_can_stack(self):
        payload = legal_payload(disciplines={"Potence": 3, "Presence": 1})
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Brutal Feed", "Awe"]
        self.assertEqual(errors_for(payload), [])

    def test_wrong_total(self):
        payload = legal_payload(disciplines={"Potence": 2, "Presence": 2, "Celerity": 1})
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Awe", "Lingering Kiss", "Rapid Reflexes"]
        assert_rejected(self, payload, "Disciplines: 2 dots in one")

    def test_blood_sorcery_predator_dot_is_tremere_only(self):
        payload = legal_payload(clan="Ventrue", predator_type="Osiris")
        payload["disciplines"] = {"Dominate": 2, "Fortitude": 1, "Blood Sorcery": 1}
        payload["discipline_powers"] = ["Cloud Memory", "Mesmerize", "Resilience", "A Taste for Blood"]
        payload["specialties"][0] = {"skill": "occult", "name": "Voodoo"}
        payload["advantages"].append({"name": "Fame", "dots": 3, "source": "predator"})
        payload["flaws"].append({"name": "Enemy", "dots": 2, "source": "predator"})
        assert_rejected(self, payload, "plus 1 dot from Osiris in one of Presence")

        payload["clan"] = "Tremere"
        payload["disciplines"] = {"Auspex": 2, "Dominate": 1, "Blood Sorcery": 1}
        payload["discipline_powers"] = ["Heightened Senses", "Premonition", "Cloud Memory", "A Taste for Blood"]
        assert_rejected(self, payload, "Rituals: Blood Sorcery gives one level-1 ritual")
        payload["rituals"] = ["Blood Walk"]
        self.assertEqual(errors_for(payload), [])

    def test_caitiff_take_any_two(self):
        payload = legal_payload(clan="Caitiff", disciplines={"Auspex": 2, "Fortitude": 1, "Celerity": 1})
        payload["discipline_powers"] = ["Heightened Senses", "Premonition", "Resilience", "Rapid Reflexes"]
        self.assertEqual(errors_for(payload), [])

    def test_thin_blood_disciplines(self):
        assert_rejected(self, thin_blood_payload(disciplines={"Auspex": 1}, discipline_powers=["Premonition"]),
                        "thin-bloods start with no Disciplines")  # fmt: skip
        payload = thin_blood_payload(disciplines={"Thin-Blood Alchemy": 1})
        payload["advantages"].append({"name": "Thin-blood Alchemist", "dots": 1})
        payload["flaws"].append({"name": "Bestial Temper", "dots": 1})
        assert_rejected(self, payload, "Formulas: Thin-blood Alchemist gives one formula")
        payload["formulas"] = ["Envelop"]
        assert_rejected(self, payload, "of level 1 or lower")
        payload["formulas"] = ["Far Reach"]
        self.assertEqual(errors_for(payload), [])
        assert_rejected(self, legal_payload(disciplines={"Thin-Blood Alchemy": 1}), "for thin-bloods only")


class PowerTests(SimpleTestCase):
    def test_level_3_power_on_a_1_dot_discipline(self):
        payload = legal_payload()
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Entrancement", "Rapid Reflexes"]
        assert_rejected(self, payload, "Powers: Entrancement needs Presence 3; you have 1")

    def test_power_from_a_discipline_the_character_lacks(self):
        payload = legal_payload()
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Awe", "Heightened Senses"]
        assert_rejected(self, payload, "Heightened Senses is a Auspex power and you have no Auspex")

    def test_one_power_per_dot(self):
        payload = legal_payload()
        payload["discipline_powers"] = ["Lethal Body", "Awe", "Rapid Reflexes"]
        assert_rejected(self, payload, "take one Potence power per dot (2); you listed 1")

    def test_amalgam_prerequisite(self):
        payload = legal_payload(clan="Malkavian", predator_type="Sandman")
        payload["disciplines"] = {"Dominate": 2, "Auspex": 1, "Obfuscate": 1}
        payload["discipline_powers"] = ["Compel", "Dementation", "Premonition", "Cloak of Shadows"]
        payload["specialties"][0] = {"skill": "stealth", "name": "Break-in"}
        assert_rejected(self, payload, "Dementation also needs Obfuscate 2")

    def test_unknown_power(self):
        payload = legal_payload()
        payload["discipline_powers"][0] = "Fireball"
        assert_rejected(self, payload, "unknown power 'Fireball'")


class AdvantageTests(SimpleTestCase):
    def test_neonate_with_nine_advantage_dots(self):
        payload = legal_payload()
        payload["advantages"].append({"name": "Herd", "dots": 2})
        assert_rejected(self, payload, "Advantages: spend at most 7 dots; you spent 9")

    def test_ancilla_with_nine_advantage_dots(self):
        self.assertEqual(errors_for(ancilla_payload()), [])

    def test_flaws_must_total_two(self):
        payload = legal_payload(flaws=[{"name": "Known Corpse", "dots": 1}])
        assert_rejected(self, payload, "Flaws: take exactly 2 dots of flaws; you took 1")

    def test_unknown_merit_and_illegal_dots(self):
        payload = legal_payload()
        payload["advantages"][3] = {"name": "Iron Will", "dots": 1}
        assert_rejected(self, payload, "unknown advantage 'Iron Will'")
        payload["advantages"][3] = {"name": "Beautiful", "dots": 1}
        assert_rejected(self, payload, "Beautiful is taken at 2 dots, not 1")
        payload["advantages"][3] = {"name": "Haven", "dots": 4}
        assert_rejected(self, payload, "Haven is rated 1-3, not 4")

    def test_instanced_background_needs_a_note(self):
        payload = legal_payload()
        del payload["advantages"][2]["note"]
        assert_rejected(self, payload, "each Allies needs a note")
        payload["advantages"][2]["note"] = "Criminals"
        payload["advantages"][2]["name"] = "Contacts"
        assert_rejected(self, payload, "two Contacts share the note")

    def test_predator_grants_are_added(self):
        sheet = build_sheet(parse_submission(legal_payload()))
        self.assertIn(("Contacts", "criminals", 3), sheet.background_instances)
        self.assertEqual((sheet.humanity, sheet.blood_potency, sheet.xp), (6, 1, 15))

    def test_predator_choices(self):
        payload = legal_payload(clan="Tremere", predator_type="Osiris")
        payload["disciplines"] = {"Auspex": 2, "Dominate": 1, "Presence": 1}
        payload["discipline_powers"] = ["Heightened Senses", "Premonition", "Cloud Memory", "Awe"]
        payload["specialties"][0] = {"skill": "occult", "name": "Santeria"}
        assert_rejected(self, payload, "Osiris gives 3 dots among Fame, Herd")
        payload["advantages"] += [
            {"name": "Fame", "dots": 1, "source": "predator"},
            {"name": "Herd", "dots": 2, "source": "predator"},
        ]
        assert_rejected(self, payload, "Osiris gives 2 dots among Enemy, any Mythical flaw")
        payload["flaws"].append({"name": "Stake Bait", "dots": 2, "source": "predator"})
        self.assertEqual(errors_for(payload), [])
        payload["flaws"][-1] = {"name": "Destitute", "dots": 1, "source": "predator"}
        assert_rejected(self, payload, "Destitute is not one of Osiris's choices")

    def test_choice_marker_without_a_choice(self):
        payload = legal_payload()
        payload["flaws"].append({"name": "Enemy", "dots": 1, "source": "predator"})
        assert_rejected(self, payload, "Alleycat gives no flaws to choose")


class RestrictionTests(SimpleTestCase):
    def test_nosferatu_take_repulsive_and_no_looks_merits(self):
        payload = legal_payload(clan="Nosferatu", disciplines={"Potence": 2, "Obfuscate": 1, "Celerity": 1})
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Cloak of Shadows", "Rapid Reflexes"]
        sub = parse_submission(payload)
        self.assertEqual(validate_v5_creation(sub), [])
        self.assertEqual(build_sheet(sub).flaws["Repulsive"], 2)
        payload["advantages"][3] = {"name": "Beautiful", "dots": 2}
        assert_rejected(self, payload, "can't take Beautiful")

    def test_caitiff_take_suspect(self):
        payload = legal_payload(clan="Caitiff")
        self.assertEqual(build_sheet(parse_submission(payload)).flaws["Suspect"], 1)

    def test_ventrue_restrictions(self):
        payload = legal_payload(clan="Ventrue", predator_type="Bagger")
        assert_rejected(self, payload, "Ventrue can't take Bagger")
        payload = legal_payload(clan="Ventrue", predator_type="Siren")
        payload["flaws"] = [{"name": "Farmer", "dots": 2}]
        assert_rejected(self, payload, "Ventrue can't take Farmer")

    def test_farmer_needs_low_blood_potency(self):
        """Every starting age is BP 2 or lower, so check the table field directly."""
        self.assertEqual(v5_data.PREDATOR_TYPES["Farmer"]["max_blood_potency"], 2)

    def test_mask_merits_need_mask_two(self):
        payload = legal_payload()
        payload["advantages"][3] = {"name": "Zeroed", "dots": 1}
        assert_rejected(self, payload, "Zeroed needs Mask 2")


class ThinBloodTests(SimpleTestCase):
    def test_legal_thin_blood(self):
        sub = parse_submission(thin_blood_payload())
        self.assertEqual(validate_v5_creation(sub), [])
        self.assertEqual(build_sheet(sub).blood_potency, 0)

    def test_pairs_must_match(self):
        payload = thin_blood_payload()
        payload["flaws"].pop()  # drop Baby Teeth
        assert_rejected(self, payload, "Thin-blood: take 1-3 thin-blood merits and the same number")

    def test_thin_blood_items_are_for_thin_bloods(self):
        payload = legal_payload()
        payload["advantages"].append({"name": "Lifelike", "dots": 1})
        payload["flaws"].append({"name": "Baby Teeth", "dots": 1})
        assert_rejected(self, payload, "Thin-blood merits and flaws are for thin-bloods only")

    def test_exclusions(self):
        payload = thin_blood_payload()
        payload["flaws"][2] = {"name": "Dead Flesh", "dots": 1}
        assert_rejected(self, payload, "can't be taken together")

    def test_clan_curse_prerequisite(self):
        payload = thin_blood_payload()
        payload["flaws"][2] = {"name": "Clan Curse", "dots": 1, "note": "Brujah"}
        assert_rejected(self, payload, "Clan Curse (Brujah) needs Bestial Temper")
        payload["flaws"][2]["note"] = "Toreador"
        self.assertEqual(errors_for(payload), [])


class ApplyChargenTests(EvenniaTest):
    def test_apply_writes_the_validated_sheet(self):
        sub = parse_submission(legal_payload())
        self.assertEqual(validate_v5_creation(sub), [])
        char = create.create_object("typeclasses.characters.Character", key="Mara Voss")
        apply_chargen(char, sub)

        self.assertEqual(char.get_trait("strength"), 4)
        self.assertEqual(char.get_trait("resolve"), 1)
        self.assertEqual(char.get_trait("intimidation"), 3)
        self.assertEqual(char.get_trait("craft"), 0)
        self.assertEqual(char.discipline_levels, {"Celerity": 1, "Potence": 2, "Presence": 1})
        self.assertCountEqual(char.known_powers, ["Lethal Body", "Prowess", "Awe", "Rapid Reflexes"])
        self.assertEqual(char.specialties, {"intimidation": ["Stickups"], "brawl": ["Boxing"]})
        self.assertEqual((char.clan, char.predator_type, char.generation), ("Brujah", "Alleycat", 13))
        self.assertEqual((char.blood_potency, char.humanity, char.hunger), (1, 6, 1))
        self.assertEqual(char.get_trait("resources"), 2)
        self.assertEqual(char.background_instances("contacts"), [{"dots": 3, "note": "criminals"}])
        self.assertEqual(char.advantages["merits"], {"Linguistics": 1})
        self.assertEqual(char.advantages["flaws"], {"Addiction": 1, "Known Corpse": 1})
        self.assertEqual(char.xp, 15)
        self.assertEqual(char.willpower_max, 3)
        self.assertEqual(char.health_max, 6)


class CreationTableTests(SimpleTestCase):
    def test_tables_are_consistent(self):
        self.assertEqual(len(v5_data.CREATION_ATTRIBUTE_SPREAD), 9)
        self.assertEqual(sum(v5_data.CREATION_ATTRIBUTE_SPREAD), 22)
        for name, distribution in v5_data.CREATION_SKILL_DISTRIBUTIONS.items():
            self.assertLessEqual(sum(distribution.values()), 27, name)
        for skill in v5_data.CREATION_FREE_SPECIALTY_SKILLS:
            v5_data.resolve_trait(skill, "skills")
        self.assertEqual(sorted(v5_data.CREATION_DISCIPLINE_DOTS), [1, 2])


class ReviewRoundOneRuleTests(SimpleTestCase):
    """Rules added or pinned in review round 1 (R-7, R-9, R-10, R-17, R-22, R-23, owner decisions)."""

    def test_caitiff_cannot_buy_status(self):
        payload = legal_payload(clan="Caitiff")
        payload["advantages"][3] = {"name": "Status", "dots": 1, "note": "Anarchs"}
        assert_rejected(self, payload, "Caitiff can't take Status at creation")

    def test_caitiff_cannot_take_thin_blood_merits(self):
        payload = legal_payload(clan="Caitiff")
        payload["advantages"].append({"name": "Lifelike", "dots": 1})
        payload["flaws"].append({"name": "Baby Teeth", "dots": 1})
        assert_rejected(self, payload, "Thin-blood merits and flaws are for thin-bloods only")

    def test_ventrue_may_take_organovore_but_not_farmer(self):
        payload = legal_payload(clan="Ventrue", predator_type="Siren")
        payload["disciplines"] = {"Dominate": 2, "Presence": 1, "Fortitude": 1}
        payload["discipline_powers"] = ["Cloud Memory", "Mesmerize", "Awe", "Resilience"]
        payload["specialties"][0] = {"skill": "persuasion", "name": "Seduction"}
        payload["flaws"] = [{"name": "Organovore", "dots": 2}]
        self.assertEqual(errors_for(payload), [])
        payload["flaws"] = [{"name": "Farmer", "dots": 2}]
        assert_rejected(self, payload, "Ventrue can't take Farmer")

    def test_nosferatu_siren_is_refused(self):
        payload = legal_payload(clan="Nosferatu", predator_type="Siren")
        assert_rejected(self, payload, "Nosferatu can't take Beautiful")

    def test_convictions_one_to_three(self):
        assert_rejected(self, legal_payload(convictions=[]), "Convictions: take 1-3")
        four = [{"conviction": f"C{i}", "touchstone": f"T{i}"} for i in range(4)]
        assert_rejected(self, legal_payload(convictions=four), "Convictions: take 1-3")
        assert_rejected(self, legal_payload(convictions=[{"conviction": "x"}]), "touchstone is required")
        assert_rejected(
            self, legal_payload(convictions=[{"conviction": "x", "touchstone": "y", "z": 1}]), "unknown key"
        )

    def test_ambition_and_desire_are_required(self):
        assert_rejected(self, legal_payload(ambition=""), "ambition: is required")
        assert_rejected(self, legal_payload(desire="  "), "desire: is required")

    def test_rituals_only_with_blood_sorcery(self):
        assert_rejected(self, legal_payload(rituals=["Blood Walk"]), "only characters with Blood Sorcery")
        assert_rejected(self, legal_payload(rituals=["Fireball Rite"]), "unknown ritual")

    def test_formulas_only_with_the_merit(self):
        assert_rejected(self, thin_blood_payload(formulas=["Far Reach"]), "Thin-blood Alchemist merit knows formulas")

    def test_reserved_names(self):
        for name in ("Me", "self", "Here", "Admin"):
            assert_rejected(self, legal_payload(name=name), "is reserved")

    # R-17: rules that had no test
    def test_alchemy_without_the_merit(self):
        assert_rejected(self, thin_blood_payload(disciplines={"Thin-Blood Alchemy": 1}), "Alchemist merit")

    def test_unknown_flaw_and_illegal_flaw_rating(self):
        payload = legal_payload()
        payload["flaws"][0] = {"name": "Clumsy Hands", "dots": 1}
        assert_rejected(self, payload, "unknown flaw 'Clumsy Hands'")
        payload["flaws"][0] = {"name": "Known Corpse", "dots": 2}
        assert_rejected(self, payload, "Known Corpse is taken at 1 dots, not 2")

    def test_merged_totals_must_stay_legal(self):
        siren = legal_payload(clan="Toreador", predator_type="Siren")
        siren["disciplines"] = {"Auspex": 2, "Presence": 1, "Fortitude": 1}
        siren["discipline_powers"] = ["Heightened Senses", "Premonition", "Awe", "Resilience"]
        siren["specialties"][0] = {"skill": "persuasion", "name": "Seduction"}
        siren["advantages"][3] = {"name": "Beautiful", "dots": 2}
        siren["advantages"][0] = {"name": "Resources", "dots": 1}
        assert_rejected(self, siren, "Beautiful would total 4 dots")

        bagger = legal_payload(clan="Tremere", predator_type="Bagger", rituals=["Blood Walk"])
        bagger["disciplines"] = {"Auspex": 2, "Dominate": 1, "Blood Sorcery": 1}
        bagger["discipline_powers"] = ["Heightened Senses", "Premonition", "Cloud Memory", "A Taste for Blood"]
        bagger["specialties"][0] = {"skill": "larceny", "name": "Lock Picking"}
        bagger["flaws"] = [{"name": "Enemy", "dots": 2}]
        assert_rejected(self, bagger, "Flaws: Enemy would total 4 dots")

        cleaver = legal_payload(clan="Ventrue", predator_type="Cleaver")
        cleaver["disciplines"] = {"Dominate": 3, "Presence": 1}
        cleaver["discipline_powers"] = ["Cloud Memory", "Mesmerize", "The Forgetful Mind", "Awe"]
        cleaver["specialties"][0] = {"skill": "subterfuge", "name": "Coverups"}
        cleaver["advantages"] = [{"name": "Herd", "dots": 4}]
        cleaver["flaws"] = [{"name": "Known Corpse", "dots": 1}]
        assert_rejected(self, cleaver, "Herd would total 6 dots; the most is 5")

    # R-23
    def test_clan_curse_must_name_a_clan(self):
        for note in ("", "Brujah clan", "Bruja", "Caitiff", "Thin-Blood"):
            payload = thin_blood_payload()
            payload["flaws"][2] = {"name": "Clan Curse", "dots": 1, "note": note}
            assert_rejected(self, payload, "Clan Curse: name the clan whose Bane you carry")

    # R-22: rules no current data reaches, pinned with patched tables
    def test_looks_category_ban_without_a_clan_ban(self):
        merit = {"category": "Looks", "dots": (1,), "description": "test"}
        with mock.patch.dict(v5_data.MERITS, {"Striking": merit}):
            payload = legal_payload(clan="Nosferatu", disciplines={"Potence": 2, "Obfuscate": 1, "Celerity": 1})
            payload["discipline_powers"] = ["Lethal Body", "Prowess", "Cloak of Shadows", "Rapid Reflexes"]
            payload["advantages"][3] = {"name": "Striking", "dots": 1}
            assert_rejected(self, payload, "Nosferatu can't take Looks merits (Striking)")

    def test_predator_blood_potency_limit(self):
        ancilla = dict(v5_data.GENERATION_BY_AGE["Ancilla"])
        ancilla["options"] = [{"generations": (10, 11), "blood_potency": 3, "thin_blood": False}]
        with mock.patch.dict(v5_data.GENERATION_BY_AGE, {"Ancilla": ancilla}):
            payload = ancilla_payload(clan="Gangrel", predator_type="Farmer")
            assert_rejected(self, payload, "Farmer needs Blood Potency 2 or lower")


class ShapeGuardTests(SimpleTestCase):
    """R-18: every parse guard rejects (never coerces or drops) a wrong value."""

    CASES = [
        ({"name": 123}, "name: must be text"),
        ({"concept": 5}, "concept: must be text"),
        ({"attributes": []}, "attributes: must be an object"),
        ({"skills": "x"}, "skills: must be an object"),
        ({"advantages": {}}, "advantages: must be a list"),
        ({"advantages": ["Resources"]}, "advantages[0]: must be an object"),
        ({"advantages": [{"dots": 2}]}, "advantages[0]: needs a name"),
        ({"advantages": [{"name": "Resources", "dots": "2"}]}, "dots must be a whole number"),
        ({"advantages": [{"name": "Allies", "dots": 1, "note": "x" * 101}]}, "note must be text of at most 100"),
        ({"advantages": [{"name": "Resources", "dots": 1, "source": "staff"}]}, 'source must be "predator"'),
        ({"specialties": {}}, "specialties: must be a list"),
        ({"specialties": ["Boxing"]}, "specialties[0]: must be an object"),
        ({"specialties": [{"skill": "hacking", "name": "x"}]}, "unknown skill 'hacking'"),
        ({"specialties": [{"skill": "brawl", "name": "x" * 51}]}, "needs a name of at most 50"),
        ({"clan": 7}, "clan: is required"),
        ({"age": 3}, "age: must be text"),
        ({"predator_type": 3}, "predator_type: must be text or null"),
        ({"disciplines": []}, "disciplines: must be an object"),
        ({"disciplines": {"Potence": 6}}, "Potence must be a whole number from 0 to 5"),
        ({"disciplines": {"Potence": 2, "potence": 1}}, "Potence is given twice"),
        ({"discipline_powers": "Prowess"}, "discipline_powers: must be a list"),
        ({"discipline_powers": ["Prowess", "prowess"]}, "Prowess is listed twice"),
        ({"convictions": {}}, "convictions: must be a list"),
        ({"rituals": "Blood Walk"}, "rituals: must be a list"),
        ({"formulas": ["Far Reach", "far reach"]}, "Far Reach is listed twice"),
    ]

    def test_each_guard(self):
        for change, fragment in self.CASES:
            with self.subTest(change=change):
                with self.assertRaises(SubmissionError) as caught:
                    parse_submission(legal_payload(**change))
                self.assertTrue(any(fragment in e for e in caught.exception.errors), caught.exception.errors)

    def test_duplicate_rating_keys(self):
        payload = legal_payload()
        payload["attributes"]["Strength"] = 4
        with self.assertRaises(SubmissionError) as caught:
            parse_submission(payload)
        self.assertIn("attributes: Strength is given twice", caught.exception.errors)


class ApplyChargenFactsTests(EvenniaTest):
    """R-24: notes, age and the free ritual/formula live on the character."""

    def test_notes_age_convictions_and_ritual(self):
        payload = legal_payload(clan="Tremere", predator_type="Bagger", rituals=["Blood Walk"])
        payload["disciplines"] = {"Auspex": 2, "Dominate": 1, "Blood Sorcery": 1}
        payload["discipline_powers"] = ["Heightened Senses", "Premonition", "Cloud Memory", "A Taste for Blood"]
        payload["specialties"][0] = {"skill": "larceny", "name": "Lock Picking"}
        payload["advantages"][3] = {"name": "Linguistics", "dots": 1, "note": "Portuguese"}
        sub = parse_submission(payload)
        self.assertEqual(validate_v5_creation(sub), [])
        char = create.create_object("typeclasses.characters.Character", key="Facts")
        apply_chargen(char, sub)
        self.assertEqual(char.age_category, "Neonate")
        self.assertEqual(char.advantage_note("merits", "Linguistics"), "Portuguese")
        self.assertEqual(char.advantage_note("flaws", "Enemy"), "someone who thinks you owe them")
        self.assertEqual(char.rituals, ["Blood Walk"])
        self.assertEqual(char.convictions, ["Never abandon a picket line"])
        self.assertEqual(char.touchstones[0]["name"], "Teo Marquez")
        self.assertEqual(char.touchstones[0]["conviction_index"], 0)

    def test_formula_and_clan_curse_note(self):
        payload = thin_blood_payload(disciplines={"Thin-Blood Alchemy": 1}, formulas=["Haze"])
        payload["advantages"].append({"name": "Thin-blood Alchemist", "dots": 1})
        payload["flaws"].append({"name": "Clan Curse", "dots": 1, "note": "toreador"})
        sub = parse_submission(payload)
        self.assertEqual(validate_v5_creation(sub), [])
        char = create.create_object("typeclasses.characters.Character", key="Alchemist")
        apply_chargen(char, sub)
        self.assertEqual(char.formulas, ["Haze"])
        self.assertEqual(char.advantage_note("flaws", "Clan Curse"), "toreador")
        self.assertEqual(char.age_category, "Childer")
