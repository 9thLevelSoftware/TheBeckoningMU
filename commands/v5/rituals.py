"""Player ritual requests and authenticated, exact-revision Storyteller attestations."""

import json

from evennia import default_cmds

from .utils import ritual_utils as rituals


class CmdRitual(default_cmds.MuxCommand):
    """Request and follow a persistent ritual casting.

    +ritual [<ritual> = <target>]
    +ritual/status <cast-id>
    +ritual/confirm <cast-id>
    +ritual/resolve <cast-id>
    +ritual/cancel <cast-id>

    Staff procedures: help ritual-guide. Requests are unpaid. Missing ritual
    facts require Builder attestation; casting success is not an automatic
    supernatural outcome. Staff adjudication may add a descriptive marker.
    """

    key = "+ritual"
    aliases = ["ritual", "+rituals"]
    locks = "cmd:all()"
    help_category = "V5 - Disciplines"

    def func(self):
        caller = self.caller
        try:
            switches = set(self.switches)
            if switches & {"attest", "pay", "adjudicate", "review"}:
                from world.rituals.casting import _staff

                # Account-aware and quell-aware; the service repeats this
                # fresh persisted check inside its locked decision boundary.
                _staff(caller)
                parts = (self.lhs or "").rsplit("/", 1)
                if len(parts) != 2 or not self.rhs:
                    raise ValueError(
                        "Staff syntax: +ritual/<action> <character>/<cast-id> = <revision>/<procedure>; see help ritual-guide"
                    )
                caster = caller.search(parts[0].strip())
                if not caster:
                    return
                cast_id = parts[1].strip()
                revision_text, separator, body = self.rhs.partition("/")
                if not separator:
                    raise ValueError("Supply the exact cast revision followed by / and the attestation")
                revision = int(revision_text.strip())
                if "attest" in switches:
                    state = rituals.attest_cast(caster, cast_id, caller, revision=revision, procedure=json.loads(body))
                elif "pay" in switches:
                    state = rituals.pay_preparation(caster, cast_id, caller, body.strip(), revision=revision)
                elif "review" in switches:
                    from world.rituals.casting import close_review

                    state = close_review(caster, cast_id, caller, revision=revision, note=body)
                else:
                    duration_text, separator, outcome = body.partition("/")
                    if not separator:
                        raise ValueError("Supply duration/outcome; use turn:<count> for a turn duration")
                    kind, _, turns = duration_text.strip().partition(":")
                    duration = {"kind": kind}
                    if kind == "turn":
                        duration["turns"] = int(turns)
                    state = rituals.adjudicate_cast(
                        caster, cast_id, caller, revision=revision, outcome=outcome, duration=duration
                    )
                caller.msg(rituals.format_cast(state))
                return
            cast_id = (self.lhs or "").strip()
            if "status" in switches:
                states = [rituals.cast_status(caller, cast_id)] if cast_id else rituals.list_casts(caller)
                caller.msg(
                    "\n\n".join(rituals.format_cast(state) for state in states) or "No ritual requests recorded."
                )
            elif "confirm" in switches:
                caller.msg(rituals.format_cast(rituals.confirm_cast(caller, cast_id)))
            elif "resolve" in switches:
                caller.msg(rituals.format_cast(rituals.resolve_cast(caller, cast_id)))
            elif "cancel" in switches:
                caller.msg(rituals.format_cast(rituals.cancel_cast(caller, cast_id)))
            elif not cast_id:
                caller.msg("Learned rituals: " + (", ".join(caller.known_rituals) or "none"))
                caller.msg(
                    "Use +ritual <name> [= target] to create an unpaid request; +ritual/status lists durable attempts."
                )
            else:
                target = caller.search(self.rhs.strip()) if self.rhs else None
                if self.rhs and not target:
                    return
                plan = rituals.prepare_cast(caller, cast_id, target=target)
                identity = rituals.begin_cast(caller, plan)
                caller.msg(rituals.format_cast(rituals.cast_status(caller, identity)))
                caller.msg(
                    "Unpaid request created. A Builder must attest its exact revision before you confirm casting."
                )
        except (ValueError, KeyError, TypeError) as error:
            caller.msg(f"Ritual refused: {error}. No automatic refund or replay.")
