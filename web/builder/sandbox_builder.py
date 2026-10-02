"""
The sandbox build unit: create a reviewed project's rooms and exits.

`build_unit(project_id)` is one unit of work (KD-6). It runs wholly on the
reactor (callers hand it over with `web.main_thread.call_in_main_thread`)
and does all of its own DB writes there, in autocommit:

1. Validate everything first: the project is approved and unbuilt, it has
   an approval snapshot, and the snapshot passes `validate_build_map`.
2. Create every room, then every exit, from the snapshot only, then add
   all their tags and Attributes in a few bulk inserts (`_bulk_tag_and_set`;
   Evennia's own `batch_add` still writes one Attribute at a time, which is
   what made a 50-room build cost ~6,000 queries, F-050). Timed-trigger data
   is stored on the rooms, but no Script is started yet. There is no
   container room: the entry room is a real room of the area
   (`validators.entry_room_key`).
3. Start the timed-trigger Scripts, last, once every room and exit exists.
4. Record what was built (`built_object_ids`, `sandbox_room_id` = entry
   room, status `built`) with one conditional update.

If anything fails, the unit undoes its own work with Evennia operations,
never a DB rollback: it stops and deletes the Scripts it started, then
deletes the exits and rooms it created (`obj.delete()`, which also clears
contents caches), and re-raises. Nothing here runs inside
`transaction.atomic()`.
"""

import copy
import logging
from typing import Any

from django.utils import timezone
from evennia.utils.ansi import strip_mxp
from evennia.utils.create import create_object

from .trigger_scripts import start_timed_trigger
from .validators import entry_room_key, validate_build_map

logger = logging.getLogger(__name__)

ROOM_TYPECLASS = "typeclasses.rooms.Room"
EXIT_TYPECLASS = "typeclasses.exits.Exit"
V5_ROOM_ATTRIBUTES = ("location_type", "day_night", "danger_level", "territory_owner")


class BuildError(Exception):
    """The project can't be built; the message is safe to show the builder."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def project_tags(project_id):
    return ["web_builder", f"project_{project_id}", "sandbox"]


def _bulk_tag_and_set(objects, tag_keys):
    """
    Tag every object with `tag_keys` and give it its Attributes, in a few
    bulk inserts instead of several queries per tag and per Attribute.

    `objects` is a list of (obj, [(attr_key, value), ...]). Writes the same
    rows Evennia's TagHandler/AttributeHandler would (plain tags and
    Attributes: no category, no attrtype, value pickled with `to_pickle`),
    then resets each object's tag and Attribute caches so the handlers
    reload from the DB.

    This mirrors Evennia 6.1's ModelAttributeBackend.do_create_attribute and
    TagHandler.add; test_sandbox.BulkRowShapeTests compares the rows field by
    field with ones written through obj.attributes.add / obj.tags.add, so an
    Evennia upgrade that changes them fails loudly.
    """
    from evennia.objects.models import ObjectDB
    from evennia.typeclasses.attributes import Attribute
    from evennia.utils.dbserialize import to_pickle

    tags = [ObjectDB.objects.create_tag(key=key) for key in tag_keys]
    tag_link = ObjectDB.db_tags.through
    tag_link.objects.bulk_create([tag_link(objectdb_id=obj.id, tag_id=tag.id) for obj, _ in objects for tag in tags])

    owners, rows = [], []
    for obj, attributes in objects:
        for key, value in attributes:
            owners.append(obj)
            rows.append(
                Attribute(
                    db_key=key,
                    db_category=None,
                    db_model="objectdb",
                    db_attrtype=None,
                    db_lock_storage="",
                    db_value=to_pickle(value),
                    db_strvalue=None,
                )
            )
    rows = Attribute.objects.bulk_create(rows)
    try:
        if any(row.pk is None for row in rows):
            raise RuntimeError("The database did not return ids for the new Attributes")
        attr_link = ObjectDB.db_attributes.through
        attr_link.objects.bulk_create(
            [attr_link(objectdb_id=obj.id, attribute_id=row.pk) for obj, row in zip(owners, rows, strict=True)]
        )
    except BaseException:
        # Unlinked Attribute rows would be invisible to obj.delete(); remove
        # them here so a failed build leaves nothing behind (R-8).
        Attribute.objects.filter(pk__in=[row.pk for row in rows if row.pk]).delete()
        raise

    for obj, _ in objects:
        obj.tags.reset_cache()
        obj.attributes.reset_cache()


def _room_attributes(room_data):
    attributes = [("desc", strip_mxp(room_data.get("description") or ""))]
    v5 = room_data.get("v5") or {}
    for key in V5_ROOM_ATTRIBUTES:
        if v5.get(key):
            attributes.append((key, v5[key]))
    if v5.get("hunting_modifier") is not None:
        attributes.append(("hunting_modifier", v5["hunting_modifier"]))
    if v5.get("location_type") == "haven" and v5.get("haven_ratings"):
        haven = v5["haven_ratings"]
        for key in ("security", "size", "luxury", "warding"):
            attributes.append((f"haven_{key}", haven.get(key, 0)))
        attributes.append(("haven_location_hidden", haven.get("location_hidden", False)))
    triggers = room_data.get("triggers")
    if triggers:
        attributes.append(("triggers", copy.deepcopy(list(triggers))))
    return attributes


def _create_room(project_id, web_id, room_data):
    """Create one sandbox room (tags and Attributes are added in bulk later)."""
    room = create_object(
        typeclass=ROOM_TYPECLASS,
        key=strip_mxp(room_data["name"]),
        location=None,
        nohome=True,
    )
    if room is None:
        raise RuntimeError(f"Evennia refused to create room {web_id}")
    return room


def _exit_attributes(exit_data):
    return [("desc", strip_mxp(exit_data["description"]))] if exit_data.get("description") else []


def _create_exit(project_id, exit_id, exit_data, rooms):
    """Create one exit between two rooms of this build."""
    source = rooms[exit_data["source"]]
    exit_obj = create_object(
        typeclass=EXIT_TYPECLASS,
        key=strip_mxp(exit_data["name"]),
        aliases=[strip_mxp(alias) for alias in exit_data.get("aliases") or []],
        location=source,
        destination=rooms[exit_data["target"]],
        home=source,
        locks=exit_data.get("locks") or None,
    )
    if exit_obj is None:
        raise RuntimeError(f"Evennia refused to create exit {exit_id}")
    return exit_obj


def _start_timed_triggers(rooms, rooms_data, started):
    """Start every enabled timed trigger; append each Script to `started`."""
    for web_id, room in rooms.items():
        for trigger in rooms_data[web_id].get("triggers") or []:
            if trigger.get("type") == "timed" and trigger.get("enabled", True):
                started.append(start_timed_trigger(room, trigger))


def undo_build(scripts, exits, rooms):
    """
    Remove what a failed build created: Scripts first (stopped, then
    deleted), then exits, then rooms. Logs and carries on past a failing
    delete so one bad object doesn't leave the rest behind.
    """
    for script in scripts:
        try:
            if script.pk:
                script.stop()
                script.delete()
        except Exception:
            logger.exception("Build undo: could not remove script %s", script)
    for obj in [*exits, *rooms]:
        try:
            if obj.pk:
                obj.delete()
        except Exception:
            logger.exception("Build undo: could not delete %s", obj)


def build_unit(project_id: int) -> dict[str, Any]:
    """
    Build a project's approved snapshot as a sandbox. Runs on the reactor.

    Returns {"sandbox_room_id", "room_count", "exit_count", "room_map",
    "script_count"}. Raises BuildError when the project can't be built, or
    the underlying exception if creation fails (after undoing everything).
    """
    from .models import BuildProject

    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise BuildError(f"Project {project_id} not found", status=404)
    if project.status != "approved":
        raise BuildError(f"Project must be approved (current status: {project.status})", status=409)
    if project.sandbox_room_id or project.built_object_ids:
        raise BuildError("Sandbox already exists", status=409)
    snapshot = project.approved_map_data or {}
    map_data = snapshot.get("map_data")
    if not map_data:
        raise BuildError("Project has no approved snapshot to build")
    errors = validate_build_map(map_data)
    if errors:
        raise BuildError("Approved map can't be built: " + "; ".join(errors[:5]))

    rooms_data = map_data["rooms"]
    exits_data = map_data.get("exits") or {}
    rooms, exits, scripts = {}, {}, []
    try:
        for web_id, room_data in rooms_data.items():
            rooms[web_id] = _create_room(project_id, web_id, room_data)
        for exit_id, exit_data in exits_data.items():
            exits[exit_id] = _create_exit(project_id, exit_id, exit_data, rooms)
        _bulk_tag_and_set(
            [(room, _room_attributes(rooms_data[web_id])) for web_id, room in rooms.items()]
            + [(exit_obj, _exit_attributes(exits_data[exit_id])) for exit_id, exit_obj in exits.items()],
            project_tags(project_id),
        )
        # Last step that can fail on its own: start the timed triggers, now
        # that every room and exit exists.
        _start_timed_triggers(rooms, rooms_data, scripts)

        entry = rooms[entry_room_key(map_data)]
        record = {
            "rooms": {web_id: room.id for web_id, room in rooms.items()},
            "exits": {exit_id: exit_obj.id for exit_id, exit_obj in exits.items()},
            "scripts": [script.id for script in scripts],
            "entry": entry.id,
        }
        updated = BuildProject.objects.filter(pk=project_id, status="approved", sandbox_room_id__isnull=True).update(
            status="built",
            sandbox_room_id=entry.id,
            built_object_ids=record,
            updated_at=timezone.now(),
        )
        if not updated:
            raise BuildError("Project changed while it was being built; nothing was kept", status=409)
    except BaseException:
        undo_build(scripts, exits.values(), rooms.values())
        raise

    logger.info(
        "Sandbox build complete for project %s: %s rooms, %s exits, %s timed triggers",
        project_id,
        len(rooms),
        len(exits),
        len(scripts),
    )
    return {
        "sandbox_room_id": entry.id,
        "room_count": len(rooms),
        "exit_count": len(exits),
        "script_count": len(scripts),
        "room_map": record["rooms"],
    }
