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
from collections.abc import Mapping
from typing import Any

from django.db import transaction
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


def recorded_fixtures(project):
    """Verify dedicated exact identities, reviewed provenance and placement.

    This is deliberately separate from the Room/Exit deletion predicate.
    No tags can add an object to this allowlist. Missing, moved, type-swapped,
    account-bearing or nonempty fixtures refuse the entire operation.
    """
    from evennia.objects.models import ObjectDB

    from .manifests import fixture_provenance
    from .prototype_catalog import FIXTURE_TYPECLASS
    from .revisions import approved_snapshot_hash

    record = project.built_object_ids or {}
    ids = record.get("fixtures", {})
    definitions = (project.approved_map_data or {}).get("prototypes", {})
    manifest = project.fixture_manifest or {}
    if not ids and not definitions and not manifest:
        return []
    try:
        placements = manifest["placements"]
        valid = (
            manifest["schema_version"] == 1
            and manifest["project_id"] == project.pk
            and manifest["approved_version"] == project.version
            and manifest["approved_snapshot_hash"] == approved_snapshot_hash(project.approved_map_data)
            and set(placements) == set(ids)
            and set(placements) <= set(definitions)
            and (record.get("cleanup_started") or set(placements) == set(definitions))
        )
        if not valid:
            raise ValueError("manifest binding")
        expected_ids = set(ids.values())
        if len(expected_ids) != len(ids) or any(type(i) is not int for i in expected_ids):
            raise ValueError("duplicate or invalid recorded ids")
        objects = {obj.pk: obj for obj in ObjectDB.objects.filter(pk__in=expected_ids)}
        tagged = ids_with_tags(expected_ids, [f"project_{project.pk}", "sandbox"])
        if set(objects) != expected_ids or tagged != expected_ids:
            raise ValueError("missing objects or provenance tags")
        for key, entry in placements.items():
            obj = objects[ids[key]]
            reviewed = definitions[key]
            provenance = fixture_provenance(project, key, reviewed)
            if (
                entry["object_id"] != obj.pk
                or entry["typeclass"] != FIXTURE_TYPECLASS
                or obj.db_typeclass_path != FIXTURE_TYPECLASS
                or obj.db_destination_id is not None
                or _has_player(obj)
                or entry["map_room_id"] != reviewed["placement"]["room_id"]
                or entry["room_id"] != record["rooms"][entry["map_room_id"]]
                or obj.db_location_id != entry["room_id"]
                or any(entry.get(field) != value for field, value in provenance.items())
                or not isinstance(obj.db.builder_fixture, Mapping)
                or dict(obj.db.builder_fixture) != provenance
            ):
                raise ValueError(f"fixture '{key}' identity or provenance")
        if ObjectDB.objects.filter(db_location_id__in=expected_ids).exists():
            raise ValueError("foreign fixture contents")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise CleanupError(
            "Recorded fixture identity, placement, contents or reviewed provenance no longer matches "
            f"({exc}). Ask an Admin to inspect it."
        ) from None
    return list(objects.values())


def check_deletable(rooms, exits, fixtures=()):
    """Raise CleanupError if deleting these rooms would touch anything else."""
    from evennia.objects.models import ObjectDB

    room_ids = [room.id for room in rooms]
    exit_ids = [exit_obj.id for exit_obj in exits]
    inside = ObjectDB.objects.filter(db_location_id__in=room_ids).exclude(
        pk__in=exit_ids + [obj.pk for obj in fixtures]
    )
    occupied = sorted(
        {
            f"{obj.db_location.db_key} (#{obj.db_location_id})"
            for obj in inside
            if _has_player(obj) or obj.is_typeclass("typeclasses.characters.Character", exact=False)
        }
    )
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
    """Delete Attributes and objects as one short database persistence unit.

    This queryset-only transaction contains no Evennia moves, object.delete
    hooks, timers or reactor handoff. The outer cleanup remains autocommit.
    Django deletion clears cached instance PKs before commit, so rollback
    must also repair the preexisting idmapper references and handlers.
    """
    from evennia.objects.models import ObjectDB
    from evennia.typeclasses.attributes import Attribute

    if not object_ids:
        return 0
    objects = [(obj.pk, obj) for obj in ObjectDB.objects.filter(pk__in=object_ids)]
    attr_ids = list(
        ObjectDB.db_attributes.through.objects.filter(objectdb_id__in=object_ids).values_list("attribute_id", flat=True)
    )
    cached_attributes = [(pk, Attribute.get_cached_instance(pk)) for pk in attr_ids]
    try:
        with transaction.atomic():
            Attribute.objects.filter(pk__in=attr_ids).delete()
            ObjectDB.objects.filter(pk__in=object_ids).delete()
    except BaseException as exc:
        failures = []
        for pk, attribute in cached_attributes:
            if attribute is None:
                continue
            try:
                attribute.pk = pk
                attribute.refresh_from_db()
                Attribute.cache_instance(attribute)
            except Exception:
                logger.exception("Cleanup rollback: could not refresh cached Attribute #%s", pk)
                failures.append(pk)
        for pk, obj in objects:
            try:
                obj.pk = pk
                obj.refresh_from_db()
                ObjectDB.cache_instance(obj)
                obj.attributes.reset_cache()
                obj.tags.reset_cache()
            except Exception:
                logger.exception("Cleanup rollback: could not refresh cached object #%s", pk)
                failures.append(pk)
        if failures:
            raise RuntimeError(
                "Cleanup deletion failed and cached state could not be restored; staff inspection is required"
            ) from exc
        raise
    return len(objects)


def delete_recorded(rooms, exits, fixtures=()):
    """
    Delete the given recorded exits and rooms in bulk (a handful of queries
    per step rather than ~45 per object, R-2): evict loose items, stop and
    delete the objects' Scripts, delete the exits, then the rooms.

    Returns (deleted_rooms, deleted_exits, errors). On an error the rest is
    left in place and reported, so the caller can keep it on record.
    """
    room_ids = [room.id for room in rooms]
    exit_ids = [exit_obj.id for exit_obj in exits]
    fixture_ids = [obj.pk for obj in fixtures]
    deleted_rooms = deleted_exits = 0
    errors = []
    try:
        _evict_contents(room_ids, exit_ids + fixture_ids)
        _remove_scripts(room_ids + exit_ids + fixture_ids)
        if fixture_ids:
            _delete_rows(fixture_ids)
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
    from .operation_runtime import OperationError, require_idle

    try:
        require_idle()
    except OperationError as exc:
        raise CleanupError(str(exc)) from exc
    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise CleanupError("Project not found")
    if project.status != "built" or not project.built_object_ids:
        raise CleanupError("Project has no active sandbox")

    rooms, exits, skipped = recorded_objects(project)
    fixtures = recorded_fixtures(project)
    if skipped:
        # Clearing the record would leave these with no handle cleanup can
        # trust, so refuse until staff sort them out.
        raise CleanupError(
            "Recorded sandbox objects no longer match the build (tags changed or an account "
            "is attached): " + ", ".join(f"#{i}" for i in skipped) + ". Ask an Admin to check them."
        )
    check_deletable(rooms, exits, fixtures)
    deleted_rooms, deleted_exits, errors = delete_recorded(rooms, exits, fixtures)
    from evennia.objects.models import ObjectDB

    remaining_fixtures = set(ObjectDB.objects.filter(pk__in=[obj.pk for obj in fixtures]).values_list("id", flat=True))

    if errors:
        # Keep what's left on record (still built) so cleanup can be retried.
        from evennia.objects.models import ObjectDB

        remaining = set(ObjectDB.objects.filter(pk__in=[o.id for o in rooms + exits]).values_list("id", flat=True))
        record = project.built_object_ids
        record = {
            **record,
            "rooms": {k: v for k, v in (record.get("rooms") or {}).items() if v in remaining},
            "exits": {k: v for k, v in (record.get("exits") or {}).items() if v in remaining},
            "fixtures": {k: v for k, v in (record.get("fixtures") or {}).items() if v in remaining_fixtures},
            "cleanup_started": True,
        }
        manifest = project.fixture_manifest
        if manifest:
            manifest = {
                **manifest,
                "placements": {
                    key: entry
                    for key, entry in manifest["placements"].items()
                    if entry["object_id"] in remaining_fixtures
                },
            }
        BuildProject.objects.filter(pk=project_id, status="built").update(
            built_object_ids=record, fixture_manifest=manifest, updated_at=timezone.now()
        )
    else:
        BuildProject.objects.filter(pk=project_id, status="built").update(
            status="approved",
            sandbox_room_id=None,
            built_object_ids={},
            fixture_manifest={},
            updated_at=timezone.now(),
        )

    return {
        "deleted_rooms": deleted_rooms,
        "deleted_exits": deleted_exits,
        "deleted_objects": len(fixtures) - len(remaining_fixtures),
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
