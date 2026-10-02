"""
Trigger execution engine for room triggers.

Triggers are stored on rooms as `room.db.triggers`. Evennia hands stored
lists and dicts back as `_SaverList` / `_SaverDict`, which are not `list` /
`dict` subclasses, so this module never type-checks against `list`/`dict`:
it accepts any `Mapping` / non-string `Sequence` and copies the stored list
before iterating.

`validate_trigger` is the single rule set. The editor API runs it when a
trigger is saved, submission and the sandbox build run it over the whole
map, and `execute_trigger` runs it again before every action, so a stored
trigger that breaks the rules (say, a `set_attribute` aimed at a
character's `experience`) is refused at save and at run.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .trigger_actions import ACTION_REGISTRY, validate_set_attribute
from .v5_conditions import check_condition, list_condition_types

logger = logging.getLogger(__name__)


class TriggerError(Exception):
    """Exception raised for trigger execution errors."""


VALID_TRIGGER_TYPES = {"entry", "exit", "timed", "interaction"}
TRIGGER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_LENGTH = 2000
MIN_TIMED_INTERVAL = 10
MAX_TIMED_INTERVAL = 86400


def _is_sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def validate_trigger(trigger_data: Any) -> tuple[bool, str | None]:
    """
    Validate one trigger's structure and parameters.

    Returns:
        (is_valid, error_message); error_message is None when valid.
    """
    if not isinstance(trigger_data, Mapping):
        return False, "Trigger data must be a dictionary"

    required_fields = {"type", "action", "parameters"}
    missing_fields = required_fields - set(trigger_data.keys())
    if missing_fields:
        return False, f"Missing required fields: {', '.join(sorted(missing_fields))}"

    trigger_id = trigger_data.get("id")
    if trigger_id is not None and (not isinstance(trigger_id, str) or not TRIGGER_ID_RE.match(trigger_id)):
        return False, "Trigger id must be 1-64 letters, digits, '_' or '-'"

    trigger_type = trigger_data.get("type")
    if trigger_type not in VALID_TRIGGER_TYPES:
        return (
            False,
            f"Invalid trigger type '{trigger_type}'. Must be one of: {', '.join(sorted(VALID_TRIGGER_TYPES))}",
        )

    action_name = trigger_data.get("action")
    if action_name not in ACTION_REGISTRY:
        return (
            False,
            f"Unknown action '{action_name}'. Available actions: {', '.join(ACTION_REGISTRY.keys())}",
        )

    parameters = trigger_data.get("parameters")
    if not isinstance(parameters, Mapping):
        return (
            False,
            f"Parameters must be a dictionary, got {type(parameters).__name__}",
        )

    enabled = trigger_data.get("enabled", True)
    if not isinstance(enabled, bool):
        return False, "Enabled field must be a boolean"

    if action_name in ("send_message", "emit_message"):
        message = parameters.get("message", "")
        if not isinstance(message, str) or len(message) > MAX_MESSAGE_LENGTH:
            return False, f"message must be text of at most {MAX_MESSAGE_LENGTH} characters"
    elif action_name == "set_attribute":
        error = validate_set_attribute(
            parameters.get("target", "room"), parameters.get("attr_name"), parameters.get("value")
        )
        if error:
            return False, error

    conditions = trigger_data.get("conditions", [])
    if conditions:
        if not _is_sequence(conditions):
            return False, "conditions must be a list"
        valid_conditions = list_condition_types()
        for condition in conditions:
            if not isinstance(condition, Mapping):
                return False, "each condition must be a dictionary"
            if "type" not in condition:
                return False, "condition missing 'type' field"
            if condition["type"] not in valid_conditions:
                return False, f"invalid condition type: {condition['type']}"
            if not isinstance(condition.get("parameters", {}), Mapping):
                return False, "condition parameters must be a dictionary"

    if trigger_type == "timed":
        interval = trigger_data.get("interval")
        if (
            not isinstance(interval, int)
            or isinstance(interval, bool)
            or not MIN_TIMED_INTERVAL <= interval <= MAX_TIMED_INTERVAL
        ):
            return (
                False,
                f"timed triggers must have an interval of {MIN_TIMED_INTERVAL}-{MAX_TIMED_INTERVAL} seconds",
            )
        if not trigger_id:
            return False, "timed triggers must have an id"

    return True, None


def stored_triggers(room) -> list:
    """The room's triggers as a plain list (empty if unset or malformed)."""
    triggers = room.attributes.get("triggers", default=None)
    if not triggers:
        return []
    if not _is_sequence(triggers):
        logger.warning("Room %s has invalid triggers data (not a list)", room)
        return []
    return list(triggers)


def _trigger_label(trigger_data):
    if isinstance(trigger_data, Mapping):
        return trigger_data.get("id", "unknown")
    return "?"


def execute_trigger(trigger_data, room, character, **context) -> bool:
    """
    Execute a single trigger.

    Returns:
        True if the trigger's action ran, False otherwise.
    """
    is_valid, error_message = validate_trigger(trigger_data)
    if not is_valid:
        logger.warning(
            "Skipping invalid trigger %s in %s: %s",
            _trigger_label(trigger_data),
            room,
            error_message,
        )
        return False

    if not trigger_data.get("enabled", True):
        logger.debug("Skipping disabled trigger: %s", _trigger_label(trigger_data))
        return False

    action_name = trigger_data["action"]
    parameters = trigger_data["parameters"]
    action_func = ACTION_REGISTRY[action_name]

    try:
        if action_name == "send_message":
            message = parameters.get("message", "")
            if not message or character is None:
                return False
            action_func(character, message)

        elif action_name == "emit_message":
            message = parameters.get("message", "")
            if not message:
                return False
            action_func(room, message, exclude=[character] if character else None)

        elif action_name == "set_attribute":
            target = parameters.get("target", "room")
            attr_name = parameters.get("attr_name")
            value = parameters.get("value")
            if target == "character":
                if character is None:
                    # A timed trigger has no character; never fall back to
                    # writing on the room instead.
                    return False
                action_func(character, attr_name, value, target="character")
            else:
                action_func(room, attr_name, value, target="room")

        else:  # pragma: no cover - validate_trigger rejects unknown actions
            return False

        return True

    except Exception:
        logger.exception("Error executing trigger %s in %s", _trigger_label(trigger_data), room)
        return False


def execute_triggers(room, trigger_type: str, character, trigger_id: str | None = None, **context) -> tuple[int, int]:
    """
    Execute all triggers of one type stored on a room.

    Args:
        room: The room where triggers fire.
        trigger_type: "entry", "exit", "timed" or "interaction".
        character: The character who caused the event (None for timed).
        trigger_id: Only run the trigger with this id (timed scripts).

    Returns:
        (executed_count, failed_count)
    """
    triggers = stored_triggers(room)
    if not triggers:
        return 0, 0

    executed_count = 0
    failed_count = 0

    for trigger_data in triggers:
        if not isinstance(trigger_data, Mapping):
            failed_count += 1
            continue
        if trigger_data.get("type") != trigger_type:
            continue
        if trigger_id and trigger_data.get("id") != trigger_id:
            continue

        conditions = trigger_data.get("conditions") or []
        if not _is_sequence(conditions):
            failed_count += 1
            continue
        conditions_met = True
        for condition in conditions:
            if not isinstance(condition, Mapping) or not check_condition(
                condition.get("type"),
                condition.get("parameters") or {},
                character=character,
                room=room,
            ):
                conditions_met = False
                break
        if not conditions_met:
            continue

        if execute_trigger(trigger_data, room, character, **context):
            executed_count += 1
        else:
            failed_count += 1

    if executed_count or failed_count:
        logger.info(
            "Executed %s %s triggers in %s (%s failed)",
            executed_count,
            trigger_type,
            room,
            failed_count,
        )

    return executed_count, failed_count
