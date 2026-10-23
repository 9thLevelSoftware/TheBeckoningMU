"""
XP System Utility Functions for V5

Costs come from world.v5_data.XP_COSTS (QR p.1). Every purchase goes through
Character.spend_xp, which validates the trait and writes the trait, the XP
total and the log together; the spend_xp_on_* helpers here are thin
wrappers that return (success, message).
"""

from collections.abc import Mapping
from datetime import datetime

from world.v5_data import UnknownTrait, WrongCategory, xp_cost

from .clan_utils import unavailable_clan


def _cost(character, name, category, note=None):
    """(cost, new) for a purchase, or (None, None) if it is past its cap.

    Raises UnknownTrait/WrongCategory for a name that isn't a trait of that kind.
    """
    try:
        plan = character.xp_spend_cost(name, category, note)
    except (UnknownTrait, WrongCategory):
        raise
    except ValueError:
        return (None, None)
    return (plan["cost"], plan["new"])


def get_xp_cost_attribute(character, attribute_name):
    """XP to raise an attribute: new rating x 5. Returns (cost, new_rating); (None, None) at the cap."""
    return _cost(character, attribute_name, "attribute")


def get_xp_cost_skill(character, skill_name):
    """XP to raise a skill: new rating x 3. Returns (cost, new_rating); (None, None) at the cap."""
    return _cost(character, skill_name, "skill")


def get_xp_cost_specialty(character, skill_name, specialty_name=None):
    """XP for a specialty: 3. None if the skill is unrated or already has that specialty."""
    try:
        plan = character.xp_spend_cost(skill_name, "specialty", specialty_name or "?")
    except (UnknownTrait, WrongCategory):
        raise
    except ValueError:
        return None
    return plan["cost"]


def unavailable_clan_message(character):
    """A refusal message if the character's stored clan is not offered, else None.

    Discipline costs depend on the clan, so they can't be priced until staff
    move the character to an available clan.
    """
    clan = unavailable_clan(character)
    if clan:
        return (f"Your clan ({clan}) is not available in this game, so discipline costs can't be "
                "worked out. Ask staff to update your character.")
    return None


def get_xp_cost_discipline(character, discipline_name):
    """
    XP to raise a discipline (QR p.1): new rating x 5 in-clan, x 6 for
    Caitiff (any discipline), x 7 otherwise.

    Returns:
        tuple: (cost, new_rating, is_in_clan); (None, None, None) at the cap
    """
    current = character.get_trait(discipline_name, 'disciplines')
    new_rating = current + 1
    if new_rating > 5:
        return (None, None, None)
    from world.v5_data import resolve_trait

    kind = character.discipline_cost_kind(resolve_trait(discipline_name, 'disciplines').name)
    return (xp_cost(kind, new_rating), new_rating, kind == "clan_discipline")


def get_current_xp(character):
    """Unspent XP."""
    return character.xp


def get_total_earned_xp(character):
    """Total XP earned."""
    return character.xp_earned


def get_total_spent_xp(character):
    """Total XP spent."""
    return character.xp_spent


def award_xp(character, amount, reason="", awarded_by=None):
    """
    Award XP to a character.

    Returns:
        tuple: (success: bool, message: str)
    """
    if amount <= 0:
        return (False, "XP amount must be positive.")

    if not isinstance(character.db.experience, Mapping):
        character.db.experience = {'total_earned': 0, 'total_spent': 0, 'log': []}

    exp = character.db.experience
    exp['total_earned'] = exp.get('total_earned', 0) + amount
    log_entry = {
        'type': 'award',
        'amount': amount,
        'reason': reason,
        'awarded_by': str(awarded_by) if awarded_by else 'System',
        'date': datetime.now().isoformat(),
        'balance': character.xp
    }
    if 'log' not in exp:
        exp['log'] = []
    exp['log'].append(log_entry)
    character.db.experience = exp

    return (True, f"Awarded {amount} XP. Current XP: {character.xp}")


def spend_xp(character, name, category, note=None, reason=""):
    """
    Spend XP through Character.spend_xp.

    Returns:
        tuple: (success: bool, message: str); nothing changes on failure.
    """
    try:
        result = character.spend_xp(name, category, note=note, reason=reason)
    except (UnknownTrait, WrongCategory, ValueError) as err:
        return (False, f"{str(err).rstrip('.')}.")
    return (True, f"{result['label']} for {result['cost']} XP.")


def spend_xp_on_attribute(character, attribute_name, reason=""):
    """Spend XP to raise an attribute. Returns (success, message)."""
    return spend_xp(character, attribute_name, "attribute", reason=reason)


def spend_xp_on_skill(character, skill_name, reason=""):
    """Spend XP to raise a skill. Returns (success, message)."""
    return spend_xp(character, skill_name, "skill", reason=reason)


def spend_xp_on_specialty(character, skill_name, specialty_name, reason=""):
    """Spend XP to add a specialty. Returns (success, message)."""
    return spend_xp(character, skill_name, "specialty", note=specialty_name, reason=reason)


def spend_xp_on_discipline(character, discipline_name, reason=""):
    """Spend XP to raise a discipline. Returns (success, message)."""
    return spend_xp(character, discipline_name, "discipline", reason=reason)


def get_xp_log(character, limit=10):
    """The character's most recent XP log entries."""
    exp = character.db.experience if isinstance(character.db.experience, Mapping) else {}
    log = exp.get('log', [])
    return log[-limit:] if limit else log


def format_xp_summary(character):
    """XP summary for display."""
    return "\n".join([
        f"Current XP: {get_current_xp(character)}",
        f"Total Earned: {get_total_earned_xp(character)}",
        f"Total Spent: {get_total_spent_xp(character)}",
    ])
