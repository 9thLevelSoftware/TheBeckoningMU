"""
Core V5 Dice Rolling Engine

This module provides the fundamental dice rolling mechanics for Vampire: The Masquerade 5th Edition,
including basic pools, Hunger dice, Rouse checks, contested rolls, and Willpower rerolls.
"""

from random import randint
from typing import Tuple, Dict, Any, Optional
from .roll_result import RollResult


def roll_v5_pool(pool_size: int, hunger: int = 0, difficulty: int = 0) -> RollResult:
    """
    Roll a V5 dice pool with Hunger dice.

    This is the main rolling function that handles all standard V5 rolls.
    Hunger dice replace an equal number of regular dice in the pool.

    V5 Dice Rules:
    - Each die is a d10
    - 6-9 = 1 success, 10 = 2 successes
    - Pair of 10s = critical (4 successes total from the pair)
    - Hunger dice replace regular dice (not added)
    - Zero pool = chance die (1 die, only 10 succeeds)

    Args:
        pool_size: Total number of dice to roll (minimum 1)
        hunger: Current Hunger level (0-5), determines Hunger dice count
        difficulty: Number of successes needed (0 = any success wins)

    Returns:
        RollResult object with comprehensive analysis

    Raises:
        ValueError: If pool_size < 1, hunger < 0, hunger > 5, or hunger > pool_size

    Examples:
        >>> result = roll_v5_pool(5, hunger=2, difficulty=3)
        >>> print(f"Successes: {result.total_successes}")
        >>> print(f"Result: {result.result_type}")
    """
    # Validate inputs
    if pool_size < 1:
        raise ValueError(f"Pool size must be at least 1 (got {pool_size})")

    if hunger < 0 or hunger > 5:
        raise ValueError(f"Hunger must be between 0 and 5 (got {hunger})")

    if hunger > pool_size:
        raise ValueError(f"Hunger ({hunger}) cannot exceed pool size ({pool_size})")

    if difficulty < 0:
        raise ValueError(f"Difficulty must be 0 or greater (got {difficulty})")

    # Special case: Zero pool becomes chance die
    # (This shouldn't happen due to pool_size validation, but included for clarity)
    if pool_size == 0:
        pool_size = 1
        hunger = 0  # Chance die has no Hunger

    # Calculate dice distribution
    num_regular = pool_size - hunger
    num_hunger = hunger

    # Roll regular dice
    regular_dice = [randint(1, 10) for _ in range(num_regular)]

    # Roll hunger dice
    hunger_dice = [randint(1, 10) for _ in range(num_hunger)]

    # Create and return result
    return RollResult(regular_dice, hunger_dice, difficulty)


def roll_chance_die() -> RollResult:
    """
    Roll a chance die (used when pool is reduced to 0 or below).

    Chance Die Rules:
    - Roll exactly 1 die
    - Only a 10 counts as a success (1 success, not 2)
    - No critical possible
    - No Hunger dice involved

    Returns:
        RollResult with single die roll

    Example:
        >>> result = roll_chance_die()
        >>> if result.total_successes > 0:
        >>>     print("Miraculous success!")
    """
    die_roll = randint(1, 10)

    # For chance die, even a 10 only counts as 1 success, not 2
    # We handle this by treating it as a regular roll with pool 1
    return RollResult([die_roll], [], difficulty=0)


def roll_rouse_check() -> Dict[str, Any]:
    """
    Roll a single d10 for a Rouse check.

    Rouse Check Rules:
    - Roll 1d10
    - 6+ = success (no Hunger gain)
    - 1-5 = failure (Hunger increases by 1)
    - Used when activating disciplines, healing, etc.

    Returns:
        Dictionary containing:
            - 'roll' (int): The die result (1-10)
            - 'success' (bool): Whether check succeeded (6+)
            - 'hunger_change' (int): Hunger increase (0 if success, +1 if failure)

    Example:
        >>> result = roll_rouse_check()
        >>> if result['success']:
        >>>     print(f"Success! Rolled {result['roll']}")
        >>> else:
        >>>     print(f"Failed with {result['roll']}, Hunger increases")
    """
    roll = randint(1, 10)
    success = roll >= 6
    hunger_change = 0 if success else 1

    return {
        'roll': roll,
        'success': success,
        'hunger_change': hunger_change
    }


def roll_contested(
    pool1: int,
    hunger1: int,
    pool2: int,
    hunger2: int
) -> Dict[str, Any]:
    """
    Roll two dice pools against each other (contested action).

    Contested Roll Rules:
    - Both participants roll their pools
    - Highest total successes wins
    - Margin = winner's successes - loser's successes
    - Tie = both have same successes (no winner)
    - Both can experience Messy Criticals or Bestial Failures

    Args:
        pool1: First roller's pool size
        hunger1: First roller's Hunger level (0-5)
        pool2: Second roller's pool size
        hunger2: Second roller's Hunger level (0-5)

    Returns:
        Dictionary containing:
            - 'roller1_result' (RollResult): First roller's full result
            - 'roller2_result' (RollResult): Second roller's full result
            - 'winner' (int): 1, 2, or None (tie)
            - 'margin' (int): Difference in successes (always positive)
            - 'is_tie' (bool): Whether successes were equal

    Example:
        >>> result = roll_contested(5, 2, 7, 1)
        >>> if result['winner'] == 1:
        >>>     print(f"Roller 1 wins by {result['margin']} successes!")
        >>> elif result['winner'] == 2:
        >>>     print(f"Roller 2 wins by {result['margin']} successes!")
        >>> else:
        >>>     print("It's a tie!")
    """
    # Roll both pools
    result1 = roll_v5_pool(pool1, hunger1, difficulty=0)
    result2 = roll_v5_pool(pool2, hunger2, difficulty=0)

    # Determine winner
    if result1.total_successes > result2.total_successes:
        winner = 1
        margin = result1.total_successes - result2.total_successes
    elif result2.total_successes > result1.total_successes:
        winner = 2
        margin = result2.total_successes - result1.total_successes
    else:
        winner = None
        margin = 0

    return {
        'roller1_result': result1,
        'roller2_result': result2,
        'winner': winner,
        'margin': margin,
        'is_tie': winner is None
    }


def apply_willpower_reroll(result: RollResult, num_rerolls: int = 3) -> Tuple[RollResult, list]:
    """
    Reroll up to 3 failed regular dice (Willpower reroll).

    Willpower Reroll Rules:
    - Can reroll up to 3 dice that did NOT succeed (showed 1-5)
    - Can ONLY reroll regular dice, NOT Hunger dice
    - Each die can only be rerolled once
    - Costs 1 Willpower point (tracked elsewhere)
    - New dice replace old dice in the pool

    Args:
        result: Original RollResult to improve
        num_rerolls: Number of failed dice to reroll (1-3, default 3)

    Returns:
        Tuple of (new_result, rerolled_indices):
            - new_result: RollResult with rerolled dice
            - rerolled_indices: List of indices that were rerolled

    Raises:
        ValueError: If num_rerolls < 1 or > 3

    Example:
        >>> original = roll_v5_pool(5, hunger=2)
        >>> if original.total_successes < original.difficulty:
        >>>     improved, rerolled = apply_willpower_reroll(original, 3)
        >>>     print(f"Rerolled {len(rerolled)} dice")
        >>>     print(f"New successes: {improved.total_successes}")
    """
    # Validate input
    if num_rerolls < 1 or num_rerolls > 3:
        raise ValueError(f"Can only reroll 1-3 dice (requested {num_rerolls})")

    # Find failed regular dice (showing 1-5)
    failed_indices = [
        i for i, die in enumerate(result.regular_dice)
        if die < 6
    ]

    # Limit to requested number of rerolls
    num_to_reroll = min(num_rerolls, len(failed_indices))

    if num_to_reroll == 0:
        # No failed dice to reroll
        return result, []

    # Select which dice to reroll (take first N failed dice)
    reroll_indices = failed_indices[:num_to_reroll]

    # Create new regular dice list with rerolls
    new_regular_dice = result.regular_dice.copy()
    for idx in reroll_indices:
        new_regular_dice[idx] = randint(1, 10)

    # Create new result with same Hunger dice but new regular dice
    new_result = RollResult(new_regular_dice, result.hunger_dice, result.difficulty)

    return new_result, reroll_indices


def validate_pool_params(pool_size: int, hunger: int) -> Tuple[int, int]:
    """
    Validate and normalize pool parameters.

    Handles edge cases:
    - Pool size < 0 becomes 0 (chance die)
    - Hunger < 0 becomes 0
    - Hunger > 5 clamped to 5
    - Hunger > pool_size clamped to pool_size

    Args:
        pool_size: Requested pool size
        hunger: Requested Hunger level

    Returns:
        Tuple of (normalized_pool, normalized_hunger)

    Example:
        >>> pool, hunger = validate_pool_params(-2, 3)
        >>> # Returns (0, 0) - chance die with no Hunger
    """
    # Normalize pool size (minimum 0 for chance die)
    pool_size = max(0, pool_size)

    # Normalize hunger (0-5 range)
    hunger = max(0, min(5, hunger))

    # Ensure hunger doesn't exceed pool
    hunger = min(hunger, pool_size)

    return pool_size, hunger


def get_success_threshold(die_value: int) -> int:
    """
    Get number of successes for a single die value.

    V5 Success Rules:
    - 1-5: 0 successes
    - 6-9: 1 success
    - 10: 2 successes

    Args:
        die_value: Value rolled on the die (1-10)

    Returns:
        Number of successes (0, 1, or 2)

    Example:
        >>> get_success_threshold(10)  # Returns 2
        >>> get_success_threshold(7)   # Returns 1
        >>> get_success_threshold(3)   # Returns 0
    """
    if die_value >= 10:
        return 2
    elif die_value >= 6:
        return 1
    else:
        return 0


# Module-level constants for reference
SUCCESS_THRESHOLD = 6  # Minimum value for a success
CRITICAL_VALUE = 10    # Value that counts as 2 successes
MAX_HUNGER = 5         # Maximum Hunger level
MAX_WILLPOWER_REROLLS = 3  # Maximum dice that can be rerolled with Willpower
