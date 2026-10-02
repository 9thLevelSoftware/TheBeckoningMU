"""
Rouse checks (QR p.4; core pp.211-212) and Blood Potency re-rolls.

perform_rouse_check is the Rouse entry point. An action that makes several
Rouse checks at once (a power's checks plus a Blood Surge's) builds them with
roll_rouse_die and settles them with resolve_rouse, which is what
perform_rouse_check does too. Hunger and Blood Potency are read and written
through the Character accessors (``character.hunger``,
``character.blood_potency``).

Timing (core pp.211-212): "Any Hunger gained is added after the desired
effect resolves". Callers roll the action first, with the Hunger it started
at, and settle its Rouse checks afterwards.
"""

import time
from dataclasses import dataclass, field

from world.v5_data import BLOOD_POTENCY

from . import dice_roller

MAX_HUNGER = 5

HUNGER_5_REFUSAL = "You are at Hunger 5 and cannot Rouse the Blood. Feed first."

# Core p.211 / p.220: a Rouse that would take Hunger past 5 calls for an
# immediate hunger frenzy test at Difficulty 4. The owed test is recorded on
# the character (flag_hunger_frenzy, one test per failure past 5); the command
# that caused it rolls it at once through
# commands.v5.utils.humanity_utils.roll_pending_frenzy_tests, which clears the
# record. A record left over (shown by `hunger` and +sheet) is rolled by +frenzy.
HUNGER_FRENZY_DIFFICULTY = 4


@dataclass(frozen=True)
class RouseDie:
    """One Rouse check: its die, plus the Blood Potency re-roll if one was made."""

    label: str
    rolls: tuple
    reroll_eligible: bool = False

    @property
    def roll(self) -> int:
        return self.rolls[-1]

    @property
    def success(self) -> bool:
        return self.rolls[-1] >= 6

    @property
    def reroll_used(self) -> bool:
        return len(self.rolls) > 1


@dataclass(frozen=True)
class RouseResult:
    """The outcome of the Rouse checks of one action.

    ``refused`` is True when nothing was rolled because the character is at
    Hunger 5; nothing changed. ``checks`` holds each check. ``frenzy_test``
    is True when failures would have taken Hunger past 5: Hunger stops at 5
    and the character owes a hunger frenzy test at Difficulty 4.

    For a single check, ``roll``, ``rolls``, ``reroll_eligible`` and
    ``reroll_used`` describe that check.
    """

    reason: str
    hunger_before: int
    hunger_after: int
    checks: tuple = field(default_factory=tuple)
    refused: bool = False
    frenzy_test: bool = False

    @property
    def success(self) -> bool:
        """True if every check passed (and something was rolled)."""
        return not self.refused and all(check.success for check in self.checks)

    @property
    def failures(self) -> int:
        return sum(1 for check in self.checks if not check.success)

    @property
    def hunger_change(self) -> int:
        return self.hunger_after - self.hunger_before

    @property
    def roll(self):
        return self.checks[0].roll if self.checks else None

    @property
    def rolls(self) -> tuple:
        return self.checks[0].rolls if self.checks else ()

    @property
    def reroll_eligible(self) -> bool:
        return any(check.reroll_eligible for check in self.checks)

    @property
    def reroll_used(self) -> bool:
        return any(check.reroll_used for check in self.checks)

    @property
    def message(self) -> str:
        return _format_rouse_message(self)


def roll_rouse_die(character, power_level: int | None = None, label: str = "") -> RouseDie:
    """Roll one Rouse check without touching Hunger.

    Blood Potency lets a vampire re-roll a failed check for a Discipline
    power at or below the table's ``rouse_reroll`` level. ``power_level`` is
    that power's level; None (a Rouse that isn't for a Discipline power)
    means no re-roll.
    """
    rolls = [dice_roller.randint(1, 10)]
    eligible = False
    if rolls[0] < 6 and power_level is not None:
        eligible = can_reroll_rouse(character, power_level)
        if eligible:
            rolls.append(dice_roller.randint(1, 10))
    return RouseDie(label=label, rolls=tuple(rolls), reroll_eligible=eligible)


def resolve_rouse(character, reason: str, checks) -> RouseResult:
    """Add the Hunger the checks' failures cost, after the action resolved.

    Each failure adds 1 Hunger, up to 5. Failures beyond 5 don't cancel the
    action; they record a pending hunger frenzy test (flag_hunger_frenzy).
    Hunger is written once.
    """
    checks = tuple(checks)
    hunger_before = character.hunger
    failures = sum(1 for check in checks if not check.success)
    hunger_after = min(MAX_HUNGER, hunger_before + failures)
    overflow = max(0, hunger_before + failures - MAX_HUNGER)
    frenzy_test = overflow > 0
    if hunger_after != hunger_before:
        character.hunger = hunger_after
    if frenzy_test:
        flag_hunger_frenzy(character, reason, count=overflow)
    return RouseResult(
        reason=reason,
        hunger_before=hunger_before,
        hunger_after=hunger_after,
        checks=checks,
        frenzy_test=frenzy_test,
    )


def perform_rouse_check(character, reason: str = "", power_level: int | None = None, count: int = 1) -> RouseResult:
    """
    Make an action's Rouse checks and add the Hunger they cost.

    Each check is one die: 6+ costs nothing, 1-5 costs 1 Hunger (QR p.4).
    A vampire can never voluntarily Rouse at Hunger 5 (core p.211): at
    Hunger 5 nothing is rolled, nothing changes and the result is
    ``refused``; a caller that hasn't acted yet must not act. Once an action
    has started below Hunger 5, all its checks are rolled; Hunger stops at
    5 and any failure beyond that records a pending hunger frenzy test
    (resolve_rouse). The action is not cancelled.

    ``power_level`` (a Discipline power's level) enables the Blood Potency
    re-roll; ``count`` is the number of checks (a power's ``rouse``).
    """
    hunger_before = character.hunger
    if hunger_before >= MAX_HUNGER:
        return RouseResult(reason=reason, hunger_before=hunger_before, hunger_after=hunger_before, refused=True)
    checks = [roll_rouse_die(character, power_level, label=reason) for _ in range(count)]
    return resolve_rouse(character, reason, checks)


def perform_forced_rouse(character, reason: str = "") -> RouseResult:
    """A Rouse check the vampire can't refuse, such as rising for the night.

    It is rolled even at Hunger 5 (one die, no Blood Potency re-roll). A
    failure below Hunger 5 raises Hunger as usual; a failure at Hunger 5
    leaves Hunger at 5 and records one hunger frenzy test at Difficulty 4
    (QR p.13 "Fail Rouse Check while at Hunger 5"; core p.211), which the
    caller rolls. A failed rise at Hunger 5 also means torpor (QR p.4); the
    caller handles that.
    """
    return resolve_rouse(character, reason, [roll_rouse_die(character, None, label=reason)])


def flag_hunger_frenzy(character, reason: str, count: int = 1) -> None:
    """Record that the character owes ``count`` hunger frenzy tests at Difficulty 4.

    One test is owed for each Rouse failure past Hunger 5; a record already
    pending is added to. Stored in ``character.db.pending_frenzy_test``
    ({"type", "difficulty", "reason", "time", "count"}); the frenzy code
    (humanity_utils.roll_pending_frenzy_tests) rolls the tests and clears it.
    """
    pending = character.db.pending_frenzy_test
    already = int(pending.get("count") or 1) if pending else 0
    character.db.pending_frenzy_test = {
        "type": "hunger",
        "difficulty": HUNGER_FRENZY_DIFFICULTY,
        "reason": reason,
        "time": time.time(),
        "count": already + max(1, int(count)),
    }


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


def format_rouse_lines(result: RouseResult) -> list:
    """Display lines for an action's Rouse checks and the Hunger they cost."""
    if result.refused:
        return [f"|r{HUNGER_5_REFUSAL}|n"]
    lines = []
    for check in result.checks:
        label = f" ({check.label})" if check.label else ""
        if check.reroll_used:
            roll_text = f"|y{check.rolls[0]}|n, Blood Potency re-roll |y{check.roll}|n"
        else:
            roll_text = f"|y{check.roll}|n"
        outcome = "|gsuccess|n" if check.success else "|rfailed|n"
        lines.append(f"Rouse Check{label}: {roll_text}, {outcome}.")
    if result.hunger_change:
        lines.append(f"Hunger rises from |r{result.hunger_before}|n to |r{result.hunger_after}|n.")
    else:
        lines.append(f"Hunger stays at |r{result.hunger_after}|n.")
    if result.frenzy_test:
        lines.append(
            "|r|hYour Hunger can't rise past 5: you must test for hunger frenzy now "
            f"(Difficulty {HUNGER_FRENZY_DIFFICULTY}).|n"
        )
    return lines


def _format_rouse_message(result: RouseResult) -> str:
    """Player-facing text for a RouseResult."""
    header = f"|wRouse Check:|n {result.reason}" if result.reason else "|wRouse Check|n"
    lines = [header]
    if result.refused:
        lines.append(f"|r{HUNGER_5_REFUSAL}|n")
        return "\n".join(lines)
    if len(result.checks) == 1:
        check = result.checks[0]
        if check.reroll_used:
            lines.append(f"Roll: |y{check.rolls[0]}|n, Blood Potency re-roll: |y{check.roll}|n")
        else:
            lines.append(f"Roll: |y{check.roll}|n")
        if check.success:
            lines.append(f"|gSuccess.|n Hunger stays at |r{result.hunger_after}|n.")
        else:
            lines.append(f"|rFailed.|n Hunger rises from |r{result.hunger_before}|n to |r{result.hunger_after}|n.")
        if result.frenzy_test:
            lines.append(format_rouse_lines(result)[-1])
        return "\n".join(lines)
    lines.extend(format_rouse_lines(result))
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
