"""
V5-aware condition checking for room triggers.

Conditions can check character state, room state, and game state
to determine if a trigger should fire.
"""

import logging
import random
from datetime import datetime
from typing import Any

from world.v5_data import CLANS

logger = logging.getLogger(__name__)

# The editor's room location types (editor.html "room-location-type").
LOCATION_TYPES = ["haven", "elysium", "rack", "hostile", "neutral", "mortal", "supernatural"]
# The editor's danger levels, in order; a condition compares their position.
DANGER_LEVELS = ["safe", "low", "moderate", "high", "deadly"]


# Condition type definitions for UI
CONDITION_TYPES = {
    "character_clan": {
        "label": "Character Clan",
        "description": "Check if character is of a specific clan",
        "parameters": {
            "clan": {
                "type": "select",
                "options": list(CLANS),
                "required": True,
            }
        },
    },
    "character_splat": {
        "label": "Character Type",
        "description": "Check what the character is (Character.splat): vampire, ghoul or mortal",
        "parameters": {
            "splat": {
                "type": "select",
                # Filled from typeclasses.characters.SPLATS by
                # list_condition_types(), so it offers exactly what
                # Character.splat can return.
                "options": [],
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
                "options": LOCATION_TYPES,
                "required": True,
            }
        },
    },
    "time_of_day": {
        "label": "Time of Day",
        "description": "Check current in-game time",
        "parameters": {"time": {"type": "select", "options": ["day", "night"], "required": True}},
    },
    "room_danger": {
        "label": "Danger Level",
        "description": "Check room's danger rating (0 safe, 1 low, 2 moderate, 3 high, 4 deadly)",
        "parameters": {
            "operator": {
                "type": "select",
                "options": ["eq", "lt", "lte", "gt", "gte"],
                "required": True,
            },
            "value": {"type": "number", "min": 0, "max": 4, "required": True},
        },
    },
    "probability": {
        "label": "Random Chance",
        "description": "Random chance for trigger to fire (percentage)",
        "parameters": {"chance": {"type": "number", "min": 1, "max": 100, "required": True}},
    },
}


def splat_values() -> tuple[str, ...]:
    """The values Character.splat can return (typeclasses.characters.SPLATS)."""
    from typeclasses.characters import SPLATS

    return tuple(SPLATS)


def list_condition_types() -> dict[str, Any]:
    """Return condition type definitions for UI rendering."""
    CONDITION_TYPES["character_splat"]["parameters"]["splat"]["options"] = list(splat_values())
    return CONDITION_TYPES


def check_condition(condition_type: str, parameters: dict[str, Any], character=None, room=None) -> bool:
    """
    Check if a condition is met.

    Args:
        condition_type: The type of condition to check
        parameters: Condition-specific parameters
        character: The character to check (may be None for timed triggers)
        room: The room where trigger is firing

    Returns:
        True if condition is met, False otherwise. A condition that can't be
        evaluated (bad parameters, an error) is logged and counts as not met.
    """
    try:
        if condition_type == "character_clan":
            return _check_character_clan(character, parameters.get("clan"))

        elif condition_type == "character_splat":
            return _check_character_splat(character, parameters.get("splat"))

        elif condition_type == "character_hunger":
            return _check_character_hunger(character, parameters.get("operator"), parameters.get("value"))

        elif condition_type == "room_type":
            return _check_room_type(room, parameters.get("location_type"))

        elif condition_type == "time_of_day":
            return _check_time_of_day(parameters.get("time"))

        elif condition_type == "room_danger":
            return _check_room_danger(room, parameters.get("operator"), parameters.get("value"))

        elif condition_type == "probability":
            return _check_probability(parameters.get("chance", 100))

        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return False

    except Exception as e:
        logger.exception(f"Error checking condition {condition_type}: {e}")
        return False


def _norm(value) -> str:
    """Compare names ignoring case and '-', '_' or space ("thin_blood" == "Thin-Blood")."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _bad_parameter(condition_type, name, value) -> bool:
    logger.warning("Condition %s has an invalid %s: %r", condition_type, name, value)
    return False


def _check_character_clan(character, clan: str) -> bool:
    """Check the character's clan (Character.clan accessor)."""
    if not clan:
        return _bad_parameter("character_clan", "clan", clan)
    if not character:
        return False
    char_clan = getattr(character, "clan", None)
    return bool(char_clan) and _norm(char_clan) == _norm(clan)


def _check_character_splat(character, splat: str) -> bool:
    """Check the character's splat (Character.splat: vampire, ghoul or mortal)."""
    if not isinstance(splat, str) or splat.lower() not in splat_values():
        return _bad_parameter("character_splat", "splat", splat)
    if not character:
        return False
    actual = getattr(character, "splat", None)
    if actual is None:
        logger.warning("Condition character_splat: %s has no splat", character)
        return False
    return actual == splat.lower()


def _check_character_hunger(character, operator: str, value) -> bool:
    """Check the character's Hunger (Character.hunger accessor)."""
    number = _as_number(value)
    if operator not in _OPERATORS or number is None:
        return _bad_parameter("character_hunger", "operator/value", (operator, value))
    if not character:
        return False
    hunger_value = getattr(character, "hunger", None)
    if hunger_value is None:
        return False
    return _compare(hunger_value, operator, number)


def _check_room_type(room, location_type: str) -> bool:
    """Check the room's V5 location type."""
    if not location_type:
        return _bad_parameter("room_type", "location_type", location_type)
    if not room:
        return False
    room_type = room.attributes.get("location_type", default=None)
    return bool(room_type) and _norm(room_type) == _norm(location_type)


def _check_time_of_day(time: str) -> bool:
    """Check current time of day."""
    if time not in ("day", "night"):
        return _bad_parameter("time_of_day", "time", time)
    hour = datetime.now().hour
    is_night = hour < 6 or hour >= 18
    return is_night if time == "night" else not is_night


def danger_rank(level) -> int | None:
    """The editor's danger level as 0 (safe) .. 4 (deadly); None if unknown."""
    if isinstance(level, bool):
        return None
    if isinstance(level, str) and level.lower() in DANGER_LEVELS:
        return DANGER_LEVELS.index(level.lower())
    number = _as_number(level)
    return None if number is None else int(number)


def _check_room_danger(room, operator: str, value) -> bool:
    """Check the room's danger level against a 0-4 rank."""
    number = _as_number(value)
    if operator not in _OPERATORS or number is None:
        return _bad_parameter("room_danger", "operator/value", (operator, value))
    if not room:
        return False
    stored = room.attributes.get("danger_level", default="safe")
    rank = danger_rank(stored)
    if rank is None:
        logger.warning("Room %s has an unknown danger_level %r", room, stored)
        return False
    return _compare(rank, operator, number)


def _check_probability(chance) -> bool:
    """Random chance check."""
    number = _as_number(chance)
    if number is None:
        return _bad_parameter("probability", "chance", chance)
    return random.randint(1, 100) <= number


_OPERATORS = ("eq", "lt", "lte", "gt", "gte")


def _as_number(value):
    """A number, or a numeric string (the editor's inputs send text); else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def _compare(actual, operator: str, expected) -> bool:
    """Compare values with operator."""
    if operator == "eq":
        return actual == expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    return False
