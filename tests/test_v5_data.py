"""
Structural invariants of world/v5_data.py, the one source of V5 rules data.

These check that the tables are internally consistent and that no other
module carries its own copy of the Blood Potency table. They don't prove the
content matches the book; the source comments in v5_data.py and the owner
sign-off do that.
"""

import ast
import re
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from evennia.utils.test_resources import EvenniaTest

from world import v5_data

REPO_ROOT = Path(__file__).resolve().parent.parent
V5_DATA_PATH = REPO_ROOT / "world" / "v5_data.py"

# The errata'd Blood Potency table (Renegade "V5 Blood Potency Correction";
# The Companion 2020 p.63; Players Guide p.248). Columns: surge, mend, power
# bonus, Rouse re-roll level, bane severity.
ERRATA_BLOOD_POTENCY = {
    0: (1, 1, 0, 0, 0),
    1: (2, 1, 0, 1, 2),
    2: (2, 2, 1, 1, 2),
    3: (3, 2, 1, 2, 3),
    4: (3, 3, 2, 2, 3),
    5: (4, 3, 2, 3, 4),
    6: (4, 3, 3, 3, 4),
    7: (5, 3, 3, 4, 5),
    8: (5, 4, 4, 4, 5),
    9: (6, 4, 4, 5, 6),
    10: (6, 5, 5, 5, 6),
}


def _parse_amalgam(text):
    name, _, level = text.rpartition(" ")
    return name, int(level)


class BloodPotencyTableTests(TestCase):
    def test_rows_match_errata(self):
        self.assertEqual(sorted(v5_data.BLOOD_POTENCY), list(range(11)))
        for bp, (surge, mend, bonus, reroll, bane) in ERRATA_BLOOD_POTENCY.items():
            row = v5_data.BLOOD_POTENCY[bp]
            self.assertEqual(
                (row["blood_surge"], row["mend_amount"], row["power_bonus"], row["rouse_reroll"], row["bane_severity"]),
                (surge, mend, bonus, reroll, bane),
                f"BP {bp}",
            )
            self.assertTrue(row["feeding_penalty"])

    def test_no_other_module_hardcodes_a_bp_table(self):
        """dice/ and commands/ read BLOOD_POTENCY; they don't carry their own ladder."""
        patterns = [
            re.compile(r"blood_potency\s*(==|in|>=|<=|>|<)\s*\[?\d"),
            re.compile(r"[\"'](blood_surge|mend_amount|power_bonus|bane_severity)[\"']\s*:"),
            re.compile(r"\bbp\s*(==|in|>=|<=)\s*\[?\d"),
        ]
        offenders = []
        for folder in ("dice", "commands"):
            for path in (REPO_ROOT / folder).rglob("*.py"):
                if "tests" in path.parts or path.name.startswith("test"):
                    continue
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if any(p.search(line) for p in patterns):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])


class BloodPotencyRoutingTests(EvenniaTest):
    """The BP readers follow the table, so changing the table changes them."""

    def test_readers_use_the_table(self):
        from commands.v5.utils import blood_utils
        from dice import discipline_roller, rouse_checker

        fake = {bp: dict(row) for bp, row in v5_data.BLOOD_POTENCY.items()}
        fake[3].update(blood_surge=9, power_bonus=8, rouse_reroll=5)
        self.char1.blood_potency = 3
        with (
            patch.object(blood_utils, "BLOOD_POTENCY", fake),
            patch.object(discipline_roller, "BLOOD_POTENCY", fake),
            patch.object(rouse_checker, "BLOOD_POTENCY", fake),
        ):
            self.assertEqual(blood_utils.get_blood_potency_bonus(self.char1), 9)
            self.assertEqual(discipline_roller.get_blood_potency_bonus(self.char1, "Auspex"), 8)
            self.assertTrue(rouse_checker.can_reroll_rouse(self.char1, 5))


class DuplicateKeyTests(TestCase):
    def test_no_duplicate_dict_keys(self):
        """A repeated key in a dict literal silently drops data (the old "powers": {} bug)."""
        tree = ast.parse(V5_DATA_PATH.read_text(encoding="utf-8"))
        duplicates = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            seen = set()
            for key in node.keys:
                if not isinstance(key, ast.Constant):
                    continue  # ** unpacking or a computed key
                if key.value in seen:
                    duplicates.append(f"line {key.lineno}: {key.value!r}")
                seen.add(key.value)
        self.assertEqual(duplicates, [])


class ClanTests(TestCase):
    def test_in_clan_disciplines_exist(self):
        for table in (v5_data.CLANS, v5_data.NON_CORE_CLANS):
            for clan, data in table.items():
                for discipline in data["disciplines"]:
                    self.assertIn(discipline, v5_data.ALL_DISCIPLINES, clan)

    def test_core_clans_use_core_disciplines(self):
        for clan, data in v5_data.CLANS.items():
            for discipline in data["disciplines"]:
                self.assertIn(discipline, v5_data.DISCIPLINES, clan)

    def test_core_and_non_core_are_separate(self):
        self.assertFalse(set(v5_data.CLANS) & set(v5_data.NON_CORE_CLANS))
        self.assertFalse(set(v5_data.DISCIPLINES) & set(v5_data.NON_CORE_DISCIPLINES))

    def test_caitiff_and_thin_blood_have_no_bane_or_compulsion(self):
        for clan in ("Caitiff", "Thin-Blood"):
            self.assertEqual(v5_data.CLANS[clan]["disciplines"], [])
            self.assertIsNone(v5_data.CLANS[clan]["bane"])
            self.assertIsNone(v5_data.CLANS[clan]["compulsion"])

    def test_every_other_core_clan_has_bane_and_compulsion(self):
        for clan, data in v5_data.CLANS.items():
            if clan in ("Caitiff", "Thin-Blood"):
                continue
            self.assertEqual(len(data["disciplines"]), 3, clan)
            self.assertTrue(data["bane"], clan)
            self.assertTrue(data["compulsion"], clan)


class DisciplineTests(TestCase):
    def _all_powers(self):
        for table in (v5_data.DISCIPLINES, v5_data.NON_CORE_DISCIPLINES):
            for discipline, data in table.items():
                for level, powers in data["powers"].items():
                    for power in powers:
                        yield discipline, level, power

    def test_power_fields(self):
        for discipline, level, power in self._all_powers():
            label = f"{discipline} {level} {power['name']}"
            self.assertIn(level, range(1, 6), label)
            self.assertIsInstance(power["rouse"], int, label)
            self.assertNotIsInstance(power["rouse"], bool, label)
            self.assertIn(power["rouse"], range(0, 4), label)
            self.assertNotIn("ritual", power, label)
            pool = power["dice_pool"]
            if pool is not None:
                self.assertNotIn(" vs ", pool, f"{label}: put the opposing pool in 'opposed_by'")

    def test_amalgams_resolve(self):
        for discipline, level, power in self._all_powers():
            if not power.get("amalgam"):
                continue
            name, amalgam_level = _parse_amalgam(power["amalgam"])
            self.assertIn(name, v5_data.ALL_DISCIPLINES, power["name"])
            self.assertNotEqual(name, discipline, power["name"])
            self.assertIn(amalgam_level, range(1, 6), power["name"])
            # A core power's amalgam must be a core discipline.
            if discipline in v5_data.DISCIPLINES:
                self.assertIn(name, v5_data.DISCIPLINES, power["name"])

    def test_power_index_covers_only_core_powers(self):
        core_names = {p["name"] for d, _, p in self._all_powers() if d in v5_data.DISCIPLINES}
        self.assertEqual(set(v5_data.DISCIPLINE_POWERS), core_names)

    def test_rituals_and_formulas_are_not_powers(self):
        for ritual in v5_data.DISCIPLINES["Blood Sorcery"]["rituals"]:
            self.assertIsNone(v5_data.find_power(ritual["name"]), ritual["name"])
            self.assertIn(ritual["level"], range(1, 6))
        formulas = v5_data.DISCIPLINES["Thin-Blood Alchemy"]["formulas"]
        self.assertTrue(formulas)
        for level, entries in formulas.items():
            self.assertIn(level, range(1, 6))
            for formula in entries:
                self.assertIsNone(v5_data.find_power(formula["name"]), formula["name"])


class PredatorTypeTests(TestCase):
    def test_predator_grants_resolve(self):
        skills = {s for group in v5_data.SKILLS.values() for s in group}
        for name, data in v5_data.PREDATOR_TYPES.items():
            # The book gives Blood Leech no single hunting roll.
            if name != "Blood Leech":
                self.assertTrue(data["hunting_pool"], name)
            for pool in (data["hunting_pool"], data.get("alt_hunting_pool")):
                if pool:
                    self.assertRegex(pool, r"^[A-Z][a-z]+( [A-Z][a-z]+)? \+ [A-Z][a-z]+( [A-Z][a-z]+)?$", name)
            for skill, _specialty in data["specialties"]:
                self.assertIn(skill, skills, name)
            for discipline in data["disciplines"]:
                self.assertIn(discipline, v5_data.DISCIPLINES, name)
            for restricted, clans in data.get("discipline_clans", {}).items():
                self.assertIn(restricted, data["disciplines"], name)
                for clan in clans:
                    self.assertIn(clan, v5_data.CLANS | v5_data.NON_CORE_CLANS, name)
            for kind, table in (("merits", v5_data.MERITS), ("flaws", v5_data.FLAWS)):
                for grant in data[kind]:
                    self.assertIn(grant["name"], table, f"{name} {kind}")
                    self.assertIn(grant["dots"], table[grant["name"]]["dots"], f"{name} {grant['name']}")
            for grant in data["backgrounds"]:
                self.assertIn(grant["name"], v5_data.BACKGROUNDS, name)
                self.assertIn(grant["dots"], range(1, 6), name)


class AdvantageTests(TestCase):
    def test_thin_blood_advantages_are_free_and_paired(self):
        thin_merits = [n for n, d in v5_data.MERITS.items() if d.get("thin_blood")]
        thin_flaws = [n for n, d in v5_data.FLAWS.items() if d.get("thin_blood")]
        self.assertTrue(thin_merits)
        self.assertTrue(thin_flaws)
        for name in thin_merits:
            self.assertEqual(v5_data.MERITS[name]["cost"], 0, name)
        for name in thin_flaws:
            self.assertEqual(v5_data.FLAWS[name]["cost"], 0, name)

    def test_every_other_advantage_costs_its_dots(self):
        for table in (v5_data.MERITS, v5_data.FLAWS):
            for name, data in table.items():
                if not data.get("thin_blood"):
                    self.assertNotIn("cost", data, name)


class MiscTableTests(TestCase):
    def test_generation_tables(self):
        self.assertEqual(sorted(v5_data.GENERATION_BLOOD_POTENCY), list(range(4, 17)))
        for age, data in v5_data.GENERATION_BY_AGE.items():
            for option in data["options"]:
                for generation in option["generations"]:
                    limits = v5_data.GENERATION_BLOOD_POTENCY[generation]
                    self.assertGreaterEqual(option["blood_potency"], limits["min"], age)
                    self.assertLessEqual(option["blood_potency"], limits["max"], age)

    def test_resonances_use_book_names(self):
        self.assertEqual(set(v5_data.RESONANCES), {"Choleric", "Melancholy", "Phlegmatic", "Sanguine"})
        for data in v5_data.RESONANCES.values():
            for discipline in data["disciplines"]:
                self.assertIn(discipline, v5_data.DISCIPLINES)

    def test_frenzy_provocations(self):
        self.assertEqual(set(v5_data.FRENZY_PROVOCATIONS), {"fury", "hunger", "terror"})
        for data in v5_data.FRENZY_PROVOCATIONS.values():
            for difficulty in data["provocations"].values():
                self.assertIn(difficulty, range(2, 5))
