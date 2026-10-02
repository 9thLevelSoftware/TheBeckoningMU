"""
Discipline Utility Functions

Helper functions for managing and using discipline powers.
"""

from world.v5_data import DISCIPLINES, find_power
from dice import discipline_roller
from .discipline_effects import (
    apply_effect,
    get_power_duration,
    apply_obfuscate_effect,
    apply_dominate_effect,
    apply_auspex_effect,
    apply_celerity_effect,
    apply_fortitude_effect,
    apply_presence_effect,
    apply_protean_effect
)


def get_character_disciplines(character):
    """
    Get all disciplines known by a character with their levels.

    Args:
        character: The character object

    Returns:
        dict: {"Discipline Name": level, ...}
    """
    disciplines = {}

    for disc_name in DISCIPLINES.keys():
        if disc_name == "Thin-Blood Alchemy":
            continue  # Handle separately

        level = character.get_trait(disc_name)
        if level > 0:
            disciplines[disc_name] = level

    return disciplines


def get_discipline_powers(character, discipline_name):
    """
    Get all powers a character can use for a given discipline.

    Args:
        character: The character object
        discipline_name: Name of the discipline

    Returns:
        list: List of power dicts the character has access to
    """
    if discipline_name not in DISCIPLINES:
        return []

    char_level = character.get_trait(discipline_name)
    if char_level == 0:
        return []

    available_powers = []
    disc_data = DISCIPLINES[discipline_name]

    # Collect all powers up to character's level
    for level in range(1, char_level + 1):
        if level in disc_data["powers"]:
            for power in disc_data["powers"][level]:
                power_copy = power.copy()
                power_copy["level"] = level
                available_powers.append(power_copy)

    return available_powers


def get_power_by_name(discipline_name, power_name):
    """
    Get a specific power by name from a discipline.

    Args:
        discipline_name: Name of the discipline
        power_name: Name of the power (case-insensitive)

    Returns:
        tuple: (power_dict, level) or (None, None) if not found
    """
    if discipline_name not in DISCIPLINES:
        return None, None

    disc_data = DISCIPLINES[discipline_name]
    power_name_lower = power_name.lower()

    # Search through all levels
    for level, powers in disc_data["powers"].items():
        for power in powers:
            if power["name"].lower() == power_name_lower:
                return power, level

    return None, None


def can_use_power(character, discipline_name, power_name):
    """
    Check whether a character may use a discipline power.

    The rule is dice.discipline_roller.can_use_power (the power must be
    known, with the discipline and any amalgam at the required rating); this
    wrapper also checks the power belongs to ``discipline_name``.

    Returns:
        tuple: (can_use: bool, reason: str)
    """
    if discipline_name not in DISCIPLINES:
        return False, f"Unknown discipline: {discipline_name}"

    power, _ = get_power_by_name(discipline_name, power_name)
    if not power:
        return False, f"Unknown power: {power_name}"

    return discipline_roller.can_use_power(character, power["name"])


def activate_discipline_power(character, discipline_name, power_name, difficulty=0, target=None, with_rouse=True):
    """
    Use a discipline power: check it, roll it if it has a dice pool, make its
    Rouse checks and track its effect.

    A power with a dice pool goes through dice.discipline_roller
    .roll_discipline_power, which rolls with the pre-Rouse Hunger and then
    makes ``power["rouse"]`` Rouse checks. A power without one is used
    without a roll and makes the same Rouse checks. Either way it is refused,
    with nothing rolled or charged, if the character can't use it, if it
    needs a Rouse at Hunger 5, or if the roll is invalid.

    Args:
        character: The character object
        discipline_name: Name of the discipline, or None to take it from the power
        power_name: Name of the power (any case)
        difficulty: Successes needed (ignored for a contested roll against ``target``)
        target: Defender for a contested power (one with ``opposed_by``)
        with_rouse: False skips the Rouse checks (staff only, enforced by the command)

    Returns:
        dict: {
            "success": bool (False means refused; nothing changed),
            "message": str,
            "power": dict or None,
            "roll": dict or None (roll_discipline_power's result),
            "rouse_results": list of RouseResult,
            "duration": str or None,
            "effect_applied": bool,
            "effect": dict or None,
        }
    """
    def refused(message, power=None):
        return {
            "success": False,
            "message": message,
            "power": power,
            "roll": None,
            "rouse_results": [],
            "duration": None,
            "effect_applied": False,
            "effect": None,
        }

    power = find_power(power_name)
    if power is None or (discipline_name and power["discipline"].lower() != discipline_name.lower()):
        return refused(f"Unknown power: {power_name}")

    try:
        if power.get("dice_pool"):
            roll = discipline_roller.roll_discipline_power(
                character, power["name"], difficulty=difficulty, with_rouse=with_rouse, target=target
            )
            rouse_results = roll["rouse_results"]
        else:
            discipline_roller.check_power_use(character, power, with_rouse=with_rouse)
            roll = None
            rouse_results = discipline_roller.pay_rouse_cost(character, power) if with_rouse else []
    except ValueError as err:
        return refused(str(err), power)

    duration = get_power_duration(power)
    effect_applied = False
    applied_effect = None

    # A power whose roll failed has no effect to track; its Rouse is still paid.
    if duration and duration != 'instant' and (roll is None or roll["success"]):
        # A "turn" power lasts one turn unless an effect handler says otherwise.
        parameters = {"turns": 1} if duration == "turn" else {}
        applied_effect = apply_effect(character, power, duration, parameters)
        effect_applied = True

        discipline_lower = power["discipline"].lower()
        if discipline_lower == 'obfuscate':
            apply_obfuscate_effect(character, power['name'])
        elif discipline_lower == 'dominate':
            apply_dominate_effect(character, power['name'])
        elif discipline_lower == 'auspex':
            apply_auspex_effect(character, power['name'])
        elif discipline_lower == 'celerity':
            apply_celerity_effect(character, power['name'])
        elif discipline_lower == 'fortitude':
            apply_fortitude_effect(character, power['name'])
        elif discipline_lower == 'presence':
            apply_presence_effect(character, power['name'])
        elif discipline_lower == 'protean':
            apply_protean_effect(character, power['name'])

    return {
        "success": True,
        "message": f"You activate {power['name']}.",
        "power": power,
        "roll": roll,
        "rouse_results": rouse_results,
        "duration": duration,
        "effect_applied": effect_applied,
        "effect": applied_effect,
    }


def format_power_display(power, level, include_level=True):
    """
    Format a power for display.

    Args:
        power: Power dictionary
        level: Level of the power
        include_level: Whether to include level in display

    Returns:
        str: Formatted power string
    """
    from world.ansi_theme import BLOOD_RED, PALE_IVORY, SHADOW_GREY, RESET

    level_str = f"{BLOOD_RED}●{RESET}" * level if include_level else ""
    rouse = power.get("rouse", 0)
    if rouse:
        rouse_str = f"{BLOOD_RED}[Rouse x{rouse}]{RESET}" if rouse > 1 else f"{BLOOD_RED}[Rouse]{RESET}"
    else:
        rouse_str = f"{SHADOW_GREY}[Free]{RESET}"

    output = f"{level_str} {PALE_IVORY}{power['name']}{RESET} {rouse_str}\n"
    output += f"   {power['description']}\n"

    if power.get("dice_pool"):
        output += f"   {SHADOW_GREY}Dice Pool:{RESET} {power['dice_pool']}\n"

    if power.get("amalgam"):
        output += f"   {SHADOW_GREY}Requires:{RESET} {power['amalgam']}\n"

    if power.get("duration"):
        output += f"   {SHADOW_GREY}Duration:{RESET} {power.get('duration_text', power['duration'])}\n"

    return output


def get_all_discipline_powers_summary(character):
    """
    Get a formatted summary of all discipline powers the character knows.

    Args:
        character: The character object

    Returns:
        str: Formatted string with all powers
    """
    from world.ansi_theme import (
        BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, RESET,
        BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
    )

    disciplines = get_character_disciplines(character)

    if not disciplines:
        return f"{SHADOW_GREY}You have no disciplines.{RESET}"

    output = []

    for disc_name, disc_level in sorted(disciplines.items()):
        disc_data = DISCIPLINES[disc_name]
        output.append(f"\n{BLOOD_RED}{disc_name} {RESET}{DARK_RED}{'●' * disc_level}{RESET}")
        output.append(f"{SHADOW_GREY}{disc_data['description']}{RESET}\n")

        powers = get_discipline_powers(character, disc_name)

        if powers:
            for power in powers:
                output.append(format_power_display(power, power["level"]))
        else:
            output.append(f"   {SHADOW_GREY}No powers learned yet.{RESET}\n")

    return "\n".join(output)
