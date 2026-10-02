"""
V5-aware condition checking for room triggers.

Conditions can check character state, room state, and game state
to determine if a trigger should fire.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


# Condition type definitions for UI
CONDITION_TYPES = {
    "character_clan": {
        "label": "Character Clan",
        "description": "Check if character is of a specific clan",
        "parameters": {
            "clan": {
                "type": "select",
                "options": [
                    "brujah",
                    "gangrel",
                    "malkavian",
                    "nosferatu",
                    "toreador",
                    "tremere",
                    "ventrue",
                    "caitiff",
                    "thin_blood",
                ],
                "required": True,
            }
        },
    },
    "character_splat": {
        "label": "Character Type",
        "description": "Check if character is vampire, ghoul, etc.",
        "parameters": {
            "splat": {
                "type": "select",
                "options": ["vampire", "ghoul", "mortal", "hunter"],
                "required": True,
            }
        },
    },
    "character_hunger": {
        "label": "Hunger Level",
        "description": "Check character's hunger level (vampires only)",
        "parameters": {
            "operator": {
                "type": "select",
                "options": ["eq", "lt", "lte", "gt", "gte"],
                "required": True,
            },
            "value": {"type": "number", "min": 0, "max": 5, "required": True},
        },
    },
    "room_type": {
        "label": "Room Type",
        "description": "Check the room's V5 location type",
        "parameters": {
            "location_type": {
                "type": "select",
                "options": [
                    "elysium",
                    "haven",
                    "rack",
                    "neutral",
                    "dangerous",
                    "hunting_ground",
                    "mystical",
                    "street",
                    "business",
                ],
                "required": True,
            }
        },
    },
    "time_of_day": {
        "label": "Time of Day",
        "description": "Check current in-game time",
        "parameters": {
            "time": {"type": "select", "options": ["day", "night"], "required": True}
        },
    },
    "room_danger": {
        "label": "Danger Level",
        "description": "Check room's danger rating",
        "parameters": {
            "operator": {
                "type": "select",
                "options": ["eq", "lt", "lte", "gt", "gte"],
                "required": True,
            },
            "value": {"type": "number", "min": 0, "max": 5, "required": True},
        },
    },
    "probability": {
        "label": "Random Chance",
        "description": "Random chance for trigger to fire (percentage)",
        "parameters": {
            "chance": {"type": "number", "min": 1, "max": 100, "required": True}
        },
    },
}


def list_condition_types() -> Dict[str, Any]:
    """Return condition type definitions for UI rendering."""
    return CONDITION_TYPES


def check_condition(
    condition_type: str, parameters: Dict[str, Any], character=None, room=None
) -> bool:
    """
    Check if a condition is met.

    Args:
        condition_type: The type of condition to check
        parameters: Condition-specific parameters
        character: The character to check (may be None for timed triggers)
        room: The room where trigger is firing

    Returns:
        True if condition is met, False otherwise
    """
    try:
        if condition_type == "character_clan":
            return _check_character_clan(character, parameters.get("clan"))

        elif condition_type == "character_splat":
            return _check_character_splat(character, parameters.get("splat"))

        elif condition_type == "character_hunger":
            return _check_character_hunger(
                character, parameters.get("operator"), parameters.get("value")
            )

        elif condition_type == "room_type":
            return _check_room_type(room, parameters.get("location_type"))

        elif condition_type == "time_of_day":
            return _check_time_of_day(parameters.get("time"))

        elif condition_type == "room_danger":
            return _check_room_danger(
                room, parameters.get("operator"), parameters.get("value")
            )

        elif condition_type == "probability":
            return _check_probability(parameters.get("chance", 100))

        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return False

    except Exception as e:
        logger.exception(f"Error checking condition {condition_type}: {e}")
        return False


def _check_character_clan(character, clan: str) -> bool:
    """Check if character is of specified clan."""
    if not character or not clan:
        return False

    char_clan = getattr(character, "clan", None)
    return bool(char_clan) and char_clan.lower() == clan.lower()


def _check_character_splat(character, splat: str) -> bool:
    """Check if character is of specified splat type."""
    if not character or not splat:
        return False

    try:
        from traits.models import CharacterBio

        bio = CharacterBio.objects.get(character_id=character.id)
        return bio.splat.lower() == splat.lower()
    except Exception:
        return False


def _check_character_hunger(character, operator: str, value: int) -> bool:
    """Check character's hunger level."""
    if not character:
        return False

    hunger_value = getattr(character, "hunger", None)
    if hunger_value is None:
        return False
    return _compare(hunger_value, operator, value)


def _check_room_type(room, location_type: str) -> bool:
    """Check room's V5 location type."""
    if not room or not location_type:
        return False

    room_type = getattr(room.db, "location_type", None)
    return room_type and room_type.lower() == location_type.lower()


def _check_time_of_day(time: str) -> bool:
    """Check current time of day."""
    # Simple implementation - could be enhanced with in-game time system
    hour = datetime.now().hour
    is_night = hour < 6 or hour >= 18

    if time == "night":
        return is_night
    elif time == "day":
        return not is_night
    return False


def _check_room_danger(room, operator: str, value: int) -> bool:
    """Check room's danger level."""
    if not room:
        return False

    danger = getattr(room.db, "danger_level", 0)
    return _compare(danger, operator, value)


def _check_probability(chance: int) -> bool:
    """Random chance check."""
    import random

    return random.randint(1, 100) <= chance


def _compare(actual, operator: str, expected) -> bool:
    """Compare values with operator."""
    if operator == "eq":
        return actual == expected
    elif operator == "lt":
        return actual < expected
    elif operator == "lte":
        return actual <= expected
    elif operator == "gt":
        return actual > expected
    elif operator == "gte":
        return actual >= expected
    return False
