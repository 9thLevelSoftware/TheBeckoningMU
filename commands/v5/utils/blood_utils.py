"""
Blood System Utilities for V5 Commands

Provides utility functions for managing vampire blood mechanics including
Hunger, feeding, Blood Surge, and resonance.
"""

from typing import Dict, Any, Optional
import time

from world.v5_data import BLOOD_POTENCY, RESONANCE_INTENSITIES, RESONANCES

# Resonance names, matching disciplines and intensity effects come from
# world.v5_data.RESONANCES and RESONANCE_INTENSITIES; this module keeps no copy.


def get_hunger_level(character) -> int:
    """
    Get character's current Hunger level (0-5), via Character.hunger.

    Args:
        character: Character object

    Returns:
        int: Hunger level (0-5)
    """
    return character.hunger


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
    Set character's Hunger level via Character.hunger (clamped to 0-5).

    Args:
        character: Character object
        hunger: New Hunger level (will be clamped to 0-5)

    Returns:
        int: Actual Hunger level set (after clamping)
    """
    character.hunger = hunger
    return character.hunger


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
    Get character's current blood resonance, via Character.resonance.

    Args:
        character: Character object

    Returns:
        dict or None: {'type': str, 'intensity': int, 'expires': float} or None
    """
    return character.resonance


def set_resonance(character, resonance_type: str, intensity: int = 1, duration: int = 3600) -> Dict[str, Any]:
    """
    Set character's blood resonance from feeding.

    Resonance types: the keys of world.v5_data.RESONANCES
    Intensity: 1 (Fleeting), 2 (Intense), 3 (Acute); see RESONANCE_INTENSITIES

    Args:
        character: Character object
        resonance_type: Type of resonance (Choleric, Melancholy, Phlegmatic, Sanguine)
        intensity: 1 Fleeting, 2 Intense, 3 Acute (default 1)
        duration: Duration in seconds (default 3600 = 1 hour)

    Returns:
        dict: Resonance data that was set

    Examples:
        >>> set_resonance(character, 'Choleric', intensity=2)
        {'type': 'Choleric', 'intensity': 2, 'expires': 1234567890.0}
    """
    character.resonance = {
        'type': resonance_type,
        'intensity': max(1, min(3, intensity)),
        'expires': time.time() + duration,
    }
    return character.resonance


def clear_resonance(character):
    """
    Clear character's blood resonance.

    Args:
        character: Character object
    """
    character.resonance = None


def _active_resonance(character) -> dict[str, Any] | None:
    """The character's resonance, or None if there is none or it has expired."""
    resonance = get_resonance(character)
    if not resonance:
        return None
    if resonance.get('expires') is not None and resonance['expires'] < time.time():
        clear_resonance(character)
        return None
    return resonance


def get_resonance_bonus(character, discipline_name: str) -> int:
    """
    Resonance dice for a Discipline roll (core p.226-231).

    A resonance adds the dice in RESONANCE_INTENSITIES for its intensity
    (Fleeting 0, Intense 1, Acute 1) to rolls of the disciplines its humour
    matches in RESONANCES. This is the one place that rule is applied.

    Returns:
        int: Bonus dice (0 or 1)
    """
    resonance = _active_resonance(character)
    if not resonance:
        return 0
    humour = RESONANCES.get(resonance.get('type'))
    if not humour or discipline_name not in humour["disciplines"]:
        return 0
    intensity = RESONANCE_INTENSITIES.get(resonance.get('intensity'))
    return intensity["discipline_dice"] if intensity else 0


def format_resonance_display(character) -> Optional[str]:
    """
    Format character's resonance for display with matching disciplines.

    Returns:
        str or None: e.g. "Resonance: Choleric (Intense) - +1 die to Celerity, Potence",
        or None if there is no resonance
    """
    resonance = _active_resonance(character)
    if not resonance:
        return None

    intensity = RESONANCE_INTENSITIES.get(resonance['intensity'])
    intensity_str = intensity["name"] if intensity else 'Unknown'

    color_map = {
        'Choleric': '|r',
        'Melancholy': '|c',
        'Phlegmatic': '|g',
        'Sanguine': '|y'
    }
    color = color_map.get(resonance['type'], '|w')

    humour = RESONANCES.get(resonance['type'], {})
    disciplines_str = ', '.join(humour.get("disciplines", []))

    dice = intensity["discipline_dice"] if intensity else 0
    effect = f"|g+{dice}|n die to {disciplines_str}" if dice else f"no extra dice (matches {disciplines_str})"
    if intensity and intensity["dyscrasia"]:
        effect += "; may carry a dyscrasia"

    return f"|wResonance:|n {color}{resonance['type']}|n ({intensity_str}) - {effect}"


# Blood Surge Management

def get_blood_potency(character) -> int:
    """
    Get character's Blood Potency rating.

    Args:
        character: Character object

    Returns:
        int: Blood Potency level (0-10)
    """
    return character.blood_potency


def get_blood_potency_bonus(character) -> int:
    """
    Get character's Blood Potency bonus for Blood Surge.

    Args:
        character: Character object

    Returns:
        int: Bonus dice, from world.v5_data.BLOOD_POTENCY["blood_surge"]
    """
    row = BLOOD_POTENCY.get(get_blood_potency(character))
    return row["blood_surge"] if row else 0


def activate_blood_surge(character, trait_type: str, trait_name: str) -> Dict[str, Any]:
    """
    Ready a Blood Surge (core p.218; QR p.4).

    The surge adds the Blood Potency table's surge dice to the character's
    next roll whose pool includes an Attribute (`roll` or a `power` roll).
    Its one Rouse check is made with that roll, and the Hunger it costs is
    added after the roll (core pp.211-212). Readying it costs nothing.

    Refused, with nothing stored, at Hunger 5 (no voluntary Rouse) or while
    another surge is pending (one surge per roll).

    The pending surge is kept in ``character.db.blood_surge`` (persistent,
    so a reload doesn't lose it) and lapses unused after one hour.

    Returns:
        dict: {'success': bool, 'bonus': int, 'trait': str, 'message': str}
    """
    from dice.rouse_checker import HUNGER_5_REFUSAL, MAX_HUNGER

    if character.hunger >= MAX_HUNGER:
        return {'success': False, 'bonus': 0, 'trait': trait_name, 'message': HUNGER_5_REFUSAL}
    if get_blood_surge(character):
        return {
            'success': False,
            'bonus': 0,
            'trait': trait_name,
            'message': "You already have a Blood Surge waiting for your next roll.",
        }

    bonus = get_blood_potency_bonus(character)
    character.db.blood_surge = {
        'trait': trait_name,
        'trait_type': trait_type,
        'bonus': bonus,
        'expires': time.time() + 3600,
    }
    return {
        'success': True,
        'bonus': bonus,
        'trait': trait_name,
        'message': f"+{bonus} dice to your next roll; its Rouse check is made with that roll.",
    }


def consume_blood_surge(character) -> int:
    """Use up a pending Blood Surge: return its bonus dice (0 if none) and clear it."""
    surge = get_blood_surge(character)
    if not surge:
        return 0
    deactivate_blood_surge(character)
    return surge.get('bonus', 0)


def get_blood_surge(character) -> Optional[Dict[str, Any]]:
    """
    The character's pending Blood Surge, or None if there is none or it lapsed.

    Returns:
        dict or None: {'trait', 'trait_type', 'bonus', 'expires'}
    """
    surge = character.db.blood_surge
    if not surge:
        return None
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
    Clear the pending Blood Surge.

    Args:
        character: Character object
    """
    if character.attributes.has('blood_surge'):
        character.attributes.remove('blood_surge')


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
