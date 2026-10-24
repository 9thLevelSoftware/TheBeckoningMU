"""Owner-approved chronicle room policy; no inferred Haven automation."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from world.v5_data import HUNTING_GROUNDS

CHRONICLE_TIMEZONE = ZoneInfo("America/New_York")
HAVEN_ACTIONS = {
    "intrusion": "Review access, intruders, defenses and the security rating.",
    "space": "Review the proposed use of space and the size rating.",
    "comfort": "Review living conditions and the luxury rating.",
    "occult": "Review the claimed threat, ritual evidence and the warding rating.",
    "concealment": "Review who knows the location and the hidden-location flag.",
}


def chronicle_time(at_time=None):
    value = timezone.now() if at_time is None else at_time
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValueError("Chronicle time must include a timezone.")
    return value.astimezone(CHRONICLE_TIMEZONE)


def is_day(at_time=None):
    return 6 <= chronicle_time(at_time).hour < 18


def _attribute(room, name, default=None):
    return room.attributes.get(name, default=default) if room is not None else default


def valid_restricted_characters(value):
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and 1 <= len(value) <= 100
        and all(type(item) is int and item > 0 for item in value)
        and len(set(value)) == len(value)
    )


def room_access(character, destination, at_time=None):
    """An additional entry gate; callers must still enforce existing locks."""
    if destination is None:
        return False, "This exit has no destination."
    policy = _attribute(destination, "day_night", "always") or "always"
    if policy == "always":
        return True, ""
    if policy in ("day_only", "night_only"):
        if is_day(at_time) == (policy == "day_only"):
            return True, ""
        hours = "06:00-18:00" if policy == "day_only" else "18:00-06:00"
        return False, f"Entry is available only {hours} America/New_York."
    if policy == "restricted":
        allowed = _attribute(destination, "restricted_characters")
        if not valid_restricted_characters(allowed):
            return False, "Restricted entry needs a reviewed character allowlist; contact staff."
        if getattr(character, "pk", None) in allowed:
            return True, ""
        return False, "Your character is not on this room's reviewed entry allowlist."
    return False, "This room's entry policy needs staff review."


def hunting_context(character, ground):
    """Apply the current room's contribution once to the selected ground."""
    if ground not in HUNTING_GROUNDS:
        raise ValueError("Unknown hunting ground.")
    room = getattr(character, "location", None)
    modifier = _attribute(room, "hunting_modifier", 0)
    warning = ""
    if type(modifier) is not int or not -5 <= modifier <= 5:
        modifier = 0
        warning = "Unrecognized room hunting modifier requires staff review; no room adjustment applied."
    base = HUNTING_GROUNDS[ground]["difficulty"]
    difficulty = max(1, base - modifier)
    return {
        "ground": ground,
        "room_id": getattr(room, "pk", None),
        "base_difficulty": base,
        "modifier": modifier,
        "difficulty": difficulty,
        "difficulty_adjustment": difficulty - base,
        "warning": warning,
    }


def haven_context(room, actor, action):
    """Facts for a named staff adjudication, with no invented bonus or outcome."""
    if action not in HAVEN_ACTIONS:
        raise ValueError("Haven actions: " + ", ".join(HAVEN_ACTIONS))
    if _attribute(room, "location_type") != "haven":
        raise ValueError("This room is not recorded as a Haven.")
    ratings, unresolved = {}, []
    for name in ("security", "size", "luxury", "warding"):
        value = _attribute(room, "haven_" + name, 0)
        if type(value) is not int or not 0 <= value <= 5:
            unresolved.append(name)
            value = None
        ratings[name] = value
    hidden = _attribute(room, "haven_location_hidden", False)
    if type(hidden) is not bool:
        unresolved.append("location_hidden")
        hidden = None
    return {
        "room_id": getattr(room, "pk", None),
        "actor_id": getattr(actor, "pk", None),
        "action": action,
        "status": "staff_adjudication_required",
        "guidance": HAVEN_ACTIONS[action],
        "ratings": ratings,
        "location_hidden": hidden,
        "unresolved": unresolved,
        "automatic_modifiers": [],
    }


def room_inspection(room, actor):
    """Staff-facing inventory, without changing or reconstructing legacy values."""

    def safe(value):
        return str(value).replace("|", "||")

    lines = [f"Room #{room.pk}: {safe(room.key)}", "Chronicle clock: America/New_York; day 06:00-18:00"]
    for key, default in (
        ("location_type", "neutral"),
        ("day_night", "always"),
        ("restricted_characters", []),
        ("danger_level", "safe"),
        ("territory_owner", ""),
        ("hunting_modifier", 0),
    ):
        lines.append(f"{key}: {safe(_attribute(room, key, default))}")
    lines.append("Positive hunting modifiers reduce difficulty once, minimum 1.")
    if _attribute(room, "location_type") == "haven":
        context = haven_context(room, actor, "intrusion")
        lines.append("Haven ratings are staff-adjudicated; no automatic bonus or outcome.")
        lines.extend(f"{name}: {value}" for name, value in context["ratings"].items())
        lines.append(f"location_hidden: {context['location_hidden']}")
        if context["unresolved"]:
            lines.append("Unresolved fields: " + ", ".join(context["unresolved"]))
        lines.extend(f"{action}: {guidance}" for action, guidance in HAVEN_ACTIONS.items())
    return "\n".join(lines)
