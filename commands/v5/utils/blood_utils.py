"""
Blood System Utilities for V5 Commands

Provides utility functions for managing vampire blood mechanics including
Hunger, feeding, Blood Surge, and resonance.
"""

from typing import Dict, Any, Optional
import time


# Constants

RESONANCE_DISCIPLINES = {
    'Choleric': ['Potence', 'Celerity'],
    'Melancholic': ['Fortitude', 'Obfuscate'],
    'Phlegmatic': ['Auspex', 'Dominate'],
    'Sanguine': ['Presence', 'Blood Sorcery']
}

RESONANCE_INTENSITY = {
    1: 'Fleeting',
    2: 'Intense',
    3: 'Dyscrasia'
}


def get_hunger_level(character) -> int:
    """
    Get character's current Hunger level.

    Supports both new vampire data structure (character.db.vampire['hunger'])
    and legacy structure (character.db.hunger).

    Args:
        character: Character object

    Returns:
        int: Hunger level (0-5), defaults to 1 if not set
    """
    try:
        # Try new vampire data structure first
        vampire_data = getattr(character.db, 'vampire', None)
        if vampire_data and isinstance(vampire_data, dict):
            hunger = vampire_data.get('hunger', 1)
        else:
            # Fall back to legacy structure
            hunger = getattr(character.db, 'hunger', 1)
    except (AttributeError, TypeError):
        hunger = 1

    # Handle None case
    if hunger is None:
        hunger = 1

    return max(0, min(5, hunger))


def get_hunger(character) -> int:
    """
    Alias for get_hunger_level() for backward compatibility.

    Args:
        character: Character object

    Returns:
        int: Hunger level (0-5)
    """
    return get_hunger_level(character)


def set_hunger_level(character, hunger: int) -> int:
    """
    Set character's Hunger level.

    Supports both new vampire data structure (character.db.vampire['hunger'])
    and legacy structure (character.db.hunger).

    Args:
        character: Character object
        hunger: New Hunger level (will be clamped to 0-5)

    Returns:
        int: Actual Hunger level set (after clamping)
    """
    clamped_hunger = max(0, min(5, hunger))

    try:
        # Try new vampire data structure first
        vampire_data = getattr(character.db, 'vampire', None)
        if vampire_data and isinstance(vampire_data, dict):
            vampire_data['hunger'] = clamped_hunger
            character.db.vampire = vampire_data  # Ensure change persists
        else:
            # Fall back to legacy structure
            character.db.hunger = clamped_hunger
    except (AttributeError, TypeError):
        # If all else fails, set legacy
        character.db.hunger = clamped_hunger

    return clamped_hunger


def reduce_hunger(character, amount: int = 1) -> int:
    """
    Reduce character's Hunger by specified amount (from feeding).

    Args:
        character: Character object
        amount: Amount to reduce (default 1)

    Returns:
        int: New Hunger level after reduction

    Examples:
        >>> reduce_hunger(character, 2)  # Feed, reduce Hunger by 2
        1
    """
    current_hunger = get_hunger_level(character)
    new_hunger = set_hunger_level(character, current_hunger - amount)
    return new_hunger


def increase_hunger(character, amount: int = 1) -> Dict[str, Any]:
    """
    Increase character's Hunger by specified amount.

    Returns warnings at Hunger 4-5 to alert player of dangerous state.

    Args:
        character: Character object
        amount: Amount to increase (default 1)

    Returns:
        dict: {
            'hunger_before': int,
            'hunger_after': int,
            'warning': str or None (warning message if Hunger is high)
        }

    Examples:
        >>> result = increase_hunger(character, 1)
        >>> if result['warning']:
        >>>     character.msg(result['warning'])
    """
    current_hunger = get_hunger_level(character)
    new_hunger = set_hunger_level(character, current_hunger + amount)

    warning = None
    if new_hunger >= 5:
        warning = "|r|hWARNING:|n You are at |r|hHunger 5|n! The Beast is in control. You cannot use most Discipline powers."
    elif new_hunger >= 4:
        warning = "|rWARNING:|n You are at |rHunger 4|n. The Beast is very close to the surface. Feed soon!"

    return {
        'hunger_before': current_hunger,
        'hunger_after': new_hunger,
        'warning': warning
    }


def format_hunger_display(character) -> str:
    """
    Format character's Hunger level for display.

    Args:
        character: Character object

    Returns:
        Formatted Hunger display string with visual indicator

    Examples:
        >>> format_hunger_display(character)
        "Hunger: ■■■□□ (3/5)"
    """
    hunger = get_hunger_level(character)

    # Create visual indicator (filled/empty boxes)
    filled = "■" * hunger
    empty = "□" * (5 - hunger)

    # Color code based on Hunger level
    if hunger >= 5:
        color = "|r|h"  # Bright red for max Hunger
    elif hunger >= 4:
        color = "|r"    # Red for high Hunger
    elif hunger >= 2:
        color = "|y"    # Yellow for moderate Hunger
    else:
        color = "|g"    # Green for low Hunger

    return f"Hunger: {color}{filled}|x{empty}|n ({hunger}/5)"


# Resonance Management

def get_resonance(character) -> Optional[Dict[str, Any]]:
    """
    Get character's current blood resonance.

    Supports both new vampire data structure and legacy structure.

    Args:
        character: Character object

    Returns:
        dict or None: {'type': str, 'intensity': int, 'expires': float} or None
    """
    try:
        # Try new vampire data structure first
        vampire_data = getattr(character.db, 'vampire', None)
        if vampire_data and isinstance(vampire_data, dict):
            resonance_type = vampire_data.get('current_resonance')
            intensity = vampire_data.get('resonance_intensity', 0)
            if resonance_type and intensity > 0:
                # Convert to unified format with expiration
                expires = vampire_data.get('resonance_expires', time.time() + 3600)
                return {
                    'type': resonance_type,
                    'intensity': intensity,
                    'expires': expires
                }
        else:
            # Fall back to legacy structure
            return getattr(character.db, 'resonance', None)
    except (AttributeError, TypeError):
        return None

    return None


def set_resonance(character, resonance_type: str, intensity: int = 1, duration: int = 3600) -> Dict[str, Any]:
    """
    Set character's blood resonance from feeding.

    Resonance types: Choleric, Melancholic, Phlegmatic, Sanguine
    Intensity: 1 (Fleeting), 2 (Intense), 3 (Dyscrasia)

    Supports both new vampire data structure and legacy structure.

    Args:
        character: Character object
        resonance_type: Type of resonance (Choleric, Melancholic, Phlegmatic, Sanguine)
        intensity: Intensity level (1-3, default 1)
        duration: Duration in seconds (default 3600 = 1 hour)

    Returns:
        dict: Resonance data that was set

    Examples:
        >>> set_resonance(character, 'Choleric', intensity=2)
        {'type': 'Choleric', 'intensity': 2, 'expires': 1234567890.0}
    """
    clamped_intensity = max(1, min(3, intensity))
    expires = time.time() + duration

    resonance = {
        'type': resonance_type,
        'intensity': clamped_intensity,
        'expires': expires
    }

    try:
        # Try new vampire data structure first
        vampire_data = getattr(character.db, 'vampire', None)
        if vampire_data and isinstance(vampire_data, dict):
            vampire_data['current_resonance'] = resonance_type
            vampire_data['resonance_intensity'] = clamped_intensity
            vampire_data['resonance_expires'] = expires
            character.db.vampire = vampire_data
        else:
            # Fall back to legacy structure
            character.db.resonance = resonance
    except (AttributeError, TypeError):
        character.db.resonance = resonance

    return resonance


def clear_resonance(character):
    """
    Clear character's blood resonance.

    Supports both new vampire data structure and legacy structure.

    Args:
        character: Character object
    """
    try:
        # Try new vampire data structure first
        vampire_data = getattr(character.db, 'vampire', None)
        if vampire_data and isinstance(vampire_data, dict):
            vampire_data['current_resonance'] = None
            vampire_data['resonance_intensity'] = 0
            vampire_data['resonance_expires'] = None
            character.db.vampire = vampire_data
        else:
            # Fall back to legacy structure
            character.db.resonance = None
    except (AttributeError, TypeError):
        character.db.resonance = None


def get_resonance_bonus(character, discipline_name: str) -> int:
    """
    Get resonance bonus dice for a discipline based on current resonance.

    Resonance provides bonus dice to matching disciplines:
    - Choleric → Potence, Celerity
    - Melancholic → Fortitude, Obfuscate
    - Phlegmatic → Auspex, Dominate
    - Sanguine → Presence, Blood Sorcery

    Intensity determines bonus:
    - Fleeting (1): +1 die
    - Intense (2): +1 die
    - Dyscrasia (3): +2 dice

    Args:
        character: Character object
        discipline_name: Name of discipline being used

    Returns:
        int: Bonus dice (0, 1, or 2)

    Examples:
        >>> # Character has Choleric resonance (Intense)
        >>> get_resonance_bonus(character, 'Potence')
        1
        >>> get_resonance_bonus(character, 'Auspex')
        0
    """
    resonance = get_resonance(character)

    if not resonance:
        return 0

    # Check if expired
    if resonance.get('expires', 0) < time.time():
        clear_resonance(character)
        return 0

    # Check if discipline matches resonance type
    resonance_type = resonance.get('type')
    matching_disciplines = RESONANCE_DISCIPLINES.get(resonance_type, [])

    if discipline_name not in matching_disciplines:
        return 0

    # Calculate bonus based on intensity
    intensity = resonance.get('intensity', 0)
    if intensity >= 3:  # Dyscrasia
        return 2
    elif intensity >= 1:  # Fleeting or Intense
        return 1
    else:
        return 0


def format_resonance_display(character) -> Optional[str]:
    """
    Format character's resonance for display with matching disciplines.

    Args:
        character: Character object

    Returns:
        str or None: Formatted resonance string or None if no resonance

    Examples:
        >>> format_resonance_display(character)
        "Resonance: Choleric (Intense) - +1 to Potence, Celerity"
    """
    resonance = get_resonance(character)

    if not resonance:
        return None

    # Check if expired
    if resonance.get('expires', 0) < time.time():
        clear_resonance(character)
        return None

    # Format intensity using constants
    intensity_str = RESONANCE_INTENSITY.get(resonance['intensity'], 'Unknown')

    # Color code by resonance type
    color_map = {
        'Choleric': '|r',    # Red
        'Melancholic': '|c',  # Cyan
        'Phlegmatic': '|g',   # Green
        'Sanguine': '|y'      # Yellow
    }
    color = color_map.get(resonance['type'], '|w')

    # Get matching disciplines
    matching_disciplines = RESONANCE_DISCIPLINES.get(resonance['type'], [])
    disciplines_str = ', '.join(matching_disciplines)

    # Calculate bonus
    bonus = 2 if resonance['intensity'] >= 3 else 1

    return f"|wResonance:|n {color}{resonance['type']}|n ({intensity_str}) - |g+{bonus}|n to {disciplines_str}"


# Blood Surge Management

def get_blood_potency(character) -> int:
    """
    Get character's Blood Potency rating.

    Args:
        character: Character object

    Returns:
        int: Blood Potency level (0-10)
    """
    from .trait_utils import get_trait_value
    return get_trait_value(character, 'Blood Potency')


def get_blood_potency_bonus(character) -> int:
    """
    Get character's Blood Potency bonus for Blood Surge.

    Args:
        character: Character object

    Returns:
        int: Bonus dice (equal to Blood Potency)
    """
    return get_blood_potency(character)


def activate_blood_surge(character, trait_type: str, trait_name: str) -> Dict[str, Any]:
    """
    Activate Blood Surge to boost a trait.

    Blood Surge adds dice equal to Blood Potency to a specified trait
    for one scene (1 hour). Requires a Rouse check.

    Args:
        character: Character object
        trait_type: Type of trait ('attribute' or 'physical_skill')
        trait_name: Name of trait to boost

    Returns:
        dict: {
            'success': bool,
            'bonus': int (BP bonus),
            'trait': str,
            'expires': float (timestamp),
            'rouse_result': dict
        }
    """
    from dice.dice_roller import roll_rouse_check

    # Perform Rouse check (using roll_rouse_check with character and reason)
    rouse_result = roll_rouse_check(character, reason=f"Blood Surge ({trait_name})")

    # Get Blood Potency bonus
    bonus = get_blood_potency_bonus(character)

    # Set Blood Surge status (expires in 1 hour)
    expires = time.time() + 3600
    character.ndb.blood_surge = {
        'trait': trait_name,
        'trait_type': trait_type,
        'bonus': bonus,
        'expires': expires
    }

    return {
        'success': True,
        'bonus': bonus,
        'trait': trait_name,
        'expires': expires,
        'rouse_result': rouse_result
    }


def get_blood_surge(character) -> Optional[Dict[str, Any]]:
    """
    Get character's active Blood Surge status.

    Args:
        character: Character object

    Returns:
        dict or None: Blood Surge data or None if inactive/expired
    """
    surge = getattr(character.ndb, 'blood_surge', None)

    if not surge:
        return None

    # Check if expired
    if surge.get('expires', 0) < time.time():
        deactivate_blood_surge(character)
        return None

    return surge


def get_blood_surge_bonus(character, trait_name: Optional[str] = None) -> int:
    """
    Get active Blood Surge bonus dice for a specific trait or any active surge.

    Args:
        character: Character object
        trait_name: Name of trait to check (optional, if None returns any active surge bonus)

    Returns:
        int: Bonus dice from active Blood Surge (0 if no surge active)

    Examples:
        >>> # Character has Blood Surge active on Strength
        >>> get_blood_surge_bonus(character, 'Strength')
        3  # (Blood Potency 3)
        >>> get_blood_surge_bonus(character, 'Brawl')
        0  # (surge not on Brawl)
    """
    surge = get_blood_surge(character)

    if not surge:
        return 0

    # If no specific trait requested, return bonus for any active surge
    if trait_name is None:
        return surge.get('bonus', 0)

    # Check if surge is active on the requested trait
    if surge.get('trait') == trait_name:
        return surge.get('bonus', 0)

    return 0


def deactivate_blood_surge(character):
    """
    Deactivate Blood Surge.

    Args:
        character: Character object
    """
    character.ndb.blood_surge = None


def format_blood_surge_display(character) -> Optional[str]:
    """
    Format character's Blood Surge status for display.

    Args:
        character: Character object

    Returns:
        str or None: Formatted Blood Surge display or None if no surge active

    Examples:
        >>> format_blood_surge_display(character)
        "Blood Surge: +3 to Strength (expires in 45 minutes)"
    """
    surge = get_blood_surge(character)

    if not surge:
        return None

    trait = surge.get('trait', 'Unknown')
    bonus = surge.get('bonus', 0)
    expires = surge.get('expires', 0)

    # Calculate time remaining
    time_remaining = expires - time.time()
    if time_remaining < 0:
        deactivate_blood_surge(character)
        return None

    # Format time remaining
    minutes = int(time_remaining / 60)
    if minutes > 60:
        hours = minutes // 60
        time_str = f"{hours} hour{'s' if hours != 1 else ''}"
    elif minutes > 0:
        time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        time_str = "less than 1 minute"

    return f"|wBlood Surge:|n |g+{bonus}|n to |y{trait}|n (expires in {time_str})"


def mend_damage(character, damage_type: str = 'superficial', amount: int = 1) -> Dict[str, Any]:
    """
    Mend damage by spending blood (vampire healing).

    Vampires can mend damage by spending blood. Superficial damage heals automatically,
    but Aggravated damage requires a Rouse check per point healed.

    Args:
        character: Character object
        damage_type: Type of damage ('superficial' or 'aggravated')
        amount: Amount of damage to heal

    Returns:
        dict: {
            'success': bool,
            'healed': int (amount actually healed),
            'damage_type': str,
            'hunger_increased': bool,
            'rouse_checks': int (number of Rouse checks made),
            'message': str
        }

    Examples:
        >>> mend_damage(character, 'superficial', 2)
        {'success': True, 'healed': 2, 'hunger_increased': False, ...}
    """
    from dice.dice_roller import roll_rouse_check

    # Get current damage
    current_superficial = getattr(character.db, 'superficial_damage', 0)
    current_aggravated = getattr(character.db, 'aggravated_damage', 0)

    healed = 0
    hunger_increased = False
    rouse_checks = 0

    if damage_type.lower() == 'superficial':
        # Superficial damage heals automatically (no Rouse check needed per V5)
        healed = min(amount, current_superficial)
        character.db.superficial_damage = current_superficial - healed
        message = f"Healed {healed} superficial damage."

    elif damage_type.lower() == 'aggravated':
        # Aggravated damage requires Rouse check per point
        for i in range(min(amount, current_aggravated)):
            rouse_result = roll_rouse_check(character, reason=f"Mending aggravated damage")
            rouse_checks += 1

            if rouse_result.get('hunger_increased', False):
                hunger_increased = True

            healed += 1

        character.db.aggravated_damage = current_aggravated - healed
        message = f"Healed {healed} aggravated damage with {rouse_checks} Rouse check(s)."
        if hunger_increased:
            message += " Hunger increased from failed Rouse check(s)."

    else:
        return {
            'success': False,
            'healed': 0,
            'damage_type': damage_type,
            'hunger_increased': False,
            'rouse_checks': 0,
            'message': f"Invalid damage type: {damage_type}. Use 'superficial' or 'aggravated'."
        }

    return {
        'success': True,
        'healed': healed,
        'damage_type': damage_type,
        'hunger_increased': hunger_increased,
        'rouse_checks': rouse_checks,
        'message': message
    }
