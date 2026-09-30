"""
Trait system utilities that bridge the new database-driven traits
with the existing character.db.stats system in world/data.py.

This allows for enhanced trait management while preserving existing character data
and enhancing the JSON import system for web-based character creation.
"""

from .models import TraitCategory, Trait, DisciplinePower, CharacterTrait, CharacterPower, CharacterBio
# Import compatibility layer from v5_data
try:
    from world.v5_data import (
        ATTRIBUTES,
        SKILLS,
        CLANS as SPLATS,
        STATS,
        PREDATOR_TYPES,
        get_trait_category as _get_trait_category_v5
    )
    
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

from evennia.objects.models import ObjectDB
from django.db import models
import json
import copy


# V5 Character Creation Rules -- must match frontend validation
# Source: character_creation.html lines 319-345 (attributes), 404-431 (skills), 557-558 (disciplines)
V5_CHARGEN_RULES = {
    'attribute_total_additional': 15,  # 7 + 5 + 3 (above base 1 per attribute)
    'attribute_base_per': 1,
    'attribute_count': 9,              # 3 physical + 3 social + 3 mental
    'skill_total': 27,                 # 13 + 9 + 5
    'discipline_total': 3,
    'discipline_min_in_clan': 2,       # At least 2 must be in-clan (non-Caitiff)
    'advantage_total': 7,
    'flaw_max': 2,
    'trait_max': 5,
}

# V5 attribute names (all start at base 1)
V5_ATTRIBUTES = [
    'strength', 'dexterity', 'stamina',
    'charisma', 'manipulation', 'composure',
    'intelligence', 'wits', 'resolve',
]

# V5 skill names (all start at 0)
V5_SKILLS = [
    # Physical
    'athletics', 'brawl', 'craft', 'drive', 'firearms', 'melee', 'larceny', 'stealth', 'survival',
    # Social
    'animal_ken', 'etiquette', 'insight', 'intimidation', 'leadership', 'performance',
    'persuasion', 'streetwise', 'subterfuge',
    # Mental
    'academics', 'awareness', 'finance', 'investigation', 'medicine', 'occult',
    'politics', 'science', 'technology',
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
    additional_dots = attribute_total - (rules['attribute_base_per'] * rules['attribute_count'])
    if additional_dots != rules['attribute_total_additional']:
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

    if skill_total != rules['skill_total']:
        errors.append(
            f"Skills: Must spend exactly {rules['skill_total']} dots (currently {skill_total})"
        )

    # --- Discipline pool validation ---
    disciplines = json_data.get('disciplines', {})
    discipline_total = 0
    if isinstance(disciplines, dict):
        for disc_name, rating in disciplines.items():
            if isinstance(rating, (int, float)):
                discipline_total += int(rating)

    # Account for predator discipline bonus (+1 dot)
    has_predator_bonus = bool(json_data.get('predator_discipline', ''))
    expected_total = rules['discipline_total'] + (1 if has_predator_bonus else 0)

    if discipline_total != expected_total:
        errors.append(
            f"Disciplines: Must spend exactly {rules['discipline_total']} in-clan dots "
            f"(plus predator bonus if applicable). Currently {discipline_total} total"
        )

    # In-clan discipline check (skip for Caitiff and Thin-Blood)
    if (discipline_total == expected_total and clan
            and clan not in ('Caitiff', 'Thin-Blood') and isinstance(disciplines, dict)):
        in_clan_discs = []
        if clan in SPLATS and 'disciplines' in SPLATS[clan]:
            in_clan_discs = SPLATS[clan]['disciplines']

        # Get predator discipline (the one allowed out-of-clan exception)
        predator_discipline = json_data.get('predator_discipline', '')
        predator_type = json_data.get('predator_type', '')

        # Validate predator discipline is valid for the predator type
        if predator_discipline and predator_type:
            valid_pred_discs = PREDATOR_TYPES.get(predator_type, {}).get('disciplines', [])
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
                    errors.append(
                        f"Disciplines: '{disc_name}' is not an in-clan discipline "
                        f"for {clan}"
                    )

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
                errors.append(
                    "Disciplines: In-clan allocation must be 2 dots in one discipline "
                    "and 1 dot in another"
                )

    # --- Advantage pool validation ---
    advantages = json_data.get('advantages', {})
    advantage_total = 0
    if isinstance(advantages, dict):
        for adv_name, adv_data in advantages.items():
            if isinstance(adv_data, dict):
                value = adv_data.get('value', 0)
                if isinstance(value, (int, float)):
                    advantage_total += int(value)
            elif isinstance(adv_data, (int, float)):
                advantage_total += int(adv_data)

    if advantage_total != rules['advantage_total']:
        errors.append(
            f"Advantages: Must spend exactly {rules['advantage_total']} points "
            f"(currently {advantage_total})"
        )

    # --- Flaw pool validation ---
    flaws = json_data.get('flaws', {})
    flaw_total = 0
    if isinstance(flaws, dict):
        for flaw_name, flaw_data in flaws.items():
            if isinstance(flaw_data, dict):
                value = flaw_data.get('value', 0)
                if isinstance(value, (int, float)):
                    flaw_total += int(value)
            elif isinstance(flaw_data, (int, float)):
                flaw_total += int(flaw_data)

    if flaw_total > rules['flaw_max']:
        errors.append(
            f"Flaws: Cannot exceed {rules['flaw_max']} points (currently {flaw_total})"
        )

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
            'name': trait.name,
            'category': trait.category.code,
            'description': trait.description,
            'min_value': trait.min_value,
            'max_value': trait.max_value,
            'has_specialties': trait.has_specialties,
            'is_instanced': trait.is_instanced,
            'splat_restriction': trait.splat_restriction,
        }
    except Trait.DoesNotExist:
        # Fallback to existing world/data.py system
        return get_trait_list(trait_name)


def get_character_trait_value(character, trait_name, instance_name=None, specialty=None):
    """
    Get a character's trait value, checking both new and old systems.

    Args:
        character: Character object
        trait_name: Name of the trait
        instance_name: Instance name for instanced traits (optional)
        specialty: Specialty name for traits with specialties (optional)

    Returns:
        Integer rating, or 0 if not found
    """
    # First check if character has the trait in the new system
    try:
        trait = Trait.objects.get(name__iexact=trait_name)
        char_trait = CharacterTrait.objects.get(
            character=character,
            trait=trait,
            instance_name=instance_name,
            specialty=specialty
        )
        return char_trait.rating
    except (Trait.DoesNotExist, CharacterTrait.DoesNotExist):
        pass

    # Fallback to existing db.stats system
    if not hasattr(character, 'db') or not character.db.stats:
        return 0

    stats = character.db.stats
    category = get_trait_category(trait_name)

    if not category or category not in stats:
        return 0

    # Handle specialties (stored separately in current system)
    if specialty and 'specialties' in stats:
        specialties = stats['specialties'].get(trait_name.lower(), {})
        return specialties.get(specialty.lower(), 0)

    # Handle instanced traits (need to parse the keys)
    if instance_name:
        # In current system, instanced traits might be stored as "trait_instance"
        for key, value in stats[category].items():
            if key.lower().startswith(trait_name.lower()) and instance_name.lower() in key.lower():
                return value
        return 0

    # Standard trait lookup
    return stats[category].get(trait_name.lower(), 0)


def set_character_trait_value(character, trait_name, rating, instance_name=None, specialty=None):
    """
    Set a character's trait value in both systems.

    Args:
        character: Character object
        trait_name: Name of the trait
        rating: New rating value
        instance_name: Instance name for instanced traits (optional)
        specialty: Specialty name for traits with specialties (optional)

    Returns:
        Boolean indicating success
    """
    # Initialize db.stats if it doesn't exist
    if not hasattr(character, 'db') or not character.db.stats:
        character.db.stats = copy.deepcopy(STATS)

    stats = character.db.stats

    # Try to update the new system first
    try:
        trait = Trait.objects.get(name__iexact=trait_name)
        char_trait, created = CharacterTrait.objects.get_or_create(
            character=character,
            trait=trait,
            instance_name=instance_name,
            specialty=specialty,
            defaults={'rating': rating}
        )
        if not created:
            char_trait.rating = rating
            char_trait.save()
    except Trait.DoesNotExist:
        pass  # Trait doesn't exist in new system, that's okay

    # Always update the existing db.stats system for backwards compatibility
    category = get_trait_category(trait_name)
    if category and category in stats:
        if specialty:
            # Handle specialties
            if 'specialties' not in stats:
                stats['specialties'] = {}
            if trait_name.lower() not in stats['specialties']:
                stats['specialties'][trait_name.lower()] = {}
            stats['specialties'][trait_name.lower()][specialty.lower()] = rating
        elif instance_name:
            # Handle instanced traits (store as "trait_instance")
            key = f"{trait_name.lower()}_{instance_name.lower().replace(' ', '_')}"
            stats[category][key] = rating
        else:
            # Standard trait
            stats[category][trait_name.lower()] = rating

    return True


def sync_character_to_new_system(character):
    """
    Sync a character's existing db.stats data to the new trait system.

    Args:
        character: Character object to sync

    Returns:
        Dictionary with sync results
    """
    if not hasattr(character, 'db') or not character.db.stats:
        return {'success': False, 'error': 'Character has no stats to sync'}

    stats = character.db.stats
    results = {
        'success': True,
        'synced_traits': 0,
        'synced_specialties': 0,
        'synced_powers': 0,
        'errors': []
    }

    # Sync basic traits (attributes, skills, etc.)
    for category_name, traits_dict in stats.items():
        if category_name in ['specialties', 'xp', 'notes', 'approved_by', 'approved']:
            continue  # Skip special categories

        if isinstance(traits_dict, dict):
            for trait_name, rating in traits_dict.items():
                if isinstance(rating, (int, float)):
                    try:
                        trait = Trait.objects.get(name__iexact=trait_name, category__code=category_name)
                        char_trait, created = CharacterTrait.objects.get_or_create(
                            character=character,
                            trait=trait,
                            defaults={'rating': int(rating)}
                        )
                        if created:
                            results['synced_traits'] += 1
                    except Trait.DoesNotExist:
                        results['errors'].append(f"Trait '{trait_name}' not found in new system")

    # Sync specialties
    if 'specialties' in stats:
        for trait_name, specialties_dict in stats['specialties'].items():
            if isinstance(specialties_dict, dict):
                for specialty_name, rating in specialties_dict.items():
                    if isinstance(rating, (int, float)):
                        try:
                            trait = Trait.objects.get(name__iexact=trait_name)
                            char_trait, created = CharacterTrait.objects.get_or_create(
                                character=character,
                                trait=trait,
                                specialty=specialty_name,
                                defaults={'rating': int(rating)}
                            )
                            if created:
                                results['synced_specialties'] += 1
                        except Trait.DoesNotExist:
                            results['errors'].append(f"Trait '{trait_name}' for specialty not found")

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
    if hasattr(character, 'db') and character.db.stats:
        splat = character.db.stats.get('splat', 'mortal')

    # Filter traits based on splat restrictions
    available_traits = Trait.objects.filter(is_active=True)

    if splat:
        # Include traits with no restriction or matching splat restriction
        available_traits = available_traits.filter(
            models.Q(splat_restriction__isnull=True) |
            models.Q(splat_restriction='') |
            models.Q(splat_restriction=splat)
        )

    return available_traits.order_by('category__sort_order', 'sort_order', 'name')


def get_character_discipline_powers(character):
    """
    Get all discipline powers a character has learned.

    Args:
        character: Character object

    Returns:
        QuerySet of CharacterPower objects
    """
    return CharacterPower.objects.filter(character=character).select_related('power__discipline')


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
    char_traits = CharacterTrait.objects.filter(character=character).select_related('trait__category')

    categories = TraitCategory.objects.all().order_by('sort_order')

    for category in categories:
        category_traits = char_traits.filter(trait__category=category)
        if category_traits.exists():
            output += f"\n|w{category.name}:|n\n"
            for char_trait in category_traits.order_by('trait__sort_order'):
                display_name = char_trait.display_name
                dots = "•" * char_trait.rating if char_trait.rating > 0 else "○"
                output += f"  {display_name:<20} {dots} ({char_trait.rating})\n"

    # Show discipline powers
    powers = get_character_discipline_powers(character)
    if powers.exists():
        output += f"\n|wDiscipline Powers:|n\n"
        current_discipline = None
        for char_power in powers.order_by('power__discipline__name', 'power__level'):
            if char_power.power.discipline != current_discipline:
                current_discipline = char_power.power.discipline
                output += f"\n  |c{current_discipline.name}:|n\n"
            output += f"    {char_power.power.name} (Level {char_power.power.level})\n"

    return output


def validate_trait_for_character(character, trait_name, rating, instance_name=None, specialty=None):
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
        character_splat = None
        if hasattr(character, 'db') and character.db.stats:
            character_splat = character.db.stats.get('splat', 'mortal')

        if character_splat != trait.splat_restriction:
            return False, f"{trait.name} is only available to {trait.splat_restriction} characters"

    # Check instanced trait requirements
    if trait.is_instanced and not instance_name:
        return False, f"{trait.name} requires an instance name (e.g., 'Allies: Police')"

    if not trait.is_instanced and instance_name:
        return False, f"{trait.name} is not an instanced trait"

    return True, ""


def enhanced_import_character_from_json(character, json_data, validate_only=False):
    """
    Enhanced version of character import that works with both old and new trait systems.

    Args:
        character: Character object to import to
        json_data: Dictionary containing character data
        validate_only: If True, only validate without applying changes

    Returns:
        Dictionary with import results
    """
    results = {
        'success': True,
        'errors': [],
        'warnings': [],
        'imported_traits': 0,
        'imported_specialties': 0,
        'imported_powers': 0,
        'validation_errors': []
    }

    # Get character's splat for validation
    splat = json_data.get('splat', 'mortal')

    # Run V5 chargen pool validation before processing individual traits
    clan = json_data.get('clan')
    pool_errors = validate_v5_chargen_pools(json_data, clan=clan)
    if pool_errors:
        results['validation_errors'].extend(pool_errors)
        results['success'] = False
        return results

    # Process basic traits
    for category_name, traits_dict in json_data.items():
        if category_name in ['splat', 'name', 'concept', 'notes', 'approved', 'approved_by', 'xp']:
            continue  # Skip non-trait fields

        if isinstance(traits_dict, dict):
            for trait_name, rating in traits_dict.items():
                if isinstance(rating, (int, float)):
                    # Validate the trait
                    is_valid, error_msg = validate_trait_for_character(
                        character, trait_name, int(rating)
                    )

                    if not is_valid:
                        results['validation_errors'].append(error_msg)
                        continue

                    # Set the trait if not validation-only
                    if not validate_only:
                        success = set_character_trait_value(character, trait_name, int(rating))
                        if success:
                            results['imported_traits'] += 1
                        else:
                            results['errors'].append(f"Failed to set {trait_name} to {rating}")

    # Process specialties
    if 'specialties' in json_data:
        for trait_name, specialties_dict in json_data['specialties'].items():
            if isinstance(specialties_dict, dict):
                for specialty_name, rating in specialties_dict.items():
                    if isinstance(rating, (int, float)):
                        # Validate specialty
                        is_valid, error_msg = validate_trait_for_character(
                            character, trait_name, int(rating), specialty=specialty_name
                        )

                        if not is_valid:
                            results['validation_errors'].append(error_msg)
                            continue

                        # Set the specialty if not validation-only
                        if not validate_only:
                            success = set_character_trait_value(
                                character, trait_name, int(rating), specialty=specialty_name
                            )
                            if success:
                                results['imported_specialties'] += 1
                            else:
                                results['errors'].append(f"Failed to set specialty {trait_name} ({specialty_name}) to {rating}")

    # Process discipline powers (if present)
    if 'discipline_powers' in json_data:
        for power_name in json_data['discipline_powers']:
            try:
                power = DisciplinePower.objects.get(name__iexact=power_name)
                can_learn, reason = can_learn_discipline_power(character, power)

                if not can_learn:
                    results['validation_errors'].append(f"Cannot learn {power_name}: {reason}")
                    continue

                # Add power if not validation-only
                if not validate_only:
                    char_power, created = CharacterPower.objects.get_or_create(
                        character=character,
                        power=power
                    )
                    if created:
                        results['imported_powers'] += 1

            except DisciplinePower.DoesNotExist:
                results['errors'].append(f"Discipline power '{power_name}' not found")

    # Set character bio information
    if not validate_only:
        bio, created = CharacterBio.objects.get_or_create(character=character)
        bio.splat = splat
        bio.concept = json_data.get('concept', '')
        bio.full_name = json_data.get('name', character.key)
        bio.save()

    # Check if there were any critical errors
    if results['validation_errors'] or results['errors']:
        results['success'] = False

    return results


def export_character_to_json(character, include_powers=True):
    """
    Export a character to JSON format compatible with web import system.

    Args:
        character: Character object to export
        include_powers: Whether to include discipline powers

    Returns:
        Dictionary containing character data in JSON-compatible format
    """
    export_data = {
        'name': character.key,
        'splat': 'mortal',
        'concept': '',
        'xp': 0
    }

    # Get character bio if it exists
    try:
        bio = character.vtm_bio
        export_data['name'] = bio.full_name or character.key
        export_data['splat'] = bio.splat
        export_data['concept'] = bio.concept
    except AttributeError:
        pass

    # Export traits from both systems
    char_traits = CharacterTrait.objects.filter(character=character)

    # Group by category
    categories = {}
    specialties = {}

    for char_trait in char_traits:
        category_code = char_trait.trait.category.code

        if char_trait.specialty:
            # Handle specialties
            if char_trait.trait.name not in specialties:
                specialties[char_trait.trait.name] = {}
            specialties[char_trait.trait.name][char_trait.specialty] = char_trait.rating
        else:
            # Handle regular traits
            if category_code not in categories:
                categories[category_code] = {}

            trait_key = char_trait.trait.name
            if char_trait.instance_name:
                trait_key = f"{trait_key}_{char_trait.instance_name.lower().replace(' ', '_')}"

            categories[category_code][trait_key] = char_trait.rating

    # Add categories to export data
    export_data.update(categories)

    # Add specialties if any
    if specialties:
        export_data['specialties'] = specialties

    # Add discipline powers if requested
    if include_powers:
        powers = CharacterPower.objects.filter(character=character)
        if powers.exists():
            export_data['discipline_powers'] = [cp.power.name for cp in powers]

    # Fall back to old system for any missing data
    if hasattr(character, 'db') and character.db.stats:
        stats = character.db.stats
        for category, traits_dict in stats.items():
            if category in ['approved', 'approved_by', 'notes']:
                continue
            if category not in export_data and isinstance(traits_dict, dict):
                export_data[category] = traits_dict.copy()

    return export_data
