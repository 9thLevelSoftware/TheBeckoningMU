"""
Discipline Power Rolling System for V5 Integration

Handles rolling discipline powers: looks powers up in
world.v5_data.DISCIPLINE_POWERS, calculates dice pools from the character's
traits (Character.get_trait), applies Blood Potency bonuses and performs
Rouse checks.
"""

from typing import Dict, Any, List, Optional, Tuple
from .dice_roller import roll_v5_pool
from .rouse_checker import perform_rouse_check, get_hunger_level
from world.v5_data import BLOOD_POTENCY, UnknownTrait, find_power


def _trait_value(character, trait_name: str) -> int:
    """A trait rating via Character.get_trait; a name that isn't a trait counts 0."""
    try:
        return character.get_trait(trait_name)
    except UnknownTrait:
        return 0


def roll_discipline_power(
    character,
    power_name: str,
    difficulty: int = 0,
    with_rouse: bool = True
) -> Dict[str, Any]:
    """
    Roll a discipline power for a character.

    This function:
    1. Looks up the discipline power in world.v5_data.DISCIPLINE_POWERS
    2. Parses the power's dice pool string (e.g., "Strength + Brawl")
    3. Calculates the total dice pool from character traits
    4. Applies Blood Potency bonuses
    5. Performs a Rouse check (if required)
    6. Rolls the dice pool with character's current Hunger
    7. Returns comprehensive results

    Args:
        character: Character object performing the roll
        power_name: Name of the discipline power (case-insensitive)
        difficulty: Target number of successes (0 = any success wins)
        with_rouse: Whether to perform Rouse check (can be disabled for Free powers)

    Returns:
        dict: {
            'power': dict (the DISCIPLINE_POWERS entry),
            'power_name': str,
            'dice_pool': int (total pool size),
            'dice_pool_breakdown': dict (trait contributions),
            'blood_potency_bonus': int,
            'rouse_result': dict or None (Rouse check result),
            'roll_result': RollResult (dice roll result),
            'hunger_before': int,
            'hunger_after': int,
            'success': bool,
            'message': str (formatted result)
        }

    Raises:
        ValueError: If the power is not found or has no dice pool

    Examples:
        >>> result = roll_discipline_power(character, "Corrosive Vitae", difficulty=2)
        >>> if result['success']:
        >>>     print(f"Success with {result['roll_result'].total_successes} successes!")
    """
    # Look up the discipline power
    power = find_power(power_name)
    if power is None:
        raise ValueError(f"Discipline power '{power_name}' not found")

    # Get character's current Hunger
    hunger_before = get_hunger_level(character)

    # Perform Rouse check if required
    rouse_result = None
    if with_rouse and power.get('rouse'):
        rouse_result = perform_rouse_check(
            character,
            reason=f"Activating {power['name']}",
            power_level=power['level']
        )

    # Get updated Hunger after Rouse check
    hunger_after = get_hunger_level(character)

    # Parse dice pool from power
    if not power.get('dice_pool'):
        raise ValueError(f"Power '{power['name']}' has no dice pool defined")

    trait_names = parse_dice_pool(power['dice_pool'])

    # Calculate dice pool from traits
    pool_breakdown = {}
    base_pool = 0

    for trait_name in trait_names:
        trait_value = _trait_value(character, trait_name)
        pool_breakdown[trait_name] = trait_value
        base_pool += trait_value

    # Apply Blood Potency bonus
    bp_bonus = get_blood_potency_bonus(character, power['discipline'])
    pool_breakdown['Blood Potency Bonus'] = bp_bonus
    total_pool = base_pool + bp_bonus

    # Ensure pool is at least 1 (chance die)
    if total_pool < 1:
        total_pool = 1

    # Roll the dice pool
    roll_result = roll_v5_pool(
        pool_size=total_pool,
        hunger=hunger_after,
        difficulty=difficulty
    )

    # Format result message
    message = _format_discipline_roll_message(
        power=power,
        pool_breakdown=pool_breakdown,
        total_pool=total_pool,
        rouse_result=rouse_result,
        roll_result=roll_result,
        difficulty=difficulty
    )

    return {
        'power': power,
        'power_name': power['name'],
        'dice_pool': total_pool,
        'dice_pool_breakdown': pool_breakdown,
        'blood_potency_bonus': bp_bonus,
        'rouse_result': rouse_result,
        'roll_result': roll_result,
        'hunger_before': hunger_before,
        'hunger_after': hunger_after,
        'success': roll_result.is_success,
        'message': message
    }


def parse_dice_pool(pool_string: str) -> List[str]:
    """
    Parse a dice pool string into trait names.

    Handles various formats:
    - "Strength + Brawl" → ['Strength', 'Brawl']
    - "Charisma + Animal Ken" → ['Charisma', 'Animal Ken']
    - "Resolve + Auspex" → ['Resolve', 'Auspex']
    - "Strength / Manipulation + Brawl" → ['Strength', 'Brawl'] (takes first alternative)

    Args:
        pool_string: Dice pool string from a DISCIPLINE_POWERS entry

    Returns:
        List of trait names to sum

    Examples:
        >>> parse_dice_pool("Strength + Brawl")
        ['Strength', 'Brawl']
        >>> parse_dice_pool("Charisma / Manipulation + Intimidation")
        ['Charisma', 'Intimidation']
    """
    if not pool_string:
        return []

    # Handle alternative traits (separated by /)
    # Take the first option before any '/'
    if '/' in pool_string:
        pool_string = pool_string.split('/')[0].strip()

    # Split on '+' to get individual traits
    traits = [trait.strip() for trait in pool_string.split('+')]

    # Filter out empty strings
    traits = [t for t in traits if t]

    return traits


def calculate_pool_from_traits(character, trait_names: List[str]) -> Tuple[int, Dict[str, int]]:
    """
    Calculate total dice pool from a list of trait names.

    Args:
        character: Character object
        trait_names: List of trait names to sum

    Returns:
        Tuple of (total_pool, breakdown_dict):
            - total_pool: Sum of all trait values
            - breakdown_dict: Dict mapping trait names to their values

    Examples:
        >>> total, breakdown = calculate_pool_from_traits(character, ['Strength', 'Brawl'])
        >>> # Returns (7, {'Strength': 4, 'Brawl': 3})
    """
    total = 0
    breakdown = {}

    for trait_name in trait_names:
        value = _trait_value(character, trait_name)
        breakdown[trait_name] = value
        total += value

    return total, breakdown


def get_blood_potency_bonus(character, discipline_name: str) -> int:
    """
    Get Blood Potency bonus dice for discipline rolls.

    Blood Potency adds dice to Discipline rolls; the amount is
    world.v5_data.BLOOD_POTENCY["power_bonus"].

    Args:
        character: Character object
        discipline_name: Name of discipline (currently unused, but included for future clan-specific bonuses)

    Returns:
        int: Bonus dice (0-5)
    """
    row = BLOOD_POTENCY.get(character.blood_potency)
    return row["power_bonus"] if row else 0


def can_use_power(character, power_name: str) -> Tuple[bool, str]:
    """
    Check if a character can use a specific discipline power.

    Checks:
    1. Character knows the power (Character.known_powers)
    2. Character has required discipline rating
    3. Character has required amalgam discipline (if applicable)
    4. Character is not at Hunger 5 (optional warning)

    Args:
        character: Character object
        power_name: Name of discipline power

    Returns:
        Tuple of (can_use: bool, reason: str)

    Examples:
        >>> can_use, reason = can_use_power(character, "Corrosive Vitae")
        >>> if not can_use:
        >>>     print(f"Cannot use power: {reason}")
    """
    # Look up the power
    power = find_power(power_name)
    if power is None:
        return False, f"Power '{power_name}' not found"

    # Check if character knows the power
    if power['name'] not in character.known_powers:
        return False, f"You don't know the power '{power['name']}'"

    # Check discipline rating
    discipline_rating = character.get_trait(power['discipline'])
    if discipline_rating < power['level']:
        return False, f"Requires {power['discipline']} {power['level']} (you have {discipline_rating})"

    # Check amalgam requirement (stored as e.g. "Obfuscate 2")
    if power.get('amalgam'):
        amalgam_name, _, amalgam_level = power['amalgam'].rpartition(' ')
        amalgam_rating = character.get_trait(amalgam_name)
        if amalgam_rating < int(amalgam_level):
            return False, f"Requires {power['amalgam']} (you have {amalgam_rating})"

    # Warn if at maximum Hunger (not a blocker, just a warning)
    hunger = get_hunger_level(character)
    if hunger >= 5:
        return True, "Warning: You are at maximum Hunger"

    return True, "Can use power"


def get_character_discipline_powers(character, discipline_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get list of discipline powers a character knows.

    Args:
        character: Character object
        discipline_name: Optional discipline name to filter by

    Returns:
        List of dicts containing power info:
            - power: dict (the DISCIPLINE_POWERS entry)
            - name: str
            - discipline: str
            - level: int
            - dice_pool: str
            - rouse: bool
            - can_use: bool
            - reason: str (if can't use)

    Examples:
        >>> powers = get_character_discipline_powers(character, "Auspex")
        >>> for power_info in powers:
        >>>     print(f"{power_info['name']} (Level {power_info['level']})")
    """
    results = []
    for name in character.known_powers:
        power = find_power(name)
        if power is None:
            continue
        if discipline_name and power['discipline'].lower() != discipline_name.lower():
            continue
        can_use, reason = can_use_power(character, power['name'])

        results.append({
            'power': power,
            'name': power['name'],
            'discipline': power['discipline'],
            'level': power['level'],
            'dice_pool': power.get('dice_pool'),
            'rouse': bool(power.get('rouse')),
            'can_use': can_use,
            'reason': reason
        })

    return results


def _format_discipline_roll_message(
    power: dict[str, Any],
    pool_breakdown: Dict[str, int],
    total_pool: int,
    rouse_result: Optional[Dict[str, Any]],
    roll_result,
    difficulty: int
) -> str:
    """
    Format a discipline power roll result for display.

    Args:
        power: DISCIPLINE_POWERS entry
        pool_breakdown: Dict of trait contributions
        total_pool: Total dice pool size
        rouse_result: Rouse check result dict (or None)
        roll_result: RollResult object
        difficulty: Target successes

    Returns:
        Formatted message string
    """
    lines = []

    # Power header
    lines.append(f"|c=== {power['name']} ===|n")
    lines.append(f"|w{power['discipline']} Level {power['level']}|n")

    if power.get('description'):
        # Show first line of description
        desc_first_line = power['description'].splitlines()[0][:80]
        lines.append(f"|x{desc_first_line}|n")

    lines.append("")

    # Rouse check result
    if rouse_result:
        if rouse_result['reroll_used']:
            lines.append(f"Rouse Check: |y{rouse_result['roll']}|n (Blood Potency reroll)")
        else:
            lines.append(f"Rouse Check: |y{rouse_result['roll']}|n")

        if rouse_result['success']:
            lines.append(f"|gSuccess!|n Hunger remains at |r{rouse_result['hunger_after']}|n")
        else:
            lines.append(f"|rFailed.|n Hunger increases to |r{rouse_result['hunger_after']}|n")
        lines.append("")

    # Dice pool breakdown
    lines.append("|wDice Pool:|n")
    for trait_name, value in pool_breakdown.items():
        if trait_name == 'Blood Potency Bonus' and value > 0:
            lines.append(f"  {trait_name}: |y+{value}|n")
        else:
            lines.append(f"  {trait_name}: {value}")

    lines.append(f"  |wTotal: {total_pool}|n")
    lines.append("")

    # Roll result
    lines.append(roll_result.format_result(show_details=True))

    return "\n".join(lines)
