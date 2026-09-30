"""
V5 Dice Rolling Engine (Skeleton)

This module will contain the core dice rolling mechanics for V5:
- Normal dice pools (d10, success on 6+, critical on 10)
- Hunger dice (replace normal dice based on Hunger level)
- Rouse checks (single d10 vs difficulty 6)
- Messy Criticals (paired 10s including Hunger dice)
- Bestial Failures (total failure with Hunger dice)

FULL IMPLEMENTATION: Phase 5 (Dice Rolling Engine)

This skeleton defines the API and basic structure only.
See V5_REFERENCE_DATABASE.md for complete dice mechanics.
"""

import random
from typing import Dict, List, Tuple, Optional

from world.v5_data import BLOOD_POTENCY, DISCIPLINES, RESONANCES, FRENZY_TRIGGERS
from world.ansi_theme import (
    DICE_CRITICAL, DICE_SUCCESS, DICE_FAILURE,
    DICE_HUNGER_CRITICAL, DICE_HUNGER_SUCCESS, DICE_HUNGER_FAILURE,
    MESSY_CRITICAL_BANNER, BESTIAL_FAILURE_BANNER, CRITICAL_SUCCESS_BANNER,
    SUCCESS_BANNER, FAILURE_BANNER
)


class DiceResult:
    """
    Represents the result of a dice roll.

    Attributes:
        normal_dice (List[int]): Results of normal dice (1-10)
        hunger_dice (List[int]): Results of Hunger dice (1-10)
        successes (int): Total successes (6+ on any die)
        criticals (int): Number of critical pairs (pairs of 10s)
        is_messy (bool): True if any Hunger die rolled a 10 in a critical pair
        is_bestial (bool): True if total failure with Hunger dice present
        margin (int): Successes minus difficulty
    """

    def __init__(
        self,
        normal_dice: List[int],
        hunger_dice: List[int],
        difficulty: int = 0
    ):
        self.normal_dice = normal_dice
        self.hunger_dice = hunger_dice
        self.difficulty = difficulty

        # Calculate successes (6+ on any die)
        self.normal_successes = sum(1 for d in normal_dice if d >= 6)
        self.hunger_successes = sum(1 for d in hunger_dice if d >= 6)
        self.successes = self.normal_successes + self.hunger_successes

        # Calculate criticals (pairs of 10s)
        normal_tens = sum(1 for d in normal_dice if d == 10)
        hunger_tens = sum(1 for d in hunger_dice if d == 10)
        total_tens = normal_tens + hunger_tens
        self.criticals = total_tens // 2  # Each pair = 1 critical (+2 successes)

        # Messy Critical: At least one pair includes a Hunger die
        self.is_messy = (self.criticals > 0) and (hunger_tens > 0)

        # Bestial Failure: Total failure (0 successes) with Hunger dice present
        self.is_bestial = (self.successes == 0) and (len(hunger_dice) > 0)

        # Margin: Successes (including critical bonuses) minus difficulty
        total_successes_with_crits = self.successes + (self.criticals * 2)
        self.margin = total_successes_with_crits - difficulty

    def is_success(self) -> bool:
        """Returns True if the roll meets or exceeds difficulty."""
        return self.margin >= 0

    def is_critical_success(self) -> bool:
        """Returns True if the roll has any critical pairs."""
        return self.criticals > 0

    def __repr__(self):
        return (
            f"DiceResult(normal={self.normal_dice}, hunger={self.hunger_dice}, "
            f"successes={self.successes}, criticals={self.criticals}, "
            f"messy={self.is_messy}, bestial={self.is_bestial})"
        )


def roll_pool(
    pool: int,
    hunger: int = 0,
    difficulty: int = 0,
    willpower: bool = False
) -> DiceResult:
    """
    Roll a dice pool with optional Hunger dice.

    Args:
        pool (int): Total dice in the pool
        hunger (int): Hunger level (0-5), determines how many dice are Hunger dice
        difficulty (int): Difficulty of the roll (number of successes needed)
        willpower (bool): If True, add +3 dice to the pool (re-roll once per scene)

    Returns:
        DiceResult: Object containing roll results and analysis
    """
    # Apply willpower bonus
    if willpower:
        pool += 3

    # Determine how many dice are Hunger dice
    # Hunger dice replace normal dice, up to the pool size
    num_hunger_dice = min(hunger, pool)
    num_normal_dice = pool - num_hunger_dice

    # Roll dice
    normal_dice = [random.randint(1, 10) for _ in range(num_normal_dice)]
    hunger_dice = [random.randint(1, 10) for _ in range(num_hunger_dice)]

    # Create and return result
    return DiceResult(normal_dice, hunger_dice, difficulty)


def rouse_check(character) -> Tuple[bool, int, int]:
    """
    Perform a Rouse check to activate disciplines or powers.

    A Rouse check is a single d10 roll:
    - Success (6+): No Hunger increase
    - Failure (1-5): Hunger increases by 1

    Blood Potency may allow re-rolls on the first failure.

    Args:
        character: The character object performing the check.

    Returns:
        Tuple[bool, int, int]: (success, die_result, rerolls_available)
    """
    die_result = random.randint(1, 10)
    success = die_result >= 6

    rerolls_available = 0
    if not success:
        blood_potency = character.db.blood_potency or 0
        if blood_potency in BLOOD_POTENCY:
            bp_data = BLOOD_POTENCY[blood_potency]
            rerolls_available = bp_data.get('rouse_reroll', 0)

    return success, die_result, rerolls_available


def rouse_reroll(character) -> Tuple[bool, int]:
    """
    Performs a re-roll for a failed Rouse check, using Blood Potency.
    This assumes the character is eligible for a re-roll.

    Args:
        character: The character object performing the re-roll.

    Returns:
        Tuple[bool, int]: (success, die_result)
    """
    die_result = random.randint(1, 10)
    success = die_result >= 6
    return success, die_result


def _format_die(value, is_hunger=False):
    """Helper to format a single die with ANSI colors."""
    if is_hunger:
        if value == 10: return DICE_HUNGER_CRITICAL
        if value >= 6: return DICE_HUNGER_SUCCESS
        return DICE_HUNGER_FAILURE
    else:
        if value == 10: return DICE_CRITICAL
        if value >= 6: return DICE_SUCCESS
        return DICE_FAILURE


def format_dice_result(result: DiceResult, character_name: str = "You") -> str:
    """
    Format a DiceResult as themed output using ansi_theme.py.

    Args:
        result (DiceResult): The dice roll result to format
        character_name (str): Name of the character rolling

    Returns:
        str: Formatted output with ANSI colors and symbols
    """
    total_dice = len(result.normal_dice) + len(result.hunger_dice)
    total_successes_with_crits = result.successes + (result.criticals * 2)

    # Build dice string
    normal_dice_str = " ".join(_format_die(d) for d in sorted(result.normal_dice, reverse=True))
    hunger_dice_str = " ".join(_format_die(d, is_hunger=True) for d in sorted(result.hunger_dice, reverse=True))
    all_dice_str = f"{normal_dice_str} {hunger_dice_str}".strip()

    # Build output
    output = f"|w{character_name} rolls {total_dice} dice (Difficulty: {result.difficulty})...|n\n"
    output += f"|wResult:|n {all_dice_str}\n"
    output += f"|wSuccesses:|n {total_successes_with_crits} (Margin: {result.margin})\n"

    # Add banners
    if result.is_messy:
        output += f"\n{MESSY_CRITICAL_BANNER}\n"
    elif result.is_bestial:
        output += f"\n{BESTIAL_FAILURE_BANNER}\n"
    elif result.is_critical_success():
        output += f"\n{CRITICAL_SUCCESS_BANNER}\n"
    elif result.is_success():
        output += f"\n{SUCCESS_BANNER}\n"
    else:
        output += f"\n{FAILURE_BANNER}\n"

    return output


def calculate_contested_roll(
    attacker_result: DiceResult,
    defender_result: DiceResult
) -> Dict[str, any]:
    """
    Calculate the outcome of a contested roll (attacker vs defender).

    In contested rolls, both parties roll and compare margins.
    The higher margin wins. Ties go to the defender.
    Special outcomes (messy, bestial) are flagged.

    Args:
        attacker_result (DiceResult): Attacker's roll
        defender_result (DiceResult): Defender's roll

    Returns:
        Dict: Contains 'winner', 'margin_difference', and special outcomes
    """
    margin_diff = attacker_result.margin - defender_result.margin

    winner = "defender"
    if margin_diff > 0:
        winner = "attacker"

    return {
        "winner": winner,
        "margin_difference": abs(margin_diff),
        "attacker_messy": attacker_result.is_messy,
        "defender_messy": defender_result.is_messy,
        "attacker_bestial": attacker_result.is_bestial,
        "defender_bestial": defender_result.is_bestial,
    }


# ============================================================================
# FUTURE FUNCTIONS (Defined in later phases)
# ============================================================================

def apply_discipline_modifiers(pool: int, character, discipline_name: str = None) -> int:
    """
    Apply discipline-based modifiers to a dice pool.

    Checks for:
    - Prowess (Potence 2): Adds Potence rating to Strength-based rolls.
    - Draught of Elegance (Celerity 4): Adds Celerity rating to Dexterity-based rolls.
    - Draught of Endurance (Fortitude 4): Adds Fortitude rating to Stamina-based rolls.
    - Resonance bonuses.

    Args:
        pool (int): The initial dice pool.
        character: The character object.
        discipline_name (str, optional): The primary discipline being used for the roll.

    Returns:
        int: The modified dice pool.
    """
    # Active Effects (e.g., Prowess, Draughts)
    # Assumes character.db.active_effects is a list of power names
    active_effects = character.db.active_effects or []
    disciplines = character.db.disciplines or {}

    if "Prowess" in active_effects and "potence" in disciplines:
        pool += disciplines["potence"]
    if "Draught of Elegance" in active_effects and "celerity" in disciplines:
        pool += disciplines["celerity"]
    if "Draught of Endurance" in active_effects and "fortitude" in disciplines:
        pool += disciplines["fortitude"]

    # Resonance Bonuses
    resonance = character.db.resonance
    if resonance and discipline_name:
        resonance_data = RESONANCES.get(resonance)
        if resonance_data and discipline_name in resonance_data.get("disciplines", []):
            pool += 1  # Add 1 die for matching resonance

    return pool


def check_frenzy(character, trigger_type: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a character resists frenzy.

    Args:
        character: The character object.
        trigger_type (str): The type of frenzy trigger (e.g., "hunger", "rage").

    Returns:
        Tuple[bool, Optional[str]]: (resisted, compulsion_on_failure)
    """
    trigger_data = FRENZY_TRIGGERS.get(trigger_type.lower())
    if not trigger_data:
        return (True, None)  # Unknown trigger, assume resistance

    difficulty = trigger_data["difficulty"]
    compulsion = trigger_data["compulsion"]

    # Hunger 5 is an automatic hunger frenzy
    if trigger_type == "hunger" and (character.db.hunger or 0) >= 5:
        return (False, compulsion)

    # Pool is Resolve + Composure
    pool = (character.db.resolve or 1) + (character.db.composure or 1)

    # Humanity can limit the pool
    humanity = character.db.humanity or 7
    if humanity < 3:
        pool = min(pool, humanity)

    # Brujah bane
    if character.db.clan == "Brujah" and compulsion == "Fight":
        difficulty += 2

    if pool <= 0:
        return (False, compulsion)

    result = roll_pool(pool, character.db.hunger or 0, difficulty)

    if result.is_success():
        return (True, None)
    else:
        return (False, compulsion)


def apply_hunger_penalties(pool: int, hunger: int) -> int:
    """
    Apply penalties to dice pool based on Hunger level.

    Note: V5 core rules do not apply direct penalties to dice pools based on
    Hunger. The risk comes from Hunger Dice replacing normal dice, leading to
    Messy Criticals and Bestial Failures. This function is included for
    extensibility in case specific powers or homebrew rules impose penalties.

    Args:
        pool (int): The initial dice pool.
        hunger (int): The character's Hunger level (0-5).

    Returns:
        int: The modified dice pool (unchanged in core V5).
    """
    # No penalties applied in core V5 rules.
    return pool
