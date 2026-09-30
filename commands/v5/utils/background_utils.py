"""
Background Utility Functions

Helper functions for Background mechanics and benefits.
"""

from world.v5_data import BACKGROUNDS
import random


def get_background_level(character, background_name):
    """Get character's level in a background.

    Args:
        character: The character object
        background_name: Name of the background

    Returns:
        int: Level (0-5)
    """
    if not hasattr(character.db, "backgrounds"):
        character.db.backgrounds = {}

    return character.db.backgrounds.get(background_name.lower(), 0)


def get_all_backgrounds(character):
    """Get all backgrounds for a character.

    Args:
        character: The character object

    Returns:
        dict: {"background_name": level}
    """
    if not hasattr(character.db, "backgrounds"):
        character.db.backgrounds = {}

    return character.db.backgrounds.copy()


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
    if not hasattr(character.db, "background_uses"):
        character.db.background_uses = {}

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
        # Check if used this week
        if background_name.lower() in character.db.background_uses:
            return 0
        return 1
    else:
        max_uses = level

    # Get current uses
    used = character.db.background_uses.get(background_name.lower(), 0)
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

    # Consume a use (if limited)
    if uses_remaining > 0:
        if not hasattr(character.db, "background_uses"):
            character.db.background_uses = {}

        used = character.db.background_uses.get(background_name.lower(), 0)
        character.db.background_uses[background_name.lower()] = used + 1

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


def use_herd_to_feed(character):
    """Use Herd background to reduce Hunger without hunting.

    Args:
        character: The character object

    Returns:
        dict: {"success": bool, "message": str, "hunger_reduced": int}
    """
    level = get_background_level(character, "Herd")

    if level == 0:
        return {
            "success": False,
            "message": "You don't have the Herd background",
            "hunger_reduced": 0
        }

    # Check if already used this week
    uses = get_background_uses_remaining(character, "Herd")
    if uses == 0:
        return {
            "success": False,
            "message": "You've already fed from your Herd this week",
            "hunger_reduced": 0
        }

    # Ensure vampire attribute exists
    if not hasattr(character.db, 'vampire'):
        character.db.vampire = {"hunger": 1}

    # Reduce Hunger by level (max to 1)
    current_hunger = character.db.vampire.get("hunger", 1)
    reduction = min(level, current_hunger - 1)

    if reduction > 0:
        character.db.vampire["hunger"] = current_hunger - reduction

        # Mark as used
        if not hasattr(character.db, "background_uses"):
            character.db.background_uses = {}
        character.db.background_uses["herd"] = 1

        return {
            "success": True,
            "message": f"You feed safely from your Herd. Hunger reduced by {reduction}.",
            "hunger_reduced": reduction
        }
    else:
        return {
            "success": False,
            "message": "Your Hunger is already at minimum (1)",
            "hunger_reduced": 0
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
    if not hasattr(character.db, "background_uses"):
        character.db.background_uses = {}

    used = character.db.background_uses.get("resources", 0)
    character.db.background_uses["resources"] = used + 1

    return {
        "success": True,
        "message": f"You acquire: {item_description} (Rating {item_rating})"
    }


def reset_background_uses(character):
    """Reset background uses (called at start of session).

    Args:
        character: The character object
    """
    character.db.background_uses = {}
