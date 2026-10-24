"""Server-owned inert scenery catalog and strict placement resolution.

Clients send identifiers and text overrides only. Definitions are frozen at
submission; approved builds validate that frozen contract without resolving
against today's catalog. Catalog changes must bump the prototype revision.
"""

import copy
from collections import Counter
from collections.abc import Mapping

from .revisions import approved_snapshot_hash

CATALOG_VERSION = "1"
MAX_FIXTURES = 100
MAX_FIXTURES_PER_ROOM = 20
FIXTURE_TYPECLASS = "typeclasses.objects.Object"
FIXTURE_LOCKS = "get:false();drop:false();puppet:false();edit:perm(Admin);control:perm(Admin);delete:perm(Admin)"
PLACEMENT_FIELDS = {"prototype_id", "prototype_revision", "room_id", "name", "description"}
CATALOG = {
    "wooden_chair": {
        "id": "wooden_chair",
        "revision": 1,
        "label": "Wooden chair",
        "description": "A plain, sturdy wooden chair.",
        "typeclass": FIXTURE_TYPECLASS,
        "locks": FIXTURE_LOCKS,
        "attributes": {"builder_inert": True},
    },
    "wooden_table": {
        "id": "wooden_table",
        "revision": 1,
        "label": "Wooden table",
        "description": "A solid wooden table with a worn surface.",
        "typeclass": FIXTURE_TYPECLASS,
        "locks": FIXTURE_LOCKS,
        "attributes": {"builder_inert": True},
    },
}


def public_catalog():
    return {
        "catalog_version": CATALOG_VERSION,
        "prototypes": [
            {key: value[key] for key in ("id", "revision", "label", "description")} for value in CATALOG.values()
        ],
        "max_fixtures": MAX_FIXTURES,
        "max_fixtures_per_room": MAX_FIXTURES_PER_ROOM,
    }


def _frozen_definition_ok(record, placement):
    definition = record.get("definition")
    if not isinstance(definition, dict):
        return False
    # A frozen snapshot may preserve old text/revisions, never arbitrary code,
    # typeclasses, locks, extra Attributes, scripts, or inherited definitions.
    return (
        set(definition) == {"id", "revision", "label", "description", "typeclass", "locks", "attributes"}
        and definition.get("id") == placement["prototype_id"]
        and definition.get("revision") == placement["prototype_revision"]
        and definition.get("typeclass") == FIXTURE_TYPECLASS
        and definition.get("locks") == FIXTURE_LOCKS
        and definition.get("attributes") == {"builder_inert": True}
        and isinstance(definition.get("label"), str)
        and isinstance(definition.get("description"), str)
        and record.get("placement") == placement
        and record.get("definition_hash") == approved_snapshot_hash(definition)
    )


def placement_errors(map_data, resolved=None):
    from .validators import MAX_DESC_LENGTH, MAX_NAME_LENGTH, OBJECT_ID_RE, _text

    errors = []
    placements = map_data.get("objects", {})
    if not isinstance(placements, Mapping):
        return ["Fixture placements must be an object"]
    if len(placements) > MAX_FIXTURES:
        errors.append(f"A project may have at most {MAX_FIXTURES} fixtures")
    if resolved is not None and (not isinstance(resolved, dict) or set(resolved) != set(placements)):
        return ["Reviewed fixture definitions do not match the placements"]
    room_counts = Counter()
    for placement_id, placement in placements.items():
        label = f"Fixture '{placement_id}'"
        if not isinstance(placement_id, str) or not OBJECT_ID_RE.fullmatch(placement_id):
            errors.append(f"{label}: id must be 1-32 letters, digits, '_' or '-'")
        if not isinstance(placement, Mapping):
            errors.append(f"{label}: placement must be an object")
            continue
        if set(placement) - PLACEMENT_FIELDS:
            errors.append(f"{label}: only prototype_id, prototype_revision, room_id, name and description are allowed")
        room_id = placement.get("room_id")
        if not isinstance(room_id, str) or room_id not in map_data.get("rooms", {}):
            errors.append(f"{label}: room_id must be a room in this project")
        else:
            room_counts[room_id] += 1
        prototype_id, revision = placement.get("prototype_id"), placement.get("prototype_revision")
        if not isinstance(prototype_id, str) or type(revision) is not int or revision < 1:
            errors.append(f"{label}: prototype_id and integer prototype_revision are required")
            continue
        if resolved is None:
            definition = CATALOG.get(prototype_id)
            if not definition or definition["revision"] != revision:
                errors.append(f"{label}: unknown prototype or stale catalog revision; choose a current catalog entry")
        elif not isinstance(resolved.get(placement_id), dict) or not _frozen_definition_ok(
            resolved[placement_id], placement
        ):
            errors.append(f"{label}: invalid reviewed definition or hash")
        _text(placement.get("name"), "name", errors, label, max_length=MAX_NAME_LENGTH)
        _text(placement.get("description"), "description", errors, label, max_length=MAX_DESC_LENGTH)
    for room_id, count in room_counts.items():
        if count > MAX_FIXTURES_PER_ROOM:
            errors.append(f"Room '{room_id}' may have at most {MAX_FIXTURES_PER_ROOM} fixtures")
    return errors


def resolve_placements(map_data):
    errors = placement_errors(map_data)
    if errors:
        raise ValueError("; ".join(errors[:5]))
    resolved = {}
    for placement_id, placement in map_data.get("objects", {}).items():
        definition = copy.deepcopy(CATALOG[placement["prototype_id"]])
        resolved[placement_id] = {
            "placement": copy.deepcopy(placement),
            "definition": definition,
            "definition_hash": approved_snapshot_hash(definition),
        }
    return resolved
