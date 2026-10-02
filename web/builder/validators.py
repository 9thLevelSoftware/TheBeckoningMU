"""
Validation utilities for the Web Builder.
"""


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
    duplicates = set(n for n in names if names.count(n) > 1 and n)
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
