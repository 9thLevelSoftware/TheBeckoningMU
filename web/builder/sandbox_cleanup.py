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
sandbox room, an exit it didn't build leads into or out of one (deleting
a room would otherwise move the character or delete that exit), or a
recorded object no longer passes those checks (clearing the record would
leave it with no trustworthy handle).

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


def plain_tags(keys):
    """The plain (no category, no tagtype) object Tags with these keys."""
    from evennia.typeclasses.tags import Tag

    return list(
        Tag.objects.filter(
            db_key__in=[key.lower() for key in keys],
            db_model="objectdb",
            db_category__isnull=True,
            db_tagtype__isnull=True,
        )
    )


def ids_with_tags(ids, keys):
    """The subset of object ids that carry every one of these plain tags (one
    query per tag, not per object)."""
    from evennia.objects.models import ObjectDB

    tags = plain_tags(keys)
    if len(tags) < len(set(keys)):
        return set()
    link = ObjectDB.db_tags.through
    result = set(ids)
    for tag in tags:
        result &= set(link.objects.filter(objectdb_id__in=result, tag_id=tag.id).values_list("objectdb_id", flat=True))
    return result


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

    objects = list(ObjectDB.objects.filter(pk__in=room_ids | exit_ids))
    found = {obj.id for obj in objects}
    tagged = ids_with_tags(found, [project_tag, "sandbox"] if require_sandbox else [project_tag])

    rooms, exits = [], []
    for obj in objects:
        if obj.id not in tagged or _has_player(obj):
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
    exit_ids = [exit_obj.id for exit_obj in exits]
    inside = ObjectDB.objects.filter(db_location_id__in=room_ids).exclude(pk__in=exit_ids)
    occupied = sorted({f"{obj.db_location.db_key} (#{obj.db_location_id})" for obj in inside if _has_player(obj)})
    if occupied:
        raise CleanupError("A character is still inside: " + ", ".join(occupied) + ". Move them out first.")
    foreign = (
        ObjectDB.objects.filter(Q(db_destination_id__in=room_ids) | Q(db_location_id__in=room_ids))
        .exclude(db_destination__isnull=True)
        .exclude(pk__in=exit_ids)
        .values_list("id", flat=True)
    )
    foreign = sorted(foreign)
    if foreign:
        raise CleanupError(
            "Exits this build didn't create lead into or out of the sandbox: "
            + ", ".join(f"#{i}" for i in foreign)
            + ". Remove them first."
        )


def _evict_contents(room_ids, exit_ids):
    """Send loose objects (dropped items) inside the rooms to their home, as
    DefaultObject.delete() would. Characters were refused by check_deletable."""
    from evennia.objects.models import ObjectDB

    for obj in ObjectDB.objects.filter(db_location_id__in=room_ids).exclude(pk__in=exit_ids):
        home = obj.home if obj.home and obj.home.id not in room_ids else None
        if home:
            obj.move_to(home, quiet=True, move_type="teleport")
        else:
            obj.location = None


def _remove_scripts(object_ids):
    """Stop the timers of the objects' Scripts, then delete them and their
    Attributes in bulk."""
    from evennia.scripts.models import ScriptDB
    from evennia.typeclasses.attributes import Attribute

    scripts = list(ScriptDB.objects.filter(db_obj_id__in=object_ids))
    for script in scripts:
        stop = getattr(script, "_stop_task", None)
        if stop:
            stop()
    script_ids = [script.id for script in scripts]
    attr_ids = ScriptDB.db_attributes.through.objects.filter(scriptdb_id__in=script_ids).values_list(
        "attribute_id", flat=True
    )
    Attribute.objects.filter(pk__in=list(attr_ids)).delete()
    ScriptDB.objects.filter(pk__in=script_ids).delete()


def _delete_rows(object_ids):
    """Delete the objects' Attributes, then the objects (their tag and
    Attribute links go with them); idmapper flushes each instance on
    pre_delete. Returns how many objects were deleted."""
    from evennia.objects.models import ObjectDB
    from evennia.typeclasses.attributes import Attribute

    if not object_ids:
        return 0
    attr_ids = ObjectDB.db_attributes.through.objects.filter(objectdb_id__in=object_ids).values_list(
        "attribute_id", flat=True
    )
    Attribute.objects.filter(pk__in=list(attr_ids)).delete()
    rows = ObjectDB.objects.filter(pk__in=object_ids)
    count = rows.count()
    rows.delete()
    return count


def delete_recorded(rooms, exits):
    """
    Delete the given recorded exits and rooms in bulk (a handful of queries
    per step rather than ~45 per object, R-2): evict loose items, stop and
    delete the objects' Scripts, delete the exits, then the rooms.

    Returns (deleted_rooms, deleted_exits, errors). On an error the rest is
    left in place and reported, so the caller can keep it on record.
    """
    room_ids = [room.id for room in rooms]
    exit_ids = [exit_obj.id for exit_obj in exits]
    deleted_rooms = deleted_exits = 0
    errors = []
    try:
        _evict_contents(room_ids, exit_ids)
        _remove_scripts(room_ids + exit_ids)
        deleted_exits = _delete_rows(exit_ids)
        deleted_rooms = _delete_rows(room_ids)
    except Exception as e:
        logger.exception("Cleanup: bulk delete failed")
        errors.append(str(e))
    # No contents-cache refresh is needed: idmapper flushes each deleted
    # object on pre_delete, and ContentsHandler.get() reloads when a cached
    # pk is gone (test_partial_cleanup_keeps_the_rest_on_record).
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
    if skipped:
        # Clearing the record would leave these with no handle cleanup can
        # trust, so refuse until staff sort them out.
        raise CleanupError(
            "Recorded sandbox objects no longer match the build (tags changed or an account "
            "is attached): " + ", ".join(f"#{i}" for i in skipped) + ". Ask an Admin to check them."
        )
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

    return {
        "deleted_rooms": deleted_rooms,
        "deleted_exits": deleted_exits,
        "deleted_objects": 0,
        "errors": errors,
    }


def cleanup_sandbox_for_project(project_id: int) -> tuple[bool, dict[str, Any]]:
    """
    Clean up a project's sandbox from any thread.

    Returns (True, {"deleted_rooms", "deleted_exits", "deleted_objects",
    "errors"}) or (False, {"error": message}).
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
