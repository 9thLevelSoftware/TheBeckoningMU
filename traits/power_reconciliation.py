"""Conservative inventory/explicit repair for historical dot-only XP purchases.

Only an intact creation grant plus a complete XP ledger can prove a legacy
choice. Unknown/malformed history is reported for staff; it never grants a
power, guesses a choice, edits historical logs or refunds XP.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence

from evennia.utils.dbserialize import deserialize

from world.power_eligibility import power_requirement_errors
from world.v5_data import find_power, resolve_trait, xp_cost

LEGACY_SPEND = re.compile(r"^Raised (.+) to ([1-5]) \((in-clan|out-of-clan|Caitiff)\)(?: - .*)?$")
COST_KINDS = {"in-clan": "clan_discipline", "out-of-clan": "other_discipline", "Caitiff": "caitiff_discipline"}


def _ledger_error(experience):
    earned = spent = balance = 0
    log = experience.get("log", [])
    if not isinstance(log, Sequence) or isinstance(log, (str, bytes)):
        return "Malformed XP ledger"
    for entry in log:
        if not isinstance(entry, Mapping):
            return "Malformed XP ledger entry"
        amount = entry.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool):
            return "XP ledger contains a non-integral amount"
        if entry.get("type") == "award" and amount > 0:
            earned += amount
        elif entry.get("type") == "spend" and amount < 0:
            spent -= amount
        else:
            return "XP ledger contains an unrecognized transaction"
        balance += amount
        if balance < 0 or ("balance" in entry and entry["balance"] != balance):
            return "XP ledger balances do not reconcile"
    if earned != experience.get("total_earned", 0) or spent != experience.get("total_spent", 0):
        return "XP totals do not match the retained ledger"
    return None


def _creation_provenance(character):
    from world.rules_chargen import parse_submission, validate_v5_creation

    bio = character.bio
    if bio is None or bio.status not in ("approved", "revoked"):
        return None, "No retained approved/revoked creation grant"
    try:
        sub = parse_submission(bio.submission)
        if validate_v5_creation(sub):
            return None, "Retained creation grant does not validate"
    except (ValueError, TypeError):
        return None, "Retained creation grant is malformed"
    if sub.clan != character.clan:
        return None, "Clan differs from the retained creation grant"
    return (bio.pk, sub), None


def inventory_discipline_powers(character):
    """Pure, selection-free inventory: proposals require explicit application."""
    experience = deserialize(character._experience())
    report = {"character": character.pk, "disciplines": [], "proposed": [], "created": [], "review": []}
    creation, grant_error = _creation_provenance(character)
    ledger_error = _ledger_error(experience)
    choices = experience.get("power_choices", [])
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
        report["review"].append({"discipline": None, "reason": "Malformed power-choice history"})
        return report
    levels = character.discipline_levels
    stats = character.db.stats
    disciplines = stats.get("disciplines", {}) if isinstance(stats, Mapping) else {}

    for discipline, rating in levels.items():
        if discipline == "Thin-Blood Alchemy":
            continue  # Its dot-plus-formula contract is a separate system.
        key = resolve_trait(discipline, "disciplines").key
        stored = disciplines.get(key)
        raw_powers = stored.get("powers", []) if isinstance(stored, Mapping) else []
        if not isinstance(raw_powers, Sequence) or isinstance(raw_powers, (str, bytes)):
            raw_powers = [None]
        valid, invalid = [], []
        for name in raw_powers:
            power = find_power(name)
            if (
                power is None
                or power["discipline"] != discipline
                or power_requirement_errors(name, levels)
                or power["name"] in valid
            ):
                invalid.append(str(name))
            else:
                valid.append(power["name"])
        deficit = max(0, rating - len(valid))
        inventory = {
            "discipline": discipline,
            "rating": rating,
            "valid_powers": valid,
            "invalid_or_duplicate": invalid,
            "deficit": deficit,
            "provenance": [],
        }
        report["disciplines"].append(inventory)
        if not deficit:
            if invalid or len(valid) > rating:
                report["review"].append({"discipline": discipline, "reason": "Power list needs staff review"})
            continue
        reason = grant_error or ledger_error
        if invalid:
            reason = "Unknown, invalid or duplicate learned powers"
        if reason:
            report["review"].append({"discipline": discipline, "reason": reason})
            continue
        bio_id, sub = creation
        base = sub.disciplines.get(discipline, 0)
        baseline_powers = {name for name in sub.discipline_powers if find_power(name)["discipline"] == discipline}
        if base > rating or not baseline_powers.issubset(valid):
            report["review"].append(
                {"discipline": discipline, "reason": "Creation powers/rating were removed or changed"}
            )
            continue
        inventory["provenance"].append(
            {"type": "creation", "bio": bio_id, "rating": base, "powers": sorted(baseline_powers)}
        )
        advances = []
        for index, entry in enumerate(experience.get("log", [])):
            if entry.get("type") != "spend":
                continue
            legacy = LEGACY_SPEND.fullmatch(str(entry.get("reason", "")))
            if legacy and legacy[1] == discipline:
                dot = int(legacy[2])
                if -entry["amount"] != xp_cost(COST_KINDS[legacy[3]], dot):
                    reason = "Historical discipline purchase has an inconsistent cost"
                    break
                advances.append({"rating": dot, "log_index": index, "legacy": True})
            elif entry.get("discipline") == discipline:
                selected = find_power(entry.get("power"))
                dot = entry.get("rating")
                if (
                    not isinstance(dot, int)
                    or isinstance(dot, bool)
                    or not 1 <= dot <= 5
                    or selected is None
                    or selected["discipline"] != discipline
                    or selected["name"] not in valid
                    or entry.get("cost_kind") not in COST_KINDS.values()
                    or -entry["amount"] != xp_cost(entry["cost_kind"], dot)
                ):
                    reason = "A recorded selected power was removed or changed"
                    break
                advances.append({"rating": dot, "log_index": index, "legacy": False})
        if reason or [item["rating"] for item in advances] != list(range(base + 1, rating + 1)):
            report["review"].append(
                {
                    "discipline": discipline,
                    "reason": reason or "No complete, ordered XP provenance for the current rating",
                }
            )
            continue
        inventory["provenance"].extend(advances)
        legacy = [item for item in advances if item["legacy"]]
        existing = [
            choice for choice in choices if isinstance(choice, Mapping) and choice.get("discipline") == discipline
        ]
        # Consumed choices stay accounted for if a staff edit removes their power.
        # Reconciliation never replaces them or silently restores that power.
        if any(choice.get("status") not in ("pending", "consumed") for choice in existing):
            report["review"].append({"discipline": discipline, "reason": "Power-choice history needs staff review"})
            continue
        pending = sum(choice.get("status") == "pending" for choice in existing)
        consumed = [choice for choice in existing if choice.get("status") == "consumed"]
        if any(choice.get("power") not in valid for choice in consumed) or pending > deficit:
            report["review"].append({"discipline": discipline, "reason": "Issued choices no longer match the sheet"})
            continue
        remaining = deficit - pending
        candidates = []
        for advance in legacy:
            identity = f"v1:{character.pk}:{key}:{advance['rating']}"
            choice_id = "pc-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
            if any(choice.get("id") == choice_id for choice in existing):
                continue
            candidates.append(
                {
                    "id": choice_id,
                    "discipline": discipline,
                    "rating": advance["rating"],
                    "status": "pending",
                    "source": {"type": "legacy_xp", "bio": bio_id, "log_index": advance["log_index"]},
                }
            )
        if remaining > len(candidates):
            report["review"].append(
                {"discipline": discipline, "reason": "Deficit exceeds proven unissued legacy purchases"}
            )
            continue
        # When some historical choices were filled separately, their exact dot
        # cannot be reconstructed. Do not pick a higher entitlement cap by guess.
        if remaining and remaining != len(candidates):
            report["review"].append(
                {"discipline": discipline, "reason": "Partially filled legacy purchases require staff review"}
            )
            continue
        report["proposed"].extend(candidates if remaining else [])
    return report


def reconcile_discipline_powers(character, apply=False):
    """Inventory by default; explicit apply only adds proven pending choices."""
    if not apply:
        return inventory_discipline_powers(character)
    with character.advancement_transaction():
        report = inventory_discipline_powers(character)
        if report["proposed"]:
            experience = deserialize(character._experience())
            experience.setdefault("power_choices", []).extend(report["proposed"])
            character.attributes.add("experience", experience)
            report["created"] = report["proposed"]
        return report
