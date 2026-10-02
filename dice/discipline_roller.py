"""
Discipline Power Rolling System for V5 Integration

Rolls discipline powers: looks powers up in world.v5_data.DISCIPLINE_POWERS,
checks the character may use them, calculates dice pools from the
character's traits (Character.get_trait), adds Blood Potency and Resonance
dice, rolls with the character's Hunger, then makes the power's Rouse checks.
"""

import re
from typing import Any

from world.v5_data import BLOOD_POTENCY, UnknownTrait, find_power

from .dice_roller import MAX_DIFFICULTY, MAX_POOL, roll_v5_pool
from .rouse_checker import HUNGER_5_REFUSAL, MAX_HUNGER, RouseResult, perform_rouse_check


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
    (QR p.4).
    """
    can_use, reason = can_use_power(character, power["name"])
    if not can_use:
        raise PowerRefused(reason)
    if with_rouse and power.get("rouse", 0) > 0 and character.hunger >= MAX_HUNGER:
        raise PowerRefused(HUNGER_5_REFUSAL)


def pay_rouse_cost(character, power: dict[str, Any]) -> list[RouseResult]:
    """Make the power's Rouse checks: ``power["rouse"]`` of them (0 = free).

    Each check may raise Hunger. If a failed check brings Hunger to 5, the
    remaining checks are refused (perform_rouse_check returns refused
    results, which change nothing); the action has already happened.
    """
    reason = f"Activating {power['name']}"
    return [
        perform_rouse_check(character, reason=reason, power_level=power["level"]) for _ in range(power.get("rouse", 0))
    ]


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
       power bonus and any Resonance dice.
    4. Roll with the character's current Hunger. When ``target`` is given
       and the power is contested (``opposed_by``), the target rolls that
       pool with their own Hunger and the user needs more successes than the
       target; ``difficulty`` is then ignored.
    5. Make the power's Rouse checks after the roll (QR p.4: Hunger rises
       after the action), unless ``with_rouse`` is False.

    Raises:
        PowerRefused (a ValueError): the power was refused; nothing changed.
        ValueError: the roll itself was invalid (e.g. a pool over MAX_POOL);
            nothing was charged.
    """
    power = lookup_power(power_name)
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
    total_pool = max(1, base_pool + bp_bonus + resonance_bonus)
    if total_pool > MAX_POOL:
        raise ValueError(f"Pool size cannot exceed {MAX_POOL} dice (got {total_pool})")

    hunger_before = character.hunger

    defense = None
    if target is not None and power.get("opposed_by"):
        defense = _roll_defense(target, power["opposed_by"])
        # UNVERIFIED tie rule: the user must beat the defender's successes.
        difficulty = min(MAX_DIFFICULTY, defense["roll_result"].total_successes + 1)

    roll_result = roll_v5_pool(pool_size=total_pool, hunger=hunger_before, difficulty=difficulty)

    rouse_results = pay_rouse_cost(character, power) if with_rouse else []

    message = _format_discipline_roll_message(
        power=power,
        pool_breakdown=pool_breakdown,
        total_pool=total_pool,
        rouse_results=rouse_results,
        roll_result=roll_result,
        difficulty=difficulty,
        defense=defense,
    )

    return {
        "power": power,
        "power_name": power["name"],
        "dice_pool": total_pool,
        "dice_pool_breakdown": pool_breakdown,
        "blood_potency_bonus": bp_bonus,
        "resonance_bonus": resonance_bonus,
        "rouse_results": rouse_results,
        "roll_result": roll_result,
        "defense": defense,
        "hunger_before": hunger_before,
        "hunger_after": character.hunger,
        "success": roll_result.is_success,
        "message": message,
    }


def _roll_defense(target, opposed_by: str) -> dict[str, Any]:
    """Roll the target's ``opposed_by`` pool with the target's own Hunger.

    A target without the Character accessors rolls one die with no Hunger.
    """
    trait_names = parse_dice_pool(opposed_by)
    if hasattr(target, "get_trait"):
        pool, breakdown = calculate_pool_from_traits(target, trait_names)
        hunger = getattr(target, "hunger", 0)
    else:
        pool, breakdown, hunger = 0, dict.fromkeys(trait_names, 0), 0
    pool = min(MAX_POOL, max(1, pool))
    return {
        "target": target,
        "opposed_by": opposed_by,
        "dice_pool": pool,
        "dice_pool_breakdown": breakdown,
        "roll_result": roll_v5_pool(pool_size=pool, hunger=hunger, difficulty=0),
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


def format_rouse_results(rouse_results: list[RouseResult]) -> list[str]:
    """Display lines for a power's Rouse checks."""
    lines = []
    for result in rouse_results:
        if result.refused:
            lines.append("Rouse Check: |rnot rolled|n (Hunger 5).")
            continue
        if result.reroll_used:
            roll_text = f"|y{result.rolls[0]}|n, Blood Potency re-roll |y{result.roll}|n"
        else:
            roll_text = f"|y{result.roll}|n"
        if result.success:
            lines.append(f"Rouse Check: {roll_text}. |gSuccess.|n Hunger stays at |r{result.hunger_after}|n.")
        else:
            lines.append(f"Rouse Check: {roll_text}. |rFailed.|n Hunger rises to |r{result.hunger_after}|n.")
    if any(result.refused for result in rouse_results):
        lines.append("|rYou reached Hunger 5; the remaining Rouse checks were not rolled.|n")
    return lines


def _format_discipline_roll_message(
    power: dict[str, Any],
    pool_breakdown: dict[str, int],
    total_pool: int,
    rouse_results: list[RouseResult],
    roll_result,
    difficulty: int,
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
        if trait_name in ("Blood Potency Bonus", "Resonance") and value > 0:
            lines.append(f"  {trait_name}: |y+{value}|n")
        else:
            lines.append(f"  {trait_name}: {value}")

    lines.append(f"  |wTotal: {total_pool}|n")
    lines.append("")

    if defense is not None:
        target = defense["target"]
        target_name = getattr(target, "key", str(target))
        lines.append(f"|wOpposed by {target_name}:|n {defense['opposed_by']} ({defense['dice_pool']} dice)")
        lines.append(defense["roll_result"].format_result(show_details=True))
        lines.append("")
        lines.append(f"|wYou need more than {defense['roll_result'].total_successes} successes.|n")
    elif power.get("opposed_by"):
        lines.append(f"|xContested: the target resists with {power['opposed_by']}.|n")

    lines.append(roll_result.format_result(show_details=True))

    if rouse_results:
        lines.append("")
        lines.extend(format_rouse_results(rouse_results))

    return "\n".join(lines)
