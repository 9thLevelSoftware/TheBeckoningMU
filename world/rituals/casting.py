"""Reactor-owned ritual units, durable claims and fail-closed restart recovery.

One persistent Script owns one plain state Attribute. An operation claim is
committed BEFORE randomness/resources; settlement is a separate short atomic
unit. An interrupted claim is never charged, rolled or adjudicated again.
"""

import hashlib
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager

from django.db import transaction
from django.db.models import F
from django.conf import settings
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB
from evennia.scripts.models import ScriptDB
from evennia.scripts.scripts import DefaultScript
from evennia.utils import create
from evennia.utils.dbserialize import deserialize

from dice.dice_roller import MAX_POOL, roll_v5_pool
from dice.discipline_roller import calculate_pool_from_traits, parse_dice_pool
from dice.pool_modifiers import impairment_for_pool, resolve_pool_traits
from dice.rouse_checker import HUNGER_5_REFUSAL, perform_rouse_check
from world.v5_data import DISCIPLINES

IN_PROGRESS = {"payment_in_progress", "resolving", "adjudicating"}
TERMINAL = {"completed", "failed", "cancelled", "review_required"}
RESOURCE_ROOTS = ("stats", "vampire", "pools", "pending_frenzy_test", "active_effects")


def current_time():
    return time.time()


def _plain(value):
    return json.loads(json.dumps(value))


def _ritual(name):
    return next((entry for entry in DISCIPLINES["Blood Sorcery"]["rituals"]
                 if entry["name"].casefold() == str(name).strip().casefold()), None)


def _eligible(caster, name):
    ritual = _ritual(name)
    if ritual is None:
        raise ValueError(f"Unknown ritual: {name}")
    if ritual["name"] not in caster.known_rituals:
        raise ValueError(f"You have not learned {ritual['name']}")
    if caster.get_trait("Blood Sorcery") < ritual["level"]:
        raise ValueError(f"{ritual['name']} needs Blood Sorcery {ritual['level']}")
    return ritual


def _target_ref(target):
    if target is None:
        return None
    if not isinstance(target, ObjectDB) or not target.pk or not ObjectDB.objects.filter(pk=target.pk).exists():
        raise ValueError("The ritual target must be an existing game object")
    return {"id": target.pk, "created": target.db_date_created.isoformat()}


def _target(state):
    ref = state.get("target")
    if ref is None:
        return None
    target = ObjectDB.objects.filter(pk=ref["id"]).first()
    if target is None or target.db_date_created.isoformat() != ref["created"]:
        raise ValueError("The attested ritual target no longer exists")
    return target


def prepare_cast(caster, ritual_name, *, target=None, context=None):
    """Validate a request without writes, payment, authorization or inventory claims."""
    ritual = _eligible(caster, ritual_name)
    if context is not None and not isinstance(context, Mapping):
        raise ValueError("Requested ritual context must be a plain mapping")
    plan = {"cast_id": uuid.uuid4().hex, "caster_id": caster.pk, "ritual": ritual["name"],
            "target": _target_ref(target), "requested_context": _plain(dict(context or {})),
            "metadata": _plain(ritual["execution"])}
    plan["request_digest"] = _digest(plan)
    return plan


def _digest(plan):
    fields = {key: value for key, value in plan.items() if key != "request_digest"}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _refresh(obj, roots):
    for root in roots:
        attr = obj.attributes.get(root, return_obj=True)
        if attr is not None:
            try:
                attr.refresh_from_db()
            except attr.DoesNotExist:
                pass
            attr.flush_from_cache(force=True)
    obj.attributes.reset_cache()
    getattr(obj, "_prefetched_objects_cache", {}).pop("db_attributes", None)


@contextmanager
def _locked(script, caster):
    """Actual write locks and fresh Attribute/idmapper state, never SQLite SELECT locks."""
    try:
        with transaction.atomic():
            if caster is not None:
                if not ObjectDB.objects.filter(pk=caster.pk).update(db_key=F("db_key")):
                    raise ValueError("The ritual caster no longer exists")
                _refresh(caster, RESOURCE_ROOTS)
            if not ScriptDB.objects.filter(pk=script.pk).update(db_key=F("db_key")):
                raise ValueError("The ritual attempt no longer exists")
            _refresh(script, ("cast_state",))
            yield deserialize(script.attributes.get("cast_state"))
    except Exception:
        if caster is not None:
            _refresh(caster, RESOURCE_ROOTS)
        _refresh(script, ("cast_state",))
        raise


def _save_state(script, state):
    script.attributes.add("cast_state", state)


def _advance(script, state, phase, action, actor=None):
    state["phase"] = phase
    state["revision"] += 1
    state["updated_at"] = current_time()
    state["history"].append({"revision": state["revision"], "phase": phase, "action": action,
                              "actor": actor, "at": state["updated_at"]})
    _save_state(script, state)


def script_for_cast(caster, cast_id):
    script = ScriptDB.objects.filter(db_key=f"ritual:{cast_id}", db_obj_id=caster.pk,
                                      db_typeclass_path=RitualCastingScript.path).first()
    if script is None:
        raise ValueError("Unknown ritual cast for this character")
    return script


def begin_cast(caster, plan):
    """Persist an unpaid request once. Caller-supplied plans grant no authority."""
    if not isinstance(plan, Mapping) or plan.get("caster_id") != caster.pk or _digest(plan) != plan.get("request_digest"):
        raise ValueError("Invalid or altered ritual request")
    ritual = _eligible(caster, plan["ritual"])
    if plan["metadata"] != ritual["execution"]:
        raise ValueError("The ritual catalog changed; prepare a new request")
    _target(plan)
    with transaction.atomic():
        if not ObjectDB.objects.filter(pk=caster.pk).update(db_key=F("db_key")):
            raise ValueError("The ritual caster no longer exists")
        _refresh(caster, RESOURCE_ROOTS)
        _eligible(caster, plan["ritual"])
        _target(plan)
        existing = ScriptDB.objects.filter(db_obj_id=caster.pk, db_key=f"ritual:{plan['cast_id']}").first()
        if existing:
            _refresh(existing, ("cast_state",))
            if existing.db.cast_state.get("request_digest") != plan["request_digest"]:
                raise ValueError("The request identity is already bound to a different attempt")
            return plan["cast_id"]
        state = _plain(dict(plan))
        state.update(schema_version=1, phase="awaiting_attestation", revision=0, operation_id=None,
                     operations=[], payments=[], result=None, procedure=None, ready_at=None,
                     unresolved=["materials", "target facts", "payment/cancellation", "failure", "opposition", "duration", "outcome"],
                     created_at=current_time(), updated_at=current_time(), history=[])
        script = create.create_script(RitualCastingScript, key=f"ritual:{plan['cast_id']}", obj=caster,
                                      persistent=True, interval=5, start_delay=True, autostart=False,
                                      attributes=[("cast_state", state)])
    script.start()
    return plan["cast_id"]


def cast_status(caster, cast_id):
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as state:
        return state  # Reads never classify an active operation as a stale one.


def list_casts(caster):
    return [cast_status(caster, script.db.cast_state["cast_id"])
            for script in ScriptDB.objects.filter(db_obj_id=caster.pk, db_typeclass_path=RitualCastingScript.path)]


def _staff(actor):
    """Persisted authority snapshot, called INSIDE the locked decision unit.

    Values queries intentionally bypass the idmapper and permission/Attribute
    handlers: a different process can revoke permissions without invalidating
    this actor's cached flags, account link, tags or quell value.
    """
    if (not isinstance(actor, (ObjectDB, AccountDB)) or not actor.pk
            or actor._state.adding):
        raise ValueError("A real persisted Builder actor is required")
    character = isinstance(actor, ObjectDB)
    if character:
        identity = ObjectDB.objects.filter(pk=actor.pk).values("db_key", "db_account_id").first()
        if identity is None or identity["db_account_id"] is None:
            raise ValueError("The Builder character needs a persisted active account")
        account_id = identity["db_account_id"]
    else:
        account_id = actor.pk
    account = AccountDB.objects.filter(pk=account_id).values("username", "is_active", "is_superuser").first()
    if account is None or not account["is_active"]:
        raise ValueError("A persisted active Builder account is required")
    quell = bool(AccountDB.objects.filter(pk=account_id, db_attributes__db_key__iexact="_quell",
        db_attributes__db_category__isnull=True, db_attributes__db_attrtype__isnull=True)
        .values_list("db_attributes__db_value", flat=True).first())
    hierarchy = [str(permission).casefold() for permission in settings.PERMISSION_HIERARCHY]
    allowed = set(hierarchy[hierarchy.index("builder"):]) if "builder" in hierarchy else {"builder"}

    def builder_permissions(model, pk):
        permissions = model.objects.filter(pk=pk, db_tags__db_tagtype="permission").values_list("db_tags__db_key", flat=True)
        return any(str(permission).casefold() in allowed
                   or (str(permission).casefold().endswith("s") and str(permission).casefold()[:-1] in allowed)
                   for permission in permissions)

    permitted = account["is_superuser"] and not quell
    if not permitted:
        permitted = builder_permissions(AccountDB, account_id)
        if character and quell:
            permitted = permitted and builder_permissions(ObjectDB, actor.pk)
    if not permitted:
        raise ValueError("Current persisted Builder authority is required")
    return {"kind": "character" if character else "account", "id": actor.pk,
            "account_id": account_id, "key": identity["db_key"] if character else account["username"]}


def _operation_staff(state, staff):
    """Recheck authority before settlement and preserve the claimed account binding."""
    actor = _staff(staff)
    claimed = next(operation for operation in state["operations"] if operation["id"] == state["operation_id"])["actor"]
    if any(actor[field] != claimed[field] for field in ("kind", "id", "account_id")):
        raise ValueError("The Builder account binding changed after the operation claim")
    return actor


def _revision(state, expected):
    if not isinstance(expected, int) or isinstance(expected, bool) or state["revision"] != expected:
        raise ValueError("The ritual cast changed; inspect its current revision")


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError(f"Record an explicit {field} attestation (1-4000 characters)")
    return value.strip()


def _procedure(state, procedure):
    if not isinstance(procedure, Mapping):
        raise ValueError("An explicit Storyteller procedure is required")
    proc = _plain(dict(procedure))
    for field in ("materials", "target_facts", "duration", "outcome", "failure", "casting_relationship"):
        _text(proc.get(field), field)
    if proc.get("duration") != "staff_adjudicated" or proc.get("cancellation") != "retain_paid":
        raise ValueError("Supported procedure: staff-adjudicated duration, retain paid costs on cancellation")
    timing = proc.get("payment_timing")
    starts = {"before_casting": "after_payment", "after_casting": "on_confirm", "staged_preparation": "after_checkpoints"}
    if timing not in starts or proc.get("casting_start") != starts[timing]:
        raise ValueError("Attest the supported relationship between payment and casting time")
    if proc.get("failure_policy") != "no_effect_retain_paid":
        raise ValueError("Attest no effect on failure and retention of paid costs")
    if state["metadata"]["opposed_by"]:
        if proc.get("opposition") not in ("catalog_roll", "staff_adjudicated"):
            raise ValueError("Attest the opposed procedure")
        if proc["opposition"] == "catalog_roll":
            if proc.get("opposed_success") != "catalog_difficulty_and_contest":
                raise ValueError("Attest the opposed success procedure: catalog difficulty and contest must both be met")
            target = _target(state)
            if target is None or not hasattr(target, "get_trait"):
                raise ValueError("Catalog opposition requires an existing character target")
            if proc.get("opposed_ties") not in ("actor_wins", "defender_wins"):
                raise ValueError("Attest who wins an opposed tie")
    elif proc.get("opposition") != "none":
        raise ValueError("This catalog entry supplies no automatic opposed roll")
    staged = state["metadata"]["preparation"] == "identified_staff_checkpoints"
    if staged != (timing == "staged_preparation"):
        raise ValueError("Escape to True Sanctuary requires explicitly staged preparation payments")
    if staged:
        checkpoints = proc.get("checkpoints")
        if not isinstance(checkpoints, list) or len(checkpoints) != state["metadata"]["rouse"]:
            raise ValueError("Record one identified checkpoint per preparation Rouse check")
        ids = []
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, Mapping) or checkpoint.get("rouse") != 1:
                raise ValueError("Each preparation checkpoint pays one Rouse check")
            ids.append(_text(checkpoint.get("id"), "checkpoint identity"))
            _text(checkpoint.get("description"), "checkpoint facts")
        if len(set(ids)) != len(ids):
            raise ValueError("Preparation checkpoint identities must be unique")
    return proc


def attest_cast(caster, cast_id, staff, *, revision, procedure):
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as state:
        actor = _staff(staff)
        _revision(state, revision)
        if state["phase"] != "awaiting_attestation":
            raise ValueError("Only an awaiting request can receive a procedure attestation")
        _eligible(caster, state["ritual"])
        _target(state)
        state["procedure"] = _procedure(state, procedure)
        state["attestation"] = {"actor": actor, "request_revision": revision, "target": state["target"], "at": current_time()}
        state["unresolved"] = ["outcome adjudication", "specific effect duration"]
        _advance(script, state, "prepared", "procedure attested for this exact request", actor)
        return state


def _claim(script, caster, phases, kind, *, revision=None, actor=None, checkpoint=None, authority=None):
    with _locked(script, caster) as state:
        if authority is not None:
            actor = _staff(authority)
        if revision is not None:
            _revision(state, revision)
        if state["phase"] not in phases:
            return None
        if kind in ("payment", "resolving"):
            _eligible(caster, state["ritual"])
        if kind == "payment":
            _target(state)
        if kind == "payment" and caster.hunger >= 5:
            raise ValueError(HUNGER_5_REFUSAL)
        op = {"id": uuid.uuid4().hex, "kind": kind, "checkpoint": checkpoint,
              "actor": actor, "started_at": current_time(), "status": "in_progress"}
        state["operation_id"] = op["id"]
        state["operations"].append(op)
        _advance(script, state, "payment_in_progress" if kind == "payment" else kind,
                 "operation claimed before randomness/resources", actor)
        return op["id"]


def _settled(state, operation):
    next(item for item in state["operations"] if item["id"] == operation)["status"] = "settled"


def _pay(caster, state, checkpoint=None, actor=None):
    count = 1 if checkpoint else state["metadata"]["rouse"]
    paid = perform_rouse_check(caster, reason=state["ritual"], count=count)
    if paid.refused:
        raise ValueError(HUNGER_5_REFUSAL)
    state["payments"].append({"operation_id": state["operation_id"], "checkpoint": checkpoint,
        "actor": actor, "at": current_time(), "hunger_before": paid.hunger_before,
        "hunger_after": paid.hunger_after, "frenzy_test_pending": paid.frenzy_test,
        "checks": [{"rolls": list(check.rolls), "success": check.success, "label": check.label} for check in paid.checks]})


def _pay_operation(caster, script, operation, checkpoint=None, actor=None, authority=None):
    with _locked(script, caster) as state:
        if state["operation_id"] != operation or state["phase"] != "payment_in_progress":
            raise ValueError("The payment operation is no longer owned")
        if authority is not None:
            actor = _operation_staff(state, authority)
        _pay(caster, state, checkpoint, actor)
        _settled(state, operation)
        preparing = checkpoint is not None and len(state["payments"]) < state["metadata"]["rouse"]
        state["ready_at"] = None if preparing else current_time() + state["metadata"]["casting_seconds"]
        _advance(script, state, "preparing" if preparing else "casting", "payment settled", actor)
        return state


def confirm_cast(caster, cast_id):
    script = script_for_cast(caster, cast_id)
    state = cast_status(caster, cast_id)
    if state["phase"] == "awaiting_attestation":
        raise ValueError("A Builder must attest this cast revision before confirmation or payment")
    if state["phase"] != "prepared":
        return state
    timing = state["procedure"]["payment_timing"]
    if timing == "before_casting":
        op = _claim(script, caster, {"prepared"}, "payment", revision=state["revision"])
        return _pay_operation(caster, script, op) if op else cast_status(caster, cast_id)
    with _locked(script, caster) as state:
        if state["phase"] != "prepared":
            return state
        _eligible(caster, state["ritual"])
        _target(state)
        staged = timing == "staged_preparation"
        state["ready_at"] = None if staged else current_time() + state["metadata"]["casting_seconds"]
        _advance(script, state, "preparing" if staged else "casting", "caster confirmed attested procedure")
        return state


def pay_preparation(caster, cast_id, staff, checkpoint_id, *, revision):
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as state:
        _staff(staff)
        if any(payment["checkpoint"] == checkpoint_id for payment in state["payments"]):
            return state
        checkpoints = (state.get("procedure") or {}).get("checkpoints", [])
        if (state["phase"] != "preparing" or len(state["payments"]) >= len(checkpoints)
                or checkpoints[len(state["payments"])]["id"] != checkpoint_id):
            raise ValueError("Confirm the next attested preparation checkpoint, one at a time")
    op = _claim(script, caster, {"preparing"}, "payment", revision=revision, checkpoint=checkpoint_id, authority=staff)
    return _pay_operation(caster, script, op, checkpoint_id, authority=staff) if op else cast_status(caster, cast_id)


def _roll(character, pool_text, difficulty):
    names = parse_dice_pool(pool_text)
    pool, breakdown = calculate_pool_from_traits(character, names)
    penalties = impairment_for_pool(character, resolve_pool_traits(names))
    breakdown.update(penalties["components"])
    pool = max(1, min(MAX_POOL, pool + penalties["penalty"]))
    rolled = roll_v5_pool(pool, character.dice_hunger, difficulty)
    return {"pool_text": pool_text, "pool": pool, "breakdown": breakdown,
            "regular": list(rolled.regular_dice), "hunger": list(rolled.hunger_dice),
            "difficulty": difficulty, "successes": rolled.total_successes, "success": rolled.is_success,
            "result_type": rolled.result_type, "margin": rolled.margin}


def resolve_cast(caster, cast_id):
    script = script_for_cast(caster, cast_id)
    state = cast_status(caster, cast_id)
    if state["phase"] != "casting" or state["ready_at"] > current_time():
        return state
    if state["procedure"]["payment_timing"] == "after_casting" and caster.hunger >= 5:
        raise ValueError(HUNGER_5_REFUSAL)  # No roll/claim; feed, then explicitly resolve.
    op = _claim(script, caster, {"casting"}, "resolving", revision=state["revision"])
    if op is None:
        return cast_status(caster, cast_id)
    with _locked(script, caster) as state:
        if state["operation_id"] != op or state["phase"] != "resolving":
            raise ValueError("The resolution operation is no longer owned")
        try:
            target = _target(state)
        except ValueError as error:
            state["result"] = {"casting_success": False, "reason": str(error), "adjudication_required": False}
            _settled(state, op)
            _advance(script, state, "failed", "target lost; no further charge or roll")
            return state
        defense = None
        if state["metadata"]["opposed_by"] and state["procedure"]["opposition"] == "catalog_roll":
            _refresh(target, RESOURCE_ROOTS)
            defense = _roll(target, state["metadata"]["opposed_by"], 0)
        roll = _roll(caster, state["metadata"]["dice_pool"], state["metadata"]["difficulty"])
        success = roll["success"]
        if defense is not None:
            beats = roll["successes"] >= defense["successes"] if state["procedure"]["opposed_ties"] == "actor_wins" else roll["successes"] > defense["successes"]
            success = success and beats
        if state["procedure"]["payment_timing"] == "after_casting":
            _pay(caster, state)
        state["result"] = {"casting_success": success, "roll": roll, "defense": defense,
            "adjudication_required": success, "facts_discovered": [], "automatic_mechanical_outcome": False,
            "requested_adjudication": state["procedure"]["outcome"],
            "failure_policy": state["procedure"]["failure_policy"], "failure_attestation": state["procedure"]["failure"]}
        _settled(state, op)
        _advance(script, state, "awaiting_adjudication" if success else "failed", "casting roll settled")
        return state


def cancel_cast(caster, cast_id):
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as state:
        if state["phase"] in IN_PROGRESS or state["phase"] == "review_required":
            raise ValueError("An indeterminate operation requires staff review, never cancellation/replay")
        if state["phase"] in TERMINAL:
            return state
        _advance(script, state, "cancelled", "cancelled; no refund of recorded payments")
        return state


def _duration(duration):
    if not isinstance(duration, Mapping) or duration.get("kind") not in ("instant", "turn", "scene", "night", "permanent"):
        raise ValueError("Staff must supply a specific supported effect duration")
    value = _plain(dict(duration))
    if value["kind"] == "turn" and (not isinstance(value.get("turns"), int) or isinstance(value["turns"], bool) or value["turns"] < 1):
        raise ValueError("Staff must supply positive remaining turns")
    return value


def adjudicate_cast(caster, cast_id, staff, *, revision, outcome, duration):
    outcome, duration = _text(outcome, "adjudicated outcome"), _duration(duration)
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as current:
        _staff(staff)
        if current["phase"] == "completed":
            previous = current["adjudication"]
            if previous["outcome"] == outcome and previous["duration"] == duration:
                return current
            raise ValueError("The completed outcome is immutable; staff must review corrections separately")
    op = _claim(script, caster, {"awaiting_adjudication"}, "adjudicating", revision=revision, authority=staff)
    if op is None:
        raise ValueError("Only a successful unresolved casting can be adjudicated")
    with _locked(script, caster) as state:
        if state["operation_id"] != op or state["phase"] != "adjudicating":
            raise ValueError("The adjudication operation is no longer owned")
        actor = _operation_staff(state, staff)
        _target(state)
        from commands.v5.utils.discipline_effects import apply_effect

        identity = f"ritual:{cast_id}:outcome"
        raw = caster.db.active_effects
        records = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else ()
        matches = [effect for effect in records if isinstance(effect, Mapping) and effect.get("id") == identity]
        if matches:
            raise ValueError("Outcome identity already exists without a settled adjudication; staff review required")
        params = {"ritual": state["ritual"], "adjudication_only": True, "adjudication": outcome,
                  "cast_id": cast_id, "staff": actor, "target": state["target"]}
        if duration["kind"] == "turn":
            params["turns"] = duration["turns"]
        effect = apply_effect(caster, {"name": state["ritual"], "discipline": "Blood Sorcery"},
                              duration["kind"], params, effect_id=identity, source_kind="ritual")
        state["adjudication"] = {"actor": actor, "outcome": outcome, "duration": duration,
                                  "effect_id": effect["id"] if effect else None, "at": current_time()}
        state["unresolved"] = []
        _settled(state, op)
        _advance(script, state, "completed", "staff adjudicated; descriptive marker only", actor)
        return state


def close_review(caster, cast_id, staff, *, revision, note):
    """Explicitly abandon an investigated indeterminate attempt without replay/refund."""
    note = _text(note, "staff investigation")
    script = script_for_cast(caster, cast_id)
    with _locked(script, caster) as state:
        actor = _staff(staff)
        _revision(state, revision)
        if state["phase"] != "review_required":
            raise ValueError("Only an interrupted attempt under review can be closed")
        state["review"] = {"actor": actor, "note": note, "at": current_time(),
                           "decision": "abandoned_without_refund_or_replay"}
        _advance(script, state, "cancelled", "staff closed review; uncertainty and ledger retained", actor)
        return state


class RitualCastingScript(DefaultScript):
    """Persistent timer/restart owner; no retry of interrupted operations."""

    def at_script_creation(self):
        self.interval = 5
        self.start_delay = True
        self.persistent = True

    def at_start(self, **kwargs):
        if not self.attributes.has("cast_state"):
            return
        with _locked(self, self.obj) as state:
            if state["phase"] in IN_PROGRESS:
                _advance(self, state, "review_required", "startup found interrupted operation; never replay")

    def at_repeat(self):
        if self.obj is None:
            return
        # This is only a scheduling hint in the reactor. Any actionable cast
        # re-enters resolve_cast's fresh, locked state/operation checks. Idle
        # attempts need no no-op write locks on every timer pulse.
        state = deserialize(self.db.cast_state)
        if state["phase"] in TERMINAL:
            self.stop()  # Stops the timer, retaining this Script and its audit state.
            return
        # Awaiting adjudication remains a recovery owner: a later claimed
        # adjudication must still be recognized as interrupted on restart.
        if state["phase"] == "casting" and state["ready_at"] <= current_time():
            try:
                settled = resolve_cast(self.obj, state["cast_id"])
            except ValueError as error:
                # A current refusal is not proof that a claim is interrupted.
                self.obj.msg(f"Ritual {state['cast_id']} awaits attention: {error}")
            else:
                self.obj.msg(f"Ritual {state['cast_id']}: {settled['phase']}. Casting success supplies no automatic facts.")
