"""Canonical effect creation, safe legacy normalization and effect lifecycle."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Optional, Dict, List, Any
import uuid

from evennia.utils.dbserialize import deserialize
from world.v5_data import DISCIPLINES, find_power

EFFECT_SCHEMA_VERSION = 1
ALCHEMY = "Thin-Blood Alchemy"
PARAMETER_KEYS = frozenset({
    "turns", "visibility", "enhanced", "disguised", "type", "target", "perception_bonus",
    "shared_senses", "speed_boost", "defense_bonus", "damage_reduction", "health_levels",
    "attraction", "untouchable", "night_vision", "claws", "damage_bonus", "transformed", "ritual",
})
DURATIONS = frozenset({"instant", "turn", "scene", "night", "permanent", "passive"})


def make_effect(*, effect_id, source_kind, power, discipline, duration, parameters, applied,
                turns_remaining=None):
    """Build one versioned record using the existing duration/parameter meanings."""
    if not isinstance(parameters, Mapping):
        raise ValueError("Effect parameters must be a mapping")
    return {"schema_version": EFFECT_SCHEMA_VERSION, "id": effect_id,
            "activation_id": effect_id, "source_kind": source_kind, "power": power,
            "discipline": discipline, "duration": duration, "parameters": deserialize(parameters),
            "applied": applied, "turns_remaining": turns_remaining}


def _catalog_effect(name, source_kind=None):
    power = find_power(name)
    if power is not None and source_kind in (None, "discipline"):
        return power, "discipline", power["discipline"]
    wanted = str(name or "").casefold()
    for discipline, field, kind in ((ALCHEMY, "formulas", "alchemy"),
                                     ("Blood Sorcery", "rituals", "ritual")):
        if source_kind not in (None, kind):
            continue
        entries = DISCIPLINES[discipline].get(field, {})
        groups = entries.values() if isinstance(entries, Mapping) else [entries]
        for group in groups:
            for entry in group:
                if entry["name"].casefold() == wanted:
                    return entry, kind, discipline
    return None, source_kind or "unknown", None


def _normalize_record(record, *, persist=False):
    """Return (plain record, reasons); never reconstruct elapsed durations."""
    if not isinstance(record, Mapping):
        return deserialize(record), ["Unsupported non-mapping effect"]
    effect = deserialize(record)
    if effect.get("schema_version") not in (None, EFFECT_SCHEMA_VERSION):
        return effect, ["Unsupported effect schema version"]
    reasons = []
    name = effect.get("power") or effect.get("name")
    source = effect.get("source_kind") or ("alchemy" if effect.get("type") == "alchemy" else None)
    catalog, kind, discipline = _catalog_effect(name, source)
    if catalog is None:
        reasons.append("Unknown effect source/power; mechanics require staff review")
    elif effect.get("discipline") not in (None, discipline):
        reasons.append("Effect discipline conflicts with its catalog source")
    effect.setdefault("power", catalog["name"] if catalog else name or "Unknown Power")
    effect.setdefault("discipline", discipline or "Unknown")
    effect.setdefault("source_kind", kind)
    effect["schema_version"] = EFFECT_SCHEMA_VERSION
    params = effect.get("parameters", {})
    if not isinstance(params, Mapping):
        reasons.append("Malformed effect parameters")
        # Preserve the original value; effect_parameters will refuse it.
    else:
        params = deserialize(params)
        for key in PARAMETER_KEYS:
            if key in effect and key not in ("type",):
                if key in params and params[key] != effect[key]:
                    reasons.append(f"Conflicting parameter: {key}")
                else:
                    params[key] = deserialize(effect[key])
        effect["parameters"] = params
    duration = effect.get("duration")
    if not isinstance(duration, str) or duration not in DURATIONS:
        reasons.append("Unknown duration; no automatic expiry")
    if effect.get("duration") == "turn":
        turns = effect.get("turns_remaining")
        if not isinstance(turns, int) or isinstance(turns, bool):
            reasons.append("Unknown remaining turns; no elapsed-duration reconstruction")
    effect.setdefault("turns_remaining", None)
    effect.setdefault("applied", None)
    identity = effect.get("id")
    if not isinstance(identity, str) or not identity.strip():
        if identity not in (None, ""):
            reasons.append("Malformed effect ID")
        if persist:
            if identity not in (None, ""):
                effect.setdefault("legacy_id", identity)
            effect["id"] = uuid.uuid4().hex
    effect["mechanics_supported"] = not reasons
    return effect, reasons


def normalize_effects(character, *, persist=False, retire_instant=False):
    """Inventory by default; explicit persistence assigns missing IDs once.

    Unknown records/metadata and historical duplicates survive. Retirement
    requires an explicit request plus a catalog formula with literal instant
    duration (Counterfeit's dynamic duration is deliberately insufficient).
    """
    raw = character.db.active_effects
    report = {"records": [], "changes": [], "unresolved": [], "retired": [], "retire_candidates": []}
    if raw is None:
        return report
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        report["unresolved"].append({"index": None, "reason": "Unsupported effect store", "record": deserialize(raw)})
        return report
    original = deserialize(raw)
    counts = Counter(e.get("id") for e in original if isinstance(e, Mapping) and isinstance(e.get("id"), str))
    for index, record in enumerate(original):
        effect, reasons = _normalize_record(record, persist=persist)
        if isinstance(effect, Mapping):
            if isinstance(effect.get("id"), str) and counts[effect["id"]] > 1:
                reasons.append("Duplicate effect ID; selective removal and mechanics require staff review")
                if effect.get("schema_version") == EFFECT_SCHEMA_VERSION:
                    effect["mechanics_supported"] = False
            catalog, kind, _ = _catalog_effect(effect.get("power"), effect.get("source_kind"))
            instant = (kind == "alchemy" and catalog is not None
                       and catalog.get("duration_text") == "instant" and effect.get("duration") == "instant"
                       and not reasons)
            if instant:
                candidate = {"index": index, "id": effect.get("id"), "power": effect.get("power")}
                report["retire_candidates"].append(candidate)
                if persist and retire_instant:
                    report["retired"].append(candidate)
                    report["changes"].append({"index": index, "action": "retired_verified_instant"})
                    continue
        for reason in reasons:
            report["unresolved"].append({"index": index, "reason": reason, "record": deserialize(record)})
        if effect != record:
            report["changes"].append({"index": index, "action": "normalized"})
        report["records"].append(effect)
    if persist and report["records"] != original:
        character.attributes.add("active_effects", report["records"])
    return report


def effect_parameters(effect: Mapping) -> Mapping:
    """Safe mechanical boundary; unsupported records contribute no parameters."""
    normalized, reasons = _normalize_record(effect)
    if reasons or not isinstance(normalized, Mapping) or effect.get("mechanics_supported") is False:
        return {}
    params = normalized.get("parameters", {})
    return params if isinstance(params, Mapping) else {}


def active_power_bonus(character, power_name, parameter):
    """Use the strongest supported named-power contribution, never a sum.

    Unknown, duplicate-ID and malformed parameter records contribute nothing.
    A legacy arbitrary number cannot exceed the user's current discipline.
    """
    catalog = find_power(power_name)
    if catalog is None:
        return 0
    rating = character.get_trait(catalog["discipline"])
    if rating < catalog["level"]:
        return 0
    bonuses = []
    for effect in get_active_effects(character):
        if str(effect.get("power", "")).casefold() != catalog["name"].casefold():
            continue
        value = effect_parameters(effect).get(parameter, 0)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            bonuses.append(min(value, rating))
    return max(bonuses, default=0)


def fleetness_defense_used(character):
    """Persistent turn usage is independent of effect IDs and reactivation."""
    return bool(character.attributes.get("fleetness_defense_used", default=False))


def consume_fleetness_defense(character):
    character.attributes.add("fleetness_defense_used", True)


def apply_effect(character, power_dict: Dict[str, Any], duration: str,
                 parameters: Optional[Dict[str, Any]] = None, *, effect_id=None, source_kind="discipline"):
    """Append one new activation record; instant actions leave no lasting effect."""
    if not duration or duration == "instant":
        return None
    params = deserialize(parameters) if isinstance(parameters, Mapping) else {}
    effect = make_effect(effect_id=effect_id or uuid.uuid4().hex, source_kind=source_kind,
                         power=power_dict.get("name", "Unknown Power"),
                         discipline=power_dict.get("discipline", "Unknown"), duration=duration,
                         parameters=params, applied=datetime.now(),
                         turns_remaining=params.get("turns", 1) if duration == "turn" else None)
    raw = character.db.active_effects
    if raw is None:
        effects = []
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        effects = list(deserialize(raw))
    else:
        # Preserve an opaque legacy store as one uninterpreted record when an
        # explicit activation needs to append. Do not discard or unpack it.
        effects = [deserialize(raw)]
    effects.append(effect)
    character.attributes.add("active_effects", effects)
    return effect


def remove_effect(character, effect_id: str) -> bool:
    """Remove exactly one canonical ID; malformed/ambiguous history survives."""
    raw = character.db.active_effects
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not isinstance(effect_id, str):
        return False
    matches = [i for i, effect in enumerate(raw) if isinstance(effect, Mapping) and effect.get("id") == effect_id]
    if len(matches) != 1:
        return False
    effects = list(deserialize(raw))
    effects.pop(matches[0])
    character.attributes.add("active_effects", effects)
    return True


def get_active_effects(character, filter_discipline: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read normalized views without IDs/writes; retain opaque entries for display."""
    report = normalize_effects(character)
    effects = [effect if isinstance(effect, Mapping) else
               {"power": "Unrecognized legacy effect", "discipline": "Unknown", "legacy_record": effect,
                "mechanics_supported": False} for effect in report["records"]]
    if report["unresolved"] and not effects:
        effects = [{"power": "Unrecognized legacy effect store", "discipline": "Unknown",
                    "mechanics_supported": False}]
    if filter_discipline:
        effects = [e for e in effects if str(e.get("discipline", "")).casefold() == filter_discipline.casefold()]
    return effects


def tick_effects(character) -> List[Dict[str, Any]]:
    """Tick only recorded integer turn counters; preserve unknown history."""
    raw = character.db.active_effects
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    expired, remaining = [], []
    changed = False
    # Support is a store-level decision: individually valid records can still
    # have ambiguous duplicate identities. Keep their original data untouched.
    report = normalize_effects(character)
    unresolved_indices = {item["index"] for item in report["unresolved"]}
    for index, effect in enumerate(deserialize(raw)):
        turns = effect.get("turns_remaining") if isinstance(effect, Mapping) else None
        if (isinstance(effect, Mapping) and effect.get("schema_version") in (None, EFFECT_SCHEMA_VERSION)
                and index not in unresolved_indices and effect.get("duration") == "turn"
                and isinstance(turns, int) and not isinstance(turns, bool)):
            effect["turns_remaining"] = turns - 1
            changed = True
            (expired if effect["turns_remaining"] <= 0 else remaining).append(effect)
        else:
            remaining.append(effect)
    if changed:
        character.attributes.add("active_effects", remaining)
    # The existing staff tick is the explicit turn boundary. Do not infer time
    # from timestamps, logins, activation IDs, or another character's actions.
    if character.attributes.get("fleetness_defense_used") is True:
        character.attributes.add("fleetness_defense_used", False)
    return expired


def get_effect_description(effect: Mapping) -> str:
    if not isinstance(effect, Mapping):
        return "Unrecognized legacy effect (staff review)"
    description = f"{effect.get('power', effect.get('name', 'Unknown'))} ({effect.get('discipline', 'Unknown')})"
    if effect.get("duration") == "scene":
        description += " - Active until end of scene"
    elif effect.get("duration") == "turn":
        description += f" - {effect.get('turns_remaining', 'unknown')} turns remaining"
    elif effect.get("duration") == "permanent":
        description += " - Permanent effect"
    return description


def has_active_effect(character, power_name: str):
    return next((effect for effect in get_active_effects(character)
                 if str(effect.get("power", "")).casefold() == power_name.casefold()), None)


def clear_all_effects(character) -> int:
    """Explicit staff clearing may remove all records, including unsupported ones."""
    raw = character.db.active_effects
    if raw is None:
        return 0
    count = len(raw) if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else 1
    character.attributes.add("active_effects", [])
    return count


def power_effect_parameters(character, power, parameters=None, target=None):
    """Named catalog contributions, assembled before creating one record.

    Fleetness has licensed Basic Rules support; Prowess and Fortitude use the
    owner's approved provisional catalog policy, not invented fixed bonuses.
    """
    params = deserialize(parameters) if isinstance(parameters, Mapping) else {}
    name, discipline = power["name"].casefold(), power["discipline"]
    if discipline == "Obfuscate":
        if "cloak" in name or "silence" in name:
            params["visibility"] = "invisible"
        elif "vanish" in name:
            params.update(visibility="vanished", enhanced=True)
        elif "mask" in name:
            params["disguised"] = True
    elif discipline == "Dominate":
        if "compel" in name or "mesmerize" in name:
            params.update(type="command" if "compel" in name else "emotion", target=str(target) if target else "unknown")
    elif discipline == "Auspex":
        if "heightened" in name or "senses" in name:
            params["perception_bonus"] = 2
        elif "share" in name:
            params["shared_senses"] = True
    elif discipline == "Celerity":
        if name == "fleetness":
            params["dexterity_bonus"] = character.get_trait("Celerity")
    elif discipline == "Potence":
        if name == "prowess":
            params["damage_bonus"] = character.get_trait("Potence")
    elif discipline == "Fortitude":
        if name == "resilience":
            params["health_levels"] = character.get_trait("Fortitude")
        elif name == "toughness":
            params["damage_reduction"] = character.get_trait("Fortitude")
    elif discipline == "Presence":
        if "awe" in name:
            params["attraction"] = True
        elif "majesty" in name:
            params["untouchable"] = True
    elif discipline == "Protean":
        if "eyes" in name and "beast" in name:
            params["night_vision"] = True
        elif "feral" in name or "weapons" in name:
            params.update(claws=True, damage_bonus=2)
        elif "shapechange" in name or "earth" in name:
            params["transformed"] = True
    return params


def _apply_specific(character, discipline, power_name, parameters=None, target=None):
    power = {"name": power_name, "discipline": discipline}
    params = power_effect_parameters(character, power, parameters, target)
    return apply_effect(character, power, "scene", params)


def apply_obfuscate_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Obfuscate", power_name, parameters)


def apply_dominate_effect(character, power_name, target=None, parameters=None):
    return _apply_specific(character, "Dominate", power_name, parameters, target)


def apply_auspex_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Auspex", power_name, parameters)


def apply_celerity_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Celerity", power_name, parameters)


def apply_fortitude_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Fortitude", power_name, parameters)


def apply_presence_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Presence", power_name, parameters)


def apply_protean_effect(character, power_name, parameters=None):
    return _apply_specific(character, "Protean", power_name, parameters)


# Blood Sorcery Ritual System

def perform_ritual(character, ritual_name: str, ingredients: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compatibility request path: never grant a free ritual or assume ingredients."""
    from world.rituals.casting import begin_cast, prepare_cast

    try:
        plan = prepare_cast(character, ritual_name, context={"requested_ingredients": list(ingredients or [])})
        identity = begin_cast(character, plan)
    except ValueError as error:
        return {"success": False, "message": str(error), "cast_id": None}
    return {"success": False, "request_created": True, "cast_id": identity,
            "message": "Unpaid ritual request created; Builder attestation and caster confirmation required."}


def get_power_duration(power_dict: Dict[str, Any]) -> Optional[str]:
    """
    Determine the duration type for a discipline power.

    Args:
        power_dict: The power dictionary

    Returns:
        Duration string or None if instant/no duration
    """
    power_name = power_dict.get('name', '').lower()
    discipline = power_dict.get('discipline', '').lower()

    # Explicitly defined duration
    if 'duration' in power_dict:
        return power_dict['duration']

    # Infer duration from power characteristics
    system = power_dict.get('system', '').lower()

    # Keywords indicating scene duration
    scene_keywords = ['scene', 'until', 'maintained', 'while active', 'as long as']
    if any(keyword in system for keyword in scene_keywords):
        return 'scene'

    # Keywords indicating turn duration
    turn_keywords = ['turn', 'round']
    if any(keyword in system for keyword in turn_keywords):
        # Try to extract number of turns
        import re
        match = re.search(r'(\d+)\s+turn', system)
        if match:
            return 'turn'

    # Discipline-specific defaults
    if discipline == 'obfuscate':
        if any(word in power_name for word in ['cloak', 'vanish', 'mask', 'silence']):
            return 'scene'

    elif discipline == 'dominate':
        if any(word in power_name for word in ['compel', 'mesmerize', 'dementation']):
            return 'scene'
        if 'forgetful mind' in power_name or 'terminal decree' in power_name:
            return 'permanent'

    elif discipline == 'auspex':
        if any(word in power_name for word in ['heightened', 'share', 'spirit']):
            return 'scene'

    elif discipline == 'celerity':
        if any(word in power_name for word in ['fleetness', 'draught']):
            return 'scene'

    elif discipline == 'fortitude':
        if any(word in power_name for word in ['resilience', 'enduring']):
            return 'scene'

    elif discipline == 'presence':
        if any(word in power_name for word in ['awe', 'majesty', 'summon', 'entrancement']):
            return 'scene'

    elif discipline == 'protean':
        if any(word in power_name for word in ['eyes', 'feral', 'earth', 'shapechange']):
            return 'scene'

    # Default: instant (no effect tracking)
    return 'instant'
