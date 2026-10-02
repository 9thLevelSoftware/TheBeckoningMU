"""
Whitelisted trigger actions for the trigger system.

Actions take only primitive arguments and do no file, network or code
execution. `set_attribute` is the one action that writes game state, so it is
narrowed: on a room it may write a plain, identifier-shaped Attribute (never
`triggers` itself), and on a character it may only write a namespaced
`trigger_flag_*` Attribute holding a primitive value. It can never reach a
character's sheet (`vampire`, `stats`, `experience`, `hunger`, ...).
"""

import logging
import re

logger = logging.getLogger(__name__)

CHARACTER_ATTR_RE = re.compile(r"^trigger_flag_[a-z0-9_]{1,32}$")
ROOM_ATTR_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# Room Attributes a trigger may not overwrite: the trigger list itself (a
# self-modifying trigger) and the room's description.
ROOM_ATTR_DENY = frozenset({"triggers", "desc"})
MAX_VALUE_LENGTH = 200


def _is_primitive(value):
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= MAX_VALUE_LENGTH


def validate_set_attribute(target, attr_name, value):
    """Return an error message, or None if this set_attribute is allowed."""
    if target not in ("room", "character"):
        return "set_attribute target must be 'room' or 'character'"
    if not isinstance(attr_name, str):
        return "set_attribute needs an attr_name"
    if target == "character":
        if not CHARACTER_ATTR_RE.match(attr_name):
            return "set_attribute on a character may only set trigger_flag_<name> (lower-case letters, digits, '_')"
    elif not ROOM_ATTR_RE.match(attr_name) or attr_name in ROOM_ATTR_DENY:
        return f"set_attribute may not set '{attr_name}' on a room"
    if not _is_primitive(value):
        return f"set_attribute value must be text (at most {MAX_VALUE_LENGTH} characters), a number, true/false or null"
    return None


def send_message(obj, message):
    """Send a message to one object (typically the triggering character)."""
    if obj and hasattr(obj, "msg") and callable(obj.msg):
        try:
            obj.msg(message)
        except Exception as e:
            logger.error(f"Error sending message to {obj}: {e}")


def emit_message(location, message, exclude=None):
    """Emit a message to everything in a location."""
    if exclude is None:
        exclude = []

    if location and hasattr(location, "msg_contents") and callable(location.msg_contents):
        try:
            location.msg_contents(message, exclude=exclude)
        except Exception as e:
            logger.error(f"Error emitting message in {location}: {e}")


def set_attribute(obj, attr_name, value, target="room"):
    """
    Set an allowed Attribute on a room or character.

    Raises ValueError for a write the rules don't allow, so the engine counts
    the trigger as failed rather than silently doing something else.
    """
    error = validate_set_attribute(target, attr_name, value)
    if error:
        raise ValueError(error)
    obj.attributes.add(attr_name, value)


def list_actions():
    """Return the available action names for UI display."""
    return list(ACTION_REGISTRY.keys())


# Registry mapping action names to their handler functions
ACTION_REGISTRY = {
    "send_message": send_message,
    "emit_message": emit_message,
    "set_attribute": set_attribute,
}
