"""Reactor-owned, reviewed live replacement with durable compensation records.

Never infer ownership from tags. Only exact identities in a current v2 live
manifest may be retained or retired. Removed live objects are never purged.
Object mutations remain autocommit. Short atomic blocks persist lifecycle
records or plain new Attribute rows/links only, never Evennia hooks, movement,
timers or thread handoffs.
"""

import copy
import logging
import re

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from evennia.utils.dbserialize import deserialize, from_pickle, to_pickle

from web.main_thread import call_in_main_thread

from . import operation_runtime, sandbox_builder
from .manifests import fixture_manifest, fixture_provenance, live_manifest, object_provenance
from .models import BuildProject
from .promotion import DIRECTION_NAMES, _exit_names, _get_opposite_direction, _remove_tags
from .prototype_catalog import FIXTURE_LOCKS, FIXTURE_TYPECLASS
from .replacement_receipts import append_receipt
from .revisions import RevisionError, approved_snapshot_hash, current_replacement_source, replacement_design
from .trigger_scripts import start_timed_trigger
from .validators import entry_room_key, is_live_room, validate_build_map, validate_connection

logger = logging.getLogger(__name__)
ROOM_KEYS = {
    "desc",
    "location_type",
    "day_night",
    "danger_level",
    "territory_owner",
    "hunting_modifier",
    "restricted_characters",
    "haven_security",
    "haven_size",
    "haven_luxury",
    "haven_warding",
    "haven_location_hidden",
    "triggers",
    "builder_revision",
    "builder_retired",
}
EXIT_KEYS = {"desc", "builder_revision", "builder_retired"}
FIXTURE_KEYS = {"desc", "builder_inert", "builder_fixture", "builder_retired"}
SCRIPT_KEYS = {
    "trigger_id",
    "trigger_action",
    "trigger_parameters",
    "_paused_time",
    "_paused_callcount",
    "_manually_paused",
}


class ReplacementError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _checkpoint(phase):
    """Failure-injection seam at each supported compensation boundary."""


def _plain(value):
    return copy.deepcopy(deserialize(value))


def _refresh_cached_rows(queryset):
    """Refresh identity-mapped fields using scalar reads, never model hydration.

    Evennia's model constructor (including refresh_from_db's query) can return
    the same stale instance. values() bypasses it. Updating __dict__ refreshes
    in-memory state only; no model setters, saves, hooks or timers run here.
    """
    model = queryset.model
    fields = [field.attname for field in model._meta.concrete_fields]
    rows = {row[model._meta.pk.attname]: row for row in queryset.values(*fields)}
    # Tags in this installed Evennia are ordinary Django models. Their handler
    # caches must be reset below, but they have no identity-mapper cache.
    get_cached = getattr(model, "get_cached_instance", None)
    if get_cached is None:
        return rows
    for pk, row in rows.items():
        cached = get_cached(pk)
        if cached is not None:
            cached.__dict__.update(row)
            cached._state.fields_cache.clear()
    return rows


def _fresh_persisted(objects, owned_by_id=None):
    """Refresh handlers and return a fresh scalar read-map for checks/undo.

    The local map also represents absent keys. Evennia's handler otherwise
    queries missing keys repeatedly despite loading all present Attributes.
    No snapshot is attached to a long-lived object or trusted across units.
    """
    if not objects:
        return {}
    model = objects[0].__dbclass__
    ids = [obj.pk for obj in objects]
    fields = _refresh_cached_rows(model.objects.filter(pk__in=ids))
    if set(fields) != set(ids):
        raise ReplacementError("A recorded live object or timer is missing")
    records = {
        pk: {
            "fields": row,
            "attributes": {},
            "attribute_rows": {},
            "duplicate_attributes": set(),
            "aliases": [],
            "read_keys": set((owned_by_id or {}).get(pk, ())),
        }
        for pk, row in fields.items()
    }
    namespace = model._meta.model_name
    owned_attribute_ids = set()
    for name in ("db_attributes", "db_tags"):
        relation = model._meta.get_field(name)
        through = relation.remote_field.through
        links = list(
            through.objects.filter(**{f"{relation.m2m_field_name()}_id__in": ids}).values_list(
                f"{relation.m2m_field_name()}_id",
                f"{relation.m2m_reverse_field_name()}_id",
            )
        )
        rows = _refresh_cached_rows(relation.remote_field.model.objects.filter(pk__in={pk for _, pk in links}))
        for owner, pk in links:
            row = rows.get(pk)
            if row is None:
                raise ReplacementError("A linked live Attribute or Tag disappeared during inspection")
            record = records[owner]
            if name == "db_attributes":
                # Match ModelAttributeBackend's case-insensitive model/key and
                # default category/attrtype query. Other gameplay namespaces
                # remain untouched; ambiguity is refused only for keys read.
                if (
                    (row["db_model"] or "").lower() != namespace
                    or row["db_category"] is not None
                    or row["db_attrtype"] is not None
                ):
                    continue
                key = row["db_key"].lower()
                if key not in record["read_keys"]:
                    # Do not deserialize arbitrary unrelated gameplay values.
                    continue
                if key in record["attributes"]:
                    record["duplicate_attributes"].add(key)
                record["attributes"][key] = _plain(from_pickle(row["db_value"]))
                record["attribute_rows"][key] = row
                owned_attribute_ids.add(pk)
            elif row["db_model"] == namespace and row["db_tagtype"] == "alias":
                record["aliases"].append(row["db_key"])
    if owned_attribute_ids:
        relation = model._meta.get_field("db_attributes")
        through = relation.remote_field.through
        seen = set()
        for pk in through.objects.filter(
            **{f"{relation.m2m_reverse_field_name()}_id__in": owned_attribute_ids}
        ).values_list(f"{relation.m2m_reverse_field_name()}_id", flat=True):
            if pk in seen:
                raise ReplacementError(
                    "A builder-owned Attribute is shared with another object; staff inspection is required"
                )
            seen.add(pk)
    for obj in objects:
        for handler in (obj.attributes, obj.aliases, obj.tags, obj.permissions):
            handler.reset_cache()
        obj.locks.reset()
    return records


def _require_actor(project, actor):
    """Use persisted web-account authority, as the ritual staff decision does.

    Keep this local to replacement: the independently reviewed ritual helper
    also accepts character actors, which the web project ownership model does
    not. Scalar/through reads bypass stale account, permission and quell caches.
    """
    from evennia.accounts.models import AccountDB

    if not isinstance(actor, AccountDB) or not actor.pk or actor._state.adding:
        raise ReplacementError("A persisted active Builder account is required", status=403)
    account = AccountDB.objects.filter(pk=actor.pk).values("is_active", "is_superuser").first()
    if not account or not account["is_active"]:
        raise ReplacementError("A persisted active Builder account is required", status=403)
    quell = (
        AccountDB.objects.filter(
            pk=actor.pk,
            db_attributes__db_key__iexact="_quell",
            db_attributes__db_category__isnull=True,
            db_attributes__db_attrtype__isnull=True,
        )
        .values_list("db_attributes__db_value", flat=True)
        .first()
    )
    permissions = {
        str(permission).casefold()
        for permission in AccountDB.objects.filter(
            pk=actor.pk,
            db_tags__db_tagtype="permission",
        ).values_list("db_tags__db_key", flat=True)
    }
    hierarchy = [str(permission).casefold() for permission in settings.PERMISSION_HIERARCHY]

    def permitted(permission):
        allowed = set(hierarchy[hierarchy.index(permission) :]) if permission in hierarchy else {permission}
        return bool(account["is_superuser"] and not quell) or bool(permissions & allowed)

    if not permitted("builder") or (project.user_id != actor.pk and not permitted("admin")):
        raise ReplacementError("Current persisted Builder ownership or Admin authority is required", status=403)


def _attributes(obj, keys, fresh=None):
    if fresh is not None:
        if keys - fresh["read_keys"]:
            raise ReplacementError("Fresh snapshot does not cover the requested builder-owned Attributes")
        if fresh["duplicate_attributes"] & keys:
            raise ReplacementError(f"Object #{obj.pk} has ambiguous builder-owned Attributes")
        values = fresh["attributes"]
        return {key: {"present": key in values, "value": _plain(values.get(key))} for key in keys}
    return {key: {"present": obj.attributes.has(key), "value": _plain(obj.attributes.get(key))} for key in keys}


def _restore_attributes(obj, attributes):
    for key, state in attributes.items():
        if state["present"]:
            obj.attributes.add(key, _plain(state["value"]))
        else:
            obj.attributes.remove(key)


def _object_state(obj, keys, fresh=None):
    if fresh is not None:
        row = fresh["fields"]
        return {
            "object_id": obj.pk,
            "key": row["db_key"],
            "location_id": row["db_location_id"],
            "destination_id": row["db_destination_id"],
            "home_id": row["db_home_id"],
            "locks": row["db_lock_storage"],
            "aliases": list(fresh["aliases"]),
            "attributes": _attributes(obj, keys, fresh),
        }
    return {
        "object_id": obj.pk,
        "key": obj.key,
        "location_id": obj.db_location_id,
        "destination_id": obj.db_destination_id,
        "home_id": obj.db_home_id,
        "locks": obj.db_lock_storage,
        "aliases": list(obj.aliases.all()),
        "attributes": _attributes(obj, keys),
    }


def _restore_object(state):
    from evennia.objects.models import ObjectDB

    obj = ObjectDB.objects.get(pk=state["object_id"])
    obj.key = state["key"]
    obj.location = ObjectDB.objects.filter(pk=state["location_id"]).first()
    obj.destination = ObjectDB.objects.filter(pk=state["destination_id"]).first()
    obj.home = ObjectDB.objects.filter(pk=state["home_id"]).first()
    obj.aliases.clear()
    if state["aliases"]:
        obj.aliases.add(state["aliases"])
    obj.locks.replace(state["locks"])
    _restore_attributes(obj, state["attributes"])
    obj.attributes.reset_cache()


def _timer_state(script, fresh=None):
    task = script.ndb._task
    return {
        "script_id": script.pk,
        "obj_id": script.db_obj_id,
        "interval": script.db_interval,
        "active": script.db_is_active,
        "running": bool(task and task.running),
        "remaining": script.time_until_next_repeat(),
        "callcount": task.callcount if task else 0,
        "attributes": _attributes(script, SCRIPT_KEYS, fresh),
    }


def _restore_timer(state, resume=True):
    from evennia.scripts.models import ScriptDB

    script = ScriptDB.objects.get(pk=state["script_id"])
    script.stop()
    script.db_obj_id = state["obj_id"]
    script.db_interval = state["interval"]
    script.db_is_active = state["active"]
    script.save(update_fields=["db_obj", "db_interval", "db_is_active"])
    _restore_attributes(script, state["attributes"])
    if state["running"] and resume:
        script.db._paused_time = max(state["remaining"] or 0, 0.000001)
        script.db._paused_callcount = state["callcount"]
        script.db._manually_paused = True
        script.unpause()


def _locks(value):
    result = {}
    for part in (value or "").split(";"):
        key, sep, expression = part.partition(":")
        if sep:
            result[key.strip()] = re.sub(r"\s+", "", expression).lower()
    return result


def _expect_attributes(obj, expected, owned, fresh=None):
    states = _attributes(obj, owned, fresh)
    for key in owned:
        present = states[key]["present"]
        if (key in expected and (not present or states[key]["value"] != expected[key])) or (
            key not in expected and present
        ):
            raise ReplacementError(
                f"Object #{obj.pk} has changed builder-owned field '{key}'; staff must review the drift"
            )


def _timed(map_data):
    return {
        f"{key}:{trigger['id']}": (key, trigger)
        for key, room in map_data["rooms"].items()
        for trigger in room.get("triggers") or []
        if trigger["type"] == "timed" and trigger.get("enabled", True)
    }


def _inventory(source, object_states=None, script_states=None):
    """Exact fresh DB identity checks, then checked live objects/typed fields."""
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    manifest, snapshot = source.live_manifest, source.approved_map_data
    data = snapshot["map_data"]
    kinds = {
        "rooms": sandbox_builder.ROOM_TYPECLASS,
        "exits": sandbox_builder.EXIT_TYPECLASS,
        "fixtures": FIXTURE_TYPECLASS,
    }
    expected = {"rooms": data["rooms"], "exits": data.get("exits", {}), "fixtures": snapshot.get("prototypes", {})}
    ids = []
    for kind in kinds:
        if set(manifest.get(kind, {})) != set(expected[kind]):
            raise ReplacementError("Live manifest does not match the approved stable map identities")
        ids.extend(entry["object_id"] for entry in manifest[kind].values())
    connectors = manifest.get("connection_exits", [])
    if len(connectors) != 2:
        raise ReplacementError("Live manifest has no exact two-way connection inventory")
    ids.extend(entry["object_id"] for entry in connectors)
    if len(set(ids)) != len(ids) or any(type(pk) is not int for pk in ids):
        raise ReplacementError("Live manifest identity is ambiguous")
    raw = {
        row["id"]: row
        for row in ObjectDB.objects.filter(pk__in=ids).values(
            "id", "db_typeclass_path", "db_key", "db_location_id", "db_destination_id", "db_account_id"
        )
    }
    if set(raw) != set(ids):
        raise ReplacementError("A recorded live object is missing")
    objects = {obj.pk: obj for obj in ObjectDB.objects.filter(pk__in=ids)}
    owned_keys = {"rooms": ROOM_KEYS, "exits": EXIT_KEYS, "fixtures": FIXTURE_KEYS}
    owned_by_id = {entry["object_id"]: owned_keys[kind] for kind in kinds for entry in manifest[kind].values()}
    owned_by_id.update({entry["object_id"]: EXIT_KEYS for entry in connectors})
    fresh_objects = _fresh_persisted(list(objects.values()), owned_by_id)
    raw = {pk: record["fields"] for pk, record in fresh_objects.items()}
    by_kind = {}
    for kind, typeclass in kinds.items():
        by_kind[kind] = {}
        for key, entry in manifest[kind].items():
            row, obj = raw[entry["object_id"]], objects[entry["object_id"]]
            if (
                entry["typeclass"] != typeclass
                or row["db_typeclass_path"] != typeclass
                or row["db_account_id"]
                or obj.sessions.count()
            ):
                raise ReplacementError(f"Recorded {kind} object #{obj.pk} has changed type or account identity")
            if kind == "rooms":
                if row["db_location_id"] is not None or row["db_destination_id"] is not None:
                    raise ReplacementError("A recorded live room moved or became an exit")
                expected_attrs = dict(sandbox_builder._room_attributes(data["rooms"][key]))
                expected_attrs["builder_revision"] = object_provenance(source, kind, key)
                owned = ROOM_KEYS
                expected_name = data["rooms"][key]["name"]
            elif kind == "exits":
                design = data["exits"][key]
                location_id = manifest["rooms"][design["source"]]["object_id"]
                destination_id = manifest["rooms"][design["target"]]["object_id"]
                if (
                    row["db_location_id"] != location_id
                    or row["db_destination_id"] != destination_id
                    or entry["location_id"] != location_id
                    or entry["destination_id"] != destination_id
                ):
                    raise ReplacementError("A recorded live exit moved or changed its destination")
                if {alias.lower() for alias in fresh_objects[obj.pk]["aliases"]} != {
                    alias.lower() for alias in design.get("aliases") or []
                }:
                    raise ReplacementError("Recorded exit aliases changed since review")
                wanted = {"traverse": "all()", "view": "all()", **_locks(design.get("locks"))}
                actual = _locks(obj.db_lock_storage)
                if any(actual.get(access) != value for access, value in wanted.items()):
                    raise ReplacementError("Recorded exit traversal/view locks changed since review")
                expected_attrs = dict(sandbox_builder._exit_attributes(design))
                expected_attrs["builder_revision"] = object_provenance(source, kind, key)
                owned, expected_name = EXIT_KEYS, design["name"]
            else:
                reviewed = snapshot["prototypes"][key]
                placement = reviewed["placement"]
                room_id = manifest["rooms"][placement["room_id"]]["object_id"]
                if (
                    row["db_location_id"] != room_id
                    or row["db_destination_id"] is not None
                    or entry["room_id"] != room_id
                ):
                    raise ReplacementError("A recorded live fixture moved or changed its placement")
                provenance = fixture_provenance(source, key, reviewed)
                if any(entry.get(field) != value for field, value in provenance.items()):
                    raise ReplacementError("A live fixture's approved manifest provenance changed")
                expected_attrs = dict(sandbox_builder._fixture_attributes(source, key, reviewed))
                owned = FIXTURE_KEYS
                expected_name = placement.get("name") or reviewed["definition"]["label"]
            if row["db_key"] != expected_name:
                raise ReplacementError(f"Object #{obj.pk} name differs from its reviewed design")
            _expect_attributes(obj, expected_attrs, owned, fresh_objects[obj.pk])
            if kind in ("rooms", "exits") and entry.get("provenance") != object_provenance(source, kind, key):
                raise ReplacementError("Live manifest object provenance is ambiguous")
            by_kind[kind][key] = obj
    entry_id = manifest["rooms"][entry_room_key(data)]["object_id"]
    if manifest.get("entry") != entry_id:
        raise ReplacementError("Live manifest entry identity differs from review")
    expected_links = [(snapshot["connection_room_id"], entry_id), (entry_id, snapshot["connection_room_id"])]
    for connector, (location_id, destination_id) in zip(connectors, expected_links, strict=True):
        row = raw[connector["object_id"]]
        if (
            connector["typeclass"] != sandbox_builder.EXIT_TYPECLASS
            or row["db_typeclass_path"] != sandbox_builder.EXIT_TYPECLASS
            or row["db_account_id"]
            or row["db_location_id"] != location_id
            or row["db_destination_id"] != destination_id
            or connector["location_id"] != location_id
            or connector["destination_id"] != destination_id
        ):
            raise ReplacementError("The reviewed live connection identity or endpoints changed")
        obj = objects[connector["object_id"]]
        old_direction = (
            snapshot["connection_direction"]
            if location_id == snapshot["connection_room_id"]
            else _get_opposite_direction(snapshot["connection_direction"])
        )
        if (
            obj.sessions.count()
            or row["db_key"] != DIRECTION_NAMES[old_direction]
            or set(fresh_objects[obj.pk]["aliases"]) != {old_direction}
        ):
            raise ReplacementError("A reviewed connection exit's name, aliases or sessions changed")
    room_ids = [obj.pk for obj in by_kind["rooms"].values()]
    fixture_ids = [obj.pk for obj in by_kind["fixtures"].values()]
    if ObjectDB.objects.filter(db_location_id__in=ids).exclude(pk__in=ids).exists():
        raise ReplacementError("Unreviewed contents or occupants (including NPCs) are inside the affected live area")
    if ObjectDB.objects.filter(db_location_id__in=fixture_ids).exists():
        raise ReplacementError("A recorded fixture has unreviewed contents")
    if (
        ObjectDB.objects.filter(Q(db_location_id__in=room_ids) | Q(db_destination_id__in=room_ids))
        .exclude(db_destination__isnull=True)
        .exclude(pk__in=ids)
        .exists()
    ):
        raise ReplacementError("An unreviewed foreign exit connects to the affected live area")
    timers, timed = {}, _timed(data)
    if set(manifest.get("scripts", {})) != set(timed):
        raise ReplacementError("Recorded timer inventory does not match the approved triggers")
    script_ids = [record["script_id"] for record in manifest["scripts"].values()]
    scripts = {script.pk: script for script in ScriptDB.objects.filter(pk__in=script_ids)}
    fresh_scripts = _fresh_persisted(list(scripts.values()), dict.fromkeys(scripts, SCRIPT_KEYS))
    for key, record in manifest["scripts"].items():
        script = scripts.get(record["script_id"])
        web_id, trigger = timed[key]
        config = (
            _attributes(script, {"trigger_id", "trigger_action", "trigger_parameters"}, fresh_scripts[script.pk])
            if script is not None
            else {}
        )
        if (
            script is None
            or record["typeclass"] != "typeclasses.scripts.RoomTriggerScript"
            or script.db_typeclass_path != record["typeclass"]
            or script.db_obj_id != by_kind["rooms"][web_id].pk
            or script.db_interval != trigger["interval"]
            or record["interval"] != script.db_interval
            or record["room_id"] != script.db_obj_id
            or record["trigger_id"] != trigger["id"]
            or config["trigger_id"]["value"] != trigger["id"]
            or config["trigger_action"]["value"] != trigger["action"]
            or config["trigger_parameters"]["value"] != trigger.get("parameters", {})
        ):
            raise ReplacementError("A recorded live timer changed identity or reviewed configuration")
        timers[key] = script
    if ScriptDB.objects.filter(db_obj_id__in=ids).exclude(pk__in=[s.pk for s in timers.values()]).exists():
        raise ReplacementError("An unreviewed Script is attached to the affected live area")
    if object_states is not None:
        object_states.update(fresh_objects)
    if script_states is not None:
        script_states.update(fresh_scripts)
    return by_kind, [objects[entry["object_id"]] for entry in connectors], timers


def _validate_connection(project, source, connectors):
    from evennia.objects.models import ObjectDB

    snapshot = project.approved_map_data
    room = ObjectDB.objects.filter(pk=snapshot["connection_room_id"]).first()
    if room is not None:
        _fresh_persisted([room])
        # is_typeclass uses the loaded Python class, not the persisted path.
        # A different-process swap therefore needs explicit staff inspection.
        if room.path != room.db_typeclass_path:
            raise ReplacementError("Reviewed attachment room changed its persisted typeclass")
    errors, room_id, direction = validate_connection(snapshot["connection_room_id"], snapshot["connection_direction"])
    if errors:
        raise ReplacementError("; ".join(errors))
    if room_id in {entry["object_id"] for entry in source.live_manifest["rooms"].values()}:
        raise ReplacementError("The reviewed connection must be outside the replaced area")
    if not is_live_room(room):
        raise ReplacementError("Reviewed attachment room is no longer live")
    ignored = {obj.pk for obj in connectors}
    wanted = {direction, DIRECTION_NAMES[direction]}
    exits = list(ObjectDB.objects.filter(db_location_id=room_id).exclude(db_destination__isnull=True))
    _fresh_persisted(exits)
    if any(obj.pk not in ignored and _exit_names(obj) & wanted for obj in exits):
        raise ReplacementError("The reviewed live connection direction is occupied")
    entry = entry_room_key(snapshot["map_data"])
    back = _get_opposite_direction(direction)
    wanted = {back, DIRECTION_NAMES[back]}
    for exit_data in snapshot["map_data"].get("exits", {}).values():
        if (
            exit_data["source"] == entry
            and {exit_data["name"].lower(), *(alias.lower() for alias in exit_data.get("aliases") or [])} & wanted
        ):
            raise ReplacementError("The reviewed entry room's connecting direction conflicts with an internal exit")
    return room, direction


def _record_journal(project, journal):
    if not BuildProject.objects.filter(pk=project.pk, status="replacing", version=project.version).update(
        replacement_journal=journal, updated_at=timezone.now()
    ):
        raise ReplacementError("Replacement record changed during execution")


def _record_addition(project, journal, obj, kind):
    expected = {
        "rooms": sandbox_builder.ROOM_TYPECLASS,
        "exits": sandbox_builder.EXIT_TYPECLASS,
        "fixtures": FIXTURE_TYPECLASS,
    }[kind]
    journal["created_object_ids"].append(obj.pk)
    receipt = {"object_id": obj.pk, "typeclass": expected, "kind": kind}
    journal["created_objects"].append(receipt)
    append_receipt(project, object_receipt=receipt)
    if obj.db_typeclass_path != expected or obj.db_account_id or obj.sessions.count():
        raise ReplacementError("A staged addition has an unexpected type or account identity")


def _guard_addition_delete(obj, journal):
    """Never let Evennia's addition deletion cascade onto a retained object.

    If restoration left an old exit/fixture/timer attached to a staged room,
    retain that room and the unfinished claim for staff inspection instead.
    """
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    record = next(entry for entry in journal["created_objects"] if entry["object_id"] == obj.pk)
    raw = ObjectDB.objects.filter(pk=obj.pk).values("db_typeclass_path", "db_account_id").first()
    if raw is None:
        return
    if raw["db_typeclass_path"] != record["typeclass"] or raw["db_account_id"] or obj.sessions.count():
        raise RuntimeError(f"Recorded addition #{obj.pk} changed type or account identity; retained for inspection")
    if (
        ObjectDB.objects.filter(Q(db_location_id=obj.pk) | Q(db_destination_id=obj.pk))
        .exclude(pk__in=journal["created_object_ids"])
        .exists()
    ):
        raise RuntimeError(
            f"Recorded addition #{obj.pk} still has retained or foreign links/contents; retained for inspection"
        )
    if ScriptDB.objects.filter(db_obj_id=obj.pk).exclude(pk__in=journal["created_script_ids"]).exists():
        raise RuntimeError(
            f"Recorded addition #{obj.pk} still hosts a retained or foreign timer; retained for inspection"
        )


def _claim(project, source, root, journal, actor):
    with transaction.atomic():
        _require_actor(project, actor)
        if not BuildProject.objects.filter(
            pk=source.pk, status="live", version=source.version, live_manifest=source.live_manifest
        ).exists():
            raise ReplacementError("Live source changed before replacement claim")
        if not BuildProject.objects.filter(
            pk=root.pk, current_live_revision_id=source.pk, replacement_claim__isnull=True
        ).update(replacement_claim=project):
            raise ReplacementError("Another replacement already claimed this lineage")
        if not BuildProject.objects.filter(
            pk=project.pk,
            user_id=project.user_id,
            status="approved",
            version=project.version,
            approved_map_data=project.approved_map_data,
        ).update(status="replacing", replacement_journal=journal, updated_at=timezone.now()):
            raise ReplacementError("Candidate changed before replacement claim")


def _bulk_new_attributes(pending):
    """Persist new plain builder metadata and its links as one DB-only unit.

    Existing Attribute writes still use model.save for monitors and hooks.
    These new rows have no prior identity or monitors; their row shape matches
    the normal handler, as in sandbox_builder's creation adapter. No object
    movement, model save hooks, timer or handler operation runs in the atomic.
    """
    if not pending:
        return
    from evennia.objects.models import ObjectDB
    from evennia.typeclasses.attributes import Attribute

    rows = [
        Attribute(
            db_key=key,
            db_category=None,
            db_model="objectdb",
            db_attrtype=None,
            db_lock_storage="",
            db_value=to_pickle(value),
            db_strvalue=None,
        )
        for _, key, value in pending
    ]
    try:
        with transaction.atomic():
            Attribute.objects.bulk_create(rows)
            if any(row.pk is None for row in rows):
                raise RuntimeError("The database did not return ids for new builder Attributes")
            link = ObjectDB.db_attributes.through
            link.objects.bulk_create(
                [link(objectdb_id=obj.pk, attribute_id=row.pk) for (obj, _, _), row in zip(pending, rows, strict=True)]
            )
    except BaseException:
        # Rollback does not undo Python PK assignments or idmapper hydration
        # by a failed link writer. Evict before a subsequent insert reuses IDs.
        for row in rows:
            if row.pk:
                Attribute.flush_cached_instance(row)
        raise
    finally:
        # Failed inserts must not leave cached associations visible to undo.
        for obj in {obj.pk: obj for obj, _, _ in pending}.values():
            obj.attributes.reset_cache()


def _set_attributes(obj, expected, owned):
    """Read current handlers per key so synchronous callbacks remain visible.

    The preflight scalar refresh prevents stale idmapper values. Warming the
    handler loads present rows without deserializing unrelated gameplay data;
    subsequent per-key reads also observe ordinary callback add/remove/update.
    A snapshot-only diff here could skip reviewed values or duplicate a key.
    """
    obj.attributes.all()
    for key in owned:
        attr = obj.attributes.get(key, return_obj=True)
        if key in expected:
            value = _plain(expected[key])
            if attr is None:
                # Persist before another owned key's save can run callbacks.
                _bulk_new_attributes([(obj, key, value)])
            elif _plain(attr.value) != value:
                attr.db_value, attr.db_strvalue = to_pickle(value), None
                attr.save(update_fields=["db_value", "db_strvalue"])
        elif attr is not None:
            obj.attributes.remove(key)


def _capture_object(obj, keys):
    fresh = _fresh_persisted([obj], {obj.pk: set(keys)})[obj.pk]
    state = _object_state(obj, set(keys), fresh)
    state.update(
        typeclass=fresh["fields"]["db_typeclass_path"],
        account_id=fresh["fields"]["db_account_id"],
        sessions=obj.sessions.count(),
    )
    return state


def _capture_script(script):
    fresh = _fresh_persisted([script], {script.pk: SCRIPT_KEYS})[script.pk]
    fields = fresh["fields"]
    return {
        "typeclass": fields["db_typeclass_path"],
        "obj_id": fields["db_obj_id"],
        "interval": fields["db_interval"],
        "active": fields["db_is_active"],
        "attributes": _attributes(script, SCRIPT_KEYS, fresh),
    }


def _audit_object(context, obj, keys, *, remember=False):
    if context is None:
        return
    current = _capture_object(obj, keys)
    previous = context["observed_objects"].get(str(obj.pk))
    # Ordinary hook calls still run under the step token. If they mutate a
    # different reviewed object, conservatively retain that actual state and
    # the fence for inspection, just as for raw between-callback drift. Never
    # silently bless unreviewed data or overwrite it during compensation.
    if not remember and previous is not None and current != previous:
        raise ReplacementError(f"Object #{obj.pk} changed between builder steps; inspection is required")
    if remember:
        context["observed_objects"][str(obj.pk)] = current


def _audit_script(context, script, *, remember=False):
    if context is None:
        return
    current = _capture_script(script)
    previous = context["observed_scripts"].get(str(script.pk))
    if not remember and previous is not None and current != previous:
        raise ReplacementError(f"Timer #{script.pk} changed between builder steps; inspection is required")
    if remember:
        context["observed_scripts"][str(script.pk)] = current


def _check_affected_links(context):
    """Retired identities remain protected, even when absent from the new map."""
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    ids = list(map(int, context["observed_objects"]))
    if ObjectDB.objects.filter(Q(db_location_id__in=ids) | Q(db_destination_id__in=ids)).exclude(pk__in=ids).exists():
        raise ReplacementError("Foreign contents or ingress touches an affected object; inspection required")
    if ScriptDB.objects.filter(db_obj_id__in=ids).exclude(pk__in=list(map(int, context["observed_scripts"]))).exists():
        raise ReplacementError("An unexpected Script touches an affected object; inspection required")


def _audit_all_affected(context):
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    ids = set(map(int, context["observed_objects"]))
    objects = list(ObjectDB.objects.filter(pk__in=ids))
    if {obj.pk for obj in objects} != ids:
        raise ReplacementError("An affected object disappeared between steps; inspection required")
    owned = {obj.pk: set(context["observed_objects"][str(obj.pk)]["attributes"]) for obj in objects}
    fresh = _fresh_persisted(objects, owned)
    for obj in objects:
        current = _object_state(obj, owned[obj.pk], fresh[obj.pk])
        current.update(
            typeclass=fresh[obj.pk]["fields"]["db_typeclass_path"],
            account_id=fresh[obj.pk]["fields"]["db_account_id"],
            sessions=obj.sessions.count(),
        )
        if current != context["observed_objects"][str(obj.pk)]:
            raise ReplacementError(f"Affected object #{obj.pk} changed between steps; inspection required")
    ids = set(map(int, context["observed_scripts"]))
    scripts = list(ScriptDB.objects.filter(pk__in=ids))
    if {script.pk for script in scripts} != ids:
        raise ReplacementError("An affected timer disappeared between steps; inspection required")
    fresh = _fresh_persisted(scripts, dict.fromkeys(ids, SCRIPT_KEYS))
    for script in scripts:
        fields = fresh[script.pk]["fields"]
        current = {
            "typeclass": fields["db_typeclass_path"],
            "obj_id": fields["db_obj_id"],
            "interval": fields["db_interval"],
            "active": fields["db_is_active"],
            "attributes": _attributes(script, SCRIPT_KEYS, fresh[script.pk]),
        }
        if current != context["observed_scripts"][str(script.pk)]:
            raise ReplacementError(f"Affected timer #{script.pk} changed between steps; inspection required")
    _check_affected_links(context)


def _apply_design_steps(project, rooms, exits, fixtures, connectors, connection_room, direction, audit=None):
    data, definitions = project.approved_map_data["map_data"], project.approved_map_data.get("prototypes", {})
    for key, obj in rooms.items():
        _audit_object(audit, obj, ROOM_KEYS)
        if obj.key != data["rooms"][key]["name"]:
            obj.key = data["rooms"][key]["name"]
        attrs = dict(sandbox_builder._room_attributes(data["rooms"][key]))
        attrs["builder_revision"] = object_provenance(project, "rooms", key)
        _set_attributes(obj, attrs, ROOM_KEYS)
        _audit_object(audit, obj, ROOM_KEYS, remember=True)
        yield
    for key, obj in exits.items():
        _audit_object(audit, obj, EXIT_KEYS)
        design = data["exits"][key]
        if obj.key != design["name"]:
            obj.key = design["name"]
        if set(obj.aliases.all()) != set(design.get("aliases") or []):
            obj.aliases.clear()
            if design.get("aliases"):
                obj.aliases.add(design["aliases"])
        if obj.db_location_id != rooms[design["source"]].pk:
            obj.location = rooms[design["source"]]
        if obj.db_destination_id != rooms[design["target"]].pk:
            obj.destination = rooms[design["target"]]
        if obj.db_home_id != rooms[design["source"]].pk:
            obj.home = rooms[design["source"]]
        wanted = {"traverse": "all()", "view": "all()", **_locks(design.get("locks"))}
        actual = _locks(obj.db_lock_storage)
        if any(actual.get(access) != value for access, value in wanted.items()):
            obj.locks.add("traverse:all();view:all()")
            if design.get("locks"):
                obj.locks.add(design["locks"])
        attrs = dict(sandbox_builder._exit_attributes(design))
        attrs["builder_revision"] = object_provenance(project, "exits", key)
        _set_attributes(obj, attrs, EXIT_KEYS)
        _audit_object(audit, obj, EXIT_KEYS, remember=True)
        yield
    for key, obj in fixtures.items():
        _audit_object(audit, obj, FIXTURE_KEYS)
        reviewed = definitions[key]
        name = reviewed["placement"].get("name") or reviewed["definition"]["label"]
        if obj.key != name:
            obj.key = name
        room = rooms[reviewed["placement"]["room_id"]]
        if obj.db_location_id != room.pk:
            obj.location = room
        if obj.db_home_id != room.pk:
            obj.home = room
        if any(_locks(obj.db_lock_storage).get(access) != value for access, value in _locks(FIXTURE_LOCKS).items()):
            obj.locks.add(FIXTURE_LOCKS)
        _set_attributes(
            obj,
            dict(sandbox_builder._fixture_attributes(project, key, reviewed)),
            FIXTURE_KEYS,
        )
        _audit_object(audit, obj, FIXTURE_KEYS, remember=True)
        yield
    entry = rooms[entry_room_key(data)]
    for obj, name, location, destination in (
        (connectors[0], direction, connection_room, entry),
        (connectors[1], _get_opposite_direction(direction), entry, connection_room),
    ):
        _audit_object(audit, obj, EXIT_KEYS)
        if obj.key != DIRECTION_NAMES[name]:
            obj.key = DIRECTION_NAMES[name]
        if set(obj.aliases.all()) != {name}:
            obj.aliases.clear()
            obj.aliases.add(name)
        if obj.db_location_id != location.pk:
            obj.location = location
        if obj.db_destination_id != destination.pk:
            obj.destination = destination
        if obj.db_home_id != location.pk:
            obj.home = location
        _audit_object(audit, obj, EXIT_KEYS, remember=True)
        yield


def _retire_steps(project, source, old, current, scripts, desired_timers, audit=None):
    if audit is not None:
        _check_affected_links(audit)
    retired = {"objects": {}, "scripts": {}}
    pending = []
    for kind in ("fixtures", "exits", "rooms"):
        for key in set(old[kind]) - set(current[kind]):
            obj = old[kind][key]
            keys = {"rooms": ROOM_KEYS, "exits": EXIT_KEYS, "fixtures": FIXTURE_KEYS}[kind]
            _audit_object(audit, obj, keys)
            retired["objects"][str(obj.pk)] = {
                "kind": kind,
                "map_id": key,
                "typeclass": obj.db_typeclass_path,
                "source_project_id": source.pk,
            }
            if obj.db_location_id is not None:
                obj.location = None
            if obj.db_destination_id is not None:
                obj.destination = None
            if obj.db_home_id is not None:
                obj.home = None
            obj.locks.add("traverse:false();view:false();get:false();puppet:false()")
            pending.append(
                (obj, "builder_retired", {"source_project_id": source.pk, "replacement_project_id": project.pk})
            )
            _bulk_new_attributes(pending)
            pending.clear()
            _audit_object(audit, obj, keys, remember=True)
            yield
    for key in set(scripts) - set(desired_timers):
        script = scripts[key]
        _audit_script(audit, script)
        retired["scripts"][str(script.pk)] = {
            "trigger_key": key,
            "source_project_id": source.pk,
            "room_id": script.db_obj_id,
            "typeclass": script.db_typeclass_path,
        }
        script.stop()
        script.db_obj_id = None
        script.save(update_fields=["db_obj"])
        _audit_script(audit, script, remember=True)
        yield
    return retired


def _publish(project, source, root, manifest, retired, journal):
    journal["state"] = "complete"
    journal["completed_at"] = timezone.now().isoformat()
    with transaction.atomic():
        if not BuildProject.objects.filter(
            pk=source.pk, status="live", version=source.version, live_manifest=source.live_manifest
        ).update(status="superseded", updated_at=timezone.now()):
            raise ReplacementError("Live source changed before publication")
        if not BuildProject.objects.filter(
            pk=root.pk, current_live_revision_id=source.pk, replacement_claim_id=project.pk
        ).update(current_live_revision=project, replacement_claim=None):
            raise ReplacementError("Lineage publication claim changed")
        if not BuildProject.objects.filter(pk=project.pk, status="replacing", version=project.version).update(
            status="live",
            promoted_at=timezone.now(),
            live_manifest=manifest,
            retired_manifest=retired,
            replacement_journal=journal,
            updated_at=timezone.now(),
        ):
            raise ReplacementError("Candidate changed before publication")


def _compensate_steps(project, source, root, journal, additions, created_scripts, operation=None, audit=None):
    errors = []
    for state in journal["saved_objects"].values():
        try:
            if audit is not None:
                from evennia.objects.models import ObjectDB

                _audit_object(audit, ObjectDB.objects.get(pk=state["object_id"]), set(state["attributes"]))
                if state["object_id"] in {obj.pk for obj in audit["connectors"]}:
                    _validate_connection(source, source, audit["connectors"])
            _restore_object(state)
        except Exception as exc:
            logger.exception("Replacement undo: object #%s failed", state["object_id"])
            errors.append(f"object #{state['object_id']}: {exc}")
        yield
    for script in reversed(created_scripts):
        try:
            _audit_script(audit, script)
            script.stop()
            script.delete()
        except Exception as exc:
            logger.exception("Replacement undo: new timer failed")
            errors.append(f"new timer: {exc}")
        yield
    for state in journal["saved_scripts"].values():
        try:
            if audit is not None:
                from evennia.scripts.models import ScriptDB

                _audit_script(audit, ScriptDB.objects.get(pk=state["script_id"]))
            _restore_timer(state, resume=operation is None)
        except Exception as exc:
            logger.exception("Replacement undo: timer #%s failed", state["script_id"])
            errors.append(f"timer #{state['script_id']}: {exc}")
        yield
    for obj in reversed(additions):
        try:
            if obj.pk:
                if audit is not None:
                    keys = set(audit["observed_objects"][str(obj.pk)]["attributes"])
                    _audit_object(audit, obj, keys)
                    if errors and obj.db_typeclass_path == sandbox_builder.ROOM_TYPECLASS:
                        raise ReplacementError("A staged room is retained because earlier compensation failed")
                _guard_addition_delete(obj, journal)
                if not obj.delete():
                    raise RuntimeError("Evennia refused recorded addition deletion")
        except Exception as exc:
            logger.exception("Replacement undo: recorded addition failed")
            errors.append(f"new object: {exc}")
        yield
    if operation is not None and not errors:
        try:
            # Raw SQL/another process can bypass runtime ingress fences. Never
            # release a restored area with unexpected contents/exits/timers.
            _inventory(source)
        except Exception as exc:
            errors.append(f"restored inventory: {exc}")
    if operation is not None and not errors:
        from evennia.scripts.models import ScriptDB

        for state in journal["saved_scripts"].values():
            if state["running"]:
                script = ScriptDB.objects.get(pk=state["script_id"])
                script.db._paused_time = max(state["remaining"] or 0, 0.000001)
                script.db._paused_callcount = state["callcount"]
                script.db._manually_paused = True
                script.unpause()
    journal["compensation_errors"] = errors
    journal.pop("completed_at", None)
    journal["state"] = "compensation_failed" if errors else "rolled_back"
    try:
        with transaction.atomic():
            if not BuildProject.objects.filter(pk=project.pk, status="replacing", version=project.version).update(
                status="replacement_failed" if errors else "approved",
                replacement_journal=journal,
                updated_at=timezone.now(),
            ):
                raise ReplacementError("Candidate record could not be restored")
            if not errors and not BuildProject.objects.filter(
                pk=root.pk, current_live_revision_id=source.pk, replacement_claim_id=project.pk
            ).update(replacement_claim=None):
                raise ReplacementError("Lineage claim could not be released")
    except Exception as exc:
        logger.exception("Replacement undo: record restoration failed")
        errors.append(f"record restoration: {exc}")
    if operation is not None:
        operation_runtime.finish_operation(
            operation,
            state="failed" if errors else "rolled_back",
            phase="compensation_failed" if errors else "rolled_back",
            release=not errors,
        )
    return errors


def _compensate(project, source, root, journal, additions, created_scripts):
    return sandbox_builder._drain_steps(_compensate_steps(project, source, root, journal, additions, created_scripts))


def _prepare_replacement(project_id, actor, expected_version):
    """Preflight exact reviewed identity and capture fresh before-state."""
    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise ReplacementError("Project not found", status=404)
    _require_actor(project, actor)
    if type(expected_version) is not int:
        raise ReplacementError("version is required", status=400)
    if project.status != "approved" or project.version != expected_version or project.has_sandbox():
        raise ReplacementError("Replacement must be approved at this version and its test sandbox cleaned up first")
    snapshot = project.approved_map_data or {}
    plan = snapshot.get("replacement") or {}
    if project.revision_intent != "replacement" or plan.get("target") != project.replacement_target:
        raise ReplacementError("No explicitly approved replacement target")
    if plan.get("design_hash") != approved_snapshot_hash(replacement_design(snapshot)):
        raise ReplacementError("Approved replacement plan does not match this design")
    errors = validate_build_map(snapshot.get("map_data"), resolved_prototypes=snapshot.get("prototypes", {}))
    if errors:
        raise ReplacementError("Reviewed replacement is invalid: " + "; ".join(errors[:5]))
    try:
        source, root = current_replacement_source(project.replacement_target)
    except RevisionError as exc:
        raise ReplacementError(str(exc), status=exc.status) from exc
    reviewed_lineage = {"revision_of_id": source.pk, "root_project_id": root.pk, "intent": "replacement"}
    if (
        project.lineage_root_id != root.pk
        or project.revision_of_id != source.pk
        or project.user_id != source.user_id
        or snapshot.get("revision") != reviewed_lineage
    ):
        raise ReplacementError("The candidate lineage or ownership differs from its exact reviewed source")
    if root.replacement_claim_id is not None or plan.get("source_manifest") != source.live_manifest:
        raise ReplacementError("The exact reviewed live inventory is no longer current or has an unfinished claim")
    try:
        fresh_objects, fresh_scripts = {}, {}
        old, connectors, old_scripts = _inventory(source, fresh_objects, fresh_scripts)
        connection_room, direction = _validate_connection(project, source, connectors)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ReplacementError("Live inventory is malformed or ambiguous; staff inspection is required") from exc
    saved = {}
    for kind, keys in (("rooms", ROOM_KEYS), ("exits", EXIT_KEYS), ("fixtures", FIXTURE_KEYS)):
        saved.update({str(obj.pk): _object_state(obj, keys, fresh_objects[obj.pk]) for obj in old[kind].values()})
    saved.update({str(obj.pk): _object_state(obj, EXIT_KEYS, fresh_objects[obj.pk]) for obj in connectors})
    journal = {
        "state": "applying",
        "actor_id": actor.pk,
        "started_at": timezone.now().isoformat(),
        "target": project.replacement_target,
        "saved_objects": saved,
        "saved_scripts": {
            str(script.pk): _timer_state(script, fresh_scripts[script.pk]) for script in old_scripts.values()
        },
        "created_object_ids": [],
        "created_objects": [],
        "created_script_ids": [],
    }
    return {
        "project": project,
        "source": source,
        "root": root,
        "journal": journal,
        "old": old,
        "connectors": connectors,
        "old_scripts": old_scripts,
        "connection_room": connection_room,
        "direction": direction,
        "additions": [],
        "created_scripts": [],
        "observed_objects": {
            pk: {
                **copy.deepcopy(state),
                "typeclass": fresh_objects[int(pk)]["fields"]["db_typeclass_path"],
                "account_id": fresh_objects[int(pk)]["fields"]["db_account_id"],
                "sessions": 0,
            }
            for pk, state in saved.items()
        },
        "observed_scripts": {
            str(script.pk): {
                "typeclass": fresh_scripts[script.pk]["fields"]["db_typeclass_path"],
                "obj_id": fresh_scripts[script.pk]["fields"]["db_obj_id"],
                "interval": fresh_scripts[script.pk]["fields"]["db_interval"],
                "active": fresh_scripts[script.pk]["fields"]["db_is_active"],
                "attributes": _attributes(script, SCRIPT_KEYS, fresh_scripts[script.pk]),
            }
            for script in old_scripts.values()
        },
    }


def _replacement_steps(context, operation=None):
    project, source, root, journal = (context[name] for name in ("project", "source", "root", "journal"))
    old, connectors, old_scripts = (context[name] for name in ("old", "connectors", "old_scripts"))
    connection_room, direction = context["connection_room"], context["direction"]
    additions, created_scripts = context["additions"], context["created_scripts"]
    snapshot = project.approved_map_data
    audit = context if operation is not None else None
    try:
        for script in old_scripts.values():
            _audit_script(audit, script)
            script.pause()
            _audit_script(audit, script, remember=True)
            yield
        data, definitions = snapshot["map_data"], snapshot.get("prototypes", {})
        current = {
            kind: {key: obj for key, obj in old[kind].items() if key in desired}
            for kind, desired in (("rooms", data["rooms"]), ("exits", data.get("exits", {})), ("fixtures", definitions))
        }
        for key, design in data["rooms"].items():
            if key not in current["rooms"]:
                if operation is not None:
                    operation_runtime.creation_pending(operation, "rooms", key, sandbox_builder.ROOM_TYPECLASS)
                obj = sandbox_builder._create_room(project.pk, key, design)
                additions.append(obj)
                current["rooms"][key] = obj
                _record_addition(project, journal, obj, "rooms")
                if operation is not None:
                    operation_runtime.record_created(operation, obj, "rooms", key)
                    _audit_object(audit, obj, ROOM_KEYS, remember=True)
                yield
        for key, design in data.get("exits", {}).items():
            if key not in current["exits"]:
                if operation is not None:
                    operation_runtime.creation_pending(operation, "exits", key, sandbox_builder.EXIT_TYPECLASS)
                obj = sandbox_builder._create_exit(project.pk, key, design, current["rooms"])
                additions.append(obj)
                current["exits"][key] = obj
                _record_addition(project, journal, obj, "exits")
                if operation is not None:
                    operation_runtime.record_created(operation, obj, "exits", key)
                    _audit_object(audit, obj, EXIT_KEYS, remember=True)
                yield
        for key, reviewed in definitions.items():
            if key not in current["fixtures"]:
                if operation is not None:
                    operation_runtime.creation_pending(operation, "fixtures", key, FIXTURE_TYPECLASS)
                obj = sandbox_builder._create_fixture(reviewed, current["rooms"])
                additions.append(obj)
                current["fixtures"][key] = obj
                _record_addition(project, journal, obj, "fixtures")
                if operation is not None:
                    operation_runtime.record_created(operation, obj, "fixtures", key)
                    _audit_object(audit, obj, FIXTURE_KEYS, remember=True)
                yield
        if additions:
            sandbox_builder._bulk_tag_and_set(
                [(obj, []) for obj in additions], sandbox_builder.project_tags(project.pk)
            )
        _checkpoint("after_additions")
        yield from _apply_design_steps(
            project,
            current["rooms"],
            current["exits"],
            current["fixtures"],
            connectors,
            connection_room,
            direction,
            audit,
        )
        _checkpoint("after_apply")
        desired_timers = _timed(data)
        retired = yield from _retire_steps(project, source, old, current, old_scripts, desired_timers, audit)
        _checkpoint("after_retire")
        timers = {}
        resume = []
        for key, (web_id, trigger) in desired_timers.items():
            if key in old_scripts:
                script = old_scripts[key]
                _audit_script(audit, script)
                old_trigger = _timed(source.approved_map_data["map_data"])[key][1]
                if script.db_interval != trigger["interval"]:
                    script.db_interval = trigger["interval"]
                    script.save(update_fields=["db_interval"])
                for attrkey, wanted in (
                    ("trigger_action", trigger["action"]),
                    ("trigger_parameters", _plain(trigger.get("parameters", {}))),
                ):
                    if _plain(script.attributes.get(attrkey)) != wanted:
                        script.attributes.add(attrkey, wanted)
                old_state = journal["saved_scripts"][str(script.pk)]
                if old_state["running"]:
                    resume.append((script, trigger["interval"], trigger["interval"] == old_trigger["interval"]))
            else:
                if operation is not None:
                    operation_runtime.creation_pending(
                        operation, "scripts", key, "typeclasses.scripts.RoomTriggerScript"
                    )
                script = start_timed_trigger(current["rooms"][web_id], trigger)
                created_scripts.append(script)
                journal["created_script_ids"].append(script.pk)
                append_receipt(project, script_id=script.pk)
                if operation is not None:
                    script.pause()
                    operation_runtime.record_created(operation, script, "scripts", key)
                    resume.append((script, trigger["interval"], True))
            timers[key] = script
            _audit_script(audit, script, remember=True)
            yield
        _checkpoint("after_timers")
        project.built_object_ids = {
            "rooms": {key: obj.pk for key, obj in current["rooms"].items()},
            "exits": {key: obj.pk for key, obj in current["exits"].items()},
            "fixtures": {key: obj.pk for key, obj in current["fixtures"].items()},
            "entry": current["rooms"][entry_room_key(data)].pk,
            "scripts": [script.pk for script in timers.values()],
        }
        project.fixture_manifest = (
            fixture_manifest(project, current["fixtures"], current["rooms"]) if current["fixtures"] else {}
        )
        if additions:
            _remove_tags(additions, ["sandbox", f"project_{project.pk}"])
        manifest = live_manifest(project, list(current["rooms"].values()), list(current["exits"].values()), connectors)
        if operation is not None:
            project.live_manifest = manifest
            _audit_all_affected(context)
            _inventory(project)
        _checkpoint("before_commit")
        if operation is not None:
            _publish(project, source, root, manifest, retired, journal)
            context["published"] = True
            operation_runtime.update_operation(operation, status="live", phase="activation")
            yield
            _audit_all_affected(context)
            _validate_connection(project, source, connectors)
            _inventory(project)
        # Timer actions remain suppressed by the fence through activation.
        for script, interval, unchanged in resume:
            if unchanged:
                script.unpause()
            else:
                script.start(interval=interval, start_delay=interval)
            _audit_script(audit, script, remember=True)
        if operation is None:
            _publish(project, source, root, manifest, retired, journal)
        else:
            operation_runtime.finish_operation(operation)
    except BaseException as exc:
        if operation is not None:
            raise
        compensation = _compensate(project, source, root, journal, additions, created_scripts)
        if compensation:
            raise ReplacementError(
                "Replacement failed; compensation failed and staff inspection is required: " + "; ".join(compensation),
                status=500,
            ) from exc
        raise ReplacementError(f"Replacement failed; recorded changes were restored: {exc}", status=500) from exc
    return {
        "status": "live",
        "project_id": project.pk,
        "replaced_project_id": source.pk,
        "added_objects": len(additions),
        "retired_objects": len(retired["objects"]),
        "root_project_id": root.pk,
    }


def replace_live_unit(project_id, actor, expected_version):
    operation_runtime.require_idle()
    context = _prepare_replacement(project_id, actor, expected_version)
    _claim(context["project"], context["source"], context["root"], context["journal"], actor)
    return sandbox_builder._drain_steps(_replacement_steps(context))


def replace_deferred(project_id, actor, expected_version, *, clock=None):
    """Prepare exact inventory, then apply within the durable maintenance fence."""
    operation_runtime.require_idle()
    context = _prepare_replacement(project_id, actor, expected_version)
    project, source, root = (context[key] for key in ("project", "source", "root"))

    def validate(operation, current):
        if (
            current.user_id != project.user_id
            or current.root_project_id != project.root_project_id
            or current.revision_of_id != project.revision_of_id
            or current.revision_intent != "replacement"
            or current.replacement_target != project.replacement_target
        ):
            raise ReplacementError("Reviewed candidate ownership or lineage changed during replacement")
        if context.get("published"):
            if (
                not BuildProject.objects.filter(
                    pk=project.pk, status="live", live_manifest=project.live_manifest
                ).exists()
                or not BuildProject.objects.filter(
                    pk=root.pk,
                    current_live_revision_id=project.pk,
                    replacement_claim__isnull=True,
                ).exists()
            ):
                raise ReplacementError("Published lineage changed during activation")
            return
        if (
            not BuildProject.objects.filter(
                pk=source.pk,
                status="live",
                version=source.version,
                live_manifest=source.live_manifest,
                approved_map_data=source.approved_map_data,
                user_id=source.user_id,
            ).exists()
            or not BuildProject.objects.filter(
                pk=root.pk,
                current_live_revision_id=source.pk,
                replacement_claim_id=project.pk,
                user_id=root.user_id,
            ).exists()
        ):
            raise ReplacementError("Reviewed source or lineage claim changed during replacement")
        # Direction is reserved by checking the managed connectors plus current
        # external exits. Unrelated attachment-room traffic stays available.
        _validate_connection(current, source, context["connectors"])

    operation = operation_runtime.claim_operation(
        project_id,
        "replacement",
        actor,
        expected_version,
        affected_ids=[int(pk) for pk in context["journal"]["saved_objects"]],
        script_ids=[script.pk for script in context["old_scripts"].values()],
        source_id=source.pk,
        root_id=root.pk,
        connection_reservations=[
            {
                "room_id": int(snapshot["connection_room_id"]),
                "names": [snapshot["connection_direction"], DIRECTION_NAMES[snapshot["connection_direction"]]],
            }
            for snapshot in (source.approved_map_data, project.approved_map_data)
        ],
        claim_callback=lambda current: _claim(current, source, root, context["journal"], actor),
        validate=validate,
    )

    def compensate(error):
        if context.get("published"):
            operation_runtime.finish_operation(operation, state="failed", phase="activation_failed", release=False)
            return
        yield from _compensate_steps(
            project,
            source,
            root,
            context["journal"],
            context["additions"],
            context["created_scripts"],
            operation,
            context,
        )

    pending = operation_runtime.run_steps(
        operation,
        _replacement_steps(context, operation),
        compensate,
        clock=clock,
    )

    def terminal_error(failure):
        record = BuildProject.objects.filter(pk=project_id).values_list("builder_operation", flat=True).first() or {}
        restored = record.get("state") == "rolled_back"
        detail = (
            "recorded changes were restored" if restored else "staff inspection is required; maintenance fence retained"
        )
        raise ReplacementError(f"Replacement failed; {detail}: {failure.value}", status=500) from failure.value

    pending.addErrback(terminal_error)
    return pending


def replace_live(project_id, actor, expected_version):
    from twisted.internet import reactor

    driver = replace_deferred if reactor.running else replace_live_unit
    return call_in_main_thread(driver, project_id, actor, expected_version)
