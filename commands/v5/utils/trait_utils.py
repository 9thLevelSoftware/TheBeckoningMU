"""
Trait Utility Functions for V5 System

Provides functions for safely getting and setting character traits,
including attributes, skills, disciplines, and advantages.

These functions provide a clean interface between commands and character data,
with proper error handling and validation.
"""


from world.v5_data import TRAIT_RANGES, UnknownTrait, find_power, resolve_trait

# ============================================================================
# Lenient wrappers over the Character accessors
# ============================================================================
# Character.get_trait/set_trait raise UnknownTrait for a name that is not an
# attribute, skill, discipline or background. These helpers keep the older
# contract: an unknown name reads as 0 and a write to it returns False.
# ============================================================================

def _db_get_trait(character, trait_name):
    """Rating of a trait via Character.get_trait, or 0 if the name is unknown."""
    try:
        return character.get_trait(trait_name)
    except UnknownTrait:
        return 0


def _db_set_trait(character, trait_name, value):
    """Set a trait via Character.set_trait; False if the name is unknown."""
    try:
        character.set_trait(trait_name, value)
    except UnknownTrait:
        return False
    return True


def get_trait_value(character, trait_name, category=None):
    """
    Get the value of a trait from a character.

    Reads through Character.get_trait, so names resolve case-insensitively
    through world.v5_data.TRAIT_REGISTRY.

    Args:
        character: Character object
        trait_name (str): Name of the trait (e.g. 'strength', 'Animal Ken')
        category (str, optional): 'attribute', 'skill', 'discipline' or
            'background'. If given and the trait is in another category,
            WrongCategory is raised.

    Returns:
        int: Trait value, or 0 if the name is not a known trait

    Examples:
        >>> get_trait_value(char, 'strength')
        3
        >>> get_trait_value(char, 'brawl', 'skill')
        2
    """
    try:
        return character.get_trait(trait_name, category)
    except UnknownTrait:
        return 0


def set_trait_value(character, trait_name, value, category=None):
    """
    Set the value of a trait on a character, through Character.set_trait.

    Args:
        character: Character object
        trait_name (str): Name of the trait
        value (int): New value for the trait
        category (str, optional): Category hint; a mismatch raises WrongCategory

    Returns:
        bool: True if set, False if the name is not a known trait

    Raises:
        ValueError: If value is out of the trait's range
    """
    try:
        character.set_trait(trait_name, value, category)
    except UnknownTrait:
        return False
    return True


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
        ValueError: If new value goes below minimum (1 for attributes, else 0)
    """
    min_value = TRAIT_RANGES[resolve_trait(trait_name, category).category][0]
    new_value = get_trait_value(character, trait_name, category) - dots

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
    key = resolve_trait(skill_name, "skills").key
    return character.specialties.get(key)


def set_specialty(character, skill_name, specialty_name):
    """
    Set a specialty for a skill.

    Args:
        character: Character object
        skill_name (str): Name of the skill
        specialty_name (str): Name of the specialty

    Returns:
        bool: True if successful, False if the skill has no dots
    """
    key = resolve_trait(skill_name, "skills").key
    if character.get_trait(key) < 1:
        return False

    character.db.stats["specialties"][key] = specialty_name
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
    key = resolve_trait(discipline_name, "disciplines").key
    entry = character.db.stats["disciplines"].get(key)
    return list(entry.get("powers", [])) if entry else []


def add_discipline_power(character, discipline_name, power_name):
    """
    Add a power to a discipline the character has.

    Args:
        character: Character object
        discipline_name (str): Name of the discipline
        power_name (str): Name of the power to add

    Returns:
        bool: True if added; False if the power is unknown, belongs to another
        discipline, is already known, or the character lacks the discipline
    """
    discipline = resolve_trait(discipline_name, "disciplines")
    power = find_power(power_name)
    if power is None or power["discipline"] != discipline.name:
        return False
    if character.get_trait(discipline.key) < 1 or power["name"] in character.known_powers:
        return False

    character.learn_power(power["name"])
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
    return power_name in character.known_powers


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
