"""
Discipline Power Rolling System for V5 Integration

Rolls discipline powers: looks powers up in world.v5_data.DISCIPLINE_POWERS,
checks the character may use them, calculates dice pools from the
character's traits (Character.get_trait), adds Blood Potency and Resonance
dice and a pending Blood Surge, rolls with the character's Hunger, then
settles the Rouse checks (Hunger is added after the action).
"""

import re
from typing import Any

from world.v5_data import BLOOD_POTENCY, UnknownTrait, find_power

from .dice_roller import MAX_DIFFICULTY, MAX_POOL, roll_v5_pool
from .rouse_checker import (
    HUNGER_5_REFUSAL,
    MAX_HUNGER,
    RouseResult,
    format_rouse_lines,
    perform_rouse_check,
    resolve_rouse,
    roll_rouse_die,
)


class PowerRefused(ValueError):  # noqa: N818 - reads as "the power was refused"
    """The power can't be used now. Nothing was rolled or charged."""


def _trait_value(character, trait_name: str) -> int:
    """A trait rating via Character.get_trait; a name that isn't a trait counts 0."""
    try:
        return character.get_trait(trait_name)
    except UnknownTrait:
        return 0


def lookup_power(power_name: str) -> dict[str, Any]:
    """The DISCIPLINE_POWERS entry for a name (any case); PowerRefused if unknown."""
    power = find_power(power_name)
    if power is None:
        raise PowerRefused(f"Discipline power '{power_name}' not found")
    return power


def check_power_use(character, power: dict[str, Any], with_rouse: bool = True) -> None:
    """Raise PowerRefused unless the character may use the power right now.

    The character must know the power and have the discipline (and any
    amalgam) rating. A power that costs a Rouse can't be used at Hunger 5
    (core p.211: no voluntary Rouse at Hunger 5). Below Hunger 5 any power
    may be started, whatever its Rouse count.
    """
    can_use, reason = can_use_power(character, power["name"])
    if not can_use:
        raise PowerRefused(reason)
    if with_rouse and power.get("rouse", 0) > 0 and character.hunger >= MAX_HUNGER:
        raise PowerRefused(HUNGER_5_REFUSAL)


def pay_rouse_cost(character, power: dict[str, Any]) -> RouseResult | None:
    """Make a power's Rouse checks, ``power["rouse"]`` of them (None if free).

    Called after the power's action. All its checks are rolled; Hunger goes
    up by the failures, stopping at 5, and failures past 5 record a pending
    hunger frenzy test (rouse_checker.resolve_rouse). The power stands.
    """
    count = power.get("rouse", 0)
    if not count:
        return None
    return perform_rouse_check(character, reason=power["name"], power_level=power["level"], count=count)


def _usable_surge(character, with_rouse: bool) -> int:
    """Dice of a pending Blood Surge this roll can use (0 if none or not now).

    A surge needs its own Rouse, so it isn't used at Hunger 5 or when the
    Rouse checks are skipped; it then stays pending.
    """
    from commands.v5.utils.blood_utils import get_blood_surge

    surge = get_blood_surge(character)
    if not surge or not with_rouse or character.hunger >= MAX_HUNGER:
        return 0
    return surge.get("bonus", 0)


def roll_discipline_power(
    character,
    power_name: str,
    difficulty: int = 0,
    with_rouse: bool = True,
    target=None,
) -> dict[str, Any]:
    """
    Roll a discipline power for a character.

    1. Look the power up in world.v5_data.DISCIPLINE_POWERS.
    2. Refuse it unless the character knows it and has the ratings, if it
       needs a Rouse at Hunger 5, or if it has no dice pool. Nothing is
       rolled or charged when it is refused.
    3. Build the pool from the power's ``dice_pool`` plus the Blood Potency
       power bonus, any Resonance dice and a pending Blood Surge.
    4. Roll with the character's current Hunger. When ``target`` (a
       Character) is given and the power is contested (``opposed_by``),
       the target rolls that pool with their own Hunger and the user needs
       at least as many successes (a tie goes to the acting character);
       ``difficulty`` is then ignored.
    5. Settle the power's Rouse checks and the surge's after the roll: the
       Hunger they cost is added after the action (core pp.211-212), unless
       ``with_rouse`` is False.

    Raises:
        PowerRefused (a ValueError): the power was refused; nothing changed.
        ValueError: the roll itself was invalid (e.g. a pool over MAX_POOL);
            nothing was charged and a pending surge is kept.
    """
    power = lookup_power(power_name)
    if not getattr(character, "is_kindred", True):
        with_rouse = False  # only vampires Rouse the Blood (Character.splat)
    check_power_use(character, power, with_rouse=with_rouse)
    if not power.get("dice_pool"):
        raise PowerRefused(f"{power['name']} has no dice roll.")

    trait_names = parse_dice_pool(power["dice_pool"])
    base_pool, pool_breakdown = calculate_pool_from_traits(character, trait_names)

    bp_bonus = get_blood_potency_bonus(character, power["discipline"])
    pool_breakdown["Blood Potency Bonus"] = bp_bonus
    resonance_bonus = _resonance_dice(character, power["discipline"])
    if resonance_bonus:
        pool_breakdown["Resonance"] = resonance_bonus
    surge_dice = _usable_surge(character, with_rouse)
    if surge_dice:
        pool_breakdown["Blood Surge"] = surge_dice
    degeneration = min(0, character.dice_penalty()) if hasattr(character, "dice_penalty") else 0
    if degeneration:
        pool_breakdown["Degeneration (Humanity tracker full)"] = degeneration
    total_pool = max(1, base_pool + bp_bonus + resonance_bonus + surge_dice + degeneration)
    if total_pool > MAX_POOL:
        surge_note = f", including {surge_dice} Blood Surge dice; the surge is kept" if surge_dice else ""
        raise ValueError(f"Pool size cannot exceed {MAX_POOL} dice (got {total_pool}{surge_note})")

    defense = None
    if target is not None and power.get("opposed_by"):
        defense = _roll_defense(target, power["opposed_by"])
        difficulty = min(MAX_DIFFICULTY, max(1, defense["roll_result"].total_successes))

    hunger_before = character.hunger
    # Hunger dice only for vampires (Character.dice_hunger: 0 for a ghoul or mortal)
    roll_result = roll_v5_pool(pool_size=total_pool, hunger=character.dice_hunger, difficulty=difficulty)

    checks = []
    if with_rouse:
        checks = [roll_rouse_die(character, power["level"], label=power["name"]) for _ in range(power.get("rouse", 0))]
    if surge_dice:
        from commands.v5.utils.blood_utils import consume_blood_surge

        consume_blood_surge(character)
        checks.append(roll_rouse_die(character, None, label="Blood Surge"))
    rouse_result = resolve_rouse(character, power["name"], checks) if checks else None

    message = _format_discipline_roll_message(
        power=power,
        pool_breakdown=pool_breakdown,
        total_pool=total_pool,
        rouse_result=rouse_result,
        roll_result=roll_result,
        defense=defense,
    )

    return {
        "power": power,
        "power_name": power["name"],
        "dice_pool": total_pool,
        "dice_pool_breakdown": pool_breakdown,
        "blood_potency_bonus": bp_bonus,
        "resonance_bonus": resonance_bonus,
        "surge_dice": surge_dice,
        "rouse_result": rouse_result,
        "roll_result": roll_result,
        "defense": defense,
        "hunger_before": hunger_before,
        "hunger_after": character.hunger,
        "success": roll_result.is_success,
        "message": message,
    }


def _roll_defense(target, opposed_by: str) -> dict[str, Any]:
    """Roll the target's ``opposed_by`` pool with the target's own Hunger dice.

    The target must be a Character (PowerRefused otherwise). Only vampires
    roll Hunger dice (Character.dice_hunger): a mortal or ghoul defender
    rolls none, so it can't get a messy critical or bestial failure.
    """
    if not hasattr(target, "get_trait"):
        raise PowerRefused(f"{getattr(target, 'key', target)} can't resist a power; name a character.")
    trait_names = parse_dice_pool(opposed_by)
    pool, breakdown = calculate_pool_from_traits(target, trait_names)
    pool = min(MAX_POOL, max(1, pool))
    return {
        "target": target,
        "opposed_by": opposed_by,
        "dice_pool": pool,
        "dice_pool_breakdown": breakdown,
        "roll_result": roll_v5_pool(pool_size=pool, hunger=target.dice_hunger, difficulty=0),
    }


def _resonance_dice(character, discipline_name: str) -> int:
    """Resonance dice for this discipline (blood_utils owns the rule)."""
    from commands.v5.utils.blood_utils import get_resonance_bonus

    return get_resonance_bonus(character, discipline_name)


_PARENTHETICAL = re.compile(r"\([^)]*\)")


def parse_dice_pool(pool_string: str) -> list[str]:
    """
    Parse a dice pool string into trait names.

    Splits on '+'. Where a part offers alternatives ('A / B'), takes the
    first. Drops parenthetical notes.

    Examples:
        >>> parse_dice_pool("Strength + Brawl")
        ['Strength', 'Brawl']
        >>> parse_dice_pool("Charisma / Manipulation + Intimidation")
        ['Charisma', 'Intimidation']
        >>> parse_dice_pool("Wits + Obfuscate (hidden vampires)")
        ['Wits', 'Obfuscate']
    """
    if not pool_string:
        return []
    pool_string = _PARENTHETICAL.sub("", pool_string)
    traits = []
    for part in pool_string.split("+"):
        option = part.split("/")[0].strip()
        if option:
            traits.append(option)
    return traits


def calculate_pool_from_traits(character, trait_names: list[str]) -> tuple[int, dict[str, int]]:
    """
    Calculate total dice pool from a list of trait names.

    Returns:
        Tuple of (total_pool, breakdown_dict), e.g. (7, {'Strength': 4, 'Brawl': 3})
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
    Blood Potency bonus dice for discipline rolls:
    world.v5_data.BLOOD_POTENCY["power_bonus"].

    ``discipline_name`` is unused; it is kept for callers.
    """
    row = BLOOD_POTENCY.get(character.blood_potency)
    return row["power_bonus"] if row else 0


def can_use_power(character, power_name: str) -> tuple[bool, str]:
    """
    Check whether a character may use a discipline power.

    The character must know the power (Character.known_powers) and have the
    discipline and any amalgam discipline at the required rating. Hunger is
    checked separately (check_power_use).

    Returns:
        Tuple of (can_use: bool, reason: str)
    """
    power = find_power(power_name)
    if power is None:
        return False, f"Power '{power_name}' not found"

    if power["name"] not in character.known_powers:
        return False, f"You don't know the power '{power['name']}'"

    discipline_rating = character.get_trait(power["discipline"])
    if discipline_rating < power["level"]:
        return False, f"Requires {power['discipline']} {power['level']} (you have {discipline_rating})"

    # Amalgam requirement, stored as e.g. "Obfuscate 2"
    if power.get("amalgam"):
        amalgam_name, _, amalgam_level = power["amalgam"].rpartition(" ")
        amalgam_rating = character.get_trait(amalgam_name)
        if amalgam_rating < int(amalgam_level):
            return False, f"Requires {power['amalgam']} (you have {amalgam_rating})"

    return True, "Can use power"


def get_character_discipline_powers(character, discipline_name: str | None = None) -> list[dict[str, Any]]:
    """
    List the discipline powers a character knows, optionally for one discipline.

    Each entry: power (the DISCIPLINE_POWERS entry), name, discipline, level,
    dice_pool, rouse (the Rouse-check count), can_use, reason.
    """
    results = []
    for name in character.known_powers:
        power = find_power(name)
        if power is None:
            continue
        if discipline_name and power["discipline"].lower() != discipline_name.lower():
            continue
        can_use, reason = can_use_power(character, power["name"])

        results.append(
            {
                "power": power,
                "name": power["name"],
                "discipline": power["discipline"],
                "level": power["level"],
                "dice_pool": power.get("dice_pool"),
                "rouse": power.get("rouse", 0),
                "can_use": can_use,
                "reason": reason,
            }
        )

    return results


def format_defense(defense: dict[str, Any]) -> str:
    """The defender's roll, without second-person outcome text or pool size."""
    roll = defense["roll_result"]
    name = getattr(defense["target"], "key", str(defense["target"]))
    dice = " ".join(str(die) for die in roll.regular_dice)
    hunger = " ".join(str(die) for die in roll.hunger_dice)
    shown = f"[{dice}]" + (f" Hunger [{hunger}]" if hunger else "")
    return f"|w{name} resists|n ({defense['opposed_by']}): {shown} - |w{roll.total_successes}|n successes."


def _format_discipline_roll_message(
    power: dict[str, Any],
    pool_breakdown: dict[str, int],
    total_pool: int,
    rouse_result: RouseResult | None,
    roll_result,
    defense: dict[str, Any] | None = None,
) -> str:
    """Format a discipline power roll for display."""
    lines = []

    lines.append(f"|c=== {power['name']} ===|n")
    lines.append(f"|w{power['discipline']} Level {power['level']}|n")

    if power.get("description"):
        desc_first_line = power["description"].splitlines()[0][:80]
        lines.append(f"|x{desc_first_line}|n")

    lines.append("")

    lines.append("|wDice Pool:|n")
    for trait_name, value in pool_breakdown.items():
        if trait_name in ("Blood Potency Bonus", "Resonance", "Blood Surge") and value > 0:
            lines.append(f"  {trait_name}: |y+{value}|n")
        else:
            lines.append(f"  {trait_name}: {value}")

    lines.append(f"  |wTotal: {total_pool}|n")
    lines.append("")

    if defense is not None:
        lines.append(format_defense(defense))
        lines.append(f"|wYou need at least {roll_result.difficulty} successes (a tie goes to you).|n")
        lines.append("")
    elif power.get("opposed_by"):
        lines.append(
            f"|xUncontested: the target resists with {power['opposed_by']}. "
            "Name a target (= <name>), or the Storyteller adjudicates.|n"
        )

    lines.append(roll_result.format_result(show_details=True))

    if rouse_result is not None:
        lines.append("")
        lines.extend(format_rouse_lines(rouse_result))

    return "\n".join(lines)
