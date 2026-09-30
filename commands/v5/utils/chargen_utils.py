"""
Character Generation Utility Functions for V5

Handles character creation validation, allocation tracking, and approval workflows.
"""

from . import trait_utils, clan_utils, blood_utils


def start_chargen(character):
    """
    Initialize character generation process.

    Args:
        character: Character object

    Returns:
        dict: Chargen status
    """
    # Reset chargen tracking
    character.db.chargen = {
        "completed": False,
        "current_step": "concept",
        "approved": False,
        "approval_job_id": None,
        "steps_completed": []
    }

    return {
        "success": True,
        "message": "Character creation started. Begin with your character concept.",
        "next_step": "concept"
    }


def get_chargen_step(character):
    """
    Get current character generation step.

    Args:
        character: Character object

    Returns:
        str: Current step name
    """
    if not character.db.chargen:
        return None

    return character.db.chargen.get("current_step", "concept")


def set_chargen_step(character, step_name):
    """
    Set current character generation step.

    Args:
        character: Character object
        step_name (str): Step name

    Returns:
        str: New step name
    """
    if not character.db.chargen:
        start_chargen(character)

    character.db.chargen["current_step"] = step_name

    # Track completed steps
    steps_completed = character.db.chargen.get("steps_completed", [])
    if step_name not in steps_completed:
        steps_completed.append(step_name)
        character.db.chargen["steps_completed"] = steps_completed

    return step_name


def mark_chargen_complete(character):
    """
    Mark character generation as complete (ready for approval).

    Args:
        character: Character object

    Returns:
        tuple: (bool, str) - (success, message)
    """
    # Validate all requirements met
    valid, errors = validate_complete_character(character)

    if not valid:
        error_msg = "Cannot complete character generation. Issues:\n"
        error_msg += "\n".join([f"  - {err}" for err in errors])
        return (False, error_msg)

    # Mark as complete
    character.db.chargen["completed"] = True
    character.db.chargen["current_step"] = "approval"

    return (True, "Character generation complete! Awaiting staff approval.")


def is_chargen_complete(character):
    """
    Check if character generation is complete.

    Args:
        character: Character object

    Returns:
        bool: True if chargen complete
    """
    return character.db.chargen.get("completed", False)


def is_character_approved(character):
    """
    Check if character has been approved by staff.

    Args:
        character: Character object

    Returns:
        bool: True if approved
    """
    return character.db.chargen.get("approved", False)


def approve_character(character):
    """
    Approve a character (staff only).

    Args:
        character: Character object

    Returns:
        bool: True if successful
    """
    character.db.chargen["approved"] = True
    character.db.stats["approved"] = True

    return True


def validate_complete_character(character):
    """
    Validate that character meets all requirements for completion.

    Returns:
        tuple: (bool, list) - (is_valid, list_of_errors)
    """
    errors = []

    # Check clan selected
    if not clan_utils.get_clan(character):
        errors.append("No clan selected")

    # Check attributes allocated (7/5/3)
    attr_valid, attr_msg = trait_utils.validate_chargen_attributes(character)
    if not attr_valid:
        errors.append(attr_msg)

    # Check skills allocated (13/9/5)
    skill_valid, skill_msg = trait_utils.validate_chargen_skills(character)
    if not skill_valid:
        errors.append(skill_msg)

    # Check disciplines allocated (typically 2-3 dots at creation)
    total_disciplines = trait_utils.get_total_discipline_dots(character)
    if total_disciplines < 2:
        errors.append(f"Must have at least 2 discipline dots (currently {total_disciplines})")
    elif total_disciplines > 3:
        errors.append(f"Cannot have more than 3 discipline dots at creation (currently {total_disciplines})")

    # Check predator type selected
    vampire = character.db.vampire
    if not vampire:
        errors.append("Character must be a vampire")
    else:
        predator = vampire.get("predator_type", None)
        if not predator:
            errors.append("No predator type selected")

    # Check specialties (should have at least 1)
    specialties = character.db.stats.get("specialties", {})
    if len(specialties) < 1:
        errors.append("Must have at least 1 skill specialty")

    return (len(errors) == 0, errors)


def get_chargen_progress(character):
    """
    Get character generation progress summary.

    Args:
        character: Character object

    Returns:
        dict: Progress information
    """
    # Check each requirement
    clan = clan_utils.get_clan(character)
    vampire = character.db.vampire
    predator = vampire.get("predator_type", None) if vampire else None

    # Attribute allocation
    physical_attr = trait_utils.get_total_attribute_dots(character, 'physical')
    social_attr = trait_utils.get_total_attribute_dots(character, 'social')
    mental_attr = trait_utils.get_total_attribute_dots(character, 'mental')
    attr_totals = sorted([physical_attr, social_attr, mental_attr], reverse=True)
    attr_complete = (attr_totals == [7, 5, 3])

    # Skill allocation
    physical_skill = trait_utils.get_total_skill_dots(character, 'physical')
    social_skill = trait_utils.get_total_skill_dots(character, 'social')
    mental_skill = trait_utils.get_total_skill_dots(character, 'mental')
    skill_totals = sorted([physical_skill, social_skill, mental_skill], reverse=True)
    skill_complete = (skill_totals == [13, 9, 5])

    # Disciplines
    total_disciplines = trait_utils.get_total_discipline_dots(character)
    disciplines_complete = (2 <= total_disciplines <= 3)

    # Specialties
    specialties = character.db.stats.get("specialties", {})
    specialties_complete = (len(specialties) >= 1)

    return {
        "clan": clan,
        "clan_complete": clan is not None,
        "predator": predator,
        "predator_complete": predator is not None,
        "attributes": attr_totals,
        "attributes_complete": attr_complete,
        "skills": skill_totals,
        "skills_complete": skill_complete,
        "disciplines": total_disciplines,
        "disciplines_complete": disciplines_complete,
        "specialties": len(specialties),
        "specialties_complete": specialties_complete,
        "overall_complete": all([
            clan is not None,
            predator is not None,
            attr_complete,
            skill_complete,
            disciplines_complete,
            specialties_complete
        ])
    }


def format_chargen_progress(character):
    """
    Create formatted progress display for character generation.

    Args:
        character: Character object

    Returns:
        str: Formatted progress display
    """
    progress = get_chargen_progress(character)

    lines = []
    lines.append("|c" + "="*60 + "|n")
    lines.append("|c" + " "*15 + "CHARACTER CREATION PROGRESS" + " "*15 + "|n")
    lines.append("|c" + "="*60 + "|n")
    lines.append("")

    # Clan
    clan_status = "|g✓|n" if progress["clan_complete"] else "|r✗|n"
    clan_name = progress["clan"] or "|xNot Set|n"
    lines.append(f"{clan_status} |wClan:|n {clan_name}")

    # Predator Type
    predator_status = "|g✓|n" if progress["predator_complete"] else "|r✗|n"
    predator_name = progress["predator"] or "|xNot Set|n"
    lines.append(f"{predator_status} |wPredator Type:|n {predator_name}")

    # Attributes
    attr_status = "|g✓|n" if progress["attributes_complete"] else "|r✗|n"
    attr_text = f"{progress['attributes'][0]}/{progress['attributes'][1]}/{progress['attributes'][2]} (need 7/5/3)"
    lines.append(f"{attr_status} |wAttributes:|n {attr_text}")

    # Skills
    skill_status = "|g✓|n" if progress["skills_complete"] else "|r✗|n"
    skill_text = f"{progress['skills'][0]}/{progress['skills'][1]}/{progress['skills'][2]} (need 13/9/5)"
    lines.append(f"{skill_status} |wSkills:|n {skill_text}")

    # Disciplines
    disc_status = "|g✓|n" if progress["disciplines_complete"] else "|r✗|n"
    disc_text = f"{progress['disciplines']} dots (need 2-3)"
    lines.append(f"{disc_status} |wDisciplines:|n {disc_text}")

    # Specialties
    spec_status = "|g✓|n" if progress["specialties_complete"] else "|r✗|n"
    spec_text = f"{progress['specialties']} (need at least 1)"
    lines.append(f"{spec_status} |wSpecialties:|n {spec_text}")

    lines.append("")

    # Overall status
    if progress["overall_complete"]:
        lines.append("|gAll requirements met! Use '+chargen/finalize' to complete.|n")
    else:
        lines.append("|yStill in progress. Complete all requirements to finalize.|n")

    lines.append("|c" + "="*60 + "|n")

    return "\n".join(lines)


def allocate_starting_dots(character, category, dots):
    """
    Helper for allocating starting character creation dots.

    Args:
        character: Character object
        category (str): 'attribute' or 'skill'
        dots (dict): Dict of {trait_name: value}

    Returns:
        tuple: (bool, str) - (success, message)
    """
    errors = []

    for trait_name, value in dots.items():
        try:
            success = trait_utils.set_trait_value(character, trait_name, value, category)
            if not success:
                errors.append(f"Failed to set {trait_name}")
        except ValueError as e:
            errors.append(str(e))

    if errors:
        return (False, "\n".join(errors))

    return (True, "Dots allocated successfully")


def reset_chargen(character):
    """
    Reset character back to blank slate for chargen.

    WARNING: This deletes all character data!

    Args:
        character: Character object

    Returns:
        bool: True if successful
    """
    # Call at_object_creation to reset all data structures
    character.at_object_creation()

    return True


def get_recommended_next_step(character):
    """
    Get recommended next step based on current progress.

    Args:
        character: Character object

    Returns:
        str: Recommendation message
    """
    progress = get_chargen_progress(character)

    if not progress["clan_complete"]:
        return "Select your clan with '+chargen/clan <name>'"

    if not progress["predator_complete"]:
        return "Select your predator type with '+chargen/predator <type>'"

    if not progress["attributes_complete"]:
        return "Allocate your attributes (7/5/3 distribution)"

    if not progress["skills_complete"]:
        return "Allocate your skills (13/9/5 distribution)"

    if not progress["disciplines_complete"]:
        return "Select your starting disciplines (2-3 dots)"

    if not progress["specialties_complete"]:
        return "Select at least one skill specialty"

    if progress["overall_complete"]:
        return "All requirements met! Use '+chargen/finalize' to complete."

    return "Continue character creation"
