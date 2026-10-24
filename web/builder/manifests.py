"""Recorded builder identities. Tags supplement these records, never create them.

Active fixture manifests stay v1. Live manifests are v2: exact object and
timer identities plus approved provenance and the publication lineage root.
"""

from .revisions import approved_snapshot_hash


def object_provenance(project, kind, map_id):
    return {"project_id": project.pk, "approved_version": project.version, "kind": kind, "map_id": map_id}


def script_manifest(project, rooms):
    from evennia.scripts.models import ScriptDB

    expected_ids = set(project.built_object_ids.get("scripts", []))
    scripts = list(ScriptDB.objects.filter(pk__in=expected_ids))
    by_id = {obj.pk: key for key, obj in rooms.items()}
    result = {}
    for script in scripts:
        web_id = by_id.get(script.db_obj_id)
        trigger_id = script.db.trigger_id
        triggers = project.approved_map_data["map_data"]["rooms"].get(web_id, {}).get("triggers", [])
        trigger = next((value for value in triggers if value["id"] == trigger_id), None)
        if (
            script.db_typeclass_path != "typeclasses.scripts.RoomTriggerScript"
            or trigger is None
            or trigger.get("type") != "timed"
            or not trigger.get("enabled", True)
            or script.db_interval != trigger["interval"]
        ):
            raise ValueError("Recorded timer differs from its reviewed definition")
        result[f"{web_id}:{trigger_id}"] = {
            "script_id": script.pk,
            "typeclass": script.db_typeclass_path,
            "room_id": script.db_obj_id,
            "trigger_id": trigger_id,
            "interval": script.db_interval,
        }
    if {entry["script_id"] for entry in result.values()} != expected_ids:
        raise ValueError("Recorded timer identity is missing or ambiguous")
    return result


def fixture_provenance(project, placement_id, reviewed):
    placement = reviewed["placement"]
    return {
        "project_id": project.pk,
        "placement_id": placement_id,
        "approved_version": project.version,
        "prototype_id": placement["prototype_id"],
        "prototype_revision": placement["prototype_revision"],
        "definition_hash": reviewed["definition_hash"],
    }


def fixture_manifest(project, fixtures, rooms):
    definitions = (project.approved_map_data or {}).get("prototypes", {})
    return {
        "schema_version": 1,
        "project_id": project.pk,
        "approved_version": project.version,
        "approved_snapshot_hash": approved_snapshot_hash(project.approved_map_data),
        "placements": {
            placement_id: {
                **fixture_provenance(project, placement_id, definitions[placement_id]),
                "object_id": obj.pk,
                "typeclass": obj.db_typeclass_path,
                "room_id": rooms[definitions[placement_id]["placement"]["room_id"]].pk,
                "map_room_id": definitions[placement_id]["placement"]["room_id"],
            }
            for placement_id, obj in fixtures.items()
        },
    }


def live_manifest(project, rooms, exits, connection_exits):
    """Caller has already verified all sandbox identities before mutating."""
    by_id = {obj.pk: obj for obj in rooms + exits}
    record = project.built_object_ids
    from evennia.objects.models import ObjectDB
    from evennia.utils.dbserialize import from_pickle

    rows = ObjectDB.db_attributes.through.objects.filter(
        objectdb_id__in=by_id,
        attribute__db_key="builder_revision",
        attribute__db_category__isnull=True,
        attribute__db_attrtype__isnull=True,
    ).values_list("objectdb_id", "attribute__db_value")
    provenance = {}
    for object_id, value in rows:
        if object_id in provenance:
            raise ValueError("Object provenance is ambiguous")
        provenance[object_id] = from_pickle(value)
    for kind in ("rooms", "exits"):
        for key, dbid in record[kind].items():
            if provenance.get(dbid) != object_provenance(project, kind, key):
                raise ValueError("Object provenance does not match the reviewed project")
    return {
        "schema_version": 2,
        "project_id": project.pk,
        "root_project_id": project.root_project_id,
        "approved_version": project.version,
        "approved_snapshot_hash": approved_snapshot_hash(project.approved_map_data),
        "rooms": {
            key: {
                "object_id": dbid,
                "typeclass": by_id[dbid].db_typeclass_path,
                "provenance": object_provenance(project, "rooms", key),
            }
            for key, dbid in record["rooms"].items()
        },
        "exits": {
            key: {
                "object_id": dbid,
                "typeclass": by_id[dbid].db_typeclass_path,
                "location_id": by_id[dbid].db_location_id,
                "destination_id": by_id[dbid].db_destination_id,
                "provenance": object_provenance(project, "exits", key),
            }
            for key, dbid in record["exits"].items()
        },
        "fixtures": (project.fixture_manifest or {}).get("placements", {}),
        "entry": record["entry"],
        "scripts": script_manifest(project, {key: by_id[dbid] for key, dbid in record["rooms"].items()}),
        "connection_exits": [
            {
                "object_id": obj.pk,
                "typeclass": obj.db_typeclass_path,
                "location_id": obj.db_location_id,
                "destination_id": obj.db_destination_id,
            }
            for obj in connection_exits
        ],
    }
