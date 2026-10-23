"""
Core V5 Dice Rolling Engine

The one dice engine for Vampire: The Masquerade 5th Edition: pools with
Hunger dice, contested rolls and Willpower re-rolls. Rouse checks are in
dice.rouse_checker; they roll their die through randint() here too.
"""

import random
from collections.abc import Iterable
from typing import Any

from .roll_result import RollResult


def randint(low: int, high: int) -> int:
    """The one die source for every roll in the game.

    Tests patch either this function (``dice.dice_roller.randint``) or
    ``random.randint``; both reach every die.
    """
    return random.randint(low, high)

# Upper bound on dice in one roll. No legitimate V5 pool comes close; the cap
# stops a typo or a malicious `roll 1000000` from tying up the server.
MAX_POOL = 30

# Allowed difficulty range (successes needed).
MIN_DIFFICULTY = 0
MAX_DIFFICULTY = 20


def roll_v5_pool(pool_size: int, hunger: int = 0, difficulty: int = 0) -> RollResult:
    """
    Roll a V5 dice pool with Hunger dice.

    Hunger dice replace regular dice, one per point of Hunger, without
    exceeding the pool (QR p.4): pool 3 at Hunger 5 rolls three Hunger dice.
    Success counting is RollResult's.

    Args:
        pool_size: Total number of dice to roll (1..MAX_POOL)
        hunger: Current Hunger (0-5)
        difficulty: Number of successes needed (0 = any success wins)

    Returns:
        RollResult object with comprehensive analysis

    Raises:
        ValueError: If pool_size is outside 1..MAX_POOL, hunger is outside 0-5,
            or difficulty is outside MIN_DIFFICULTY..MAX_DIFFICULTY
    """
    if pool_size < 1:
        raise ValueError(f"Pool size must be at least 1 (got {pool_size})")

    if pool_size > MAX_POOL:
        raise ValueError(f"Pool size cannot exceed {MAX_POOL} dice (got {pool_size})")

    if hunger < 0 or hunger > 5:
        raise ValueError(f"Hunger must be between 0 and 5 (got {hunger})")

    if not MIN_DIFFICULTY <= difficulty <= MAX_DIFFICULTY:
        raise ValueError(f"Difficulty must be between {MIN_DIFFICULTY} and {MAX_DIFFICULTY} (got {difficulty})")

    num_hunger = min(hunger, pool_size)
    num_regular = pool_size - num_hunger

    regular_dice = [randint(1, 10) for _ in range(num_regular)]
    hunger_dice = [randint(1, 10) for _ in range(num_hunger)]

    return RollResult(regular_dice, hunger_dice, difficulty)


def roll_contested(
    pool1: int,
    hunger1: int,
    pool2: int,
    hunger2: int
) -> dict[str, Any]:
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


def apply_willpower_reroll(result: RollResult, dice_values: Iterable[int]) -> tuple[RollResult, list]:
    """
    Re-roll regular dice the player chose, for 1 Willpower (QR p.3).

    The player picks up to three non-Hunger dice of the roll, any value
    (a 10 included). Dice are chosen by the value they show: ``[2, 10]``
    re-rolls one regular die showing 2 and one showing 10. Hunger dice are
    never re-rolled. Marking the Willpower damage is the caller's job.

    Args:
        result: The roll to improve
        dice_values: Values of the regular dice to re-roll (1-3 of them)

    Returns:
        Tuple of (new_result, rerolled_indices), the indices being positions
        in ``result.regular_dice``.

    Raises:
        ValueError: If no dice or more than three are chosen, or a chosen
            value isn't showing on a regular die that's still available.
    """
    values = list(dice_values)
    if not 1 <= len(values) <= MAX_WILLPOWER_REROLLS:
        raise ValueError(f"Choose 1 to {MAX_WILLPOWER_REROLLS} regular dice to re-roll (got {len(values)})")

    available = list(enumerate(result.regular_dice))
    reroll_indices = []
    for value in values:
        match = next((pos for pos, (_, die) in enumerate(available) if die == value), None)
        if match is None:
            raise ValueError(f"No regular die showing {value} is left to re-roll")
        index, _ = available.pop(match)
        reroll_indices.append(index)

    new_regular_dice = list(result.regular_dice)
    for index in reroll_indices:
        new_regular_dice[index] = randint(1, 10)

    return RollResult(new_regular_dice, result.hunger_dice, result.difficulty), reroll_indices


def validate_pool_params(pool_size: int, hunger: int) -> tuple[int, int]:
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
    - 6-10: 1 success (a pair of 10s adds 2 more; that is RollResult's job)

    Args:
        die_value: Value rolled on the die (1-10)

    Returns:
        Number of successes (0 or 1)
    """
    return 1 if die_value >= SUCCESS_THRESHOLD else 0


# Module-level constants for reference
SUCCESS_THRESHOLD = 6  # Minimum value for a success
CRITICAL_VALUE = 10    # A pair of these is a critical
MAX_HUNGER = 5         # Maximum Hunger level
MAX_WILLPOWER_REROLLS = 3  # Maximum dice that can be rerolled with Willpower
