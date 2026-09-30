"""
Clan System Utility Functions for V5

Handles clan selection, validation, banes, and compulsions.
"""

from world.v5_data import CLANS


def get_available_clans():
    """
    Get list of all available clans.

    Returns:
        list: Clan names
    """
    return list(CLANS.keys())


def get_clan_info(clan_name):
    """
    Get full information about a clan.

    Args:
        clan_name (str): Name of the clan

    Returns:
        dict: Clan data (disciplines, bane, compulsion) or None if not found
    """
    return CLANS.get(clan_name, None)


def is_valid_clan(clan_name):
    """
    Check if a clan name is valid.

    Args:
        clan_name (str): Name to check

    Returns:
        bool: True if valid clan
    """
    return clan_name in CLANS


def get_clan(character):
    """
    Get character's current clan.

    Args:
        character: Character object

    Returns:
        str or None: Clan name
    """
    vampire = character.db.vampire
    if not vampire:
        return None
    return vampire.get("clan", None)


def set_clan(character, clan_name):
    """
    Set character's clan and apply clan-specific data.

    This sets:
    - Clan name
    - Clan bane
    - Clan compulsion
    - In-clan disciplines (but does NOT grant dots automatically)

    Args:
        character: Character object
        clan_name (str): Name of the clan

    Returns:
        bool: True if successful, False if invalid clan

    Raises:
        ValueError: If character already has a clan set
    """
    if not is_valid_clan(clan_name):
        return False

    # Ensure vampire data exists
    if not character.db.vampire:
        raise ValueError("Character must be a vampire to have a clan.")

    # Check if clan already set (can't change clan mid-game without admin)
    if character.db.vampire.get("clan") is not None:
        raise ValueError("Character already has a clan. Contact staff to change.")

    clan_data = get_clan_info(clan_name)

    # Set clan
    character.db.vampire["clan"] = clan_name
    character.db.vampire["bane"] = clan_data["bane"]
    character.db.vampire["compulsion"] = clan_data["compulsion"]

    # Note: We don't automatically grant discipline dots here
    # That happens during character creation or via XP spending
    # We just record which disciplines are in-clan for cost purposes

    return True


def get_inclan_disciplines(character):
    """
    Get list of in-clan disciplines for character.

    Args:
        character: Character object

    Returns:
        list: Discipline names, or empty list if no clan set
    """
    clan = get_clan(character)
    if not clan:
        return []

    clan_data = get_clan_info(clan)
    return clan_data.get("disciplines", [])


def is_discipline_inclan(character, discipline_name):
    """
    Check if a discipline is in-clan for character.

    Args:
        character: Character object
        discipline_name (str): Name of the discipline

    Returns:
        bool: True if in-clan
    """
    inclan = get_inclan_disciplines(character)
    return discipline_name in inclan


def get_discipline_xp_cost(character, discipline_name, current_level, new_level):
    """
    Calculate XP cost to raise a discipline.

    In-clan: new level × 5
    Out-of-clan: new level × 7

    Args:
        character: Character object
        discipline_name (str): Name of the discipline
        current_level (int): Current discipline level
        new_level (int): Desired discipline level

    Returns:
        int: XP cost

    Raises:
        ValueError: If new_level <= current_level or new_level > 5
    """
    if new_level <= current_level:
        raise ValueError("New level must be higher than current level")

    if new_level > 5:
        raise ValueError("Discipline level cannot exceed 5")

    # Check if in-clan
    inclan = is_discipline_inclan(character, discipline_name)

    total_cost = 0
    for level in range(current_level + 1, new_level + 1):
        if inclan:
            total_cost += level * 5
        else:
            total_cost += level * 7

    return total_cost


def get_bane(character):
    """
    Get character's clan bane description.

    Args:
        character: Character object

    Returns:
        str or None: Bane description
    """
    vampire = character.db.vampire
    if not vampire:
        return None
    return vampire.get("bane", None)


def get_compulsion(character):
    """
    Get character's clan compulsion description.

    Args:
        character: Character object

    Returns:
        str or None: Compulsion description
    """
    vampire = character.db.vampire
    if not vampire:
        return None
    return vampire.get("compulsion", None)


def trigger_compulsion(character):
    """
    Trigger character's clan compulsion.

    This is typically called by staff or automated when a Bestial Failure occurs.

    Args:
        character: Character object

    Returns:
        dict: Compulsion data
            - compulsion: Compulsion description
            - effect: Mechanical effect
            - message: Narrative message
    """
    compulsion = get_compulsion(character)
    clan = get_clan(character)

    if not compulsion:
        return {
            "compulsion": None,
            "effect": "None",
            "message": "You have no compulsion."
        }

    # Parse compulsion to extract mechanical effect
    # Most compulsions cause -1 or -2 dice penalty to certain pools
    message = f"|rYour {clan} compulsion activates:|n {compulsion}"

    return {
        "compulsion": compulsion,
        "effect": "See compulsion description for mechanical effects",
        "message": message
    }


def format_clan_display(character):
    """
    Create formatted clan information display.

    Args:
        character: Character object

    Returns:
        str: Formatted clan display
    """
    clan = get_clan(character)

    if not clan:
        return "Clan: |xNot Set|n"

    clan_data = get_clan_info(clan)

    lines = []
    lines.append(f"|wClan:|n {clan}")
    lines.append(f"|wIn-Clan Disciplines:|n {', '.join(clan_data['disciplines'])}")
    lines.append(f"|wBane:|n {clan_data['bane']}")
    lines.append(f"|wCompulsion:|n {clan_data['compulsion']}")

    return "\n".join(lines)


def get_clan_summary(clan_name):
    """
    Get a summary of clan information (for chargen selection).

    Args:
        clan_name (str): Name of the clan

    Returns:
        str: Formatted summary
    """
    if not is_valid_clan(clan_name):
        return f"|rInvalid clan: {clan_name}|n"

    clan_data = get_clan_info(clan_name)

    lines = []
    lines.append(f"|w{clan_name}|n")
    lines.append(f"  |cDisciplines:|n {', '.join(clan_data['disciplines'])}")
    lines.append(f"  |yBane:|n {clan_data['bane']}")
    lines.append(f"  |mCompulsion:|n {clan_data['compulsion']}")

    return "\n".join(lines)


def list_all_clans():
    """
    Get formatted list of all clans with brief info.

    Returns:
        str: Formatted clan list
    """
    lines = []
    lines.append("|c" + "="*70 + "|n")
    lines.append("|c" + " "*25 + "VAMPIRE CLANS" + " "*25 + "|n")
    lines.append("|c" + "="*70 + "|n")
    lines.append("")

    for clan_name in sorted(get_available_clans()):
        clan_data = get_clan_info(clan_name)
        disciplines = ", ".join(clan_data["disciplines"])
        lines.append(f"|w{clan_name}|n")
        lines.append(f"  Disciplines: |c{disciplines}|n")
        lines.append("")

    lines.append("|xUse 'help clans' for detailed clan information.|n")

    return "\n".join(lines)


def validate_clan_selection(character, clan_name):
    """
    Validate whether character can select this clan during chargen.

    Args:
        character: Character object
        clan_name (str): Desired clan

    Returns:
        tuple: (bool, str) - (is_valid, error_message)
    """
    # Check if valid clan
    if not is_valid_clan(clan_name):
        return (False, f"'{clan_name}' is not a valid clan.")

    # Check if already has clan
    if get_clan(character):
        return (False, "You already have a clan selected. Use 'chargen/reset' to start over.")

    # Special clans (like Caitiff, Thin-Blood) might require staff approval
    restricted_clans = ["Thin-Blood", "Caitiff", "Salubri"]
    if clan_name in restricted_clans:
        return (False, f"{clan_name} requires staff approval. Please submit a character concept first.")

    return (True, "Clan selection valid")


def get_starting_disciplines_for_clan(clan_name):
    """
    Get the in-clan disciplines that characters typically start with.

    During chargen, characters typically choose 1 or 2 of their in-clan disciplines.

    Args:
        clan_name (str): Name of the clan

    Returns:
        list: In-clan discipline names
    """
    clan_data = get_clan_info(clan_name)
    if clan_data:
        return clan_data["disciplines"]
    return []
