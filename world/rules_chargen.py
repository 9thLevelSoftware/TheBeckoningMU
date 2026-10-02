"""
V5 character creation: the one schema, validator and writer for a new character.

The website is the only way to make a player character. Its form posts a
submission (a JSON object) that goes through three steps, all here:

    sub = parse_submission(data)        # shape: fixed keys, types; raises SubmissionError
    errors = validate_v5_creation(sub)  # rules: pure, reads world/v5_data.py
    apply_chargen(character, sub)       # writes through the Character accessors

`apply_chargen` consumes the same `Submission` the validator checked, and both
derive the stored sheet from `build_sheet(sub)`, so what is validated is what
is written.

Submission keys (any other key, at any level, is rejected):

    name, concept, sire, ambition, desire, background   text
    clan          a key of CLANS (core clans only)
    age           a key of GENERATION_BY_AGE ("Childer", "Neonate", "Ancilla")
    generation    a generation that age category allows
    predator_type a key of PREDATOR_TYPES, or null (thin-bloods and Childer)
    attributes    {attribute: rating} for all 9 Attributes
    skills        {skill: rating} for all 27 Skills
    specialties   [{"skill", "name"}]: every specialty, the predator one included
    disciplines   {discipline: dots}: every dot, the predator dot included
    discipline_powers  [power name]: one per discipline dot
    advantages    [{"name", "dots", "note"?, "source"?}]: backgrounds and merits
    flaws         [{"name", "dots", "note"?, "source"?}]

`source: "predator"` marks the advantages and flaws the player picked for the
predator type's choice grants (Osiris, Blood Leech, Scene Queen). The predator
type's fixed grants and a clan's required flaws are added by the server and
are not submitted. `note` names the target of an instanced background
(Allies, Contacts, ...) or describes a flaw.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from world.v5_data import (
    ATTRIBUTES,
    BACKGROUNDS,
    CLANS,
    CREATION_ADVANTAGE_DOTS,
    CREATION_ATTRIBUTE_SPREAD,
    CREATION_DISCIPLINE_DOTS,
    CREATION_EXTRA_FREE_SPECIALTIES,
    CREATION_FLAW_DOTS,
    CREATION_FREE_SPECIALTY_SKILLS,
    CREATION_HUMANITY,
    CREATION_HUNGER,
    CREATION_SKILL_DISTRIBUTIONS,
    CREATION_THIN_BLOOD_PAIRS,
    DISCIPLINES,
    FLAWS,
    GENERATION_BLOOD_POTENCY,
    GENERATION_BY_AGE,
    MERITS,
    PREDATOR_TYPES,
    SKILLS,
    find_power,
    normalize_trait_name,
)

THIN_BLOOD_CLAN = "Thin-Blood"
CAITIFF_CLAN = "Caitiff"
ALCHEMY = "Thin-Blood Alchemy"

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '\-]{1,29}$")
TEXT_LIMITS = {
    "concept": 100,
    "sire": 100,
    "ambition": 500,
    "desire": 500,
    "background": 10000,
}
NOTE_LIMIT = 100
SPECIALTY_LIMIT = 50

REQUIRED_KEYS = (
    "name",
    "clan",
    "age",
    "generation",
    "predator_type",
    "attributes",
    "skills",
    "specialties",
    "disciplines",
    "discipline_powers",
    "advantages",
    "flaws",
)
OPTIONAL_TEXT_KEYS = tuple(TEXT_LIMITS)
ALLOWED_KEYS = frozenset(REQUIRED_KEYS + OPTIONAL_TEXT_KEYS)
ITEM_KEYS = frozenset({"name", "dots", "note", "source"})
SPECIALTY_KEYS = frozenset({"skill", "name"})
ITEM_SOURCES = (None, "predator")

# Display names keyed by storage key, in sheet order.
ATTRIBUTE_NAMES = {normalize_trait_name(n): n for group in ATTRIBUTES.values() for n in group}
SKILL_NAMES = {normalize_trait_name(n): n for group in SKILLS.values() for n in group}
FREE_SPECIALTY_KEYS = tuple(normalize_trait_name(n) for n in CREATION_FREE_SPECIALTY_SKILLS)


class SubmissionError(ValueError):
    """The submission has the wrong shape. `errors` lists every problem found."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Item:
    """One advantage or flaw entry."""

    name: str
    dots: int
    note: str = ""
    source: str | None = None  # None (bought) or "predator" (a predator choice grant)

    def as_dict(self):
        data = {"name": self.name, "dots": self.dots}
        if self.note:
            data["note"] = self.note
        if self.source:
            data["source"] = self.source
        return data


@dataclass(frozen=True)
class Submission:
    name: str
    clan: str
    age: str
    generation: int
    predator_type: str | None
    attributes: dict  # {storage key: rating}, all 9
    skills: dict  # {storage key: rating}, all 27
    specialties: tuple  # ((skill key, name), ...)
    disciplines: dict  # {canonical discipline name: dots}, dots > 0
    discipline_powers: tuple  # canonical power names
    advantages: tuple  # Items: backgrounds and merits
    flaws: tuple  # Items
    concept: str = ""
    sire: str = ""
    ambition: str = ""
    desire: str = ""
    background: str = ""

    def as_dict(self):
        """The submission in its JSON shape (canonical names)."""
        return {
            "name": self.name,
            "concept": self.concept,
            "clan": self.clan,
            "age": self.age,
            "generation": self.generation,
            "predator_type": self.predator_type,
            "sire": self.sire,
            "ambition": self.ambition,
            "desire": self.desire,
            "background": self.background,
            "attributes": dict(self.attributes),
            "skills": dict(self.skills),
            "specialties": [{"skill": skill, "name": name} for skill, name in self.specialties],
            "disciplines": dict(self.disciplines),
            "discipline_powers": list(self.discipline_powers),
            "advantages": [item.as_dict() for item in self.advantages],
            "flaws": [item.as_dict() for item in self.flaws],
        }


@dataclass
class Sheet:
    """What apply_chargen writes, derived from a Submission by build_sheet()."""

    blood_potency: int
    humanity: int
    xp: int
    backgrounds: dict = field(default_factory=dict)  # {name: dots} single-rating backgrounds
    background_instances: list = field(default_factory=list)  # [(name, note, dots)]
    merits: dict = field(default_factory=dict)  # {name: dots}
    flaws: dict = field(default_factory=dict)  # {name: dots}


# ----------------------------------------------------------------------------
# Parsing (shape only)
# ----------------------------------------------------------------------------


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(data, key, errors, limit=None, required=False):
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors.append(f"{key}: must be text")
        return ""
    value = value.strip()
    if required and not value:
        errors.append(f"{key}: is required")
    if limit is not None and len(value) > limit:
        errors.append(f"{key}: at most {limit} characters")
    return value


def _canonical(value, names):
    """Match a name case-insensitively (and ignoring spacing) to one of `names`."""
    if not isinstance(value, str):
        return None
    wanted = normalize_trait_name(value)
    for name in names:
        if normalize_trait_name(name) == wanted:
            return name
    return None


def _rating_map(value, label, names, errors):
    """Parse {name: int} that must name every key in `names` exactly once."""
    if not isinstance(value, dict):
        errors.append(f"{label}: must be an object of ratings")
        return {}
    result, present = {}, set()
    for raw_key, rating in value.items():
        key = normalize_trait_name(raw_key) if isinstance(raw_key, str) else None
        if key not in names:
            errors.append(f"{label}: unknown key {raw_key!r}")
            continue
        if key in present:
            errors.append(f"{label}: {names[key]} is given twice")
            continue
        present.add(key)
        if not _is_int(rating):
            errors.append(f"{label}: {names[key]} must be a whole number")
            continue
        result[key] = rating
    missing = [names[key] for key in names if key not in present]
    if missing:
        errors.append(f"{label}: missing {', '.join(missing)}")
    return {key: result[key] for key in names if key in result}


def _items(value, label, errors):
    if not isinstance(value, list):
        errors.append(f"{label}: must be a list")
        return ()
    items = []
    for index, raw in enumerate(value):
        where = f"{label}[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be an object")
            continue
        unknown = sorted(str(key) for key in raw if key not in ITEM_KEYS)
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(unknown)}")
            continue
        name, dots = raw.get("name"), raw.get("dots")
        note, source = raw.get("note", ""), raw.get("source")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: needs a name")
            continue
        if not _is_int(dots):
            errors.append(f"{where}: dots must be a whole number")
            continue
        if note is None:
            note = ""
        if not isinstance(note, str) or len(note.strip()) > NOTE_LIMIT:
            errors.append(f"{where}: note must be text of at most {NOTE_LIMIT} characters")
            continue
        if source not in ITEM_SOURCES:
            errors.append(f'{where}: source must be "predator" or absent')
            continue
        items.append(Item(name.strip(), dots, note.strip(), source))
    return tuple(items)


def _specialties(value, errors):
    if not isinstance(value, list):
        errors.append("specialties: must be a list")
        return ()
    result = []
    for index, raw in enumerate(value):
        where = f"specialties[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be an object")
            continue
        unknown = sorted(str(key) for key in raw if key not in SPECIALTY_KEYS)
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(unknown)}")
            continue
        skill = normalize_trait_name(raw.get("skill")) if isinstance(raw.get("skill"), str) else None
        name = raw.get("name")
        if skill not in SKILL_NAMES:
            errors.append(f"{where}: unknown skill {raw.get('skill')!r}")
            continue
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > SPECIALTY_LIMIT:
            errors.append(f"{where}: needs a name of at most {SPECIALTY_LIMIT} characters")
            continue
        result.append((skill, name.strip()))
    return tuple(result)


def parse_submission(data):
    """Check the submission's shape and return a Submission.

    Raises SubmissionError listing every shape problem: a non-object body,
    unknown or missing keys at any level, wrong types, unknown trait names.
    Rules (distributions, totals, eligibility) are validate_v5_creation's job.
    """
    if not isinstance(data, dict):
        raise SubmissionError(["The character must be a JSON object"])
    errors = []
    unknown = sorted(str(key) for key in data if key not in ALLOWED_KEYS)
    if unknown:
        errors.append(f"Unknown key(s): {', '.join(unknown)}")
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        errors.append(f"Missing key(s): {', '.join(missing)}")
    if errors:
        raise SubmissionError(errors)

    name = _text(data, "name", errors, required=True)
    texts = {key: _text(data, key, errors, limit) for key, limit in TEXT_LIMITS.items()}

    clan = data["clan"]
    if not isinstance(clan, str) or not clan.strip():
        errors.append("clan: is required")
        clan = ""
    age = data["age"]
    if not isinstance(age, str):
        errors.append("age: must be text")
        age = ""
    generation = data["generation"]
    if not _is_int(generation):
        errors.append("generation: must be a whole number")
        generation = 0
    predator = data["predator_type"]
    if predator == "":
        predator = None
    if predator is not None and not isinstance(predator, str):
        errors.append("predator_type: must be text or null")
        predator = None

    attributes = _rating_map(data["attributes"], "attributes", ATTRIBUTE_NAMES, errors)
    skills = _rating_map(data["skills"], "skills", SKILL_NAMES, errors)
    specialties = _specialties(data["specialties"], errors)

    disciplines = {}
    raw_disciplines = data["disciplines"]
    if not isinstance(raw_disciplines, dict):
        errors.append("disciplines: must be an object of ratings")
    else:
        for raw_name, dots in raw_disciplines.items():
            name_ = _canonical(raw_name, DISCIPLINES)
            if name_ is None:
                errors.append(f"disciplines: unknown discipline {raw_name!r}")
            elif name_ in disciplines:
                errors.append(f"disciplines: {name_} is given twice")
            elif not _is_int(dots) or not 0 <= dots <= 5:
                errors.append(f"disciplines: {name_} must be a whole number from 0 to 5")
            elif dots:
                disciplines[name_] = dots

    powers = []
    raw_powers = data["discipline_powers"]
    if not isinstance(raw_powers, list):
        errors.append("discipline_powers: must be a list")
    else:
        for raw_power in raw_powers:
            power = find_power(raw_power) if isinstance(raw_power, str) else None
            if power is None:
                errors.append(f"discipline_powers: unknown power {raw_power!r}")
            elif power["name"] in powers:
                errors.append(f"discipline_powers: {power['name']} is listed twice")
            else:
                powers.append(power["name"])

    advantages = _items(data["advantages"], "advantages", errors)
    flaws = _items(data["flaws"], "flaws", errors)

    if errors:
        raise SubmissionError(errors)
    return Submission(
        name=name,
        clan=clan.strip(),
        age=age.strip(),
        generation=generation,
        predator_type=predator.strip() if predator else None,
        attributes=attributes,
        skills=skills,
        specialties=specialties,
        disciplines=disciplines,
        discipline_powers=tuple(powers),
        advantages=advantages,
        flaws=flaws,
        **texts,
    )


# ----------------------------------------------------------------------------
# Derived values
# ----------------------------------------------------------------------------


def age_option(sub):
    """The GENERATION_BY_AGE option for the submission's age and generation, or None."""
    age = GENERATION_BY_AGE.get(sub.age)
    if not age:
        return None
    for option in age["options"]:
        if sub.generation in option["generations"]:
            return option
    return None


def _predator(sub):
    return PREDATOR_TYPES.get(sub.predator_type) if sub.predator_type else None


def _resolve_advantage(name):
    """("backgrounds"|"merits", canonical name) for an advantage name, or (None, None)."""
    for kind, table in (("backgrounds", BACKGROUNDS), ("merits", MERITS)):
        canonical = _canonical(name, table)
        if canonical:
            return kind, canonical
    return None, None


def granted_items(sub):
    """Advantages and flaws the server adds: predator fixed grants and clan-required flaws.

    Returns ([(kind, Item)], [Item]) with kind "backgrounds" or "merits".
    """
    advantages, flaws = [], []
    predator = _predator(sub)
    if predator:
        default_note = f"{sub.predator_type} predator type"
        for grant in predator.get("backgrounds", []):
            advantages.append(
                ("backgrounds", Item(grant["name"], grant["dots"], grant.get("note") or default_note, "predator"))
            )
        for grant in predator.get("merits", []):
            advantages.append(("merits", Item(grant["name"], grant["dots"], grant.get("note", ""), "predator")))
        for grant in predator.get("flaws", []):
            flaws.append(Item(grant["name"], grant["dots"], grant.get("note", ""), "predator"))
    for grant in CLANS.get(sub.clan, {}).get("required_flaws", []):
        flaws.append(Item(grant["name"], grant["dots"], "", "clan"))
    return advantages, flaws


def build_sheet(sub):
    """Merge the submission with the server's grants into what gets stored.

    Pure. Assumes names resolve (validate first); unknown names are skipped.
    """
    option = age_option(sub) or {"blood_potency": 0}
    age = GENERATION_BY_AGE.get(sub.age, {})
    predator = _predator(sub) or {}
    sheet = Sheet(
        blood_potency=option["blood_potency"] + predator.get("blood_potency", 0),
        humanity=CREATION_HUMANITY + age.get("humanity_change", 0) + predator.get("humanity", 0),
        xp=age.get("xp", 0),
    )
    granted_advantages, granted_flaws = granted_items(sub)
    advantages = list(granted_advantages)
    for item in sub.advantages:
        kind, canonical = _resolve_advantage(item.name)
        if kind:
            advantages.append((kind, Item(canonical, item.dots, item.note, item.source)))
    for kind, item in advantages:
        if kind == "merits":
            sheet.merits[item.name] = sheet.merits.get(item.name, 0) + item.dots
        elif BACKGROUNDS[item.name].get("instanced"):
            sheet.background_instances.append((item.name, item.note, item.dots))
        else:
            sheet.backgrounds[item.name] = sheet.backgrounds.get(item.name, 0) + item.dots
    for item in list(granted_flaws) + list(sub.flaws):
        canonical = _canonical(item.name, FLAWS)
        if canonical:
            sheet.flaws[canonical] = sheet.flaws.get(canonical, 0) + item.dots
    return sheet


# ----------------------------------------------------------------------------
# Validation (rules)
# ----------------------------------------------------------------------------


def validate_name(name):
    """Errors for a character name (format only; uniqueness is checked against the DB)."""
    if "|" in name or not NAME_RE.match(name):
        return ["Name: 2-30 characters, starting with a letter, using only letters, spaces, apostrophes and hyphens"]
    return []


def _identity_errors(sub):
    errors = validate_name(sub.name)
    if sub.clan not in CLANS:
        errors.append(f"Clan: '{sub.clan}' is not available")
    if sub.age not in GENERATION_BY_AGE:
        errors.append(f"Age: choose one of {', '.join(GENERATION_BY_AGE)}")
        return errors
    option = age_option(sub)
    if option is None:
        allowed = sorted(g for opt in GENERATION_BY_AGE[sub.age]["options"] for g in opt["generations"])
        errors.append(f"Generation: a {sub.age} is of generation {', '.join(str(g) for g in allowed)}")
        return errors
    if sub.clan in CLANS and option["thin_blood"] != (sub.clan == THIN_BLOOD_CLAN):
        if option["thin_blood"]:
            errors.append("Generation: 14th-16th generation vampires are thin-bloods (clan Thin-Blood)")
        else:
            errors.append("Generation: thin-bloods are of the 14th-16th generation and are Childer")

    no_predator = sub.clan == THIN_BLOOD_CLAN or sub.age == "Childer"
    if no_predator:
        if sub.predator_type:
            errors.append("Predator type: thin-bloods and Childer (recently Embraced) take no predator type")
    elif not sub.predator_type:
        errors.append("Predator type: choose one")
    elif sub.predator_type not in PREDATOR_TYPES:
        errors.append(f"Predator type: '{sub.predator_type}' is not a predator type")
    else:
        predator = PREDATOR_TYPES[sub.predator_type]
        if sub.clan in predator.get("excluded_clans", []):
            errors.append(f"Predator type: {sub.clan} can't take {sub.predator_type}")
        limit = predator.get("max_blood_potency")
        if limit is not None and option["blood_potency"] > limit:
            errors.append(f"Predator type: {sub.predator_type} needs Blood Potency {limit} or lower")

    blood_potency = build_sheet(sub).blood_potency
    bp_range = GENERATION_BLOOD_POTENCY.get(sub.generation)
    if bp_range and not bp_range["min"] <= blood_potency <= bp_range["max"]:
        errors.append(
            f"Blood Potency: {blood_potency} is outside generation {sub.generation}'s "
            f"range {bp_range['min']}-{bp_range['max']}"
        )
    return errors


def _attribute_errors(sub):
    if sorted(sub.attributes.values(), reverse=True) != sorted(CREATION_ATTRIBUTE_SPREAD, reverse=True):
        spread = "/".join(str(v) for v in sorted(CREATION_ATTRIBUTE_SPREAD, reverse=True))
        return [f"Attributes: rate them {spread} (one at 4, three at 3, four at 2, one at 1)"]
    return []


def skill_distribution(skills):
    """Name of the CREATION_SKILL_DISTRIBUTIONS entry `skills` follows, or None."""
    counts = Counter(rating for rating in skills.values() if rating)
    for name, distribution in CREATION_SKILL_DISTRIBUTIONS.items():
        if counts == Counter(distribution):
            return name
    return None


def _skill_errors(sub):
    if skill_distribution(sub.skills):
        return []
    options = "; ".join(
        f"{name}: " + ", ".join(f"{count} at {rating}" for rating, count in sorted(dist.items(), reverse=True))
        for name, dist in CREATION_SKILL_DISTRIBUTIONS.items()
    )
    return [f"Skills: use one distribution ({options}); every other Skill is 0"]


def _predator_specialty_matches(predator, skill, name):
    for option_skill, option_name in predator.get("specialties", []):
        if normalize_trait_name(option_skill) != skill:
            continue
        if option_name.lower().startswith("specific") or option_name.lower() == name.lower():
            return True
    return False


def _specialty_errors(sub):
    errors = []
    seen = set()
    for skill, name in sub.specialties:
        if sub.skills.get(skill, 0) < 1:
            errors.append(f"Specialties: {SKILL_NAMES[skill]} ({name}) needs at least one dot in {SKILL_NAMES[skill]}")
        key = (skill, name.lower())
        if key in seen:
            errors.append(f"Specialties: {SKILL_NAMES[skill]} ({name}) is listed twice")
        seen.add(key)
    if errors:
        return errors

    predator = _predator(sub) if sub.predator_type in PREDATOR_TYPES else None
    required = [skill for skill in FREE_SPECIALTY_KEYS if sub.skills.get(skill, 0) >= 1]
    expected = len(required) + CREATION_EXTRA_FREE_SPECIALTIES + (1 if predator else 0)
    rule = (
        "one free specialty in each of Academics, Craft, Performance and Science you have dots in, "
        f"{CREATION_EXTRA_FREE_SPECIALTIES} more of your choice"
        + (", and one of your predator type's" if predator else "")
    )
    if len(sub.specialties) != expected:
        return [f"Specialties: take {expected} ({rule}); you have {len(sub.specialties)}"]

    specialties = list(sub.specialties)
    candidates = [None]
    if predator:
        candidates = [
            i for i, (skill, name) in enumerate(specialties) if _predator_specialty_matches(predator, skill, name)
        ]
        if not candidates:
            choices = ", ".join(f"{skill} ({name})" for skill, name in predator.get("specialties", []))
            return [f"Specialties: {sub.predator_type} gives one of {choices}"]
    for candidate in candidates:
        remaining = [spec for i, spec in enumerate(specialties) if i != candidate]
        ok = True
        for skill in required:
            match = next((spec for spec in remaining if spec[0] == skill), None)
            if match is None:
                ok = False
                break
            remaining.remove(match)
        if ok:
            return []
    return [f"Specialties: take {rule}"]


def _discipline_errors(sub, merit_names):
    errors = []
    levels = dict(sub.disciplines)
    if sub.clan == THIN_BLOOD_CLAN:
        alchemy = levels.pop(ALCHEMY, 0)
        if alchemy != (1 if "Thin-blood Alchemist" in merit_names else 0):
            errors.append("Disciplines: a thin-blood has Thin-Blood Alchemy 1 only with the Thin-blood Alchemist merit")
        affinity = "Discipline Affinity" in merit_names
        if (affinity and list(levels.values()) != [1]) or (not affinity and levels):
            errors.append(
                "Disciplines: thin-bloods start with no Disciplines (one dot in one with the Discipline Affinity merit)"
            )
        return errors
    if ALCHEMY in levels:
        return ["Disciplines: Thin-Blood Alchemy is for thin-bloods only"]

    in_clan = CLANS.get(sub.clan, {}).get("disciplines", [])
    predator = PREDATOR_TYPES.get(sub.predator_type) if sub.predator_type else None
    predator_choices = [None]
    if predator:
        predator_choices = [
            name
            for name in predator.get("disciplines", [])
            if sub.clan in predator.get("discipline_clans", {}).get(name, [sub.clan])
        ]

    def base_ok(base):
        base = {name: dots for name, dots in base.items() if dots}
        if sorted(base.values(), reverse=True) != list(CREATION_DISCIPLINE_DOTS):
            return False
        if sub.clan == CAITIFF_CLAN:
            return all(name != ALCHEMY for name in base)
        return all(name in in_clan for name in base)

    for choice in predator_choices:
        base = dict(levels)
        if choice is not None:
            if not base.get(choice):
                continue
            base[choice] -= 1
        if base_ok(base):
            return []
    where = "any two Disciplines" if sub.clan == CAITIFF_CLAN else f"two of {', '.join(in_clan)}"
    rule = f"Disciplines: 2 dots in one and 1 in another of {where}"
    if predator:
        rule += (
            f", plus 1 dot from {sub.predator_type} in one of {', '.join(predator_choices) or '(none for your clan)'}"
        )
    return [rule]


def _power_errors(sub):
    errors = []
    counts = Counter()
    for power_name in sub.discipline_powers:
        power = find_power(power_name)
        discipline, level = power["discipline"], power["level"]
        dots = sub.disciplines.get(discipline, 0)
        if not dots:
            errors.append(f"Powers: {power_name} is a {discipline} power and you have no {discipline}")
            continue
        if level > dots:
            errors.append(f"Powers: {power_name} needs {discipline} {level}; you have {dots}")
        if power.get("amalgam"):
            other, _, other_level = power["amalgam"].rpartition(" ")
            if sub.disciplines.get(other, 0) < int(other_level):
                errors.append(f"Powers: {power_name} also needs {power['amalgam']}")
        counts[discipline] += 1
    for discipline, dots in sub.disciplines.items():
        expected = 0 if discipline == ALCHEMY else dots
        if counts[discipline] != expected:
            if discipline == ALCHEMY:
                errors.append("Powers: Thin-Blood Alchemy has formulas, not powers; list none")
            else:
                errors.append(f"Powers: take one {discipline} power per dot ({dots}); you listed {counts[discipline]}")
    return errors


def _item_errors(sub):
    """Each named advantage/flaw exists and is taken at an allowed rating."""
    errors = []
    for item in sub.advantages:
        kind, canonical = _resolve_advantage(item.name)
        if kind is None:
            errors.append(f"Advantages: unknown advantage '{item.name}'")
        elif kind == "backgrounds":
            top = BACKGROUNDS[canonical].get("max_dots", 5)
            if not 1 <= item.dots <= top:
                errors.append(f"Advantages: {canonical} is rated 1-{top}, not {item.dots}")
            if BACKGROUNDS[canonical].get("instanced") and not item.note:
                errors.append(f"Advantages: each {canonical} needs a note saying who or what it is")
        elif item.dots not in MERITS[canonical]["dots"]:
            allowed = ", ".join(str(d) for d in MERITS[canonical]["dots"])
            errors.append(f"Advantages: {canonical} is taken at {allowed} dots, not {item.dots}")
    for item in sub.flaws:
        canonical = _canonical(item.name, FLAWS)
        if canonical is None:
            errors.append(f"Flaws: unknown flaw '{item.name}'")
        elif item.dots not in FLAWS[canonical]["dots"]:
            allowed = ", ".join(str(d) for d in FLAWS[canonical]["dots"])
            errors.append(f"Flaws: {canonical} is taken at {allowed} dots, not {item.dots}")
    return errors


def _choice_errors(sub, label, items, groups, table_for):
    """Items marked source "predator" must exactly fill the predator type's choice grants."""
    chosen = [item for item in items if item.source == "predator"]
    if not groups:
        if chosen:
            return [f"{label}: {sub.predator_type or 'your predator type'} gives no {label.lower()} to choose"]
        return []
    errors = []
    for group in groups:
        names = set(group.get("from", []))
        categories = set(group.get("from_categories", []))
        total = 0
        for item in chosen:
            kind, canonical = table_for(item.name)
            category = kind and kind.get(canonical, {}).get("category")
            if canonical in names or category in categories:
                total += item.dots
            else:
                errors.append(f"{label}: {item.name} is not one of {sub.predator_type}'s choices")
        if total != group["dots"]:
            options = ", ".join(sorted(names) + [f"any {c} flaw" for c in sorted(categories)])
            errors.append(f"{label}: {sub.predator_type} gives {group['dots']} dots among {options}; you chose {total}")
    return errors


def _advantage_errors(sub):
    errors = _item_errors(sub)
    if errors:
        return errors
    sheet = build_sheet(sub)
    age = GENERATION_BY_AGE.get(sub.age, {})
    is_thin = sub.clan == THIN_BLOOD_CLAN
    predator = _predator(sub) if sub.predator_type in PREDATOR_TYPES else {}

    def advantage_table(name):
        kind, canonical = _resolve_advantage(name)
        return ({"merits": MERITS, "backgrounds": BACKGROUNDS}.get(kind), canonical)

    def flaw_table(name):
        return FLAWS, _canonical(name, FLAWS)

    errors += _choice_errors(
        sub, "Advantages", sub.advantages, (predator or {}).get("advantage_choices", []), advantage_table
    )
    errors += _choice_errors(sub, "Flaws", sub.flaws, (predator or {}).get("flaw_choices", []), flaw_table)

    # Bought dots (thin-blood pairs and predator choices don't count).
    thin_merits, thin_flaws, bought_advantages, bought_flaws = [], [], 0, 0
    for item in sub.advantages:
        kind, canonical = _resolve_advantage(item.name)
        if kind == "merits" and MERITS[canonical].get("thin_blood"):
            thin_merits.append(canonical)
        elif item.source is None:
            bought_advantages += item.dots
    for item in sub.flaws:
        canonical = _canonical(item.name, FLAWS)
        if FLAWS[canonical].get("thin_blood"):
            thin_flaws.append(canonical)
        elif item.source is None:
            bought_flaws += item.dots

    advantage_budget = CREATION_ADVANTAGE_DOTS + age.get("extra_advantage_dots", 0)
    flaw_budget = CREATION_FLAW_DOTS + age.get("extra_flaw_dots", 0)
    if bought_advantages > advantage_budget:
        errors.append(f"Advantages: spend at most {advantage_budget} dots; you spent {bought_advantages}")
    if bought_flaws != flaw_budget:
        errors.append(f"Flaws: take exactly {flaw_budget} dots of flaws; you took {bought_flaws}")

    low, high = CREATION_THIN_BLOOD_PAIRS
    if is_thin:
        if not low <= len(thin_merits) <= high or len(thin_flaws) != len(thin_merits):
            errors.append(
                f"Thin-blood: take {low}-{high} thin-blood merits and the same number of thin-blood flaws "
                f"(you have {len(thin_merits)} and {len(thin_flaws)})"
            )
    elif thin_merits or thin_flaws:
        errors.append("Thin-blood merits and flaws are for thin-bloods only")

    # Totals on the sheet: each merged rating must still be a legal one.
    for name, dots in sheet.merits.items():
        if dots not in MERITS[name]["dots"]:
            errors.append(f"Advantages: {name} would total {dots} dots, which isn't a rating it has")
    for name, dots in sheet.flaws.items():
        if dots not in FLAWS[name]["dots"]:
            errors.append(f"Flaws: {name} would total {dots} dots, which isn't a rating it has")
    for name, dots in sheet.backgrounds.items():
        top = BACKGROUNDS[name].get("max_dots", 5)
        if dots > top:
            errors.append(f"Advantages: {name} would total {dots} dots; the most is {top}")
    seen_instances = set()
    for name, note, _dots in sheet.background_instances:
        key = (name, note.lower())
        if key in seen_instances:
            errors.append(f"Advantages: two {name} share the note '{note}'; give each a different one")
        seen_instances.add(key)

    errors += _restriction_errors(sub, sheet)
    return errors


def _restriction_errors(sub, sheet):
    """Clan bans, exclusions and prerequisites recorded in MERITS/FLAWS/CLANS."""
    errors = []
    clan = CLANS.get(sub.clan, {})
    banned_categories = set(clan.get("excluded_merit_categories", []))
    taken = set(sheet.merits) | set(sheet.flaws)
    reported = set()
    entries = [("merits", n, MERITS[n]) for n in sheet.merits] + [("flaws", n, FLAWS[n]) for n in sheet.flaws]
    for kind, name, entry in entries:
        if sub.clan in entry.get("excluded_clans", []):
            errors.append(f"{kind.title()}: {sub.clan} can't take {name}")
        if kind == "merits" and entry.get("category") in banned_categories:
            errors.append(f"Merits: {sub.clan} can't take {entry['category']} merits ({name})")
        for other in entry.get("excludes", []):
            pair = frozenset((name, other))
            if other in taken and pair not in reported:
                reported.add(pair)
                errors.append(f"{name} and {other} can't be taken together")
        for requirement in entry.get("requires", []):
            if _sheet_rating(sheet, requirement["kind"], requirement["name"]) < requirement["dots"]:
                errors.append(f"{name} needs {requirement['name']} {requirement['dots']}")
        by_clan = entry.get("requires_by_clan")
        if by_clan:
            curse_clan = _clan_from_note(sub, name)
            for needed in by_clan.get(curse_clan, []):
                if needed not in taken:
                    errors.append(f"{name} ({curse_clan}) needs {needed}")
    return errors


def _clan_from_note(sub, flaw_name):
    """The clan a Clan Curse names in its note."""
    for item in sub.flaws:
        if _canonical(item.name, FLAWS) == flaw_name:
            return _canonical(item.note, CLANS) or item.note
    return None


def _sheet_rating(sheet, kind, name):
    if kind == "merits":
        return sheet.merits.get(name, 0)
    if kind == "flaws":
        return sheet.flaws.get(name, 0)
    if BACKGROUNDS.get(name, {}).get("instanced"):
        return sum(dots for bg, _note, dots in sheet.background_instances if bg == name)
    return sheet.backgrounds.get(name, 0)


def validate_v5_creation(sub):
    """Every V5 creation rule the submission breaks, as player-facing strings.

    Pure: reads only `sub` and world/v5_data.py. An empty list means valid.
    Name uniqueness is checked against the database by the caller.
    """
    errors = _identity_errors(sub)
    errors += _attribute_errors(sub)
    errors += _skill_errors(sub)
    errors += _specialty_errors(sub)
    merit_names = {_resolve_advantage(item.name)[1] for item in sub.advantages}
    errors += _discipline_errors(sub, merit_names)
    errors += _power_errors(sub)
    errors += _advantage_errors(sub)
    return errors


# ----------------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------------


def apply_chargen(character, sub):
    """Write a validated submission onto a fresh character through its accessors.

    Call only after validate_v5_creation(sub) returned no errors, on a
    character whose chargen stores are fresh (new, or reset_sheet()).
    """
    from commands.v5.utils.xp_utils import award_xp

    sheet = build_sheet(sub)
    character.clan = sub.clan
    character.generation = sub.generation
    character.blood_potency = sheet.blood_potency
    character.humanity = sheet.humanity
    character.hunger = CREATION_HUNGER
    character.predator_type = sub.predator_type

    for key, rating in sub.attributes.items():
        character.set_trait(key, rating, "attributes")
    for key, rating in sub.skills.items():
        character.set_trait(key, rating, "skills")
    for skill, name in sub.specialties:
        character.add_specialty(skill, name)
    for discipline, dots in sub.disciplines.items():
        character.set_trait(discipline, dots, "disciplines")
    for power in sub.discipline_powers:
        character.learn_power(power)

    for name, dots in sheet.backgrounds.items():
        character.set_trait(name, dots, "backgrounds")
    for name, note, dots in sheet.background_instances:
        character.set_background_instance(name, note, dots)
    for name, dots in sheet.merits.items():
        character.set_advantage("merits", name, dots)
    for name, dots in sheet.flaws.items():
        character.set_advantage("flaws", name, dots)

    if sheet.xp:
        award_xp(character, sheet.xp, reason=f"Starting experience ({sub.age})")
    return sheet
