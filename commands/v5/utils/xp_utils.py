"""
XP System Utility Functions for V5

Handles experience point costs, spending, and tracking.
"""

from .trait_utils import get_trait_value, set_trait_value
from .clan_utils import get_clan, get_inclan_disciplines


def get_xp_cost_attribute(character, attribute_name):
    """
    Calculate XP cost to raise an attribute.

    Cost = New Rating × 5 XP

    Args:
        character: Character object
        attribute_name (str): Attribute name

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    current = get_trait_value(character, attribute_name, category='attributes')
    new_rating = current + 1

    if new_rating > 5:
        return (None, None)  # Cannot exceed 5

    cost = new_rating * 5
    return (cost, new_rating)


def get_xp_cost_skill(character, skill_name):
    """
    Calculate XP cost to raise a skill.

    Cost = New Rating × 3 XP

    Args:
        character: Character object
        skill_name (str): Skill name

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    current = get_trait_value(character, skill_name, category='skills')
    new_rating = current + 1

    if new_rating > 5:
        return (None, None)  # Cannot exceed 5

    cost = new_rating * 3
    return (cost, new_rating)


def get_xp_cost_specialty(character, skill_name):
    """
    Calculate XP cost for a specialty.

    Cost = 3 XP (flat)

    Args:
        character: Character object
        skill_name (str): Skill to add specialty to

    Returns:
        int: Cost (3 XP or None if invalid)
    """
    # Check if skill is at least 1
    skill_value = get_trait_value(character, skill_name, category='skills')
    if skill_value < 1:
        return None

    # Check if already has specialty
    specialties = character.db.stats.get('specialties', {})
    if skill_name in specialties:
        return None  # Already has specialty

    return 3


def get_xp_cost_discipline(character, discipline_name):
    """
    Calculate XP cost to raise a discipline.

    Cost:
    - In-clan: New Rating × 5 XP
    - Out-of-clan: New Rating × 7 XP

    Args:
        character: Character object
        discipline_name (str): Discipline name

    Returns:
        tuple: (cost: int, new_rating: int, is_in_clan: bool)
    """
    # Get current level
    disciplines = character.db.stats.get('disciplines', {})
    current = disciplines.get(discipline_name, {}).get('level', 0)
    new_rating = current + 1

    if new_rating > 5:
        return (None, None, None)  # Cannot exceed 5

    # Check if in-clan
    inclan_disciplines = get_inclan_disciplines(character)
    is_in_clan = discipline_name.lower() in [d.lower() for d in inclan_disciplines]

    # Calculate cost
    if is_in_clan:
        cost = new_rating * 5
    else:
        cost = new_rating * 7

    return (cost, new_rating, is_in_clan)


def get_xp_cost_background(character, background_name):
    """
    Calculate XP cost to raise a background.

    Cost = 3 XP per dot

    Args:
        character: Character object
        background_name (str): Background name

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    advantages = character.db.advantages if hasattr(character.db, 'advantages') else {}
    backgrounds = advantages.get('backgrounds', {})

    current = backgrounds.get(background_name, 0)
    new_rating = current + 1

    if new_rating > 5:
        return (None, None)  # Cannot exceed 5

    cost = 3  # Flat 3 XP per dot
    return (cost, new_rating)


def get_xp_cost_merit(character, merit_name):
    """
    Calculate XP cost to raise a merit.

    Cost = 3 XP per dot

    Args:
        character: Character object
        merit_name (str): Merit name

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    advantages = character.db.advantages if hasattr(character.db, 'advantages') else {}
    merits = advantages.get('merits', {})

    current = merits.get(merit_name, 0)
    new_rating = current + 1

    if new_rating > 5:
        return (None, None)  # Cannot exceed 5

    cost = 3  # Flat 3 XP per dot
    return (cost, new_rating)


def get_xp_cost_humanity(character):
    """
    Calculate XP cost to raise Humanity.

    Cost = New Rating × 10 XP

    Args:
        character: Character object

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    vamp = character.db.vampire if hasattr(character.db, 'vampire') else {}
    current = vamp.get('humanity', 7)
    new_rating = current + 1

    if new_rating > 10:
        return (None, None)  # Cannot exceed 10

    cost = new_rating * 10
    return (cost, new_rating)


def get_xp_cost_willpower(character):
    """
    Calculate XP cost to raise permanent Willpower.

    Cost = 8 XP (flat)

    Args:
        character: Character object

    Returns:
        tuple: (cost: int, new_rating: int)
    """
    pools = character.db.pools if hasattr(character.db, 'pools') else {}
    current = pools.get('willpower', 0)
    new_rating = current + 1

    if new_rating > 10:
        return (None, None)  # Cannot exceed 10

    cost = 8  # Flat 8 XP
    return (cost, new_rating)


def get_current_xp(character):
    """
    Get character's current unspent XP.

    Args:
        character: Character object

    Returns:
        int: Current XP
    """
    exp = character.db.experience if hasattr(character.db, 'experience') else {}
    return exp.get('current', 0)


def get_total_earned_xp(character):
    """
    Get character's total earned XP (lifetime).

    Args:
        character: Character object

    Returns:
        int: Total earned XP
    """
    exp = character.db.experience if hasattr(character.db, 'experience') else {}
    return exp.get('total_earned', 0)


def get_total_spent_xp(character):
    """
    Get character's total spent XP.

    Args:
        character: Character object

    Returns:
        int: Total spent XP
    """
    exp = character.db.experience if hasattr(character.db, 'experience') else {}
    return exp.get('total_spent', 0)


def award_xp(character, amount, reason="", awarded_by=None):
    """
    Award XP to a character.

    Args:
        character: Character object
        amount (int): XP amount to award
        reason (str): Reason for award
        awarded_by: Character/account awarding XP

    Returns:
        tuple: (success: bool, message: str)
    """
    if amount <= 0:
        return (False, "XP amount must be positive.")

    if not hasattr(character.db, 'experience'):
        character.db.experience = {
            'total_earned': 0,
            'total_spent': 0,
            'current': 0,
            'log': []
        }

    exp = character.db.experience

    # Update totals
    exp['current'] += amount
    exp['total_earned'] += amount

    # Log the award
    from datetime import datetime
    log_entry = {
        'type': 'award',
        'amount': amount,
        'reason': reason,
        'awarded_by': str(awarded_by) if awarded_by else 'System',
        'date': datetime.now().isoformat(),
        'balance': exp['current']
    }

    if 'log' not in exp:
        exp['log'] = []
    exp['log'].append(log_entry)

    character.db.experience = exp

    return (True, f"Awarded {amount} XP. Current XP: {exp['current']}")


def spend_xp_on_attribute(character, attribute_name, reason=""):
    """
    Spend XP to raise an attribute.

    Args:
        character: Character object
        attribute_name (str): Attribute to raise
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost, new_rating = get_xp_cost_attribute(character, attribute_name)

    if cost is None:
        return (False, f"Cannot raise {attribute_name} further (max 5).")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Raise attribute
    set_trait_value(character, attribute_name, new_rating, category='attributes')

    # Deduct XP
    _deduct_xp(character, cost, f"Raised {attribute_name} to {new_rating}" + (f" - {reason}" if reason else ""))

    # Update derived stats
    if hasattr(character, 'update_derived_stats'):
        character.update_derived_stats()

    return (True, f"Raised {attribute_name} to {new_rating} for {cost} XP.")


def spend_xp_on_skill(character, skill_name, reason=""):
    """
    Spend XP to raise a skill.

    Args:
        character: Character object
        skill_name (str): Skill to raise
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost, new_rating = get_xp_cost_skill(character, skill_name)

    if cost is None:
        return (False, f"Cannot raise {skill_name} further (max 5).")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Raise skill
    set_trait_value(character, skill_name, new_rating, category='skills')

    # Deduct XP
    _deduct_xp(character, cost, f"Raised {skill_name} to {new_rating}" + (f" - {reason}" if reason else ""))

    return (True, f"Raised {skill_name} to {new_rating} for {cost} XP.")


def spend_xp_on_specialty(character, skill_name, specialty_name, reason=""):
    """
    Spend XP to add a specialty.

    Args:
        character: Character object
        skill_name (str): Skill to add specialty to
        specialty_name (str): Name of specialty
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost = get_xp_cost_specialty(character, skill_name)

    if cost is None:
        return (False, f"Cannot add specialty to {skill_name}. Skill must be at least 1 and not already have a specialty.")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Add specialty
    if not hasattr(character.db, 'stats'):
        return (False, "Character stats not initialized.")

    if 'specialties' not in character.db.stats:
        character.db.stats['specialties'] = {}

    character.db.stats['specialties'][skill_name] = specialty_name

    # Deduct XP
    _deduct_xp(character, cost, f"Added specialty: {skill_name} ({specialty_name})" + (f" - {reason}" if reason else ""))

    return (True, f"Added specialty {specialty_name} to {skill_name} for {cost} XP.")


def spend_xp_on_discipline(character, discipline_name, reason=""):
    """
    Spend XP to raise a discipline.

    Args:
        character: Character object
        discipline_name (str): Discipline to raise
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost, new_rating, is_in_clan = get_xp_cost_discipline(character, discipline_name)

    if cost is None:
        return (False, f"Cannot raise {discipline_name} further (max 5).")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Raise discipline
    if not hasattr(character.db, 'stats'):
        return (False, "Character stats not initialized.")

    if 'disciplines' not in character.db.stats:
        character.db.stats['disciplines'] = {}

    if discipline_name not in character.db.stats['disciplines']:
        character.db.stats['disciplines'][discipline_name] = {'level': 0, 'powers': []}

    character.db.stats['disciplines'][discipline_name]['level'] = new_rating

    # Deduct XP
    clan_str = " (in-clan)" if is_in_clan else " (out-of-clan)"
    _deduct_xp(character, cost, f"Raised {discipline_name} to {new_rating}{clan_str}" + (f" - {reason}" if reason else ""))

    return (True, f"Raised {discipline_name} to {new_rating} for {cost} XP{clan_str}.")


def spend_xp_on_humanity(character, reason=""):
    """
    Spend XP to raise Humanity.

    Args:
        character: Character object
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost, new_rating = get_xp_cost_humanity(character)

    if cost is None:
        return (False, "Cannot raise Humanity further (max 10).")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Raise Humanity
    if not hasattr(character.db, 'vampire'):
        return (False, "Character vampire data not initialized.")

    character.db.vampire['humanity'] = new_rating

    # Deduct XP
    _deduct_xp(character, cost, f"Raised Humanity to {new_rating}" + (f" - {reason}" if reason else ""))

    return (True, f"Raised Humanity to {new_rating} for {cost} XP.")


def spend_xp_on_willpower(character, reason=""):
    """
    Spend XP to raise permanent Willpower.

    Args:
        character: Character object
        reason (str): Reason for purchase

    Returns:
        tuple: (success: bool, message: str)
    """
    cost, new_rating = get_xp_cost_willpower(character)

    if cost is None:
        return (False, "Cannot raise Willpower further (max 10).")

    current_xp = get_current_xp(character)
    if current_xp < cost:
        return (False, f"Insufficient XP. Need {cost}, have {current_xp}.")

    # Raise Willpower
    if not hasattr(character.db, 'pools'):
        return (False, "Character pools not initialized.")

    character.db.pools['willpower'] = new_rating
    character.db.pools['current_willpower'] = new_rating  # Also restore to full

    # Deduct XP
    _deduct_xp(character, cost, f"Raised permanent Willpower to {new_rating}" + (f" - {reason}" if reason else ""))

    return (True, f"Raised permanent Willpower to {new_rating} for {cost} XP.")


def _deduct_xp(character, amount, reason):
    """
    Internal function to deduct XP and log it.

    Args:
        character: Character object
        amount (int): XP to deduct
        reason (str): Reason for expenditure
    """
    exp = character.db.experience

    exp['current'] -= amount
    exp['total_spent'] += amount

    # Log the expenditure
    from datetime import datetime
    log_entry = {
        'type': 'spend',
        'amount': -amount,
        'reason': reason,
        'date': datetime.now().isoformat(),
        'balance': exp['current']
    }

    if 'log' not in exp:
        exp['log'] = []
    exp['log'].append(log_entry)

    character.db.experience = exp


def get_xp_log(character, limit=10):
    """
    Get character's XP log (recent entries).

    Args:
        character: Character object
        limit (int): Number of recent entries to return

    Returns:
        list: XP log entries
    """
    exp = character.db.experience if hasattr(character.db, 'experience') else {}
    log = exp.get('log', [])

    return log[-limit:] if limit else log


def format_xp_summary(character):
    """
    Format XP summary for display.

    Args:
        character: Character object

    Returns:
        str: Formatted XP summary
    """
    current = get_current_xp(character)
    earned = get_total_earned_xp(character)
    spent = get_total_spent_xp(character)

    lines = []
    lines.append(f"Current XP: {current}")
    lines.append(f"Total Earned: {earned}")
    lines.append(f"Total Spent: {spent}")

    return "\n".join(lines)
