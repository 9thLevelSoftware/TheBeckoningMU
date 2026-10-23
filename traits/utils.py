"""
Trait system utilities that bridge the new database-driven traits
with the existing character.db.stats system in world/data.py.

This allows for enhanced trait management while preserving existing character data
and enhancing the JSON import system for web-based character creation.
"""

from .models import CharacterBio, CharacterPower, CharacterTrait, DisciplinePower, Trait, TraitCategory

# Import compatibility layer from v5_data
try:
    from world.v5_data import ATTRIBUTES, PREDATOR_TYPES, SKILLS, STATS
    from world.v5_data import CLANS as SPLATS
    from world.v5_data import get_trait_category as _get_trait_category_v5

    # Use v5_data's get_trait_category function
    get_trait_category = _get_trait_category_v5

    # Stub function for compatibility (not used in v5 system)
    def get_trait_list(category):
        return []

except ImportError:
    # Fallback if v5_data is not available
    ATTRIBUTES = {}
    SKILLS = {}
    SPLATS = {}
    STATS = {}
    PREDATOR_TYPES = {}

    def get_trait_list(category):
        return []

    def get_trait_category(trait_name):
        return None


import copy
from collections.abc import Mapping, MutableSequence

from django.db import models, transaction

# V5 Character Creation Rules -- must match frontend validation
# Source: character_creation.html lines 319-345 (attributes), 404-431 (skills), 557-558 (disciplines)
V5_CHARGEN_RULES = {
    "attribute_total_additional": 15,  # 7 + 5 + 3 (above base 1 per attribute)
    "attribute_base_per": 1,
    "attribute_count": 9,  # 3 physical + 3 social + 3 mental
    "skill_total": 27,  # 13 + 9 + 5
    "discipline_total": 3,
    "discipline_min_in_clan": 2,  # At least 2 must be in-clan (non-Caitiff)
    "advantage_total": 7,
    "flaw_max": 2,
    "trait_max": 5,
}

# V5 attribute names (all start at base 1)
V5_ATTRIBUTES = [
    "strength",
    "dexterity",
    "stamina",
    "charisma",
    "manipulation",
    "composure",
    "intelligence",
    "wits",
    "resolve",
]

# V5 skill names (all start at 0)
V5_SKILLS = [
    # Physical
    "athletics",
    "brawl",
    "craft",
    "drive",
    "firearms",
    "melee",
    "larceny",
    "stealth",
    "survival",
    # Social
    "animal_ken",
    "etiquette",
    "insight",
    "intimidation",
    "leadership",
    "performance",
    "persuasion",
    "streetwise",
    "subterfuge",
    # Mental
    "academics",
    "awareness",
    "finance",
    "investigation",
    "medicine",
    "occult",
    "politics",
    "science",
    "technology",
]


def validate_v5_chargen_pools(json_data, clan=None):
    """
    Validate V5 character creation pool totals against chargen rules.

    Checks that total dots spent on attributes, skills, disciplines,
    advantages, and flaws match the allowed totals from V5 chargen rules.
    Does NOT validate priority distribution (which category gets 7/5/3).

    Args:
        json_data: Dictionary containing character data from the frontend.
                   Attributes and skills are flat keys (e.g., 'strength': 3).
                   Disciplines are in json_data['disciplines'] dict.
                   Advantages are in json_data['advantages'] dict with {value, instance?, specialty?}.
                   Flaws are in json_data['flaws'] dict with {value, instance?, specialty?}.
        clan: Optional clan name for in-clan discipline validation.

    Returns:
        List of validation error strings (empty if valid).
    """
    errors = []
    rules = V5_CHARGEN_RULES

    # --- Attribute pool validation ---
    # Attributes are flat keys in json_data with base of 1 each
    attribute_total = 0
    for attr_name in V5_ATTRIBUTES:
        rating = json_data.get(attr_name, 0)
        if isinstance(rating, (int, float)):
            attribute_total += int(rating)

    # Total additional dots = total ratings - (base 1 * 9 attributes)
    additional_dots = attribute_total - (rules["attribute_base_per"] * rules["attribute_count"])
    if additional_dots != rules["attribute_total_additional"]:
        errors.append(
            f"Attributes: Must spend exactly {rules['attribute_total_additional']} additional dots "
            f"(currently {additional_dots})"
        )

    # --- Skill pool validation ---
    # Skills are flat keys in json_data with base of 0
    skill_total = 0
    for skill_name in V5_SKILLS:
        rating = json_data.get(skill_name, 0)
        if isinstance(rating, (int, float)):
            skill_total += int(rating)

    if skill_total != rules["skill_total"]:
        errors.append(f"Skills: Must spend exactly {rules['skill_total']} dots (currently {skill_total})")

    # --- Discipline pool validation ---
    disciplines = json_data.get("disciplines", {})
    discipline_total = 0
    if isinstance(disciplines, dict):
        for _disc_name, rating in disciplines.items():
            if isinstance(rating, (int, float)):
                discipline_total += int(rating)

    # Account for predator discipline bonus (+1 dot)
    has_predator_bonus = bool(json_data.get("predator_discipline", ""))
    expected_total = rules["discipline_total"] + (1 if has_predator_bonus else 0)

    if discipline_total != expected_total:
        errors.append(
            f"Disciplines: Must spend exactly {rules['discipline_total']} in-clan dots "
            f"(plus predator bonus if applicable). Currently {discipline_total} total"
        )

    # In-clan discipline check (skip for Caitiff and Thin-Blood)
    if (
        discipline_total == expected_total
        and clan
        and clan not in ("Caitiff", "Thin-Blood")
        and isinstance(disciplines, dict)
    ):
        in_clan_discs = []
        if clan in SPLATS and "disciplines" in SPLATS[clan]:
            in_clan_discs = SPLATS[clan]["disciplines"]

        # Get predator discipline (the one allowed out-of-clan exception)
        predator_discipline = json_data.get("predator_discipline", "")
        predator_type = json_data.get("predator_type", "")

        # Validate predator discipline is valid for the predator type
        if predator_discipline and predator_type:
            valid_pred_discs = PREDATOR_TYPES.get(predator_type, {}).get("disciplines", [])
            if predator_discipline not in valid_pred_discs:
                errors.append(
                    f"Disciplines: '{predator_discipline}' is not a valid discipline "
                    f"for predator type '{predator_type}'"
                )

        if in_clan_discs:
            for disc_name, rating in disciplines.items():
                if not isinstance(rating, (int, float)) or int(rating) <= 0:
                    continue
                # Subtract predator bonus to isolate in-clan allocation
                base_rating = int(rating)
                if disc_name == predator_discipline:
                    base_rating -= 1
                if base_rating > 0 and disc_name not in in_clan_discs:
                    errors.append(f"Disciplines: '{disc_name}' is not an in-clan discipline for {clan}")

            # Validate 2+1 pattern for in-clan allocation (excluding predator bonus)
            in_clan_ratings = []
            for disc_name, rating in disciplines.items():
                if not isinstance(rating, (int, float)) or int(rating) <= 0:
                    continue
                base_rating = int(rating)
                if disc_name == predator_discipline:
                    base_rating -= 1
                if base_rating > 0:
                    in_clan_ratings.append(base_rating)

            if sorted(in_clan_ratings) != [1, 2]:
                errors.append("Disciplines: In-clan allocation must be 2 dots in one discipline and 1 dot in another")

    # --- Advantage pool validation ---
    advantages = json_data.get("advantages", {})
    advantage_total = 0
    if isinstance(advantages, dict):
        for _adv_name, adv_data in advantages.items():
            if isinstance(adv_data, dict):
                value = adv_data.get("value", 0)
                if isinstance(value, (int, float)):
                    advantage_total += int(value)
            elif isinstance(adv_data, (int, float)):
                advantage_total += int(adv_data)

    if advantage_total != rules["advantage_total"]:
        errors.append(f"Advantages: Must spend exactly {rules['advantage_total']} points (currently {advantage_total})")

    # --- Flaw pool validation ---
    flaws = json_data.get("flaws", {})
    flaw_total = 0
    if isinstance(flaws, dict):
        for _flaw_name, flaw_data in flaws.items():
            if isinstance(flaw_data, dict):
                value = flaw_data.get("value", 0)
                if isinstance(value, (int, float)):
                    flaw_total += int(value)
            elif isinstance(flaw_data, (int, float)):
                flaw_total += int(flaw_data)

    if flaw_total > rules["flaw_max"]:
        errors.append(f"Flaws: Cannot exceed {rules['flaw_max']} points (currently {flaw_total})")

    return errors


def get_trait_definition(trait_name):
    """
    Get trait definition from the database, with fallback to world/data.py.

    Args:
        trait_name: Name of the trait to look up

    Returns:
        Dictionary with trait information, or None if not found
    """
    try:
        trait = Trait.objects.get(name__iexact=trait_name)
        return {
            "name": trait.name,
            "category": trait.category.code,
            "description": trait.description,
            "min_value": trait.min_value,
            "max_value": trait.max_value,
            "has_specialties": trait.has_specialties,
            "is_instanced": trait.is_instanced,
            "splat_restriction": trait.splat_restriction,
        }
    except Trait.DoesNotExist:
        # Fallback to existing world/data.py system
        return get_trait_list(trait_name)


def _trait_key(name):
    return name.lower().replace(" ", "_")


def _plain(value):
    """Detach Evennia's saved containers before constructing a replacement."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (MutableSequence, tuple)):
        return [_plain(item) for item in value]
    return value


def _gameplay_stats(character):
    """Normalize the legacy flat template to the Character gameplay schema."""
    stats = _plain(character.db.stats) if character.db.stats else {}
    for category, definitions, default in (("attributes", ATTRIBUTES, 1), ("skills", SKILLS, 0)):
        old = stats.get(category, {})
        normalized = {}
        for group, names in definitions.items():
            group_values = old.get(group.lower(), {}) if isinstance(old, Mapping) else {}
            normalized[group.lower()] = {
                _trait_key(name): group_values.get(
                    _trait_key(name), old.get(_trait_key(name), old.get(name.lower(), default))
                )
                for name in names
            }
        stats[category] = normalized
    disciplines = stats.get("disciplines", {})
    stats["disciplines"] = {
        _trait_key(name): (_plain(value) if isinstance(value, Mapping) else {"level": value, "powers": []})
        for name, value in disciplines.items()
    }
    stats.setdefault("specialties", {})
    return stats


def _find_trait(name):
    return Trait.objects.select_related("category").get(name__iexact=name.replace("_", " "))


def get_character_trait_value(character, trait_name, instance_name=None, specialty=None):
    """Read the database bridge, with the nested gameplay schema as fallback."""
    try:
        trait = _find_trait(trait_name)
        return CharacterTrait.objects.get(
            character=character, trait=trait, instance_name=instance_name, specialty=specialty
        ).rating
    except (Trait.DoesNotExist, CharacterTrait.DoesNotExist):
        pass
    if not hasattr(character, "db"):
        return 0
    key = _trait_key(trait_name)
    stats = character.db.stats or {}
    if specialty:
        values = stats.get("specialties", {}).get(key, {})
        if isinstance(values, str):
            return int(values.lower() == specialty.lower())
        return values.get(specialty.lower(), 0)
    for category in ("attributes", "skills"):
        values = stats.get(category, {})
        for group in ("physical", "social", "mental"):
            if key in values.get(group, {}):
                return values[group][key]
        if key in values:
            return values[key]
        if trait_name.lower() in values:
            return values[trait_name.lower()]
    disciplines = stats.get("disciplines", {})
    if key in disciplines:
        value = disciplines[key]
        return value.get("level", 0) if isinstance(value, Mapping) else value
    if key in ("blood_potency", "humanity", "generation"):
        return (character.db.vampire or {}).get(key, stats.get(key, 0))
    advantages = character.db.advantages or {}
    if instance_name:
        key = f"{key}_{_trait_key(instance_name)}"
    for category in ("backgrounds", "merits", "flaws"):
        if key in advantages.get(category, {}):
            return advantages[category][key]
    return stats.get("backgrounds", {}).get(key, 0)


def set_character_trait_value(character, trait_name, rating, instance_name=None, specialty=None):
    """Write the DB bridge and the actual nested Character gameplay schema."""
    if not hasattr(character, "db"):
        return False
    try:
        trait = _find_trait(trait_name)
    except Trait.DoesNotExist:
        trait = None
    if trait:
        CharacterTrait.objects.update_or_create(
            character=character,
            trait=trait,
            instance_name=instance_name,
            specialty=specialty,
            defaults={"rating": rating},
        )
    stats = _gameplay_stats(character)
    key = _trait_key(trait_name)
    category = trait.category.code if trait else get_trait_category(trait_name.replace("_", " ").title())
    if specialty and category not in ("advantages", "flaws", "backgrounds", "merits"):
        values = stats["specialties"].get(key, {})
        if isinstance(values, str):
            values = {values.lower(): 1}
        values[specialty.lower()] = rating
        stats["specialties"][key] = values
    else:
        assigned = False
        for kind in ("attributes", "skills"):
            for values in stats[kind].values():
                if key in values:
                    values[key] = rating
                    assigned = True
        if not assigned and category == "disciplines":
            stats["disciplines"].setdefault(key, {"level": 0, "powers": []})["level"] = rating
        elif not assigned:
            advantages = _plain(character.db.advantages) if character.db.advantages else {}
            target = "flaws" if category == "flaws" else "backgrounds"
            stored_key = f"{key}_{_trait_key(instance_name)}" if instance_name else key
            advantages.setdefault(target, {})[stored_key] = rating
            character.db.advantages = advantages
    character.db.stats = stats
    return True


def sync_character_to_new_system(character):
    """
    Sync a character's existing db.stats data to the new trait system.

    Args:
        character: Character object to sync

    Returns:
        Dictionary with sync results
    """
    if not hasattr(character, "db") or not character.db.stats:
        return {"success": False, "error": "Character has no stats to sync"}

    stats = character.db.stats
    results = {"success": True, "synced_traits": 0, "synced_specialties": 0, "synced_powers": 0, "errors": []}

    # Sync basic traits (attributes, skills, etc.)
    for category_name, traits_dict in stats.items():
        if category_name in ["specialties", "xp", "notes", "approved_by", "approved"]:
            continue  # Skip special categories

        if isinstance(traits_dict, dict):
            for trait_name, rating in traits_dict.items():
                if isinstance(rating, (int, float)):
                    try:
                        trait = Trait.objects.get(name__iexact=trait_name, category__code=category_name)
                        char_trait, created = CharacterTrait.objects.get_or_create(
                            character=character, trait=trait, defaults={"rating": int(rating)}
                        )
                        if created:
                            results["synced_traits"] += 1
                    except Trait.DoesNotExist:
                        results["errors"].append(f"Trait '{trait_name}' not found in new system")

    # Sync specialties
    if "specialties" in stats:
        for trait_name, specialties_dict in stats["specialties"].items():
            if isinstance(specialties_dict, dict):
                for specialty_name, rating in specialties_dict.items():
                    if isinstance(rating, (int, float)):
                        try:
                            trait = Trait.objects.get(name__iexact=trait_name)
                            char_trait, created = CharacterTrait.objects.get_or_create(
                                character=character,
                                trait=trait,
                                specialty=specialty_name,
                                defaults={"rating": int(rating)},
                            )
                            if created:
                                results["synced_specialties"] += 1
                        except Trait.DoesNotExist:
                            results["errors"].append(f"Trait '{trait_name}' for specialty not found")

    return results


def get_available_traits_for_character(character):
    """
    Get all available traits for a character based on their splat.

    Args:
        character: Character object

    Returns:
        QuerySet of available Trait objects
    """
    # Get character's splat
    splat = None
    if hasattr(character, "db") and character.db.stats:
        splat = character.db.stats.get("splat", "mortal")

    # Filter traits based on splat restrictions
    available_traits = Trait.objects.filter(is_active=True)

    if splat:
        # Include traits with no restriction or matching splat restriction
        available_traits = available_traits.filter(
            models.Q(splat_restriction__isnull=True)
            | models.Q(splat_restriction="")
            | models.Q(splat_restriction=splat)
        )

    return available_traits.order_by("category__sort_order", "sort_order", "name")


def get_character_discipline_powers(character):
    """
    Get all discipline powers a character has learned.

    Args:
        character: Character object

    Returns:
        QuerySet of CharacterPower objects
    """
    return CharacterPower.objects.filter(character=character).select_related("power__discipline")


def can_learn_discipline_power(character, power):
    """
    Check if a character can learn a specific discipline power.

    Args:
        character: Character object
        power: DisciplinePower object

    Returns:
        Tuple (can_learn: bool, reason: str)
    """
    # Check if character has required discipline level
    discipline_rating = get_character_trait_value(character, power.discipline.name)
    if discipline_rating < power.level:
        return False, f"Requires {power.discipline.name} {power.level} (current: {discipline_rating})"

    # Check amalgam requirements
    if power.amalgam_discipline:
        amalgam_rating = get_character_trait_value(character, power.amalgam_discipline.name)
        if amalgam_rating < power.amalgam_level:
            return False, f"Requires {power.amalgam_discipline.name} {power.amalgam_level} (current: {amalgam_rating})"

    # Check if already known
    if CharacterPower.objects.filter(character=character, power=power).exists():
        return False, "Already known"

    return True, "Can learn"


def format_character_sheet_database(character):
    """
    Format a character sheet using data from the new trait system.
    This provides an enhanced view with database-driven information.

    Args:
        character: Character object

    Returns:
        Formatted string for display
    """
    output = f"|w=== {character.key}'s Character Sheet (Database View) ===|n\n"

    # Get character traits organized by category
    char_traits = CharacterTrait.objects.filter(character=character).select_related("trait__category")

    categories = TraitCategory.objects.all().order_by("sort_order")

    for category in categories:
        category_traits = char_traits.filter(trait__category=category)
        if category_traits.exists():
            output += f"\n|w{category.name}:|n\n"
            for char_trait in category_traits.order_by("trait__sort_order"):
                display_name = char_trait.display_name
                dots = "•" * char_trait.rating if char_trait.rating > 0 else "○"
                output += f"  {display_name:<20} {dots} ({char_trait.rating})\n"

    # Show discipline powers
    powers = get_character_discipline_powers(character)
    if powers.exists():
        output += "\n|wDiscipline Powers:|n\n"
        current_discipline = None
        for char_power in powers.order_by("power__discipline__name", "power__level"):
            if char_power.power.discipline != current_discipline:
                current_discipline = char_power.power.discipline
                output += f"\n  |c{current_discipline.name}:|n\n"
            output += f"    {char_power.power.name} (Level {char_power.power.level})\n"

    return output


def validate_trait_for_character(character, trait_name, rating, instance_name=None, specialty=None, splat=None):
    """
    Validate if a character can have a specific trait at a specific rating.

    Args:
        character: Character object
        trait_name: Name of the trait
        rating: Desired rating
        instance_name: Instance name for instanced traits (optional)
        specialty: Specialty name for traits with specialties (optional)

    Returns:
        Tuple (is_valid: bool, error_message: str)
    """
    try:
        trait = Trait.objects.get(name__iexact=trait_name)
    except Trait.DoesNotExist:
        # Fall back to old system validation
        trait_info = get_trait_list(trait_name)
        if not trait_info:
            return False, f"Trait '{trait_name}' not found"
        # Use old system validation logic here
        return True, ""

    # Check rating bounds
    if rating < trait.min_value:
        return False, f"Rating {rating} is below minimum {trait.min_value} for {trait.name}"

    if rating > trait.max_value:
        return False, f"Rating {rating} exceeds maximum {trait.max_value} for {trait.name}"

    # Check splat restrictions
    if trait.splat_restriction:
        character_splat = splat
        if character_splat is None and hasattr(character, "db") and character.db.stats:
            character_splat = character.db.stats.get("splat", "mortal")

        if character_splat != trait.splat_restriction:
            return False, f"{trait.name} is only available to {trait.splat_restriction} characters"

    # Check instanced trait requirements
    if trait.is_instanced and not instance_name:
        return False, f"{trait.name} requires an instance name (e.g., 'Allies: Police')"

    if not trait.is_instanced and instance_name:
        return False, f"{trait.name} is not an instanced trait"

    return True, ""


def refresh_character_attribute_cache(character, attributes=()):
    """Restore this character's cached Attributes from scalar rows after rollback.

    Model refresh_from_db is insufficient with Evennia's identity mapper: it can
    return the same mutated instance. Preserve object references but replace its
    scalar state directly; evict only Attributes whose creation was rolled back.
    """
    from evennia.typeclasses.attributes import Attribute

    held = {}
    for item in (*attributes, *character.attributes.backend._cache.values()):
        pk, attribute = item if isinstance(item, tuple) else (getattr(item, "pk", None), item)
        if pk:
            held[pk] = attribute
    rows = {row["id"]: row for row in Attribute.objects.filter(pk__in=held).values()}
    for pk, attribute in held.items():
        if pk not in rows:
            attribute.flush_from_cache(force=True)
            continue
        attribute.__dict__.update(rows[pk])
        attribute._state.fields_cache.clear()
        attribute.__dict__.pop("_prefetched_objects_cache", None)
        attribute.__dict__.pop("_is_deleted", None)
    character.__dict__.pop("_prefetched_objects_cache", None)
    character._state.fields_cache.pop("vtm_bio", None)
    character.attributes.reset_cache()


def _import_result():
    return {
        "success": True,
        "errors": [],
        "warnings": [],
        "validation_errors": [],
        "imported_traits": 0,
        "imported_specialties": 0,
        "imported_powers": 0,
    }


def _normalize_import(json_data, errors):
    """Accept frontend flat fields and exported maps without silent conflicts."""
    if not isinstance(json_data, dict):
        errors.append("Character data must be an object")
        return {}
    data = copy.deepcopy(json_data)
    for category, names in (("attributes", V5_ATTRIBUTES), ("skills", V5_SKILLS)):
        nested = data.get(category, {})
        if not isinstance(nested, dict):
            errors.append(f"{category} must be an object")
            continue
        entries = []
        for name, value in nested.items():
            if name in ("physical", "social", "mental") and isinstance(value, dict):
                entries.extend(value.items())
            else:
                entries.append((name, value))
        for name, rating in entries:
            if not isinstance(name, str) or _trait_key(name) not in names:
                errors.append(f"Unknown {category} trait: {name}")
                continue
            key = _trait_key(name)
            if key in data and (type(data[key]) is not type(rating) or data[key] != rating):
                errors.append(f"Conflicting values for {key}")
            else:
                data[key] = rating
    return data


def _prepare_character_import(character, json_data, result):
    errors = result["validation_errors"]
    data = _normalize_import(json_data, errors)
    if errors:
        return data, [], []
    splat = data.setdefault("splat", "vampire")
    if splat not in ("vampire", "ghoul", "mortal"):
        errors.append("Invalid character splat")
    for name in (
        "name",
        "full_name",
        "concept",
        "clan",
        "sire",
        "predator_type",
        "predator_discipline",
        "ambition",
        "desire",
        "background",
    ):
        if name in data and not isinstance(data[name], str):
            errors.append(f"{name} must be text")
    for name, limit in (
        ("name", 200),
        ("full_name", 200),
        ("concept", 100),
        ("clan", 50),
        ("sire", 100),
        ("predator_type", 50),
    ):
        if isinstance(data.get(name), str) and len(data[name]) > limit:
            errors.append(f"{name} cannot exceed {limit} characters")
    generation = data.get("generation")
    if generation is not None and (type(generation) is not int or not 1 <= generation <= 32767):
        errors.append("generation must be a positive integer or null")
    if isinstance(data.get("clan"), str) and data["clan"] and data["clan"] not in SPLATS:
        errors.append("Invalid vampire clan")
    if (
        isinstance(data.get("predator_type"), str)
        and data["predator_type"]
        and data["predator_type"] not in PREDATOR_TYPES
    ):
        errors.append("Invalid predator type")

    prepared = []
    categories = {
        "attributes": {name: data.get(name, 0) for name in V5_ATTRIBUTES},
        "skills": {name: data.get(name, 0) for name in V5_SKILLS},
        **{name: data.get(name, {}) for name in ("disciplines", "advantages", "flaws")},
    }
    # Pool validation receives the same canonical, catalog-cased values as writes.
    pool_data = {**data, "disciplines": {}, "advantages": {}, "flaws": {}}
    seen = set()
    for category, values in categories.items():
        if not isinstance(values, dict):
            errors.append(f"{category} must be an object")
            continue
        for name, raw in values.items():
            if not isinstance(name, str):
                errors.append(f"{category} names must be text")
                continue
            entries = raw if isinstance(raw, list) and category in ("advantages", "flaws") else [raw]
            if not entries:
                errors.append(f"{name} must have at least one entry")
            for entry in entries:
                structured = isinstance(entry, dict)
                rating = entry.get("value") if structured else entry
                instance = entry.get("instance") if structured else None
                specialty = entry.get("specialty") if structured else None
                if structured and set(entry) - {"value", "instance", "specialty"}:
                    errors.append(f"Invalid fields for {name}")
                if type(rating) is not int or not 0 <= rating <= 5:
                    errors.append(f"{name} must have an integer rating between 0 and 5")
                    continue
                if category in ("attributes", "skills") and structured:
                    errors.append(f"{name} must have an integer rating")
                    continue
                if any(
                    value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 100)
                    for value in (instance, specialty)
                ):
                    errors.append(f"{name} instance/specialty must be nonempty text of at most 100 characters")
                    continue
                # Empty optional choices need not be seeded catalog entries.
                if rating == 0 and category != "attributes":
                    continue
                try:
                    trait = _find_trait(name)
                except Trait.DoesNotExist:
                    errors.append(f"Trait '{name}' not found")
                    continue
                if trait.category.code != category:
                    errors.append(f"{trait.name} is not in category {category}")
                    continue
                if not trait.is_active:
                    errors.append(f"{trait.name} is not active")
                    continue
                if specialty and not trait.has_specialties:
                    errors.append(f"{trait.name} does not support specialties")
                    continue
                valid, error = validate_trait_for_character(
                    character, trait.name, rating, instance, specialty, splat=splat
                )
                if not valid:
                    errors.append(error)
                    continue
                identity = (trait.pk, instance, specialty)
                if identity in seen:
                    errors.append(f"Duplicate trait {trait.name}")
                    continue
                seen.add(identity)
                prepared.append((trait, rating, instance, specialty))
                if category in ("advantages", "flaws"):
                    pool_data[category][f"{trait.pk}:{instance}:{specialty}"] = rating
                elif category == "disciplines":
                    pool_data[category][trait.name] = rating
    specialties = data.get("specialties", {})
    if not isinstance(specialties, dict):
        errors.append("specialties must be an object")
    else:
        for name, values in specialties.items():
            if not isinstance(name, str) or not isinstance(values, dict):
                errors.append("Specialties must map skill names to specialty ratings")
                continue
            try:
                trait = _find_trait(name)
            except Trait.DoesNotExist:
                errors.append(f"Trait '{name}' not found")
                continue
            if trait.category.code != "skills" or not trait.has_specialties:
                errors.append(f"{name} does not support skill specialties")
                continue
            for specialty, rating in values.items():
                if (
                    not isinstance(specialty, str)
                    or not specialty.strip()
                    or len(specialty) > 100
                    or type(rating) is not int
                    or not 1 <= rating <= 5
                ):
                    errors.append(f"Invalid specialty for {name}")
                    continue
                if data.get(_trait_key(trait.name), 0) < 1:
                    errors.append(f"{name} requires a dot before taking a specialty")
                    continue
                valid, error = validate_trait_for_character(
                    character, trait.name, rating, specialty=specialty, splat=splat
                )
                if not valid:
                    errors.append(error)
                    continue
                identity = (trait.pk, None, specialty)
                if identity in seen:
                    errors.append(f"Duplicate specialty for {name}")
                    continue
                seen.add(identity)
                prepared.append((trait, rating, None, specialty))
    powers = []
    power_names = data.get("discipline_powers", [])
    if not isinstance(power_names, list) or any(not isinstance(name, str) for name in power_names):
        errors.append("discipline_powers must be a list of names")
    else:
        levels = {
            trait.pk: rating
            for trait, rating, _, specialty in prepared
            if trait.category.code == "disciplines" and not specialty
        }
        seen_powers = set()
        for name in power_names:
            try:
                power = DisciplinePower.objects.select_related("discipline", "amalgam_discipline").get(
                    name__iexact=name
                )
            except DisciplinePower.DoesNotExist:
                errors.append(f"Discipline power '{name}' not found")
                continue
            if power.pk in seen_powers:
                errors.append(f"Duplicate discipline power '{name}'")
            elif not power.is_active or levels.get(power.discipline_id, 0) < power.level:
                errors.append(f"Cannot learn {name}: requires {power.discipline.name} {power.level}")
            elif power.amalgam_discipline_id and levels.get(power.amalgam_discipline_id, 0) < (
                power.amalgam_level or 0
            ):
                errors.append(f"Cannot learn {name}: amalgam requirement not met")
            else:
                powers.append(power)
                seen_powers.add(power.pk)
    if not errors:
        errors.extend(validate_v5_chargen_pools(pool_data, clan=data.get("clan")))
    return data, prepared, powers


def enhanced_import_character_from_json(character, json_data, validate_only=False):
    """Validate a complete sheet, then atomically replace its trait snapshot."""
    result = _import_result()
    data, prepared, powers = _prepare_character_import(character, json_data, result)
    if result["validation_errors"]:
        result["success"] = False
        return result
    if validate_only:
        return result
    attributes = [(attribute.pk, attribute) for attribute in character.attributes.all()]
    try:
        with transaction.atomic():
            result = _apply_character_import(character, data, prepared, powers)
            if not result["success"]:
                transaction.set_rollback(True)
    except Exception:
        refresh_character_attribute_cache(character, attributes)
        raise
    if not result["success"]:
        refresh_character_attribute_cache(character, attributes)
        for key in ("imported_traits", "imported_specialties", "imported_powers"):
            result[key] = 0
    return result


def _apply_character_import(character, data, prepared, powers):
    result = _import_result()
    stats = _gameplay_stats(character)
    for category, definitions, default in (("attributes", ATTRIBUTES, 1), ("skills", SKILLS, 0)):
        stats[category] = {
            group.lower(): {_trait_key(name): default for name in names} for group, names in definitions.items()
        }
    stats["disciplines"] = {}
    stats["specialties"] = {}
    stats["splat"] = data["splat"]
    # These are an imported snapshot, never an incremental XP transaction.
    CharacterTrait.objects.filter(character=character).delete()
    CharacterPower.objects.filter(character=character).delete()
    character.db.stats = stats
    character.db.advantages = {"backgrounds": {}, "merits": {}, "flaws": {}}
    for trait, rating, instance, specialty in prepared:
        if not set_character_trait_value(character, trait.name, rating, instance, specialty):
            result["errors"].append(f"Failed to set {trait.name}")
            result["success"] = False
            return result
        result["imported_specialties" if specialty and trait.category.code == "skills" else "imported_traits"] += 1
    for power in powers:
        CharacterPower.objects.create(character=character, power=power)
        character.db.stats["disciplines"][_trait_key(power.discipline.name)]["powers"].append(power.name)
        result["imported_powers"] += 1
    bio, _ = CharacterBio.objects.get_or_create(character=character)
    for name in ("concept", "clan", "sire", "generation", "predator_type", "ambition", "desire", "background"):
        if name in data:
            setattr(bio, name, data[name])
    bio.full_name = data.get("name", data.get("full_name", character.key))
    bio.splat = data["splat"]
    bio.save()
    character._state.fields_cache.pop("vtm_bio", None)
    if data["splat"] == "vampire":
        vampire = _plain(character.db.vampire) if character.db.vampire else {}
        for key in ("clan", "generation", "predator_type", "predator_discipline"):
            if key in data:
                vampire[key] = data[key]
        # Omitted predator bonus is a real removal on a resubmitted snapshot.
        vampire["predator_discipline"] = data.get("predator_discipline", "")
        character.db.vampire = vampire
    character.update_derived_stats()
    return result


def export_character_to_json(character, include_powers=True):
    """Export frontend/edit-compatible maps and lossless structured trait data."""
    stats = _gameplay_stats(character)
    vampire = character.db.vampire or {}
    result = {"name": character.key, "full_name": character.key, "splat": stats.get("splat", "vampire"), "concept": ""}
    for category in ("attributes", "skills"):
        result[category] = {name: rating for group in stats[category].values() for name, rating in group.items()}
    result["disciplines"] = {
        name.replace("_", " ").title(): value.get("level", 0) for name, value in stats["disciplines"].items()
    }
    result["advantages"] = {}
    result["flaws"] = {}
    result["specialties"] = {}
    for name, value in stats.get("specialties", {}).items():
        result["specialties"][name] = {value: 1} if isinstance(value, str) else _plain(value)
    try:
        bio = character.vtm_bio
    except CharacterBio.DoesNotExist:
        bio = None
    for name in ("concept", "clan", "sire", "generation", "predator_type", "ambition", "desire", "background", "splat"):
        if bio is not None:
            result[name] = getattr(bio, name)
        elif name in vampire:
            result[name] = vampire[name]
    if bio is not None:
        result["name"] = result["full_name"] = bio.full_name or character.key
    result["predator_discipline"] = vampire.get("predator_discipline", "")
    for row in CharacterTrait.objects.filter(character=character).select_related("trait__category"):
        category = row.trait.category.code
        name = row.trait.name
        key = _trait_key(name)
        if category in ("attributes", "skills"):
            if row.specialty:
                values = result["specialties"].get(key, {})
                values = {name: rating for name, rating in values.items() if name.lower() != row.specialty.lower()}
                values[row.specialty] = row.rating
                result["specialties"][key] = values
            else:
                result[category][key] = row.rating
        elif category == "disciplines":
            result[category][name] = row.rating
        elif category in ("advantages", "flaws"):
            value = {"value": row.rating}
            if row.instance_name:
                value["instance"] = row.instance_name
            if row.specialty:
                value["specialty"] = row.specialty
            previous = result[category].get(name)
            if previous is None:
                result[category][name] = value
            elif isinstance(previous, list):
                previous.append(value)
            else:
                result[category][name] = [previous, value]
    for category in ("attributes", "skills"):
        result.update(result[category])
    if include_powers:
        result["discipline_powers"] = list(
            CharacterPower.objects.filter(character=character).values_list("power__name", flat=True)
        )
    return result
