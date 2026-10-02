"""
Promotion: make a built sandbox part of the live world.

`promote_unit(project_id, ...)` is one unit of work that runs wholly on the
reactor (KD-6), validate-then-mutate (KD-7):

1. Validate, with no mutations: the project is built and has an approval
   snapshot; any connection in the request matches the reviewed one
   (`approved_map_data`) exactly; the reviewed connection room still exists
   and is a live Room; every recorded room and exit still passes the
   cleanup checks (recorded id, `project_N` + `sandbox`, right typeclass, no
   account); and the direction is free at both ends (exit keys and aliases,
   short and long forms).
2. Mutate: remove `sandbox` and `project_N` from the recorded rooms and
   exits, create the two connecting exits last, sweep any recorded object
   that is still a sandbox object (none, normally; the same recorded-id rule
   as cleanup), and record the project as live with an empty
   `built_object_ids`.
3. On any error: delete the connecting exits it created, put the tags back,
   and re-raise. No DB rollback is relied on.
"""

import logging
from typing import Any

from django.utils import timezone
from evennia.utils.create import create_object

from web.main_thread import call_in_main_thread

from .sandbox_cleanup import delete_recorded, recorded_objects
from .validators import is_live_room

logger = logging.getLogger(__name__)

DIRECTION_NAMES = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
    "u": "up",
    "d": "down",
}
DIRECTION_OPPOSITES = {
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "ne": "sw",
    "sw": "ne",
    "nw": "se",
    "se": "nw",
    "u": "d",
    "d": "u",
}


class PromotionError(Exception):
    """Promotion was refused; nothing changed. Safe to show the builder."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _get_opposite_direction(direction: str) -> str | None:
    return DIRECTION_OPPOSITES.get(direction.lower())


def _exit_names(obj):
    return {obj.key.lower(), *(alias.lower() for alias in obj.aliases.all())}


def _direction_taken(room, direction):
    """Does `room` already have an exit called n/north (key or alias)?"""
    wanted = {direction, DIRECTION_NAMES[direction]}
    return any(obj.destination and _exit_names(obj) & wanted for obj in room.contents)


def _create_connection_exit(direction, location, destination):
    exit_obj = create_object(
        typeclass="typeclasses.exits.Exit",
        key=DIRECTION_NAMES[direction],
        aliases=[direction],
        location=location,
        destination=destination,
        home=location,
        tags=["web_builder"],
    )
    if exit_obj is None:
        raise RuntimeError(f"Evennia refused to create the {direction} exit")
    return exit_obj


def _reviewed_connection(project, connection_room_id, connection_direction):
    snapshot = project.approved_map_data or {}
    room_id = snapshot.get("connection_room_id")
    direction = snapshot.get("connection_direction")
    if not snapshot.get("map_data") or room_id is None or direction not in DIRECTION_NAMES:
        raise PromotionError("Project has no reviewed connection to promote with")
    if connection_room_id is not None or connection_direction is not None:
        try:
            requested_room = int(connection_room_id)
        except (TypeError, ValueError):
            requested_room = None
        requested_direction = connection_direction.lower() if isinstance(connection_direction, str) else None
        if requested_room != room_id or requested_direction != direction:
            raise PromotionError(
                f"The connection was reviewed as #{room_id} going {direction}; "
                "promotion can't use a different one. Resubmit the project to change it.",
                status=409,
            )
    return room_id, direction


def promote_unit(
    project_id: int, connection_room_id: int | None = None, connection_direction: str | None = None
) -> dict[str, Any]:
    """Promote a built project into the live world. Runs on the reactor."""
    from evennia.objects.models import ObjectDB

    from .models import BuildProject

    # 1. Validate (no mutations).
    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise PromotionError("Project not found", status=404)
    if project.status != "built" or not project.built_object_ids:
        raise PromotionError(f"Project must be in 'built' status (current: {project.status})")
    room_id, direction = _reviewed_connection(project, connection_room_id, connection_direction)

    live_room = ObjectDB.objects.filter(pk=room_id).first()
    if live_room is None or not is_live_room(live_room):
        raise PromotionError(f"The reviewed connection room #{room_id} is no longer a live room", status=409)

    rooms, exits, skipped = recorded_objects(project)
    if skipped:
        raise PromotionError(
            "Recorded sandbox objects no longer match the build (tags changed or a player "
            "owns them): " + ", ".join(f"#{i}" for i in skipped)
        )
    entry_id = project.built_object_ids.get("entry")
    entry = next((room for room in rooms if room.id == entry_id), None)
    if entry is None:
        raise PromotionError("The sandbox entry room is missing")

    back = _get_opposite_direction(direction)
    if _direction_taken(live_room, direction):
        raise PromotionError(f"{live_room.key} (#{live_room.id}) already has an exit {direction}", status=409)
    if _direction_taken(entry, back):
        raise PromotionError(f"The entry room {entry.key} already has an exit {back}", status=409)

    # 2. Mutate; 3. compensate on any error.
    project_tag = f"project_{project_id}"
    flipped, created = [], []
    try:
        for obj in rooms + exits:
            flipped.append(obj)
            obj.tags.remove("sandbox")
            obj.tags.remove(project_tag)
        created.append(_create_connection_exit(direction, live_room, entry))
        created.append(_create_connection_exit(back, entry, live_room))

        # Promotion's cleanup: anything recorded that is still a sandbox
        # object. Promoted objects no longer carry the tags, and nothing
        # unrecorded is ever considered.
        leftover_rooms, leftover_exits, _ = recorded_objects(project)
        delete_recorded(leftover_rooms, leftover_exits)

        updated = BuildProject.objects.filter(pk=project_id, status="built").update(
            status="live",
            promoted_at=timezone.now(),
            sandbox_room_id=None,
            built_object_ids={},
            updated_at=timezone.now(),
        )
        if not updated:
            raise PromotionError("Project changed while it was being promoted", status=409)
    except BaseException:
        for exit_obj in created:
            try:
                exit_obj.delete()
            except Exception:
                logger.exception("Promotion undo: could not delete exit %s", exit_obj)
        for obj in flipped:
            try:
                obj.tags.add("sandbox")
                obj.tags.add(project_tag)
            except Exception:
                logger.exception("Promotion undo: could not restore tags on %s", obj)
        raise

    logger.info(
        "Promoted project %s: %s rooms, %s exits, connected to #%s going %s",
        project_id,
        len(rooms),
        len(exits),
        live_room.id,
        direction,
    )
    return {
        "promoted_rooms": len(rooms),
        "promoted_exits": len(exits),
        "created_exits": [
            {"id": e.id, "name": e.key, "source": e.location.id, "destination": e.destination.id} for e in created
        ],
        "entry_room_id": entry.id,
    }


def promote_project_to_live(
    project_id: int, connection_room_id: int | None = None, connection_direction: str | None = None
) -> tuple[bool, dict[str, Any]]:
    """
    Promote a built project from any thread.

    Returns (True, result) or (False, {"error": message, "status": http}).
    """
    try:
        return True, call_in_main_thread(promote_unit, project_id, connection_room_id, connection_direction)
    except PromotionError as e:
        return False, {"error": str(e), "status": e.status}
    except Exception as e:
        logger.exception("Promotion failed for project %s", project_id)
        return False, {"error": f"Promotion failed: {e}", "status": 500}
