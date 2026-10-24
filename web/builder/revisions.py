"""Pure Django revision records; this module never mutates game objects.

Live manifest v2 (populated by the verified promotion unit, never a client):
schema_version, project_id, approved_version, approved_snapshot_hash,
rooms/exits/fixtures mapping stable map ids to {object_id, typeclass}; fixtures
also bind prototype_id, prototype_revision and the reviewed definition hash.
Connection exits are recorded separately with exact ids and endpoint ids.
Rooms/exits bind per-object provenance; scripts bind stable room/trigger keys
to exact timer ids, types, rooms and reviewed intervals. Only the current
root publication pointer may authorize a replacement. Empty/v1 historical
manifests remain unverified for replacement until reviewed adoption.
"""

import copy
import hashlib
import json

from django.db import transaction

from web.permissions import has_perm

from .models import BuildProject


class RevisionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def approved_snapshot_hash(snapshot):
    """Bind exact reviewed design/connection/provenance using stable JSON."""
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fork_revision(project_id, actor, expected_version):
    """Copy reviewed design into an independent draft with source provenance.

    A short transaction keeps the version check and copied snapshot together;
    no reactor handoff or Evennia mutation is performed inside this transaction.
    There is deliberately no replacement authority in this operation.
    """
    if type(expected_version) is not int:
        raise RevisionError("version is required")
    with transaction.atomic():
        source = BuildProject.objects.filter(pk=project_id).first()
        if source is None:
            raise RevisionError("Project not found", status=404)
        if source.user_id != actor.pk or not has_perm(actor, "Builder"):
            raise RevisionError("Only the project owner may create a draft copy", status=403)
        if source.version != expected_version:
            raise RevisionError("Project changed. Reload before creating a draft copy.", status=409)
        if source.status not in ("approved", "built", "live"):
            raise RevisionError("Only an approved, built or live project can be copied", status=409)
        snapshot = source.approved_map_data
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("map_data"), dict):
            raise RevisionError("Project has no trustworthy approved design snapshot", status=409)
        return BuildProject.objects.create(
            user=actor,
            name=source.name,
            description=source.description,
            is_public=source.is_public,
            revision_of=source,
            revision_intent="copy",
            map_data=copy.deepcopy(snapshot["map_data"]),
            connection_room_id=snapshot.get("connection_room_id"),
            connection_direction=snapshot.get("connection_direction"),
        )


def replacement_design(snapshot):
    return {key: snapshot.get(key) for key in ("map_data", "connection_room_id", "connection_direction", "prototypes")}


def current_replacement_source(target):
    """Recheck the immutable target against the current publication pointer."""
    try:
        source = BuildProject.objects.get(pk=target["project_id"])
        root = BuildProject.objects.get(pk=target["root_project_id"])
        manifest = source.live_manifest
        if (
            source.status != "live"
            or source.version != target["version"]
            or source.root_project_id != root.pk
            or root.current_live_revision_id != source.pk
            or manifest.get("schema_version") != 2
            or manifest.get("project_id") != source.pk
            or manifest.get("approved_version") != source.version
            or manifest.get("root_project_id") != root.pk
            or manifest.get("approved_snapshot_hash") != approved_snapshot_hash(source.approved_map_data)
            or approved_snapshot_hash(manifest) != target["manifest_hash"]
        ):
            raise ValueError
        return source, root
    except (BuildProject.DoesNotExist, KeyError, TypeError, ValueError, AttributeError):
        raise RevisionError(
            "The named live source changed or has no trustworthy replacement inventory. A new reviewed revision is required.",
            status=409,
        ) from None


def fork_replacement(project_id, actor, expected_version):
    """Create an explicitly targeted replacement draft, never a new live copy."""
    if type(expected_version) is not int:
        raise RevisionError("version is required")
    with transaction.atomic():
        source = BuildProject.objects.filter(pk=project_id).first()
        if source is None:
            raise RevisionError("Project not found", status=404)
        if source.user_id != actor.pk or not has_perm(actor, "Builder"):
            raise RevisionError("Only the source owner may create a replacement revision", status=403)
        target = {
            "project_id": source.pk,
            "version": expected_version,
            "root_project_id": source.root_project_id,
            "manifest_hash": approved_snapshot_hash(source.live_manifest),
        }
        source, root = current_replacement_source(target)
        if root.replacement_claim_id is not None:
            raise RevisionError("This lineage has an unfinished replacement requiring staff inspection", status=409)
        snapshot = source.approved_map_data
        return BuildProject.objects.create(
            user=actor,
            name=source.name,
            description=source.description,
            is_public=source.is_public,
            revision_of=source,
            lineage_root=root,
            revision_intent="replacement",
            replacement_target=target,
            map_data=copy.deepcopy(snapshot["map_data"]),
            connection_room_id=snapshot["connection_room_id"],
            connection_direction=snapshot["connection_direction"],
        )


def _field_changes(before, after):
    changes = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if isinstance(old, dict) and isinstance(new, dict):
            changes.update({f"{key}.{field}": change for field, change in _field_changes(old, new).items()})
        else:
            changes[key] = {"before": old, "after": new}
    return changes


def prepare_replacement(project_id, actor, *, draft=None):
    """Freeze exact target identity plus a field-level design/connection diff.

    Pure Django reads only. Runtime ownership, contents and timer checks occur
    again inside the reactor-owned execution unit immediately before mutation.
    """
    from .prototype_catalog import resolve_placements

    project = draft if draft is not None else BuildProject.objects.get(pk=project_id)
    if project.user_id != actor.pk and not has_perm(actor, "Admin"):
        raise RevisionError("Not authorized", status=403)
    if project.revision_intent != "replacement":
        raise RevisionError("This project is an independent copy, not a replacement", status=409)
    source, root = current_replacement_source(project.replacement_target)
    if root.replacement_claim_id is not None:
        raise RevisionError("This lineage has an unfinished replacement", status=409)
    snapshot = {
        "map_data": project.map_data,
        "connection_room_id": project.connection_room_id,
        "connection_direction": project.connection_direction,
        "prototypes": resolve_placements(project.map_data),
    }
    changes = {}
    for kind in ("rooms", "exits", "objects"):
        before, after = source.approved_map_data["map_data"].get(kind, {}), project.map_data.get(kind, {})
        changes[kind] = {
            "additions": {key: after[key] for key in sorted(set(after) - set(before))},
            "retirements": {key: before[key] for key in sorted(set(before) - set(after))},
            "changes": {
                key: _field_changes(before[key], after[key])
                for key in sorted(set(before) & set(after))
                if before[key] != after[key]
            },
        }
    changes["connection"] = _field_changes(
        {key: source.approved_map_data[key] for key in ("connection_room_id", "connection_direction")},
        {key: snapshot[key] for key in ("connection_room_id", "connection_direction")},
    )
    old_definitions = source.approved_map_data.get("prototypes", {})
    changes["prototype_definitions"] = {
        key: {"before": old_definitions.get(key), "after": snapshot["prototypes"].get(key)}
        for key in sorted(set(old_definitions) | set(snapshot["prototypes"]))
        if old_definitions.get(key) != snapshot["prototypes"].get(key)
    }
    return {
        "target": copy.deepcopy(project.replacement_target),
        "source_manifest": copy.deepcopy(source.live_manifest),
        "design_hash": approved_snapshot_hash(snapshot),
        "changes": changes,
    }
