"""Command-facing ritual lifecycle access; one execution path in world.rituals."""

from world.rituals.casting import (  # noqa: F401
    adjudicate_cast,
    attest_cast,
    begin_cast,
    cancel_cast,
    cast_status,
    confirm_cast,
    list_casts,
    pay_preparation,
    prepare_cast,
    resolve_cast,
)


def format_cast(state):
    lines = [
        f"Ritual {state['cast_id']}: {state['ritual']} — {state['phase']} (revision {state['revision']})",
        f"Paid Rouse checks: {sum(len(p['checks']) for p in state['payments'])}/{state['metadata']['rouse']}",
        f"Casting time: {state['metadata']['casting_seconds']} seconds (provisional catalog)",
    ]
    if state.get("ready_at") is not None:
        from datetime import UTC, datetime

        lines.append(f"Ready at: {datetime.fromtimestamp(state['ready_at'], UTC).isoformat()}")
    if state.get("procedure"):
        proc = state["procedure"]
        lines += [
            f"Payment: {proc['payment_timing']}; casting starts: {proc['casting_start']}",
            f"Materials attested: {proc['materials']}",
            f"Target facts attested: {proc['target_facts']}",
            f"Failure: {proc['failure']}",
            "Cancellation retains paid costs.",
        ]
    for payment in state["payments"]:
        dice = [check["rolls"] for check in payment["checks"]]
        lines.append(
            f"Payment {payment['checkpoint'] or 'casting'}: {dice}; Hunger {payment['hunger_before']} → {payment['hunger_after']}"
        )
        if payment.get("frenzy_test_pending"):
            lines.append("A pending Hunger frenzy test is recorded; use +frenzy.")
    result = state.get("result")
    if result:
        if result.get("roll"):
            roll = result["roll"]
            lines.append(
                f"Casting: {roll['pool_text']}, {roll['pool']} dice; {roll['breakdown']}; "
                f"regular {roll['regular']}, Hunger {roll['hunger']}; {roll['successes']} successes vs {roll['difficulty']}"
            )
        if result.get("defense"):
            defense = result["defense"]
            lines.append(
                f"Opposition: {defense['pool_text']}, {defense['regular']} / Hunger {defense['hunger']}; {defense['successes']} successes"
            )
        lines.append(
            "Casting roll succeeded; staff adjudication is required. No facts or powers were granted."
            if result["casting_success"]
            else f"Casting did not succeed: {result.get('reason', 'attested failure policy applies')}"
        )
    if state.get("adjudication"):
        lines.append(f"Staff-adjudicated outcome: {state['adjudication']['outcome']} (descriptive only)")
    if state["phase"] == "review_required":
        lines.append(
            "An interrupted operation is indeterminate. No automatic charge, reroll or replay is allowed; Builder review required."
        )
    return "\n".join(lines)
