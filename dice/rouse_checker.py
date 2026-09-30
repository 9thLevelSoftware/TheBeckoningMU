"""
Rouse Check System for V5 Dice Integration

Handles Rouse checks and Blood Potency reroll mechanics, integrating with
the character trait system to track and update Hunger levels.
"""

from typing import Dict, Any, Optional
from .dice_roller import roll_rouse_check as base_rouse_check
from traits.utils import get_character_trait_value


def perform_rouse_check(character, reason: str = '', power_level: int = 1) -> Dict[str, Any]:
    """
    Perform a Rouse check and update character Hunger.

    A Rouse check is made when using vampiric powers, healing damage, or
    performing other blood-powered actions. On a failure (1-5), Hunger increases.

    Blood Potency allows rerolling failed Rouse checks for low-level powers:
    - BP 1-2: Can reroll Level 1 power Rouse checks
    - BP 3: Can reroll Level 1-2 power Rouse checks
    - BP 4-5: Can reroll Level 1-2 power Rouse checks
    - BP 6-7: Can reroll Level 1-3 power Rouse checks
    - BP 8-9: Can reroll Level 1-4 power Rouse checks
    - BP 10: Can reroll Level 1-5 power Rouse checks

    Args:
        character: Character object performing the Rouse check
        reason: Description of why the Rouse check is happening (e.g., "Activating Corrosive Vitae")
        power_level: Level of power being used (1-5, for Blood Potency reroll eligibility)

    Returns:
        dict: {
            'roll': int (die result 1-10),
            'success': bool (True if 6+),
            'hunger_before': int (Hunger before check),
            'hunger_after': int (Hunger after check),
            'hunger_change': int (0 or +1),
            'reroll_eligible': bool (whether BP reroll was available),
            'reroll_used': bool (whether a reroll occurred),
            'reason': str (reason for the check)
        }

    Examples:
        >>> result = perform_rouse_check(character, "Blood Surge", power_level=1)
        >>> if result['success']:
        >>>     print(f"Success! Hunger stays at {result['hunger_after']}")
        >>> else:
        >>>     print(f"Failed. Hunger increased to {result['hunger_after']}")
    """
    # Get current Hunger
    hunger_before = getattr(character.db, 'hunger', 1)
    hunger_before = max(0, min(5, hunger_before))  # Clamp to 0-5

    # Check if Hunger is already at maximum
    if hunger_before >= 5:
        return {
            'roll': 0,
            'success': False,
            'hunger_before': 5,
            'hunger_after': 5,
            'hunger_change': 0,
            'reroll_eligible': False,
            'reroll_used': False,
            'reason': reason,
            'message': "Hunger already at maximum (5). Rouse check not rolled."
        }

    # Perform initial Rouse check
    initial_result = base_rouse_check()
    roll_value = initial_result['roll']
    success = initial_result['success']
    reroll_used = False
    reroll_eligible = False

    # Check if character can reroll based on Blood Potency
    if not success:
        reroll_eligible = can_reroll_rouse(character, power_level)

        if reroll_eligible:
            # Perform automatic reroll (Blood Potency benefit)
            reroll_result = base_rouse_check()
            roll_value = reroll_result['roll']
            success = reroll_result['success']
            reroll_used = True

    # Update Hunger if failed
    hunger_change = 0 if success else 1
    hunger_after = min(5, hunger_before + hunger_change)

    # Save updated Hunger to character
    character.db.hunger = hunger_after

    return {
        'roll': roll_value,
        'success': success,
        'hunger_before': hunger_before,
        'hunger_after': hunger_after,
        'hunger_change': hunger_change,
        'reroll_eligible': reroll_eligible,
        'reroll_used': reroll_used,
        'reason': reason,
        'message': _format_rouse_message(
            roll_value, success, hunger_before, hunger_after, reroll_used, reason
        )
    }


def can_reroll_rouse(character, power_level: int) -> bool:
    """
    Check if character can reroll a failed Rouse check based on Blood Potency.

    Blood Potency allows vampires to reroll failed Rouse checks for powers
    at or below a certain level threshold.

    Reroll Eligibility by Blood Potency:
    - BP 0: No rerolls
    - BP 1-2: Reroll Level 1 powers
    - BP 3: Reroll Level 1-2 powers
    - BP 4-5: Reroll Level 1-2 powers
    - BP 6-7: Reroll Level 1-3 powers
    - BP 8-9: Reroll Level 1-4 powers
    - BP 10: Reroll Level 1-5 powers (all powers)

    Args:
        character: Character object
        power_level: Level of the power being used (1-5)

    Returns:
        bool: True if character can reroll this power's Rouse check

    Examples:
        >>> # Character with BP 3 using Level 2 power
        >>> can_reroll_rouse(character, power_level=2)
        True
        >>> # Same character using Level 3 power
        >>> can_reroll_rouse(character, power_level=3)
        False
    """
    # Get character's Blood Potency
    blood_potency = get_character_trait_value(character, 'Blood Potency')

    # Determine maximum power level eligible for reroll
    if blood_potency == 0:
        max_reroll_level = 0  # No rerolls
    elif blood_potency in [1, 2]:
        max_reroll_level = 1  # Level 1 only
    elif blood_potency == 3:
        max_reroll_level = 2  # Levels 1-2
    elif blood_potency in [4, 5]:
        max_reroll_level = 2  # Levels 1-2
    elif blood_potency in [6, 7]:
        max_reroll_level = 3  # Levels 1-3
    elif blood_potency in [8, 9]:
        max_reroll_level = 4  # Levels 1-4
    elif blood_potency >= 10:
        max_reroll_level = 5  # All levels
    else:
        max_reroll_level = 0

    return power_level <= max_reroll_level


def get_hunger_level(character) -> int:
    """
    Get character's current Hunger level.

    Args:
        character: Character object

    Returns:
        int: Hunger level (0-5), defaults to 1 if not set
    """
    hunger = getattr(character.db, 'hunger', 1)
    return max(0, min(5, hunger))  # Clamp to valid range


def set_hunger_level(character, hunger: int) -> int:
    """
    Set character's Hunger level.

    Args:
        character: Character object
        hunger: New Hunger level (will be clamped to 0-5)

    Returns:
        int: Actual Hunger level set (after clamping)
    """
    clamped_hunger = max(0, min(5, hunger))
    character.db.hunger = clamped_hunger
    return clamped_hunger


def _format_rouse_message(
    roll: int,
    success: bool,
    hunger_before: int,
    hunger_after: int,
    reroll_used: bool,
    reason: str
) -> str:
    """
    Format a Rouse check result message for display.

    Args:
        roll: Die result (1-10)
        success: Whether check succeeded
        hunger_before: Hunger before check
        hunger_after: Hunger after check
        reroll_used: Whether Blood Potency reroll was used
        reason: Reason for check

    Returns:
        Formatted message string
    """
    lines = []

    # Reason (if provided)
    if reason:
        lines.append(f"|wRouse Check:|n {reason}")
    else:
        lines.append("|wRouse Check|n")

    # Result
    if reroll_used:
        lines.append(f"Initial roll failed, Blood Potency reroll: |y{roll}|n")
    else:
        lines.append(f"Roll: |y{roll}|n")

    # Success/Failure
    if success:
        lines.append(f"|gSuccess!|n Hunger remains at |r{hunger_after}|n")
    else:
        if hunger_after >= 5:
            lines.append(f"|r|hFailed.|n Hunger increases to |r|h{hunger_after}|n (MAXIMUM)")
            lines.append("|xThe Beast grows stronger...|n")
        else:
            lines.append(f"|rFailed.|n Hunger increases from |r{hunger_before}|n to |r{hunger_after}|n")

    return "\n".join(lines)


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
