"""
Display formatting utilities for V5 character sheets and game information.

This module provides WoD-style formatting with dot leaders adapted to V5 data.
"""

from evennia.utils.ansi import ANSIString

from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, DEEP_PURPLE,
    MIDNIGHT_BLUE, BONE_WHITE, DECAY_GREEN, GOLD, VAMPIRE_GOLD, RESET,
    HUNGER_0, HUNGER_1_2, HUNGER_3_4, HUNGER_5,
    get_hunger_color,
    DBOX_H, DBOX_V, DBOX_TL, DBOX_TR, DBOX_BL, DBOX_BR,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR, BOX_L, BOX_R
)

from collections.abc import Mapping


# V5 Skills organized by category (matching WoD pattern)
PHYSICAL_SKILLS = ['athletics', 'brawl', 'craft', 'drive', 'firearms', 'larceny', 'melee', 'stealth', 'survival']
SOCIAL_SKILLS = ['animal_ken', 'etiquette', 'insight', 'intimidation', 'leadership', 'performance', 'persuasion', 'streetwise', 'subterfuge']
MENTAL_SKILLS = ['academics', 'awareness', 'finance', 'investigation', 'medicine', 'occult', 'politics', 'science', 'technology']

# Bio fields to display
BIO_FIELDS = ['full_name', 'birthdate', 'concept', 'splat', 'ambition', 'sire', 'desire', 'predator', 'clan', 'generation']


def format(key="", val=0, width=24, just="rjust", type="", temp=0):
    """
    Format a key-value pair with optional dot leaders.

    Adapted from WoD utils.py to work with V5 data.

    Args:
        key: Label for the value
        val: Value to display
        width: Total width of the formatted string
        just: Justification - "ljust" for spaces, "rjust" for dot leaders
        type: "specialty" for indented specialty display
        temp: Temporary modifier value

    Returns:
        ANSIString with formatted output
    """
    # Only highlight (white) if value >= 1, otherwise grey
    try:
        val_num = int(val) if val else 0
        title = "|w" if val_num >= 1 else "|x"
        text_val = "|w" if val_num >= 1 else "|x"
    except (ValueError, TypeError):
        # For string values, highlight if non-empty
        title = "|w" if val else "|x"
        text_val = "|w" if val else "|x"

    title += key.capitalize() + ":|n"
    text_val += str(val) + "|n"
    if temp:
        text_val += f"|w({temp})|n"

    if just == "ljust":
        if type == "specialty":
            return ANSIString(ANSIString(title).ljust(20) + ANSIString("{}".format(str(val)))).ljust(width)[0:width]
        else:
            return ANSIString(ANSIString(title).ljust(15) + ANSIString("{}".format(str(val)))).ljust(width)[0:width]
    else:
        if type == "specialty":
            return "  " + ANSIString(ANSIString(title).ljust(width - 2 - len(ANSIString("{}".format(text_val))), ANSIString("|x.|n")) + "{}".format(text_val))
        else:
            return ANSIString(ANSIString(title).ljust(width - len(ANSIString("{}".format(text_val))), ANSIString("|x.|n")) + "{}".format(text_val))


def format_character_sheet(character):
    """
    Format V5 character sheet matching WoD style with dot leaders.

    Args:
        character: Character object (read only through its accessors)

    Returns:
        str: Formatted character sheet
    """
    # Header
    output = ANSIString(
        "|Y[|n |wCharacter Sheet|n for: |c{}|n |Y]|n".format(character.key)
    ).center(78, ANSIString("|R=|n"))

    # Bio Section
    output += _format_bio_section(character)
    output += _format_vitals_section(character)

    # Attributes Section
    output += "\n" + ANSIString("|w Attributes |n").center(78, ANSIString("|R=|n"))
    output += _format_attributes_section(character)

    # Skills Section
    output += ANSIString("|w Skills |n").center(78, ANSIString("|R=|n"))
    output += _format_skills_section(character)

    # Disciplines Section (if any)
    disciplines_output = _format_disciplines_section(character)
    if disciplines_output:
        output += ANSIString("|w Disciplines |n").center(78, ANSIString("|R=|n"))
        output += disciplines_output

    # Humanity Section
    humanity_output = _format_humanity_section(character)
    if humanity_output:
        output += ANSIString("|w Humanity |n").center(78, ANSIString("|R=|n"))
        output += humanity_output

    # Advantages Section (Backgrounds, Merits, Flaws)
    advantages_output = _format_advantages_section(character)
    if advantages_output:
        output += ANSIString("|w Advantages |n").center(78, ANSIString("|R=|n"))
        output += advantages_output

    # Status Section (if any)
    status_output = _format_status_section(character)
    if status_output:
        output += ANSIString("|w Status |n").center(78, ANSIString("|R=|n"))
        output += status_output

    # Boons Section (if any)
    boons_output = _format_boons_section(character)
    if boons_output:
        output += ANSIString("|w Boons |n").center(78, ANSIString("|R=|n"))
        output += boons_output

    # Coterie Section (if any)
    coterie_output = _format_coterie_section(character)
    if coterie_output:
        output += ANSIString("|w Coterie |n").center(78, ANSIString("|R=|n"))
        output += coterie_output

    # Experience Section
    output += ANSIString("|w Experience Points |n").center(78, ANSIString("|R=|n"))
    output += _format_experience_section(character)

    # Bottom border in dark red
    output += "\n" + "|R" + "=" * 78 + "|n"

    return output


def _format_bio_section(character):
    """Format bio section with two-column space-padded layout."""
    bio_record = character.bio
    bio = []

    def bio_text(field):
        return getattr(bio_record, field, "") if bio_record else ""

    # Build bio items
    bio_data = {
        'full_name': bio_text('full_name'),
        'birthdate': '',
        'concept': bio_text('concept'),
        'splat': 'Vampire',  # V5 is vampire-focused
        'ambition': bio_text('ambition'),
        'sire': bio_text('sire'),
        'desire': bio_text('desire'),
        'predator': character.predator_type or '',
        'clan': character.clan or '',
        'generation': str(character.generation),
    }

    for field in BIO_FIELDS:
        val = bio_data.get(field, '')
        bio.append(format(key=field.replace('_', ' '), val=val, width=38, just="ljust"))

    # Display in two columns
    output = ""
    count = 0
    for i in range(len(bio)):
        if count % 2 == 0:
            output += "\n "
        else:
            output += " "
        count += 1
        output += bio[i]

    return output


def _format_vitals_section(character):
    """Hunger, Blood Potency, Humanity and the derived Health/Willpower tracks."""
    return (
        f"\n\n Hunger: {character.hunger}  Blood Potency: {character.blood_potency}"
        f"  Humanity: {character.humanity}"
        f"  Health: {character.current_health}/{character.health_max}"
        f"  Willpower: {character.current_willpower}/{character.willpower_max}"
    )


def _format_attributes_section(character):
    """Format attributes in three columns with dot leaders."""
    physical = [format(name, character.get_trait(name)) for name in ("Strength", "Dexterity", "Stamina")]
    mental = [format(name, character.get_trait(name)) for name in ("Intelligence", "Wits", "Resolve")]
    social = [format(name, character.get_trait(name)) for name in ("Charisma", "Manipulation", "Composure")]

    # Format output
    output = "\n" + "Physical".center(26) + "Mental".center(26) + "Social".center(26) + "\n"
    for i in range(3):
        output += " " + physical[i] + "  " + mental[i] + "  " + social[i] + "\n"

    return output


def _format_skills_section(character):
    """Format skills in three columns with dot leaders, showing ALL skills."""
    physical = [format(skill.replace('_', ' '), character.get_trait(skill)) for skill in PHYSICAL_SKILLS]
    mental = [format(skill.replace('_', ' '), character.get_trait(skill)) for skill in MENTAL_SKILLS]
    social = [format(skill.replace('_', ' '), character.get_trait(skill)) for skill in SOCIAL_SKILLS]

    # Pad lists to same length
    max_len = max(len(physical), len(mental), len(social))
    while len(physical) < max_len:
        physical.append(" " * 24)
    while len(mental) < max_len:
        mental.append(" " * 24)
    while len(social) < max_len:
        social.append(" " * 24)

    # Format output
    output = "\n"
    for i in range(max_len):
        output += " " + physical[i] + "  " + mental[i] + "  " + social[i] + "\n"

    return output


def _format_experience_section(character):
    """Format experience points section."""
    return (
        f"\n Earned XP: {character.xp_earned}"
        f"\n Spent XP: {character.xp_spent}"
        f"\n Current XP: {character.xp}\n"
    )


def _format_disciplines_section(character):
    """Format disciplines section (V5 powers)."""
    disciplines = character.discipline_levels

    if not disciplines:
        return None

    output = "\n"
    for disc, level in sorted(disciplines.items()):
        output += f" {disc}: {'●' * level} ({level})\n"

    return output


def _format_humanity_section(character):
    """Format humanity, touchstones, and convictions."""
    humanity = character.humanity
    stains = character.stains
    touchstones = character.touchstones
    convictions = character.convictions

    output = f"\n Humanity: {humanity}  Stains: {stains}\n"

    if convictions:
        output += "\n Convictions:\n"
        for conviction in convictions:
            output += f"  - {conviction}\n"

    if touchstones:
        output += "\n Touchstones:\n"
        for touchstone in touchstones:
            name = touchstone.get('name', touchstone) if isinstance(touchstone, Mapping) else touchstone
            output += f"  - {name}\n"

    return output if (convictions or touchstones or humanity != 7 or stains > 0) else None


def _format_advantages_section(character):
    """Format backgrounds, merits, and flaws."""
    advantages = character.advantages
    backgrounds = advantages['backgrounds']
    merits = advantages['merits']
    flaws = advantages['flaws']

    has_content = False
    output = "\n"

    if backgrounds and any(val > 0 for val in backgrounds.values()):
        output += " Backgrounds:\n"
        for bg, level in sorted(backgrounds.items()):
            if level > 0:
                output += f"  {bg.replace('_', ' ').title()}: {'●' * level} ({level})\n"
        has_content = True

    if merits:
        if has_content:
            output += "\n"
        output += " Merits:\n"
        for merit, dots in sorted(merits.items()):
            output += f"  - {merit} ({dots})\n"
        has_content = True

    if flaws:
        if has_content:
            output += "\n"
        output += " Flaws:\n"
        for flaw, dots in sorted(flaws.items()):
            output += f"  - {flaw} ({dots})\n"
        has_content = True

    return output if has_content else None


def _format_status_section(character):
    """Format status information."""
    from status.models import CharacterStatus

    try:
        char_status = CharacterStatus.objects.get(character=character)
        if char_status.total_status > 0 or char_status.position:
            output = f"\n Total Status: {char_status.total_status}\n"
            if char_status.position:
                output += f" Position: {char_status.position.name}\n"
            return output
    except CharacterStatus.DoesNotExist:
        pass

    return None


def _format_boons_section(character):
    """Format boons owed and owed by."""
    from boons.models import Boon

    try:
        boons_owed = Boon.objects.filter(debtor=character, status='active')
        boons_owing = Boon.objects.filter(creditor=character, status='active')

        if not boons_owed.exists() and not boons_owing.exists():
            return None

        output = "\n"
        if boons_owed.exists():
            output += f" Boons Owed: {boons_owed.count()}\n"
        if boons_owing.exists():
            output += f" Boons Owed To You: {boons_owing.count()}\n"

        return output
    except:
        return None


def _format_coterie_section(character):
    """Format coterie membership (there is no coterie store yet)."""
    return None


def format_short_sheet(character):
    """Compact one-line status display."""
    name = character.key
    clan = character.clan or "Unknown"
    generation = character.generation
    hunger = character.hunger

    hunger_color = get_hunger_color(hunger)
    hunger_dots = f"{hunger_color}{'●' * hunger}{SHADOW_GREY}{'○' * (5 - hunger)}{RESET}"

    health = f"{character.current_health}/{character.health_max}"
    willpower = f"{character.current_willpower}/{character.willpower_max}"

    return (
        f"{BONE_WHITE}{name}{RESET} "
        f"({DARK_RED}{clan}{RESET} Gen {generation}) "
        f"Hunger: {hunger_dots} "
        f"Health: {health} Willpower: {willpower}"
    )
