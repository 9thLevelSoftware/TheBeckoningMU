"""
Sandbox cleanup: delete what a sandbox build created, and nothing else.

Tags are not authority here. Evennia's `tag` command lets any Builder tag any
object, so a live room or a player character can carry `sandbox` and
`project_N` too (AF-2). Cleanup therefore acts only on the narrow
intersection (KD-7):

    ids recorded in BuildProject.built_object_ids at build time
    ∩ tagged `project_N` and `sandbox`
    ∩ typeclass Room (recorded as a room) or Exit (recorded as an exit)
    ∩ objects with no account and no sessions

and it refuses outright, deleting nothing, while a character is inside a
sandbox room or an exit it didn't build leads into or out of one (deleting
a room would otherwise move the character or delete that exit).

`cleanup_unit(project_id)` is one unit of work that runs wholly on the
reactor. Its three callers all go through it (or, for promotion, through
`delete_recorded`): the web endpoint `builder/api/build/<pk>/cleanup/`,
the in-game `@cleanup_sandbox`, and promotion's sweep of unpromoted objects.
Cleanup never deletes the BuildProject record.
"""

import logging
from typing import Any

from django.db.models import Q
from django.utils import timezone

from web.main_thread import call_in_main_thread

logger = logging.getLogger(__name__)

ROOM_TYPECLASS = "typeclasses.rooms.Room"
EXIT_TYPECLASS = "typeclasses.exits.Exit"


class CleanupError(Exception):
    """Cleanup was refused; nothing was deleted. Safe to show the builder."""


def _has_player(obj):
    return bool(obj.db_account_id) or obj.sessions.count() > 0


def recorded_objects(project, *, require_sandbox=True):
    """
    Split the project's recorded objects into those the builder may act on
    and those it must leave alone.

    Returns (rooms, exits, skipped): rooms and exits are recorded objects
    that still carry `project_N` (and `sandbox`, if `require_sandbox`), are
    of the recorded kind, and have no account or sessions; `skipped` lists
    the recorded ids that failed any of those checks.
    """
    from evennia.objects.models import ObjectDB

    project_tag = f"project_{project.pk}"
    record = project.built_object_ids or {}
    room_ids = {int(i) for i in (record.get("rooms") or {}).values()}
    exit_ids = {int(i) for i in (record.get("exits") or {}).values()}

    rooms, exits = [], []
    found = set()
    for obj in ObjectDB.objects.filter(pk__in=room_ids | exit_ids):
        found.add(obj.id)
        if not obj.tags.has(project_tag) or (require_sandbox and not obj.tags.has("sandbox")):
            continue
        if _has_player(obj):
            continue
        if obj.id in room_ids and obj.is_typeclass(ROOM_TYPECLASS, exact=False):
            rooms.append(obj)
        elif obj.id in exit_ids and obj.is_typeclass(EXIT_TYPECLASS, exact=False):
            exits.append(obj)
    kept = {obj.id for obj in rooms + exits}
    skipped = sorted(found - kept)
    return rooms, exits, skipped


def check_deletable(rooms, exits):
    """Raise CleanupError if deleting these rooms would touch anything else."""
    from evennia.objects.models import ObjectDB

    room_ids = [room.id for room in rooms]
    occupied = [f"{room.key} (#{room.id})" for room in rooms if any(_has_player(obj) for obj in room.contents)]
    if occupied:
        raise CleanupError("A character is still inside: " + ", ".join(occupied) + ". Move them out first.")
    foreign = (
        ObjectDB.objects.filter(Q(db_destination_id__in=room_ids) | Q(db_location_id__in=room_ids))
        .exclude(db_destination__isnull=True)
        .exclude(pk__in=[exit_obj.id for exit_obj in exits])
        .values_list("id", flat=True)
    )
    foreign = sorted(foreign)
    if foreign:
        raise CleanupError(
            "Exits this build didn't create lead into or out of the sandbox: "
            + ", ".join(f"#{i}" for i in foreign)
            + ". Remove them first."
        )


def delete_recorded(rooms, exits):
    """Delete exits, then rooms (Scripts on a room go with it). Returns
    (deleted_rooms, deleted_exits, errors)."""
    deleted_rooms = deleted_exits = 0
    errors = []
    for exit_obj in exits:
        try:
            exit_obj.delete()
            deleted_exits += 1
        except Exception as e:
            logger.exception("Cleanup: could not delete exit #%s", exit_obj.id)
            errors.append(f"Exit #{exit_obj.id}: {e}")
    for room in rooms:
        try:
            room.delete()
            deleted_rooms += 1
        except Exception as e:
            logger.exception("Cleanup: could not delete room #%s", room.id)
            errors.append(f"Room #{room.id}: {e}")
    return deleted_rooms, deleted_exits, errors


def cleanup_unit(project_id: int) -> dict[str, Any]:
    """
    Delete a built project's sandbox and return it to `approved`.

    Runs on the reactor. Raises CleanupError (nothing deleted) when the
    project has no sandbox or deleting it would touch anything else.
    """
    from .models import BuildProject

    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise CleanupError("Project not found")
    if project.status != "built" or not project.built_object_ids:
        raise CleanupError("Project has no active sandbox")

    rooms, exits, skipped = recorded_objects(project)
    check_deletable(rooms, exits)
    deleted_rooms, deleted_exits, errors = delete_recorded(rooms, exits)

    if errors:
        # Keep what's left on record (still built) so cleanup can be retried.
        from evennia.objects.models import ObjectDB

        remaining = set(ObjectDB.objects.filter(pk__in=[o.id for o in rooms + exits]).values_list("id", flat=True))
        record = project.built_object_ids
        record = {
            **record,
            "rooms": {k: v for k, v in (record.get("rooms") or {}).items() if v in remaining},
            "exits": {k: v for k, v in (record.get("exits") or {}).items() if v in remaining},
        }
        BuildProject.objects.filter(pk=project_id, status="built").update(
            built_object_ids=record, updated_at=timezone.now()
        )
    else:
        BuildProject.objects.filter(pk=project_id, status="built").update(
            status="approved",
            sandbox_room_id=None,
            built_object_ids={},
            updated_at=timezone.now(),
        )

    if skipped:
        logger.warning(
            "Cleanup of project %s left recorded objects that no longer pass the checks: %s",
            project_id,
            skipped,
        )
    return {
        "deleted_rooms": deleted_rooms,
        "deleted_exits": deleted_exits,
        "deleted_objects": 0,
        "skipped": skipped,
        "errors": errors,
    }


def cleanup_sandbox_for_project(project_id: int) -> tuple[bool, dict[str, Any]]:
    """
    Clean up a project's sandbox from any thread.

    Returns (True, {"deleted_rooms", "deleted_exits", "deleted_objects",
    "skipped", "errors"}) or (False, {"error": message}).
    """
    try:
        result = call_in_main_thread(cleanup_unit, project_id)
    except CleanupError as e:
        return False, {"error": str(e)}
    except Exception as e:
        logger.exception("Sandbox cleanup failed for project %s", project_id)
        return False, {"error": f"Cleanup failed: {e}"}
    if result["errors"]:
        return False, {"error": "; ".join(result["errors"]), **result}
    return True, result
