"""
Rouse checks (QR p.4) and Blood Potency re-rolls.

perform_rouse_check is the only Rouse function in the game. Hunger and Blood
Potency are read and written through the Character accessors
(``character.hunger``, ``character.blood_potency``).
"""

from dataclasses import dataclass, field

from world.v5_data import BLOOD_POTENCY

from . import dice_roller

MAX_HUNGER = 5

HUNGER_5_REFUSAL = "You are at Hunger 5 and cannot Rouse the Blood. Feed first."


@dataclass(frozen=True)
class RouseResult:
    """The outcome of one Rouse check.

    ``refused`` is True when the check was not rolled because the character
    is at Hunger 5; nothing changed. ``rolls`` holds every die rolled (two
    when Blood Potency allowed a re-roll); ``roll`` is the one that counts.
    """

    reason: str
    hunger_before: int
    hunger_after: int
    success: bool
    refused: bool = False
    roll: int | None = None
    rolls: tuple = field(default_factory=tuple)
    reroll_eligible: bool = False
    reroll_used: bool = False

    @property
    def hunger_change(self) -> int:
        return self.hunger_after - self.hunger_before

    @property
    def message(self) -> str:
        return _format_rouse_message(self)


def perform_rouse_check(character, reason: str = "", power_level: int | None = None) -> RouseResult:
    """
    Make one Rouse check and write the new Hunger through ``character.hunger``.

    Roll one die: 6+ leaves Hunger alone, 1-5 raises it by 1 (QR p.4). At
    Hunger 5 the check is refused and nothing changes: a character can't
    Rouse the Blood at Hunger 5 (QR p.4). Callers must treat a refused check
    as "the action doesn't happen".

    Blood Potency lets a vampire re-roll a failed check for a Discipline
    power at or below the table's ``rouse_reroll`` level. ``power_level`` is
    that power's level; None (any Rouse that isn't for a Discipline power)
    means no re-roll.

    A power that costs several Rouse checks calls this once per check.
    """
    hunger_before = character.hunger
    if hunger_before >= MAX_HUNGER:
        return RouseResult(
            reason=reason, hunger_before=hunger_before, hunger_after=hunger_before, success=False, refused=True
        )

    rolls = [dice_roller.randint(1, 10)]
    reroll_eligible = False
    if rolls[0] < 6 and power_level is not None:
        reroll_eligible = can_reroll_rouse(character, power_level)
        if reroll_eligible:
            rolls.append(dice_roller.randint(1, 10))

    success = rolls[-1] >= 6
    hunger_after = hunger_before if success else hunger_before + 1
    if not success:
        character.hunger = hunger_after

    return RouseResult(
        reason=reason,
        hunger_before=hunger_before,
        hunger_after=hunger_after,
        success=success,
        roll=rolls[-1],
        rolls=tuple(rolls),
        reroll_eligible=reroll_eligible,
        reroll_used=len(rolls) > 1,
    )


def can_reroll_rouse(character, power_level: int) -> bool:
    """
    Check if character can reroll a failed Rouse check based on Blood Potency.

    Blood Potency lets a vampire re-roll a failed Rouse check for powers at
    or below a level set by world.v5_data.BLOOD_POTENCY["rouse_reroll"]
    (0 = no re-roll). The table is the only source of these values.

    Args:
        character: Character object
        power_level: Level of the power being used (1-5)

    Returns:
        bool: True if character can reroll this power's Rouse check
    """
    row = BLOOD_POTENCY.get(character.blood_potency)
    if row is None:
        return False
    return power_level <= row["rouse_reroll"]


def get_hunger_level(character) -> int:
    """
    Get character's current Hunger level.

    Args:
        character: Character object

    Returns:
        int: Hunger level (0-5), defaults to 1 if not set
    """
    return character.hunger


def set_hunger_level(character, hunger: int) -> int:
    """
    Set character's Hunger level.

    Args:
        character: Character object
        hunger: New Hunger level (will be clamped to 0-5)

    Returns:
        int: Actual Hunger level set (after clamping)
    """
    character.hunger = hunger
    return character.hunger


def _format_rouse_message(result: RouseResult) -> str:
    """Player-facing text for a RouseResult."""
    lines = [f"|wRouse Check:|n {result.reason}" if result.reason else "|wRouse Check|n"]

    if result.refused:
        lines.append(f"|r{HUNGER_5_REFUSAL}|n")
        return "\n".join(lines)

    if result.reroll_used:
        lines.append(f"Roll: |y{result.rolls[0]}|n, Blood Potency re-roll: |y{result.roll}|n")
    else:
        lines.append(f"Roll: |y{result.roll}|n")

    if result.success:
        lines.append(f"|gSuccess.|n Hunger stays at |r{result.hunger_after}|n.")
    elif result.hunger_after >= MAX_HUNGER:
        lines.append(f"|r|hFailed.|n Hunger rises to |r|h{result.hunger_after}|n (maximum).")
    else:
        lines.append(f"|rFailed.|n Hunger rises from |r{result.hunger_before}|n to |r{result.hunger_after}|n.")

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
        color = "|r"  # Red for high Hunger
    elif hunger >= 2:
        color = "|y"  # Yellow for moderate Hunger
    else:
        color = "|g"  # Green for low Hunger

    return f"Hunger: {color}{filled}|x{empty}|n ({hunger}/5)"
