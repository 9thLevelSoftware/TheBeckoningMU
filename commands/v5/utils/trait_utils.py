"""
Trait Utility Functions for V5 System

Provides functions for safely getting and setting character traits,
including attributes, skills, disciplines, and advantages.

These functions provide a clean interface between commands and character data,
with proper error handling and validation.
"""


# ============================================================================
# Internal Bridge Functions
# ============================================================================
# These provide a unified interface for accessing character traits,
# whether stored in character.db.stats or in Django models (future).
# ============================================================================

def _db_get_trait(character, trait_name):
    """
    Internal function to get a trait value from character.db.stats.

    Args:
        character: Character object
        trait_name (str): Name of the trait (normalized)

    Returns:
        int: Trait value, or 0 if not found
    """
    trait_name = trait_name.lower().replace(" ", "_")

    if not hasattr(character.db, 'stats') or not character.db.stats:
        return 0

    stats = character.db.stats

    # Check attributes (physical, social, mental)
    for category in ['physical', 'social', 'mental']:
        attrs = stats.get('attributes', {}).get(category, {})
        if trait_name in attrs:
            return attrs[trait_name]

    # Check skills
    for category in ['physical', 'social', 'mental']:
        skills = stats.get('skills', {}).get(category, {})
        if trait_name in skills:
            return skills[trait_name]

    # Check disciplines
    disciplines = stats.get('disciplines', {})
    if trait_name in disciplines:
        return disciplines[trait_name].get('level', 0)

    # Check advantages/backgrounds
    if hasattr(character.db, 'advantages'):
        backgrounds = character.db.advantages.get('backgrounds', {})
        if trait_name in backgrounds:
            return backgrounds[trait_name]

    return 0


def _db_set_trait(character, trait_name, value):
    """
    Internal function to set a trait value in character.db.stats.

    Args:
        character: Character object
        trait_name (str): Name of the trait (normalized)
        value (int): New value for the trait

    Returns:
        bool: True if trait was found and updated, False otherwise
    """
    trait_name = trait_name.lower().replace(" ", "_")

    if not hasattr(character.db, 'stats') or not character.db.stats:
        return False

    stats = character.db.stats

    # Try to set in attributes
    for category in ['physical', 'social', 'mental']:
        attrs = stats.get('attributes', {}).get(category, {})
        if trait_name in attrs:
            attrs[trait_name] = value
            return True

    # Try to set in skills
    for category in ['physical', 'social', 'mental']:
        skills = stats.get('skills', {}).get(category, {})
        if trait_name in skills:
            skills[trait_name] = value
            return True

    # Try to set in disciplines
    disciplines = stats.get('disciplines', {})
    if trait_name in disciplines:
        disciplines[trait_name]['level'] = value
        return True

    return False


def get_trait_value(character, trait_name, category=None):
    """
    Get the value of a trait from a character.

    Uses the bridge function from traits.utils to ensure compatibility
    with both web imports (Django models) and in-game chargen (char.db.stats).

    Args:
        character: Character object
        trait_name (str): Name of the trait (lowercase, e.g., 'strength', 'athletics')
        category (str, optional): Category hint ('attribute', 'skill', 'discipline', etc.)

    Returns:
        int: Trait value, or 0 if not found

    Examples:
        >>> get_trait_value(char, 'strength')
        3
        >>> get_trait_value(char, 'brawl', 'skill')
        2
    """
    # Use the existing bridge function which checks both Django models and char.db.stats
    value = _db_get_trait(character, trait_name)

    if value > 0:
        return value

    # Fallback for disciplines (which are stored differently in char.db.stats)
    trait_name = trait_name.lower().replace(" ", "_")

    if category in [None, 'discipline', 'disciplines']:
        if hasattr(character.db, 'stats') and character.db.stats:
            disciplines = character.db.stats.get("disciplines", {})
            if trait_name in disciplines:
                return disciplines[trait_name].get("level", 0)

    # Try backgrounds (might not be in Django models yet)
    if category in [None, 'background', 'backgrounds']:
        if hasattr(character.db, 'advantages') and character.db.advantages:
            backgrounds = character.db.advantages.get("backgrounds", {})
            if trait_name in backgrounds:
                return backgrounds[trait_name]

    return 0


def set_trait_value(character, trait_name, value, category=None):
    """
    Set the value of a trait on a character.

    Uses the bridge function from traits.utils to update BOTH the Django models
    and char.db.stats, ensuring compatibility with web imports.

    Args:
        character: Character object
        trait_name (str): Name of the trait
        value (int): New value for the trait
        category (str, optional): Category hint

    Returns:
        bool: True if successful, False if trait not found

    Raises:
        ValueError: If value is out of valid range
    """
    trait_name = trait_name.lower().replace(" ", "_")

    # Validate value range
    if value < 0 or value > 5:
        raise ValueError(f"Trait value must be between 0 and 5, got {value}")

    # Use the bridge function to update both Django models and char.db.stats
    success = _db_set_trait(character, trait_name, value)

    # Special handling for disciplines (stored differently)
    if category in [None, 'discipline', 'disciplines']:
        if not hasattr(character.db, 'stats') or not character.db.stats:
            return False

        disciplines = character.db.stats.get("disciplines", {})
        if trait_name in disciplines:
            disciplines[trait_name]["level"] = value
            success = True
        elif category == 'discipline':
            # Create new discipline entry
            disciplines[trait_name] = {"level": value, "powers": []}
            success = True

    # Special handling for backgrounds (might not be in Django models)
    if category in [None, 'background', 'backgrounds']:
        if not hasattr(character.db, 'advantages'):
            character.db.advantages = {"backgrounds": {}, "merits": {}, "flaws": {}}

        backgrounds = character.db.advantages.get("backgrounds", {})
        backgrounds[trait_name] = value
        success = True

    # Recalculate derived stats if attributes changed
    if category in ['attribute', 'attributes']:
        character.update_derived_stats()

    return success


def add_trait_dots(character, trait_name, dots=1, category=None):
    """
    Add dots to a trait (increase by N).

    Args:
        character: Character object
        trait_name (str): Name of the trait
        dots (int): Number of dots to add (default 1)
        category (str, optional): Category hint

    Returns:
        int: New trait value

    Raises:
        ValueError: If new value exceeds maximum (5)
    """
    current = get_trait_value(character, trait_name, category)
    new_value = current + dots

    if new_value > 5:
        raise ValueError(f"Cannot increase {trait_name} above 5 (would be {new_value})")

    set_trait_value(character, trait_name, new_value, category)
    return new_value


def remove_trait_dots(character, trait_name, dots=1, category=None):
    """
    Remove dots from a trait (decrease by N).

    Args:
        character: Character object
        trait_name (str): Name of the trait
        dots (int): Number of dots to remove (default 1)
        category (str, optional): Category hint

    Returns:
        int: New trait value

    Raises:
        ValueError: If new value goes below minimum (0 for skills, 1 for attributes)
    """
    current = get_trait_value(character, trait_name, category)
    new_value = current - dots

    # Determine minimum value based on category
    min_value = 0
    if category in ['attribute', 'attributes']:
        # Check if this is actually an attribute
        for cat_name, attrs in character.db.stats.get("attributes", {}).items():
            if trait_name in attrs:
                min_value = 1  # Attributes minimum is 1
                break

    if new_value < min_value:
        raise ValueError(f"Cannot decrease {trait_name} below {min_value} (would be {new_value})")

    set_trait_value(character, trait_name, new_value, category)
    return new_value


def get_specialty(character, skill_name):
    """
    Get the specialty for a skill.

    Args:
        character: Character object
        skill_name (str): Name of the skill

    Returns:
        str or None: Specialty name, or None if no specialty
    """
    skill_name = skill_name.lower().replace(" ", "_")
    return character.db.stats.get("specialties", {}).get(skill_name, None)


def set_specialty(character, skill_name, specialty_name):
    """
    Set a specialty for a skill.

    Args:
        character: Character object
        skill_name (str): Name of the skill
        specialty_name (str): Name of the specialty

    Returns:
        bool: True if successful
    """
    skill_name = skill_name.lower().replace(" ", "_")

    # Verify the skill exists and has dots
    skill_value = get_trait_value(character, skill_name, 'skill')
    if skill_value < 1:
        return False

    character.db.stats["specialties"][skill_name] = specialty_name
    return True


def get_discipline_powers(character, discipline_name):
    """
    Get the list of powers known for a discipline.

    Args:
        character: Character object
        discipline_name (str): Name of the discipline

    Returns:
        list: List of power names
    """
    discipline_name = discipline_name.lower().replace(" ", "_")
    disciplines = character.db.stats.get("disciplines", {})

    if discipline_name in disciplines:
        return disciplines[discipline_name].get("powers", [])

    return []


def add_discipline_power(character, discipline_name, power_name):
    """
    Add a power to a discipline.

    Args:
        character: Character object
        discipline_name (str): Name of the discipline
        power_name (str): Name of the power to add

    Returns:
        bool: True if successful, False if already known or discipline not found
    """
    discipline_name = discipline_name.lower().replace(" ", "_")
    disciplines = character.db.stats.get("disciplines", {})

    if discipline_name not in disciplines:
        return False

    powers = disciplines[discipline_name].get("powers", [])
    if power_name in powers:
        return False  # Already known

    powers.append(power_name)
    disciplines[discipline_name]["powers"] = powers
    return True


def has_discipline_power(character, power_name):
    """
    Check if character knows a specific discipline power.

    Args:
        character: Character object
        power_name (str): Name of the power

    Returns:
        bool: True if character knows the power
    """
    disciplines = character.db.stats.get("disciplines", {})

    for disc_name, disc_data in disciplines.items():
        if power_name in disc_data.get("powers", []):
            return True

    return False


def get_total_attribute_dots(character, category=None):
    """
    Get total dots spent in attributes, optionally filtered by category.

    Args:
        character: Character object
        category (str, optional): 'physical', 'social', or 'mental'

    Returns:
        int: Total dots spent
    """
    total = 0
    attributes = character.db.stats.get("attributes", {})

    if category:
        category = category.lower()
        if category in attributes:
            for value in attributes[category].values():
                # Attributes start at 1, so count dots above 1
                total += max(0, value - 1)
    else:
        for cat_attrs in attributes.values():
            for value in cat_attrs.values():
                total += max(0, value - 1)

    return total


def get_total_skill_dots(character, category=None):
    """
    Get total dots spent in skills, optionally filtered by category.

    Args:
        character: Character object
        category (str, optional): 'physical', 'social', or 'mental'

    Returns:
        int: Total dots spent
    """
    total = 0
    skills = character.db.stats.get("skills", {})

    if category:
        category = category.lower()
        if category in skills:
            total = sum(skills[category].values())
    else:
        for cat_skills in skills.values():
            total += sum(cat_skills.values())

    return total


def get_total_discipline_dots(character):
    """
    Get total dots spent in disciplines.

    Args:
        character: Character object

    Returns:
        int: Total discipline dots
    """
    total = 0
    disciplines = character.db.stats.get("disciplines", {})

    for disc_data in disciplines.values():
        total += disc_data.get("level", 0)

    return total


def validate_chargen_attributes(character):
    """
    Validate that attribute allocation follows V5 rules (7/5/3).

    Args:
        character: Character object

    Returns:
        tuple: (bool, str) - (is_valid, error_message)
    """
    physical_dots = get_total_attribute_dots(character, 'physical')
    social_dots = get_total_attribute_dots(character, 'social')
    mental_dots = get_total_attribute_dots(character, 'mental')

    totals = sorted([physical_dots, social_dots, mental_dots], reverse=True)

    if totals != [7, 5, 3]:
        return (False, f"Attributes must be allocated 7/5/3. Current: {totals}")

    return (True, "Attributes valid")


def validate_chargen_skills(character):
    """
    Validate that skill allocation follows V5 rules (13/9/5).

    Args:
        character: Character object

    Returns:
        tuple: (bool, str) - (is_valid, error_message)
    """
    physical_dots = get_total_skill_dots(character, 'physical')
    social_dots = get_total_skill_dots(character, 'social')
    mental_dots = get_total_skill_dots(character, 'mental')

    totals = sorted([physical_dots, social_dots, mental_dots], reverse=True)

    if totals != [13, 9, 5]:
        return (False, f"Skills must be allocated 13/9/5. Current: {totals}")

    return (True, "Skills valid")


def get_dice_pool(character, trait1, trait2=None, specialty=None):
    """
    Calculate dice pool for a roll (attribute + skill).

    Args:
        character: Character object
        trait1 (str): First trait (usually attribute)
        trait2 (str, optional): Second trait (usually skill)
        specialty (bool, optional): Whether specialty applies (+1 die)

    Returns:
        int: Total dice pool

    Examples:
        >>> get_dice_pool(char, 'strength', 'brawl')
        5  # Strength 3 + Brawl 2
        >>> get_dice_pool(char, 'strength', 'brawl', specialty=True)
        6  # With specialty
    """
    pool = get_trait_value(character, trait1)

    if trait2:
        pool += get_trait_value(character, trait2)

    if specialty:
        pool += 1

    return pool
