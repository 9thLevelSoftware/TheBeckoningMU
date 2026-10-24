"""
The sandbox build unit: create a reviewed project's rooms and exits.

Production uses `build_deferred`: a durable operation fence owns the reviewed
snapshot while small synchronous steps run on the reactor. Each hooked create
has a pending intent and typed receipt before the next callback. Metadata uses
bounded batches. Scripts remain paused through publication; a distinct terminal
activation callback releases the fence only after success. Failure before
publication compensates in steps; unexpected drift or activation failure keeps
the durable fence for inspection. `build_unit` drains the same steps without
scheduling for synchronous unit callers, and refuses another active operation.

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
   room, status `built`) with one conditional update, then activate paused
   timers and release the production operation fence.

Before publication, the unit undoes its own work with Evennia operations,
never a DB rollback: it stops and deletes the Scripts it started, then
deletes the exits and rooms it created (`obj.delete()`, which also clears
contents caches), and re-raises. Nothing here runs inside
`transaction.atomic()`.
"""

import copy
import logging
from typing import Any

from django.utils import timezone
from evennia.utils.create import create_object

from . import operation_runtime
from .manifests import fixture_manifest, fixture_provenance, object_provenance
from .markup import remove_mxp
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
    attributes = [("desc", remove_mxp(room_data.get("description") or ""))]
    v5 = room_data.get("v5") or {}
    for key in V5_ROOM_ATTRIBUTES:
        if v5.get(key):
            attributes.append((key, v5[key]))
    if v5.get("hunting_modifier") is not None:
        attributes.append(("hunting_modifier", v5["hunting_modifier"]))
    if "restricted_characters" in v5:
        attributes.append(("restricted_characters", copy.deepcopy(v5["restricted_characters"])))
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
        key=remove_mxp(room_data["name"]),
        location=None,
        nohome=True,
    )
    if room is None:
        raise RuntimeError(f"Evennia refused to create room {web_id}")
    return room


def _exit_attributes(exit_data):
    return [("desc", remove_mxp(exit_data["description"]))] if exit_data.get("description") else []


def _create_exit(project_id, exit_id, exit_data, rooms):
    """Create one exit between two rooms of this build."""
    source = rooms[exit_data["source"]]
    exit_obj = create_object(
        typeclass=EXIT_TYPECLASS,
        key=remove_mxp(exit_data["name"]),
        aliases=[remove_mxp(alias) for alias in exit_data.get("aliases") or []],
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


def _create_fixture(reviewed, rooms):
    placement, definition = reviewed["placement"], reviewed["definition"]
    room = rooms[placement["room_id"]]
    obj = create_object(
        typeclass=definition["typeclass"],
        key=placement.get("name") or definition["label"],
        location=room,
        home=room,
        locks=definition["locks"],
    )
    if obj is None:
        raise RuntimeError("Evennia refused to create a reviewed fixture")
    return obj


def _fixture_attributes(project, placement_id, reviewed):
    return [
        ("desc", reviewed["placement"].get("description", reviewed["definition"]["description"])),
        *reviewed["definition"]["attributes"].items(),
        ("builder_fixture", fixture_provenance(project, placement_id, reviewed)),
    ]


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


def _audit_build_objects(state, objects, *, remember=False):
    from .live_replacement import EXIT_KEYS, FIXTURE_KEYS, ROOM_KEYS, _fresh_persisted, _object_state

    if not objects:
        return
    keys = {"rooms": ROOM_KEYS, "exits": EXIT_KEYS, "fixtures": FIXTURE_KEYS}
    kinds = {obj.pk: kind for kind in keys for obj in state[kind].values() if obj.pk}
    fresh = _fresh_persisted(objects, {obj.pk: keys[kinds[obj.pk]] for obj in objects})
    observed = state.setdefault("observed_objects", {})
    for obj in objects:
        snapshot = _object_state(obj, keys[kinds[obj.pk]], fresh[obj.pk])
        snapshot.update(
            typeclass=fresh[obj.pk]["fields"]["db_typeclass_path"],
            account_id=fresh[obj.pk]["fields"]["db_account_id"],
            sessions=obj.sessions.count(),
        )
        if not remember and observed.get(obj.pk) != snapshot:
            raise BuildError(f"Build addition #{obj.pk} changed between steps; inspection required", status=409)
        if remember:
            observed[obj.pk] = snapshot


def _audit_build_script(state, script, *, remember=False):
    from .live_replacement import _capture_script

    snapshot = _capture_script(script)
    observed = state.setdefault("observed_scripts", {})
    if not remember and observed.get(script.pk) != snapshot:
        raise BuildError(f"Build timer #{script.pk} changed between steps; inspection required", status=409)
    if remember:
        observed[script.pk] = snapshot


def _check_build_inventory(state):
    """Fresh exact ownership boundary, including fixture/exit attachments."""
    from django.db.models import Q
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    objects = [obj for kind in ("rooms", "exits", "fixtures") for obj in state[kind].values()]
    _audit_build_objects(state, objects)
    ids = [obj.pk for obj in objects]
    if ObjectDB.objects.filter(Q(db_location_id__in=ids) | Q(db_destination_id__in=ids)).exclude(pk__in=ids).exists():
        raise BuildError("Foreign contents or ingress touches the build; inspection required", status=409)
    if ScriptDB.objects.filter(db_obj_id__in=ids).exclude(pk__in=[script.pk for script in state["scripts"]]).exists():
        raise BuildError("An unexpected Script is attached to the build; inspection required", status=409)
    for script in state["scripts"]:
        _audit_build_script(state, script)


def _build_steps(project_id: int, operation=None, state=None):
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
    definitions = snapshot.get("prototypes", {})
    errors = validate_build_map(map_data, resolved_prototypes=definitions)
    if errors:
        raise BuildError("Approved map can't be built: " + "; ".join(errors[:5]))

    rooms_data = map_data["rooms"]
    exits_data = map_data.get("exits") or {}
    state = {} if state is None else state
    rooms, exits, fixtures, scripts = {}, {}, {}, []
    state.update(rooms=rooms, exits=exits, fixtures=fixtures, scripts=scripts)
    try:
        for web_id, room_data in rooms_data.items():
            if operation is not None:
                operation_runtime.creation_pending(operation, "rooms", web_id, ROOM_TYPECLASS)
            rooms[web_id] = _create_room(project_id, web_id, room_data)
            if operation is not None:
                operation_runtime.record_created(operation, rooms[web_id], "rooms", web_id)
                _audit_build_objects(state, [rooms[web_id]], remember=True)
            yield
        for exit_id, exit_data in exits_data.items():
            if operation is not None:
                operation_runtime.creation_pending(operation, "exits", exit_id, EXIT_TYPECLASS)
            exits[exit_id] = _create_exit(project_id, exit_id, exit_data, rooms)
            if operation is not None:
                operation_runtime.record_created(operation, exits[exit_id], "exits", exit_id)
                _audit_build_objects(state, [exits[exit_id]], remember=True)
            yield
        for placement_id, reviewed in definitions.items():
            # Record immediately, before any metadata/lock/provenance step can fail.
            if operation is not None:
                operation_runtime.creation_pending(
                    operation, "fixtures", placement_id, reviewed["definition"]["typeclass"]
                )
            fixtures[placement_id] = _create_fixture(reviewed, rooms)
            if operation is not None:
                operation_runtime.record_created(operation, fixtures[placement_id], "fixtures", placement_id)
                _audit_build_objects(state, [fixtures[placement_id]], remember=True)
            yield
        metadata = (
            [
                (
                    room,
                    [
                        *_room_attributes(rooms_data[web_id]),
                        ("builder_revision", object_provenance(project, "rooms", web_id)),
                    ],
                )
                for web_id, room in rooms.items()
            ]
            + [
                (
                    exit_obj,
                    [
                        *_exit_attributes(exits_data[exit_id]),
                        ("builder_revision", object_provenance(project, "exits", exit_id)),
                    ],
                )
                for exit_id, exit_obj in exits.items()
            ]
            + [
                (obj, _fixture_attributes(project, placement_id, definitions[placement_id]))
                for placement_id, obj in fixtures.items()
            ]
        )
        for offset in range(0, len(metadata), 20):
            batch = metadata[offset : offset + 20]
            if operation is not None:
                _audit_build_objects(state, [obj for obj, _ in batch])
            _bulk_tag_and_set(batch, project_tags(project_id))
            if operation is not None:
                _audit_build_objects(state, [obj for obj, _ in batch], remember=True)
            yield
        # Last step that can fail on its own: start the timed triggers, now
        # that every room and exit exists.
        if operation is None:
            _start_timed_triggers(rooms, rooms_data, scripts)
        else:
            for web_id, room in rooms.items():
                for trigger in rooms_data[web_id].get("triggers") or []:
                    if trigger.get("type") == "timed" and trigger.get("enabled", True):
                        map_id = f"{web_id}:{trigger['id']}"
                        operation_runtime.creation_pending(
                            operation, "scripts", map_id, "typeclasses.scripts.RoomTriggerScript"
                        )
                        script = start_timed_trigger(room, trigger)
                        scripts.append(script)
                        script.pause()
                        operation_runtime.record_created(operation, script, "scripts", map_id)
                        _audit_build_script(state, script, remember=True)
                        yield

        entry = rooms[entry_room_key(map_data)]
        record = {
            "rooms": {web_id: room.id for web_id, room in rooms.items()},
            "exits": {exit_id: exit_obj.id for exit_id, exit_obj in exits.items()},
            "scripts": [script.id for script in scripts],
            "entry": entry.id,
            "fixtures": {key: obj.pk for key, obj in fixtures.items()},
        }
        if operation is not None:
            _check_build_inventory(state)
        updated = BuildProject.objects.filter(
            pk=project_id,
            status="approved",
            version=project.version,
            approved_map_data=snapshot,
            sandbox_room_id__isnull=True,
        ).update(
            status="built",
            sandbox_room_id=entry.id,
            built_object_ids=record,
            fixture_manifest=fixture_manifest(project, fixtures, rooms) if fixtures else {},
            updated_at=timezone.now(),
        )
        if not updated:
            raise BuildError("Project changed while it was being built; nothing was kept", status=409)
        if operation is not None:
            state["published"] = True
            operation_runtime.update_operation(operation, status="built", phase="activation")
            yield
            # The <=30 timer activation callback is measured independently.
            _check_build_inventory(state)
            for script in scripts:
                script.unpause()
            operation_runtime.finish_operation(operation)
    except BaseException:
        if operation is not None:
            raise
        undo_build(scripts, [*fixtures.values(), *exits.values()], rooms.values())
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
        "fixture_count": len(fixtures),
        "room_map": record["rooms"],
    }


def _drain_steps(steps):
    """Run shared world steps without scheduling (synchronous unit adapter)."""
    iterator = iter(steps)
    while True:
        try:
            next(iterator)
        except StopIteration as result:
            return result.value


def build_unit(project_id: int) -> dict[str, Any]:
    operation_runtime.require_idle()
    return _drain_steps(_build_steps(project_id))


def _undo_build_steps(state, operation, error):
    if state.get("published"):
        operation_runtime.finish_operation(operation, state="failed", phase="activation_failed", release=False)
        return
    errors = []
    for script in state.get("scripts", []):
        try:
            if script.pk:
                _audit_build_script(state, script)
                script.stop()
                script.delete()
        except Exception as exc:
            errors.append(f"timer: {exc}")
        yield
    for obj in [
        *state.get("fixtures", {}).values(),
        *state.get("exits", {}).values(),
        *state.get("rooms", {}).values(),
    ]:
        try:
            if obj.pk:
                from .live_replacement import _guard_addition_delete

                _audit_build_objects(state, [obj])
                if errors and obj.db_typeclass_path == ROOM_TYPECLASS:
                    raise RuntimeError("Staged room retained after earlier compensation failure")
                all_objects = [
                    (kind, item) for kind in ("rooms", "exits", "fixtures") for item in state[kind].values() if item.pk
                ]
                _guard_addition_delete(
                    obj,
                    {
                        "created_objects": [
                            {"object_id": item.pk, "kind": kind, "typeclass": item.db_typeclass_path}
                            for kind, item in all_objects
                        ],
                        "created_object_ids": [item.pk for _, item in all_objects],
                        "created_script_ids": [script.pk for script in state["scripts"] if script.pk],
                    },
                )
                if not obj.delete():
                    raise RuntimeError("Evennia refused recorded build addition deletion")
        except Exception as exc:
            errors.append(f"object: {exc}")
        yield
    if errors:
        operation_runtime.finish_operation(operation, state="failed", phase="compensation_failed", release=False)
        raise BuildError(
            "Build compensation failed; staff inspection required: " + "; ".join(errors), status=500
        ) from error
    operation_runtime.finish_operation(operation, state="rolled_back", phase="rolled_back")


def build_deferred(project_id, actor, expected_version, *, clock=None):
    """Claim a reviewed build and return only its terminal Deferred result."""
    state = {}
    operation = operation_runtime.claim_operation(project_id, "build", actor, expected_version)
    return operation_runtime.run_steps(
        operation,
        _build_steps(project_id, operation, state),
        lambda error: _undo_build_steps(state, operation, error),
        clock=clock,
    )
