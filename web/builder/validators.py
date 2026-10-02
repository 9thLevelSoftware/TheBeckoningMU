"""
Validation utilities for the Web Builder.
"""

import re
from collections.abc import Mapping, Sequence


def validate_project(map_data):
    """
    Validate a project's map data before building.

    Returns:
        tuple: (is_valid, errors, warnings)
    """
    errors = []
    warnings = []

    rooms = map_data.get("rooms", {})
    exits = map_data.get("exits", {})

    if not rooms:
        errors.append("Project has no rooms.")
        return False, errors, warnings

    # ------------------------------------------------------------------
    # Shape validation: rooms
    # ------------------------------------------------------------------
    valid_room_ids = set()
    for room_id, room in rooms.items():
        if not isinstance(room, dict):
            errors.append(f"Room '{room_id}' has invalid data format")
            continue
        if not room.get("name"):
            errors.append(f"Room '{room_id}' is missing a name")
        # Position validation (rooms should have grid coordinates)
        if "x" not in room and "gridX" not in room:
            warnings.append(
                f"Room '{room.get('name', room_id)}' has no grid position"
            )
        valid_room_ids.add(room_id)

    # ------------------------------------------------------------------
    # Shape validation: exits
    # ------------------------------------------------------------------
    valid_exits = {}  # exit_id -> exit_data for exits that pass shape check
    for exit_id, exit_data in exits.items():
        if not isinstance(exit_data, dict):
            errors.append(f"Exit '{exit_id}' has invalid data format")
            continue
        if not exit_data.get("source"):
            errors.append(f"Exit '{exit_id}' is missing source room")
            continue
        if not exit_data.get("target"):
            errors.append(f"Exit '{exit_id}' is missing target room")
            continue
        if not exit_data.get("name"):
            warnings.append(f"Exit '{exit_id}' has no name")
        valid_exits[exit_id] = exit_data

    # ------------------------------------------------------------------
    # Connectivity validation (only exits that passed shape check)
    # ------------------------------------------------------------------
    room_connections = {rid: {"in": [], "out": []} for rid in valid_room_ids}

    for exit_id, exit_data in valid_exits.items():
        source = exit_data.get("source")
        target = exit_data.get("target")

        if source not in rooms:
            errors.append(f"Exit '{exit_id}' has invalid source room '{source}'")
        elif source in valid_room_ids:
            room_connections[source]["out"].append(exit_id)

        if target not in rooms:
            errors.append(f"Exit '{exit_id}' has invalid target room '{target}'")
        elif target in valid_room_ids:
            room_connections[target]["in"].append(exit_id)

    # Warn about isolated rooms
    for room_id, connections in room_connections.items():
        room_name = rooms[room_id].get("name", room_id)
        if not connections["in"] and not connections["out"]:
            warnings.append(f"Room '{room_name}' has no exits (isolated)")
        elif not connections["in"] and len(rooms) > 1:
            warnings.append(f"Room '{room_name}' has no incoming exits (unreachable)")

    # Warn about empty descriptions
    for room_id in valid_room_ids:
        room = rooms[room_id]
        if not room.get("description"):
            warnings.append(f"Room '{room.get('name', room_id)}' has no description")

    # Check for duplicate room names
    names = [
        rooms[rid].get("name", "")
        for rid in valid_room_ids
    ]
    duplicates = {n for n in names if names.count(n) > 1 and n}
    for name in duplicates:
        warnings.append(f"Multiple rooms named '{name}'")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


# Directions a build may hang off its live connection room.
CONNECTION_DIRECTIONS = ("n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d")


def is_live_room(obj):
    """A Room (or Room subclass) that isn't part of a sandbox build."""
    return obj.is_typeclass("typeclasses.rooms.Room", exact=False) and not (
        obj.tags.has("sandbox")
    )


def live_rooms():
    """All live rooms a build may connect to, by typeclass family (not key)."""
    from typeclasses.rooms import Room

    return [room for room in Room.objects.all_family() if is_live_room(room)]


def validate_connection(connection_room_id, connection_direction):
    """
    Validate the live attachment point a project is submitted with.

    The connection is part of what the reviewer approves, so it must name an
    existing live (non-sandbox) Room and a known direction.

    Returns:
        tuple: (errors, room_id, direction) where room_id is an int and
        direction is lower-cased when valid.
    """
    from evennia.objects.models import ObjectDB

    errors = []
    try:
        room_id = int(connection_room_id)
    except (TypeError, ValueError):
        room_id = None
    if room_id is None or isinstance(connection_room_id, bool):
        errors.append("connection_room_id is required and must be a room dbref")
        room_id = None

    direction = connection_direction.lower() if isinstance(connection_direction, str) else ""
    if direction not in CONNECTION_DIRECTIONS:
        errors.append(
            "connection_direction is required and must be one of: "
            + ", ".join(CONNECTION_DIRECTIONS)
        )

    if room_id is not None:
        room = ObjectDB.objects.filter(pk=room_id).first()
        if room is None or not room.is_typeclass("typeclasses.rooms.Room", exact=False):
            errors.append(f"Connection room #{room_id} is not a room")
        elif not is_live_room(room):
            errors.append(f"Connection room #{room_id} is a sandbox room, not a live one")

    return errors, room_id, direction


# ----------------------------------------------------------------------
# Strict build validation (submit and sandbox build)
# ----------------------------------------------------------------------
# validate_project above gives the editor soft feedback while a draft is
# being drawn. validate_build_map is the hard gate: a project can't be
# submitted, and its approved snapshot can't be built, unless it passes.

OBJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_ROOMS = 200
MAX_EXITS = 800
MAX_NAME_LENGTH = 80
MAX_DESC_LENGTH = 10000
MAX_ALIASES = 10
MAX_ALIAS_LENGTH = 32

DAY_NIGHT_VALUES = ("always", "day_only", "night_only", "restricted")
HAVEN_RATINGS = ("security", "size", "luxury", "warding")
HUNTING_MODIFIER_RANGE = (-5, 5)
HAVEN_RATING_RANGE = (0, 5)

# Exit locks a builder may set: traverse/view, built from all(), perm(X)
# and tag(x[, category]) with and/or/not and parentheses.
LOCK_ACCESS_TYPES = ("traverse", "view")
_LOCK_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<lp>\()|(?P<rp>\))"
    r"|(?P<op>and|or)\b|(?P<neg>not)\b"
    r"|(?P<func>all\(\s*\)"
    r"|perm\(\s*[A-Za-z][A-Za-z_]{0,31}\s*\)"
    r"|tag\(\s*[A-Za-z0-9_-]{1,32}\s*(?:,\s*[A-Za-z0-9_-]{1,32}\s*)?\))"
    r")"
)


def _lock_tokens(expr):
    tokens, pos = [], 0
    expr = expr.rstrip()
    while pos < len(expr):
        match = _LOCK_TOKEN_RE.match(expr, pos)
        if not match or match.end() == pos:
            return None
        tokens.append(match.lastgroup)
        pos = match.end()
    return tokens


def _lock_expr_ok(tokens):
    """expr := term (op term)* ; term := not term | ( expr ) | func"""
    pos = 0

    def term():
        nonlocal pos
        if pos >= len(tokens):
            return False
        kind = tokens[pos]
        if kind == "neg":
            pos += 1
            return term()
        if kind == "func":
            pos += 1
            return True
        if kind == "lp":
            pos += 1
            if not expr() or pos >= len(tokens) or tokens[pos] != "rp":
                return False
            pos += 1
            return True
        return False

    def expr():
        nonlocal pos
        if not term():
            return False
        while pos < len(tokens) and tokens[pos] == "op":
            pos += 1
            if not term():
                return False
        return True

    return expr() and pos == len(tokens)


def validate_lock_string(lockstring):
    """Return an error message, or None if the exit lock string is allowed."""
    if not isinstance(lockstring, str):
        return "locks must be text"
    if len(lockstring) > 200:
        return "locks must be at most 200 characters"
    seen = set()
    for part in lockstring.split(";"):
        part = part.strip()
        if not part:
            continue
        access_type, sep, expr = part.partition(":")
        access_type = access_type.strip()
        if not sep or access_type not in LOCK_ACCESS_TYPES:
            return f"lock '{part}': only {' and '.join(LOCK_ACCESS_TYPES)} locks are allowed"
        if access_type in seen:
            return f"lock type '{access_type}' is given twice"
        seen.add(access_type)
        tokens = _lock_tokens(expr.strip())
        if not tokens or not _lock_expr_ok(tokens):
            return (
                f"lock '{part}': use all(), perm(<Perm>) or tag(<tag>[, <category>]) "
                "joined with and/or/not"
            )
    return None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_list(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _text(value, field, errors, label, required=False, max_length=MAX_DESC_LENGTH):
    if value is None or value == "":
        if required:
            errors.append(f"{label} is missing a {field}")
        return
    if not isinstance(value, str) or (required and not value.strip()):
        errors.append(f"{label}: {field} must be text")
    elif len(value) > max_length:
        errors.append(f"{label}: {field} is longer than {max_length} characters")


def _validate_v5(v5, label, errors):
    from .v5_conditions import DANGER_LEVELS, LOCATION_TYPES

    if v5 is None:
        return
    if not isinstance(v5, Mapping):
        errors.append(f"{label}: v5 settings must be an object")
        return
    enums = (
        ("location_type", LOCATION_TYPES),
        ("day_night", DAY_NIGHT_VALUES),
        ("danger_level", DANGER_LEVELS),
    )
    for field, allowed in enums:
        value = v5.get(field)
        if value not in (None, "") and value not in allowed:
            errors.append(f"{label}: {field} must be one of {', '.join(allowed)}")
    modifier = v5.get("hunting_modifier")
    low, high = HUNTING_MODIFIER_RANGE
    if modifier is not None and (not _is_int(modifier) or not low <= modifier <= high):
        errors.append(f"{label}: hunting_modifier must be a whole number from {low} to {high}")
    _text(v5.get("territory_owner"), "territory_owner", errors, label, max_length=MAX_NAME_LENGTH)
    haven = v5.get("haven_ratings")
    if haven is not None:
        if not isinstance(haven, Mapping):
            errors.append(f"{label}: haven_ratings must be an object")
            return
        low, high = HAVEN_RATING_RANGE
        for field in HAVEN_RATINGS:
            value = haven.get(field, 0)
            if not _is_int(value) or not low <= value <= high:
                errors.append(f"{label}: haven {field} must be a whole number from {low} to {high}")
        if not isinstance(haven.get("location_hidden", False), bool):
            errors.append(f"{label}: haven location_hidden must be true or false")


def _trigger_label(trigger):
    if isinstance(trigger, Mapping) and isinstance(trigger.get("id"), str):
        return f"'{trigger['id']}'"
    return "(no id)"


def _validate_triggers(triggers, label, errors):
    from .trigger_engine import validate_trigger

    if triggers is None:
        return
    if not _is_list(triggers):
        errors.append(f"{label}: triggers must be a list")
        return
    seen = set()
    for trigger in triggers:
        ok, error = validate_trigger(trigger)
        if not ok:
            errors.append(f"{label}: trigger {_trigger_label(trigger)}: {error}")
            continue
        trigger_id = trigger.get("id")
        if trigger_id in seen:
            errors.append(f"{label}: trigger id '{trigger_id}' is used twice")
        seen.add(trigger_id)


def validate_build_map(map_data):
    """
    Validate a map for submission and for the sandbox build.

    Returns a list of error strings (empty when the map can be built).
    """
    errors = []
    if not isinstance(map_data, Mapping):
        return ["Map data must be an object"]
    rooms = map_data.get("rooms")
    exits = map_data.get("exits") or {}
    if not isinstance(rooms, Mapping) or not rooms:
        return ["Project has no rooms."]
    if not isinstance(exits, Mapping):
        return ["Exits must be an object"]
    if len(rooms) > MAX_ROOMS:
        errors.append(f"A project may have at most {MAX_ROOMS} rooms")
    if len(exits) > MAX_EXITS:
        errors.append(f"A project may have at most {MAX_EXITS} exits")

    entries = []
    for room_id, room in rooms.items():
        if not isinstance(room_id, str) or not OBJECT_ID_RE.match(room_id):
            errors.append(f"Room id '{room_id}' must be 1-32 letters, digits, '_' or '-'")
            continue
        label = f"Room '{room_id}'"
        if not isinstance(room, Mapping):
            errors.append(f"{label} has invalid data format")
            continue
        _text(room.get("name"), "name", errors, label, required=True, max_length=MAX_NAME_LENGTH)
        _text(room.get("description"), "description", errors, label)
        is_entry = room.get("is_entry", False)
        if not isinstance(is_entry, bool):
            errors.append(f"{label}: is_entry must be true or false")
        elif is_entry:
            entries.append(room_id)
        _validate_v5(room.get("v5"), label, errors)
        _validate_triggers(room.get("triggers"), label, errors)
    if len(entries) > 1:
        errors.append("Only one room may be the entry room")

    for exit_id, exit_data in exits.items():
        if not isinstance(exit_id, str) or not OBJECT_ID_RE.match(exit_id):
            errors.append(f"Exit id '{exit_id}' must be 1-32 letters, digits, '_' or '-'")
            continue
        label = f"Exit '{exit_id}'"
        if not isinstance(exit_data, Mapping):
            errors.append(f"{label} has invalid data format")
            continue
        for end in ("source", "target"):
            end_id = exit_data.get(end)
            if not isinstance(end_id, str) or end_id not in rooms:
                errors.append(f"{label}: {end} must be a room in this project")
        _text(exit_data.get("name"), "name", errors, label, required=True, max_length=MAX_NAME_LENGTH)
        _text(exit_data.get("description"), "description", errors, label)
        aliases = exit_data.get("aliases") or []
        if (
            not _is_list(aliases)
            or len(aliases) > MAX_ALIASES
            or not all(isinstance(a, str) and 0 < len(a) <= MAX_ALIAS_LENGTH for a in aliases)
        ):
            errors.append(
                f"{label}: aliases must be a list of at most {MAX_ALIASES} names "
                f"of 1-{MAX_ALIAS_LENGTH} characters"
            )
        locks = exit_data.get("locks")
        if locks:
            error = validate_lock_string(locks)
            if error:
                errors.append(f"{label}: {error}")
    return errors


def entry_room_key(map_data):
    """The web id of the room players enter from the live world.

    A room flagged `is_entry: true` if there is one; otherwise the first room
    in the map (the editor's first-drawn room).
    """
    rooms = map_data["rooms"]
    for room_id, room in rooms.items():
        if room.get("is_entry") is True:
            return room_id
    return next(iter(rooms))
