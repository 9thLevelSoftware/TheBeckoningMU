"""Durable ownership and bounded reactor callbacks for builder world changes.

Only lifecycle records are transactional. Each iterator advance is a complete
synchronous world step; its hooks run in autocommit and its authority expires
before the next reactor callback. Recovery fences evidence and never replays it.
"""

import copy
import logging
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from twisted.internet import defer, reactor
from twisted.python.failure import Failure

from .models import BuilderOperationGuard, BuildProject
from .revisions import approved_snapshot_hash

logger = logging.getLogger(__name__)
_mutation_token = ContextVar("builder_mutation_token", default=None)
_fences = {}
_script_fences = {}
_connection_reservations = {}
_recovered = False
_maintenance_hold = True
_active_runner = None
_ACTIVE_STATES = {"running", "compensating", "failed", "interrupted"}


class OperationError(ValueError):
    status = 409


@dataclass
class Operation:
    project_id: int
    token: str
    version: int
    actor: object
    validate: object = None

    @property
    def envelope(self):
        return _owned(self)[1]


def _ids(values):
    result = []
    for value in values:
        value = getattr(value, "pk", value)
        if type(value) is not int or value <= 0:
            raise OperationError("An exact positive object identity is required")
        result.append(value)
    return sorted(set(result))


def _reservations(values):
    result = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {"room_id", "names"}:
            raise OperationError("An exact directed connection reservation is required")
        room_id = _ids([value["room_id"]])[0]
        if not isinstance(value["names"], (list, tuple)) or not value["names"] or any(
            not isinstance(name, str) or not name.strip() for name in value["names"]
        ):
            raise OperationError("Directed connection names must be explicit nonempty strings")
        result.append({"room_id": room_id, "names": sorted({name.strip().casefold() for name in value["names"]})})
    return result


def _require_actor(project, actor):
    """Read persisted account permissions, avoiding Evennia identity caches."""
    from evennia.accounts.models import AccountDB

    if not isinstance(actor, AccountDB) or not actor.pk or actor._state.adding:
        raise OperationError("A persisted active Builder account is required")
    account = AccountDB.objects.filter(pk=actor.pk).values("is_active", "is_superuser").first()
    if not account or not account["is_active"]:
        raise OperationError("A persisted active Builder account is required")
    permissions = {
        str(value).casefold()
        for value in AccountDB.objects.filter(pk=actor.pk, db_tags__db_tagtype="permission")
        .values_list("db_tags__db_key", flat=True)
    }
    quell = AccountDB.objects.filter(
        pk=actor.pk, db_attributes__db_key__iexact="_quell",
        db_attributes__db_category__isnull=True, db_attributes__db_attrtype__isnull=True,
    ).values_list("db_attributes__db_value", flat=True).first()
    hierarchy = [str(value).casefold() for value in settings.PERMISSION_HIERARCHY]

    def allowed(permission):
        permitted = set(hierarchy[hierarchy.index(permission):]) if permission in hierarchy else {permission}
        return bool(account["is_superuser"] and not quell) or bool(permissions & permitted)

    if not allowed("builder") or (project.user_id != actor.pk and not allowed("admin")):
        raise OperationError("Current persisted Builder ownership or Admin authority is required")


def _schema_valid(envelope):
    if not isinstance(envelope, dict):
        return False
    return (
        envelope.get("schema_version") == 1
        and isinstance(envelope.get("token"), str) and bool(envelope["token"])
        and envelope.get("state") in _ACTIVE_STATES | {"completed", "rolled_back"}
        and type(envelope.get("version")) is int
        and isinstance(envelope.get("snapshot_hash"), str) and len(envelope["snapshot_hash"]) == 64
        and isinstance(envelope.get("kind"), str) and bool(envelope["kind"])
        and isinstance(envelope.get("phase"), str)
        and isinstance(envelope.get("status"), str)
        and type(envelope.get("actor_id")) is int
        and isinstance(envelope.get("receipts"), list)
        and isinstance(envelope.get("affected_ids"), list)
        and isinstance(envelope.get("script_ids"), list)
        and isinstance(envelope.get("connection_reservations"), list)
        and all(
            isinstance(reservation, dict) and type(reservation.get("room_id")) is int
            and reservation["room_id"] > 0 and isinstance(reservation.get("names"), list)
            and bool(reservation["names"]) and all(isinstance(name, str) and name for name in reservation["names"])
            for reservation in envelope["connection_reservations"]
        )
        and all(type(pk) is int and pk > 0 for pk in envelope["affected_ids"] + envelope["script_ids"])
        and "pending_creation" in envelope
        and (envelope["pending_creation"] is None or (
            isinstance(envelope["pending_creation"], dict)
            and {"kind", "map_id", "expected_type"} <= envelope["pending_creation"].keys()
        ))
        and all(
            isinstance(receipt, dict) and type(receipt.get("object_id")) is int
            and isinstance(receipt.get("kind"), str) and "map_id" in receipt
            and isinstance(receipt.get("typeclass"), str) and bool(receipt["typeclass"])
            and receipt["object_id"] in (
                envelope["script_ids"] if receipt["kind"] in {"script", "scripts", "timer", "timers"}
                else envelope["affected_ids"]
            )
            for receipt in envelope["receipts"]
        )
    )


def recover_operation_fences():
    """Reconstruct exact fences before scripts resume; never run world hooks.

    A creation without a receipt has no proven object identity. Malformed or
    orphaned records likewise retain a global maintenance hold for inspection.
    No journal, receipt, timer state or claim is changed during recovery.
    """
    global _recovered, _maintenance_hold, _fences, _script_fences, _connection_reservations
    _recovered, _maintenance_hold = False, True
    fences, scripts, reservations, unsafe = {}, {}, {}, False
    try:
        guard = BuilderOperationGuard.objects.filter(pk=1).values("token", "project_id").first()
        active = []
        for project_id, envelope in BuildProject.objects.exclude(builder_operation={}).values_list(
            "pk", "builder_operation"
        ):
            if not _schema_valid(envelope):
                unsafe = True
                continue
            if envelope["state"] not in _ACTIVE_STATES:
                continue
            active.append((project_id, envelope["token"]))
            fences[envelope["token"]] = set(envelope["affected_ids"])
            scripts[envelope["token"]] = set(envelope["script_ids"])
            reservations[envelope["token"]] = copy.deepcopy(envelope["connection_reservations"])
            unsafe |= envelope["pending_creation"] is not None
        expected = [(guard["project_id"], guard["token"])] if guard and guard["token"] else []
        unsafe |= sorted(active) != sorted(expected)
        unsafe |= bool(guard and bool(guard["token"]) != bool(guard["project_id"]))
    except Exception:
        # Missing migration, DB outage and startup ordering all fail closed.
        # Do not mark recovery complete: the next guard may safely try again.
        logger.exception("Builder operation recovery unavailable; retaining maintenance hold")
        _fences = fences
        _script_fences = scripts
        _connection_reservations = reservations
        return False
    _fences, _maintenance_hold, _recovered = fences, bool(unsafe), True
    _script_fences = scripts
    _connection_reservations = reservations
    if unsafe:
        logger.error("Builder operation inventory needs inspection; global maintenance hold retained")
    return not unsafe


def _ensure_recovered():
    if not _recovered:
        recover_operation_fences()


def object_is_fenced(obj_or_id):
    _ensure_recovered()
    pk = getattr(obj_or_id, "pk", obj_or_id)
    return _maintenance_hold or any(pk in values for values in _fences.values())


def world_mutation_is_guarded():
    """Cheap save-hook fast path after the startup/lazy recovery read."""
    _ensure_recovered()
    return _maintenance_hold or bool(_fences) or bool(_script_fences) or bool(_connection_reservations)


def script_is_fenced(script_or_id, object_id=None):
    """Timer suppression deliberately ignores the builder mutation token."""
    _ensure_recovered()
    pk = getattr(script_or_id, "pk", script_or_id)
    if object_id is None:
        object_id = getattr(script_or_id, "db_obj_id", None)
    return (_maintenance_hold or any(pk in values for values in _script_fences.values())
            or (object_id is not None and object_is_fenced(object_id)))


def assert_script_mutation_allowed(script_or_id=None, object_id=None):
    _ensure_recovered()
    pk = getattr(script_or_id, "pk", script_or_id)
    if object_id is None:
        object_id = getattr(script_or_id, "db_obj_id", None)
    assert_mutation_allowed(object_id)
    token = _mutation_token.get()
    if any(owner != token and pk in values for owner, values in _script_fences.items()):
        raise OperationError("This timer is fenced by an unfinished builder operation")


def assert_connection_allowed(room_id, names=(), object_id=None):
    """Reserve only named outgoing directions, preserving unrelated traffic."""
    _ensure_recovered()
    assert_mutation_allowed(object_id)
    room_id = getattr(room_id, "pk", room_id)
    names = {str(name).strip().casefold() for name in names}
    token = _mutation_token.get()
    for owner, reservations in _connection_reservations.items():
        if owner == token:
            continue
        if any(value["room_id"] == room_id and names.intersection(value["names"]) for value in reservations):
            raise OperationError("This outgoing connection is reserved by an unfinished builder operation")


def assert_connection_room_allowed(room_id):
    """Guard attachment deletion without preventing ordinary room traffic."""
    _ensure_recovered()
    assert_mutation_allowed(room_id)
    room_id = getattr(room_id, "pk", room_id)
    token = _mutation_token.get()
    for owner, reservations in _connection_reservations.items():
        if owner != token and any(value["room_id"] == room_id for value in reservations):
            raise OperationError("This room anchors a reserved builder connection")


def assert_mutation_allowed(obj_or_id=None, target_ids=()):
    """Reject external mutation/movement into or out of a protected identity."""
    _ensure_recovered()
    token = _mutation_token.get()
    if _maintenance_hold:
        raise OperationError("Builder recovery requires staff inspection before world mutation")
    identities = [getattr(value, "pk", value) for value in (obj_or_id, *target_ids)]
    for owner, values in _fences.items():
        if owner != token and any(pk in values for pk in identities if pk is not None):
            raise OperationError("This object is fenced by an unfinished builder operation")


def assert_project_idle(project_id):
    _ensure_recovered()
    if _maintenance_hold:
        raise OperationError("Builder recovery requires staff inspection")
    project = BuildProject.objects.filter(pk=project_id).first()
    if project is None:
        raise OperationError("Project not found")
    envelope = project.builder_operation
    if envelope and (not _schema_valid(envelope) or envelope.get("state") in _ACTIVE_STATES):
        raise OperationError("This project has an unfinished builder operation")
    if BuilderOperationGuard.objects.filter(pk=1).exclude(token="").exists():
        raise OperationError("Another builder operation is active")
    return project


def assert_project_mutation_allowed(project_id):
    """Fence normal model/admin changes to a claimed candidate/source/root."""
    _ensure_recovered()
    if _maintenance_hold:
        raise OperationError("Builder recovery requires staff inspection")
    guard = BuilderOperationGuard.objects.filter(pk=1).exclude(token="").first()
    if guard is None or guard.token == _mutation_token.get():
        return
    envelope = BuildProject.objects.filter(pk=guard.project_id).values_list("builder_operation", flat=True).first()
    if not _schema_valid(envelope) or project_id in {
        guard.project_id, envelope.get("source_id"), envelope.get("root_id"),
    }:
        raise OperationError("This project belongs to an unfinished builder operation")


def require_idle(project_id=None, object_ids=()):
    if project_id is not None:
        assert_project_idle(project_id)
    else:
        _ensure_recovered()
        if _maintenance_hold or BuilderOperationGuard.objects.filter(pk=1).exclude(token="").exists():
            raise OperationError("An unfinished builder operation requires inspection")
    assert_mutation_allowed(target_ids=object_ids)


def claim_operation(project_id, kind, actor, expected_version, *, affected_ids=(), script_ids=(),
                    source_id=None, root_id=None, claim_callback=None, validate=None, connection_reservations=()):
    """CAS the singleton and reviewed project together, without world hooks."""
    global _maintenance_hold
    if threading.current_thread() is not threading.main_thread():
        raise OperationError("Builder claims belong to the reactor thread")
    _ensure_recovered()
    if _maintenance_hold:
        raise OperationError("Builder recovery requires staff inspection")
    if type(expected_version) is not int:
        raise OperationError("An exact reviewed version is required")
    object_ids, timer_ids = _ids(affected_ids), _ids(script_ids)
    reservations = _reservations(connection_reservations)
    token = uuid.uuid4().hex
    with transaction.atomic():
        BuilderOperationGuard.objects.get_or_create(pk=1)
        if not BuilderOperationGuard.objects.filter(pk=1, token="", project__isnull=True).update(
            token=token, project_id=project_id
        ):
            raise OperationError("Another builder operation is active")
        project = BuildProject.objects.get(pk=project_id)
        previous = copy.deepcopy(project.builder_operation)
        if previous and (not _schema_valid(previous) or previous["state"] in _ACTIVE_STATES):
            raise OperationError("Project has an unfinished builder operation")
        if project.version != expected_version or project.status != "approved":
            raise OperationError("Reviewed project changed before builder claim")
        _require_actor(project, actor)
        snapshot_hash = approved_snapshot_hash(project.approved_map_data)
        if claim_callback:
            claim_callback(project)
            project.refresh_from_db()
        envelope = {
            "schema_version": 1, "token": token, "kind": str(kind),
            "version": project.version, "snapshot_hash": snapshot_hash,
            "state": "running", "phase": "claimed", "status": project.status,
            "actor_id": actor.pk, "source_id": source_id, "root_id": root_id,
            "affected_ids": object_ids, "script_ids": timer_ids,
            "connection_reservations": reservations,
            "pending_creation": None, "receipts": [],
        }
        if not BuildProject.objects.filter(
            pk=project_id, version=expected_version, builder_operation=previous,
        ).update(builder_operation=envelope, updated_at=timezone.now()):
            raise OperationError("Project changed during builder claim")
    _fences[token] = set(object_ids)
    _script_fences[token] = set(timer_ids)
    _connection_reservations[token] = reservations
    return Operation(project_id, token, project.version, actor, validate)


def _owned(op):
    project = BuildProject.objects.get(pk=op.project_id)
    envelope = project.builder_operation
    if (not _schema_valid(envelope) or envelope["token"] != op.token
            or envelope["state"] not in _ACTIVE_STATES
            or not BuilderOperationGuard.objects.filter(pk=1, token=op.token, project_id=op.project_id).exists()):
        raise OperationError("Builder continuation no longer owns its durable claim")
    return project, copy.deepcopy(envelope)


def assert_current(op, *, compensation=False):
    project, envelope = _owned(op)
    if (project.version != envelope["version"] or project.version != op.version
            or approved_snapshot_hash(project.approved_map_data) != envelope["snapshot_hash"]
            or project.status != envelope["status"]):
        raise OperationError("Builder continuation's reviewed identity changed")
    if not compensation:
        _require_actor(project, op.actor)
        if op.validate:
            op.validate(op, project)
    return project


@contextmanager
def mutation_context(op, *, compensation=False):
    if threading.current_thread() is not threading.main_thread():
        raise OperationError("Builder world mutation belongs to the reactor thread")
    if any(not getattr(block, "_from_testcase", False) for block in connection.atomic_blocks):
        raise OperationError("Builder world hooks cannot run inside a transaction")
    assert_current(op, compensation=compensation)
    marker = _mutation_token.set(op.token)
    try:
        yield
    finally:
        _mutation_token.reset(marker)


def update_operation(op, **fields):
    """Persist step evidence with a full-envelope CAS; tokens are immutable."""
    if set(fields) & {"token", "schema_version", "actor_id", "snapshot_hash"}:
        raise OperationError("Builder operation identity is immutable")
    _, previous = _owned(op)
    envelope = copy.deepcopy(previous)
    envelope.update(copy.deepcopy(fields))
    if not _schema_valid(envelope):
        raise OperationError("Malformed builder operation evidence refused")
    if not BuildProject.objects.filter(pk=op.project_id, builder_operation=previous).update(
        builder_operation=envelope, updated_at=timezone.now()
    ):
        raise OperationError("Builder step evidence changed concurrently")
    op.version = envelope["version"]
    _fences[op.token] = set(envelope["affected_ids"])
    _script_fences[op.token] = set(envelope["script_ids"])
    _connection_reservations[op.token] = copy.deepcopy(envelope["connection_reservations"])
    return envelope


def add_fenced_ids(op, object_ids=(), script_ids=()):
    envelope = op.envelope
    return update_operation(
        op, affected_ids=_ids([*envelope["affected_ids"], *object_ids]),
        script_ids=_ids([*envelope["script_ids"], *script_ids]),
    )


def creation_pending(op, kind, map_id=None, expected_type=None):
    if op.envelope["pending_creation"] is not None:
        raise OperationError("An earlier builder creation has no durable receipt")
    return update_operation(op, pending_creation={
        "kind": str(kind), "map_id": map_id, "expected_type": expected_type,
    })


def record_created(op, obj, kind, map_id=None):
    envelope = op.envelope
    pk = _ids([obj])[0]
    pending = envelope["pending_creation"]
    if pending is None or pending["kind"] != str(kind) or pending["map_id"] != map_id:
        raise OperationError("Builder creation receipt does not match its durable intent")
    script = str(kind) in {"script", "scripts", "timer", "timers"}
    from evennia.objects.models import ObjectDB
    from evennia.scripts.models import ScriptDB

    model = ScriptDB if script else ObjectDB
    if not isinstance(obj, model):
        raise OperationError("Builder creation receipt has the wrong object/script identity namespace")
    fields = ("db_typeclass_path", "db_obj_id") if script else ("db_typeclass_path", "db_account_id", "db_sessid")
    identity = model.objects.filter(pk=pk).values(*fields).first()
    typeclass = identity["db_typeclass_path"] if identity else None
    if not typeclass or (pending["expected_type"] is not None and typeclass != pending["expected_type"]):
        raise OperationError("Builder creation has no exact matching typed identity; inspection required")
    if not script and (identity["db_account_id"] is not None or identity["db_sessid"]):
        raise OperationError("A builder creation has account or session ownership; inspection required")
    envelope["receipts"].append({
        "object_id": pk, "kind": str(kind), "map_id": map_id, "typeclass": typeclass,
        "expected_type": pending["expected_type"], "identity": identity,
    })
    key = "script_ids" if script else "affected_ids"
    return update_operation(op, **{
        key: _ids([*envelope[key], pk]), "receipts": envelope["receipts"], "pending_creation": None,
    })


def finish_operation(op, state="completed", phase="complete", release=True):
    """Release only after lifecycle terminal records and all hooks succeeded."""
    global _maintenance_hold
    _, previous = _owned(op)
    if release and (state not in {"completed", "rolled_back"} or previous["pending_creation"] is not None):
        raise OperationError("Unresolved builder work must retain its claim and fence")
    envelope = copy.deepcopy(previous)
    envelope.update(state=state, phase=phase)
    if not _schema_valid(envelope):
        raise OperationError("Malformed builder terminal evidence refused")
    with transaction.atomic():
        if not BuildProject.objects.filter(pk=op.project_id, builder_operation=previous).update(
            builder_operation=envelope, updated_at=timezone.now()
        ):
            raise OperationError("Builder terminal evidence changed concurrently")
        if release and not BuilderOperationGuard.objects.filter(pk=1, token=op.token, project_id=op.project_id).update(
            token="", project=None
        ):
            raise OperationError("Builder terminal claim changed concurrently")
    if release:
        _fences.pop(op.token, None)
        _script_fences.pop(op.token, None)
        _connection_reservations.pop(op.token, None)
    elif previous["pending_creation"] is not None:
        _maintenance_hold = True


class _TerminalDeferred(defer.Deferred):
    def cancel(self):
        """The operation owns completion; disconnect cannot abandon its world."""


def run_steps(op, forward_steps, compensate_steps=None, *, clock=None):
    """Advance exactly one synchronous step per reactor callback.

    Forward/compensation iterators must yield None after bounded work and may
    return a terminal result. They cannot yield asynchronous work inside a
    mutation scope. A cancelled observer still receives final outcome.
    """
    global _active_runner
    if _active_runner is not None:
        raise OperationError("A builder runner already owns the reactor")
    clock = reactor if clock is None else clock
    result = _TerminalDeferred()
    runner = object()
    _active_runner = runner
    iterator = iter(forward_steps)
    original_error = None
    compensating = False

    def terminal(value=None, error=None):
        global _active_runner
        if _active_runner is runner:
            _active_runner = None
        if error is None:
            result.callback(value)
        else:
            result.errback(error)

    def complete(value):
        try:
            envelope = BuildProject.objects.filter(pk=op.project_id).values_list("builder_operation", flat=True).first()
            if not _schema_valid(envelope) or envelope["token"] != op.token:
                terminal(error=original_error or Failure(OperationError("Builder terminal ownership changed")))
                return
            if envelope["state"] in {"running", "compensating"}:
                finish_operation(op, state="failed", phase="missing_terminal_record", release=False)
                terminal(error=original_error or Failure(OperationError("Builder returned without a durable terminal record")))
                return
            if original_error is not None:
                terminal(error=original_error)
            elif envelope["state"] not in {"completed", "rolled_back"}:
                terminal(error=Failure(OperationError("Builder operation requires staff inspection")))
            else:
                terminal(value)
        except BaseException:
            # Even an unavailable evidence DB must resolve the observer. The
            # durable gate/fence is left as-is and recovery decides its scope.
            terminal(error=original_error or Failure())

    def advance():
        nonlocal iterator, original_error, compensating
        try:
            with mutation_context(op, compensation=compensating):
                yielded = next(iterator)
                if yielded is not None:
                    raise OperationError("Builder steps must finish synchronously and yield only None")
        except StopIteration as done:
            complete(done.value)
            return
        except BaseException:
            error = Failure()
            try:
                # Stale tokens/versions are inert, including compensation. Do
                # not grant a lost owner fresh authority to undo newer work.
                assert_current(op, compensation=True)
                if compensating or compensate_steps is None or op.envelope["pending_creation"] is not None:
                    finish_operation(op, state="failed", phase="inspection_required", release=False)
                    terminal(error=original_error or error)
                    return
                update_operation(op, state="compensating", phase="compensating")
                original_error = error
                compensating = True
                iterator = iter(compensate_steps(error.value) if callable(compensate_steps) else compensate_steps)
            except BaseException:
                # Preserve evidence on lost claim, invalid identity or a
                # compensation factory failure; recovery will retain fences.
                terminal(error=original_error or error)
                return
        clock.callLater(0, advance)

    clock.callLater(0, advance)
    return result


def drain_steps(op, forward_steps, compensate_steps=None):
    """Synchronous qualification adapter using the identical bounded driver."""
    from collections import deque

    callbacks = deque()

    class DrainClock:
        def callLater(self, delay, callback):  # noqa: N802 - Twisted clock API
            callbacks.append(callback)

    outcome = []
    pending = run_steps(op, forward_steps, compensate_steps, clock=DrainClock())
    pending.addBoth(outcome.append)
    while callbacks:
        callbacks.popleft()()
    if not outcome:
        raise OperationError("Builder synchronous driver did not reach terminal outcome")
    if isinstance(outcome[0], Failure):
        outcome[0].raiseException()
    return outcome[0]
