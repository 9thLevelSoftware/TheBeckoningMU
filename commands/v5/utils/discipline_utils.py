"""
Discipline Utility Functions

Helper functions for managing and using discipline powers.
"""

from world.v5_data import DISCIPLINES
from dice.dice_roller import roll_rouse_check
from .blood_utils import get_blood_potency, increase_hunger
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

        level = character.db.disciplines.get(disc_name, 0)
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

    char_level = character.db.disciplines.get(discipline_name, 0)
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
    Check if a character can use a specific discipline power.

    Args:
        character: The character object
        discipline_name: Name of the discipline
        power_name: Name of the power

    Returns:
        tuple: (can_use: bool, reason: str)
    """
    # Check if discipline exists
    if discipline_name not in DISCIPLINES:
        return False, f"Unknown discipline: {discipline_name}"

    # Get the power
    power, power_level = get_power_by_name(discipline_name, power_name)
    if not power:
        return False, f"Unknown power: {power_name}"

    # Check character's discipline level
    char_level = character.db.disciplines.get(discipline_name, 0)
    if char_level < power_level:
        return False, f"You need {discipline_name} {power_level} to use {power_name} (you have {char_level})"

    # Check amalgam prerequisites
    if power.get("amalgam"):
        amalgam_req = power["amalgam"]
        # Parse amalgam requirement (e.g., "Obfuscate 2" or "Dominate 3")
        parts = amalgam_req.split()
        if len(parts) >= 2:
            req_disc = " ".join(parts[:-1])
            req_level = int(parts[-1])

            char_amalgam_level = character.db.disciplines.get(req_disc, 0)
            if char_amalgam_level < req_level:
                return False, f"{power_name} requires {amalgam_req} (you have {req_disc} {char_amalgam_level})"

    return True, "OK"


def activate_discipline_power(character, discipline_name, power_name):
    """
    Activate a discipline power, handling Rouse checks and effects.

    Args:
        character: The character object
        discipline_name: Name of the discipline
        power_name: Name of the power

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "rouse_result": dict or None (if Rouse check was needed)
        }
    """
    # Check if character can use the power
    can_use, reason = can_use_power(character, discipline_name, power_name)
    if not can_use:
        return {
            "success": False,
            "message": reason,
            "rouse_result": None
        }

    # Get the power
    power, power_level = get_power_by_name(discipline_name, power_name)

    # Handle Rouse check if required
    rouse_success = True
    rouse_die = None
    if power["rouse"]:
        # Perform Rouse check
        rouse_result = roll_rouse_check(character, reason=f"Activating {power['name']}")
        rouse_success = not rouse_result.get('hunger_increased', False)
        rouse_die = rouse_result.get('die', None)

        # If Rouse check fails, Hunger increases
        if not rouse_success:
            new_hunger = increase_hunger(character, 1)
            return {
                "success": True,
                "message": f"You activate {power['name']}, but your Beast stirs... (Hunger increased to {new_hunger})",
                "rouse_result": {"success": False, "die": rouse_die, "hunger_increased": True},
                "power": power
            }

    # Check for Resonance bonus
    resonance_bonus = check_resonance_bonus(character, discipline_name)

    # Apply effect tracking if power has duration
    power_copy = power.copy()
    power_copy['discipline'] = discipline_name

    duration = get_power_duration(power_copy)
    effect_applied = False
    applied_effect = None

    if duration and duration != 'instant':
        # Apply generic effect
        applied_effect = apply_effect(character, power_copy, duration)
        effect_applied = True

        # Apply discipline-specific effects
        discipline_lower = discipline_name.lower()
        power_name_lower = power['name'].lower()

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

    # Build rouse_result dictionary if a Rouse check was performed
    rouse_result_dict = None
    if power["rouse"]:
        rouse_result_dict = {
            "success": rouse_success,
            "die": rouse_die,
            "hunger_increased": not rouse_success
        }

    result = {
        "success": True,
        "message": f"You successfully activate {power['name']}.",
        "rouse_result": rouse_result_dict,
        "power": power,
        "resonance_bonus": resonance_bonus,
        "duration": duration,
        "effect_applied": effect_applied,
        "effect": applied_effect
    }

    return result


def check_resonance_bonus(character, discipline_name):
    """
    Check if character gets a Resonance bonus for using this discipline.

    In V5, if a vampire has a matching Resonance for a discipline, they get +1 die.

    Resonance mappings:
    - Sanguine (enthusiastic): Celerity, Presence
    - Melancholic (sad): Fortitude, Obfuscate
    - Choleric (angry): Potence, Presence
    - Phlegmatic (calm): Auspex, Dominate
    - Animal: Animalism, Protean
    - Blood Sorcery: Any intense emotion

    Args:
        character: The character object
        discipline_name: Name of the discipline

    Returns:
        dict: {"bonus": int, "resonance": str} or None
    """
    current_resonance = character.db.resonance or ""

    # Map disciplines to resonances that grant bonuses
    resonance_map = {
        "Animalism": ["animal"],
        "Auspex": ["phlegmatic"],
        "Blood Sorcery": ["sanguine", "melancholic", "choleric", "phlegmatic"],  # Any intense
        "Celerity": ["sanguine"],
        "Dominate": ["phlegmatic"],
        "Fortitude": ["melancholic"],
        "Obfuscate": ["melancholic"],
        "Oblivion": [],  # No resonance bonus typically
        "Potence": ["choleric"],
        "Presence": ["sanguine", "choleric"],
        "Protean": ["animal"]
    }

    matching_resonances = resonance_map.get(discipline_name, [])

    if current_resonance.lower() in matching_resonances:
        return {
            "bonus": 1,
            "resonance": current_resonance
        }

    return None


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
    rouse_str = f"{BLOOD_RED}[Rouse]{RESET}" if power["rouse"] else f"{SHADOW_GREY}[No Rouse]{RESET}"

    output = f"{level_str} {PALE_IVORY}{power['name']}{RESET} {rouse_str}\n"
    output += f"   {power['description']}\n"

    if power.get("dice_pool"):
        output += f"   {SHADOW_GREY}Dice Pool:{RESET} {power['dice_pool']}\n"

    if power.get("amalgam"):
        output += f"   {SHADOW_GREY}Requires:{RESET} {power['amalgam']}\n"

    if power.get("duration"):
        output += f"   {SHADOW_GREY}Duration:{RESET} {power['duration']}\n"

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
