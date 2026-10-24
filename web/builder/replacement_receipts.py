"""Append immediate addition receipts without rewriting saved world before-state.

Only replacement record data is touched here. No object hooks, movement, timers,
or external work may run in these short transactions. Callers keep their own
in-memory journal and retain the existing full initial/final journal writes.
"""

import json

from django.db import connections, models, router, transaction
from django.db.models.expressions import RawSQL
from django.utils import timezone

from .models import BuildProject

_LIST_KEYS = ("created_object_ids", "created_objects", "created_script_ids")
_KINDS = {"rooms", "exits", "fixtures"}


class ReceiptError(ValueError):
    """The claimed replacement record cannot accept a durable receipt."""


def _valid_id(value):
    return type(value) is int and value > 0


def _validate_receipt(project, object_receipt, script_id):
    if not project.pk or not _valid_id(project.version):
        raise ReceiptError("A persisted, versioned replacement record is required")
    if object_receipt is None and script_id is None:
        raise ReceiptError("An object or script receipt is required")
    if object_receipt is not None and (
        not isinstance(object_receipt, dict)
        or set(object_receipt) != {"object_id", "typeclass", "kind"}
        or not _valid_id(object_receipt["object_id"])
        or not isinstance(object_receipt["typeclass"], str)
        or not object_receipt["typeclass"]
        or not isinstance(object_receipt["kind"], str)
        or object_receipt["kind"] not in _KINDS
    ):
        raise ReceiptError("An exact typed object receipt is required")
    if script_id is not None and not _valid_id(script_id):
        raise ReceiptError("A positive integer script receipt is required")


def _valid_journal(journal):
    return (
        isinstance(journal, dict)
        and all(isinstance(journal.get(key), list) for key in _LIST_KEYS)
        and len(journal["created_object_ids"]) == len(journal["created_objects"])
    )


def append_receipt(project, *, object_receipt=None, script_id=None):
    """Append typed receipts to the exact current replacing/version claim.

    SQLite appends both object lists in one bound UPDATE, without reading or
    serializing saved_objects/saved_scripts. Other databases lock only the
    project row and append to its current persisted journal. A stale caller's
    Python journal is never used. The caller's project instance is unchanged.
    """
    _validate_receipt(project, object_receipt, script_id)
    alias = project._state.db or router.db_for_write(BuildProject, instance=project)
    connection = connections[alias]
    records = BuildProject.objects.using(alias).filter(pk=project.pk, status="replacing", version=project.version)
    with transaction.atomic(using=alias):
        if connection.vendor == "sqlite":
            column = connection.ops.quote_name(BuildProject._meta.get_field("replacement_journal").column)
            arguments = []
            values = []
            if object_receipt is not None:
                arguments.extend(("'$.created_object_ids[#]', json(%s)", "'$.created_objects[#]', json(%s)"))
                values.extend(
                    (json.dumps(object_receipt["object_id"]), json.dumps(object_receipt, separators=(",", ":")))
                )
            if script_id is not None:
                arguments.append("'$.created_script_ids[#]', json(%s)")
                values.append(json.dumps(script_id))
            # Paths/column identifiers are fixed code; every value is bound.
            # Missing/non-array lists must fail rather than silently losing a
            # receipt (SQLite json_insert otherwise ignores unsuitable paths).
            shape = " AND ".join(
                [f"json_type({column}) = 'object'"]
                + [f"json_type({column}, '$.{key}') = 'array'" for key in _LIST_KEYS]
                + [
                    f"json_array_length({column}, '$.created_object_ids') = json_array_length({column}, '$.created_objects')"
                ]
            )
            updated = records.filter(RawSQL(shape, (), output_field=models.BooleanField())).update(
                replacement_journal=RawSQL(
                    f"json_insert({column}, {', '.join(arguments)})", values, output_field=models.JSONField()
                ),
                updated_at=timezone.now(),
            )
        else:
            try:
                journal = records.select_for_update().values_list("replacement_journal", flat=True).get()
            except BuildProject.DoesNotExist as exc:
                raise ReceiptError("Replacement record changed or is no longer replacing") from exc
            if not _valid_journal(journal):
                raise ReceiptError("Replacement journal has invalid receipt lists")
            if object_receipt is not None:
                journal["created_object_ids"].append(object_receipt["object_id"])
                journal["created_objects"].append(dict(object_receipt))
            if script_id is not None:
                journal["created_script_ids"].append(script_id)
            updated = records.update(replacement_journal=journal, updated_at=timezone.now())
        if updated != 1:
            raise ReceiptError("Replacement record changed or has invalid receipt lists")
