"""
Background Utility Functions

Helper functions for Background mechanics and benefits.
"""

from world.v5_data import BACKGROUNDS, TRAIT_REGISTRY, UnknownTrait
import random


WEEK = 7 * 24 * 3600


def weekly_key(background_name):
    """The background_uses key holding a weekly background's last-use time."""
    return f"{str(background_name).lower()}_week"


def _background_uses(character):
    """The per-session background use counters, created if missing."""
    if character.db.background_uses is None:
        character.db.background_uses = {}
    return character.db.background_uses


def get_background_level(character, background_name):
    """Get character's level in a background.

    Args:
        character: The character object
        background_name: Name of the background

    Returns:
        int: Level (0-5)
    """
    try:
        return character.get_trait(background_name, "backgrounds")
    except UnknownTrait:
        return 0


def get_all_backgrounds(character):
    """Get all backgrounds for a character.

    Args:
        character: The character object

    Returns:
        dict: {"background_key": level}; an instanced background (Allies,
        Contacts, ...) rates as the total of its instances
    """
    return {
        key: character.get_trait(key)
        for key in character.advantages["backgrounds"]
        if key in TRAIT_REGISTRY
    }


def get_background_benefits(character, background_name):
    """Get the mechanical benefits of a background.

    Args:
        character: The character object
        background_name: Name of the background

    Returns:
        dict: {"level": int, "benefit": str, "uses_remaining": int}
    """
    level = get_background_level(character, background_name)

    if level == 0:
        return {
            "level": 0,
            "benefit": "None",
            "uses_remaining": 0
        }

    bg_data = BACKGROUNDS.get(background_name, {})
    benefit = bg_data.get("benefit", "Unknown")

    # Replace [dots] with actual level
    benefit = benefit.replace("[dots]", str(level))

    # Get uses remaining
    uses_remaining = get_background_uses_remaining(character, background_name)

    return {
        "level": level,
        "benefit": benefit,
        "uses_remaining": uses_remaining,
        "description": bg_data.get("description", "")
    }


def get_background_uses_remaining(character, background_name):
    """Get remaining uses of a background this session.

    Args:
        character: The character object
        background_name: Name of the background

    Returns:
        int: Remaining uses (-1 for unlimited)
    """
    uses = _background_uses(character)

    level = get_background_level(character, background_name)
    bg_data = BACKGROUNDS.get(background_name, {})
    uses_per_session = bg_data.get("uses_per_session", "unlimited")

    if uses_per_session == "unlimited" or uses_per_session == "passive":
        return -1

    # Calculate max uses
    if uses_per_session == "dots":
        max_uses = level
    elif uses_per_session == "dots * 2":
        max_uses = level * 2
    elif uses_per_session == "1 per week":
        # Weekly backgrounds (Herd) keep the time of their last use under
        # their own key, which a session reset doesn't clear.
        import time

        last = uses.get(weekly_key(background_name))
        if isinstance(last, (int, float)) and not isinstance(last, bool):
            return 0 if time.time() - last < WEEK else 1
        return 1
    else:
        max_uses = level

    # Get current uses
    used = uses.get(background_name.lower(), 0)
    return max(0, max_uses - used)


def use_background(character, background_name, task_description):
    """Use a background for a task.

    Args:
        character: The character object
        background_name: Name of the background
        task_description: Description of what they're doing

    Returns:
        dict: {"success": bool, "message": str, "bonus": int}
    """
    level = get_background_level(character, background_name)

    if level == 0:
        return {
            "success": False,
            "message": f"You don't have the {background_name} background",
            "bonus": 0
        }

    uses_remaining = get_background_uses_remaining(character, background_name)

    if uses_remaining == 0:
        return {
            "success": False,
            "message": f"You've used all your {background_name} uses this session",
            "bonus": 0
        }

    # Consume a use (if limited); a weekly background records the time
    if uses_remaining > 0:
        import time

        uses = _background_uses(character)
        if BACKGROUNDS.get(background_name, {}).get("uses_per_session") == "1 per week":
            uses[weekly_key(background_name)] = time.time()
        else:
            uses[background_name.lower()] = uses.get(background_name.lower(), 0) + 1

    # Calculate bonus based on background type
    bonus = calculate_background_bonus(character, background_name, task_description)

    return {
        "success": True,
        "message": f"Using {background_name} (Level {level}) for: {task_description}",
        "bonus": bonus,
        "uses_remaining": get_background_uses_remaining(character, background_name)
    }


def calculate_background_bonus(character, background_name, task_description):
    """Calculate the dice bonus from using a background.

    Args:
        character: The character object
        background_name: Name of the background
        task_description: What they're doing

    Returns:
        int: Dice bonus
    """
    level = get_background_level(character, background_name)

    # Most backgrounds give +level bonus
    return level


HERD_WEEK = WEEK


def use_herd_to_feed(character, now=None):
    """Feed on your Herd: slake up to your Herd dots of Hunger, once a week, with no
    hunting roll (core p.189; BACKGROUNDS["Herd"]).

    The Blood Potency rules still apply: only a kill takes Hunger below
    min_hunger_without_kill, and high Blood Potency slakes less per human
    (hunting_utils.slake). The week is counted from the last Herd feeding
    (stored as a timestamp in db.background_uses["herd_week"], shared with
    +background/use Herd and kept by a session reset).

    Returns:
        dict: {"success": bool, "message": str, "hunger_reduced": int}
    """
    import time

    from world.v5_data import BLOOD_POTENCY

    level = get_background_level(character, "Herd")
    if level == 0:
        return {"success": False, "message": "You don't have the Herd background", "hunger_reduced": 0}

    now = time.time() if now is None else now
    uses = _background_uses(character)
    last = uses.get(weekly_key("Herd"))
    if isinstance(last, (int, float)) and not isinstance(last, bool) and now - last < HERD_WEEK:
        days = max(1, int((HERD_WEEK - (now - last)) // 86400) + 1)
        return {
            "success": False,
            "message": f"You've already fed from your Herd this week (again in about {days} day(s)).",
            "hunger_reduced": 0,
        }

    row = BLOOD_POTENCY.get(character.blood_potency, BLOOD_POTENCY[0])
    floor = row["min_hunger_without_kill"]
    current = character.hunger
    reduction = max(0, min(level - row["human_slake_penalty"], current - floor))
    if reduction <= 0:
        return {
            "success": False,
            "message": f"Your Hunger is already as low as feeding without a kill can take it ({floor}).",
            "hunger_reduced": 0,
        }

    character.hunger = current - reduction
    uses[weekly_key("Herd")] = now
    return {
        "success": True,
        "message": f"You feed safely from your Herd. Hunger reduced by {reduction}.",
        "hunger_reduced": reduction,
    }


def use_resources_to_acquire(character, item_description, item_rating):
    """Use Resources background to acquire an item.

    Args:
        character: The character object
        item_description: What they're acquiring
        item_rating: Difficulty rating (1-5)

    Returns:
        dict: {"success": bool, "message": str}
    """
    level = get_background_level(character, "Resources")

    if level == 0:
        return {
            "success": False,
            "message": "You don't have the Resources background"
        }

    if item_rating > level:
        return {
            "success": False,
            "message": f"Item rating ({item_rating}) exceeds your Resources level ({level})"
        }

    # Check uses
    uses = get_background_uses_remaining(character, "Resources")
    if uses == 0:
        return {
            "success": False,
            "message": "You've used all your Resources this session"
        }

    # Consume use
    uses = _background_uses(character)
    uses["resources"] = uses.get("resources", 0) + 1

    return {
        "success": True,
        "message": f"You acquire: {item_description} (Rating {item_rating})"
    }


def reset_background_uses(character):
    """Reset the per-session background uses (start of session); weekly timers are kept.

    Args:
        character: The character object
    """
    uses = _background_uses(character)
    character.db.background_uses = {key: value for key, value in uses.items() if key.endswith("_week")}
