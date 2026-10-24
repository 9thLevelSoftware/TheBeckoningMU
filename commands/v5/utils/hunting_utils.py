"""
Hunting and feeding for V5.

The rules come from world.v5_data:
- the hunting roll is the predator type's ``hunting_pool``
  (PREDATOR_TYPES, core p.307-308) against the hunting ground's difficulty
  (HUNTING_GROUNDS, QR p.12);
- the Hunger a feeding slakes comes from FEEDING_SOURCES (QR p.12), less
  the Blood Potency feeding penalties (BLOOD_POTENCY), and only a kill takes
  Hunger below ``min_hunger_without_kill`` (1 at low Blood Potency).

The resonance of a hunted vessel and the complications on a messy critical
or bestial failure are a game convention (the book leaves both to the
Storyteller): the prey flavour and weights below are not rules data.
"""

import random

from dice.dice_roller import MAX_POOL, roll_v5_pool
from world.v5_data import (
    BLOOD_POTENCY,
    FEEDING_SOURCES,
    HUNTING_GROUNDS,
    PREDATOR_TYPES,
    RESONANCE_INTENSITIES,
    UnknownTrait,
)

from .blood_utils import clear_resonance, set_resonance

# Flavour text for prey of each resonance (game convention). The humours'
# disciplines and intensity effects are world.v5_data.RESONANCES /
# RESONANCE_INTENSITIES.
RESONANCE_TYPES = {
    "Choleric": {
        "emotions": ["angry", "violent", "passionate", "envious", "competitive"],
        "prey_types": ["bar fighter", "road rager", "abusive partner", "gang member", "sports fanatic"]
    },
    "Melancholy": {
        "emotions": ["sad", "depressed", "intellectual", "contemplative", "grieving"],
        "prey_types": ["mourner", "depressed artist", "struggling student", "lonely academic", "heartbroken lover"]
    },
    "Phlegmatic": {
        "emotions": ["calm", "lazy", "apathetic", "controlling", "medicated"],
        "prey_types": ["bureaucrat", "security guard", "exhausted worker", "stoner", "meditation practitioner"]
    },
    "Sanguine": {
        "emotions": ["happy", "lustful", "enthusiastic", "high", "flirty"],
        "prey_types": ["partygoer", "lover", "drug user", "optimist", "seducer"]
    }
}

# Which humours are likelier on each hunting ground (game convention).
GROUND_RESONANCE_WEIGHTS = {
    "slum": {"Choleric": 40, "Melancholy": 30, "Phlegmatic": 20, "Sanguine": 10},
    "bohemian": {"Sanguine": 40, "Melancholy": 30, "Choleric": 20, "Phlegmatic": 10},
    "downtown": {"Choleric": 30, "Sanguine": 30, "Phlegmatic": 25, "Melancholy": 15},
    "suburbs": {"Phlegmatic": 40, "Melancholy": 30, "Sanguine": 20, "Choleric": 10},
    "wealthy": {"Phlegmatic": 35, "Sanguine": 35, "Choleric": 20, "Melancholy": 10},
}

# Complications the Storyteller can use on a messy critical or bestial
# failure (game convention).
HUNTING_COMPLICATIONS = [
    {"type": "witness", "severity": "minor", "desc": "Someone sees you feed"},
    {"type": "struggle", "severity": "minor", "desc": "The vessel struggles more than expected"},
    {"type": "police", "severity": "moderate", "desc": "Police are nearby"},
    {"type": "rival", "severity": "moderate", "desc": "Another vampire is hunting nearby"},
    {"type": "hunter", "severity": "severe", "desc": "A hunter spots you"},
    {"type": "messy", "severity": "moderate", "desc": "You lose control and feed messily"},
    {"type": "disease", "severity": "minor", "desc": "The vessel has tainted blood"},
]


def find_ground(name):
    """The HUNTING_GROUNDS key for a name (any case, or a unique prefix), or None."""
    wanted = str(name or "").strip().lower()
    if wanted in HUNTING_GROUNDS:
        return wanted
    matches = [key for key in HUNTING_GROUNDS if key.startswith(wanted)] if wanted else []
    return matches[0] if len(matches) == 1 else None


def _is_physical(pool_text):
    """True if the pool uses a Physical Attribute (so Health impairment applies)."""
    from dice.pool_modifiers import is_physical_pool, resolve_pool_traits

    return is_physical_pool(resolve_pool_traits(part.strip() for part in pool_text.split("+")))


def hunting_pool(character, alternative=False):
    """The character's hunting roll from PREDATOR_TYPES, as (pool text, None) or (None, reason).

    ``alternative`` picks the type's ``alt_hunting_pool`` (the book's second
    option, e.g. Alleycat Wits + Streetwise).

    Blood Leech has no single hunting roll in the book, and characters
    without a predator type (thin-bloods, fledglings) have none either:
    their hunts are run by the Storyteller.
    """
    predator = character.predator_type
    if not predator:
        return None, "You have no predator type, so your hunts are run by the Storyteller (+hunt/staffed)."
    data = PREDATOR_TYPES.get(predator, {})
    if alternative:
        pool = data.get("alt_hunting_pool")
        if not pool:
            return None, f"{predator}s have no alternative hunting roll."
        return pool, None
    pool = data.get("hunting_pool")
    if not pool:
        return None, (f"{predator}s have no single hunting roll in the book; the Storyteller runs your hunts "
                      "(+hunt/staffed).")
    return pool, None


def pool_size(character, pool_text):
    """Dice for a pool such as "Strength + Brawl" (traits read through Character.get_trait).

    Raises UnknownTrait for a part that isn't a trait.
    """
    size = 0
    breakdown = []
    for part in (p.strip() for p in pool_text.split("+")):
        value = character.get_trait(part)
        size += value
        breakdown.append(f"{part} {value}")
    return size, " + ".join(breakdown)


def determine_resonance(ground="downtown"):
    """A random humour and intensity for a human vessel (game convention).

    Returns:
        dict: {"type", "intensity" (1-3), "intensity_name", "prey_description", "description"}
    """
    weights = GROUND_RESONANCE_WEIGHTS.get(ground, dict.fromkeys(RESONANCE_TYPES, 25))
    res_type = random.choices(list(weights), weights=list(weights.values()))[0]
    roll = random.randint(1, 100)
    intensity = 1 if roll <= 70 else 2 if roll <= 95 else 3
    prey = random.choice(RESONANCE_TYPES[res_type]["prey_types"])
    name = RESONANCE_INTENSITIES[intensity]["name"]
    return {
        "type": res_type,
        "intensity": intensity,
        "intensity_name": name,
        "prey_description": prey,
        "description": f"a {prey} with {res_type} resonance ({name})",
    }


def slake(character, source, amount=None):
    """
    Feed from a source in FEEDING_SOURCES and lower Hunger (QR p.12).

    ``amount`` overrides the source's slake (a harmful drink slakes 1-4).
    Blood Potency penalties apply (BLOOD_POTENCY: animal and bagged blood
    slake less or nothing; each human slakes ``human_slake_penalty`` less).
    Without a kill Hunger can't go below ``min_hunger_without_kill``; a
    kill takes it to 0.

    Animal Succulence (Animalism 3) adds 1 to animal blood and counts Blood
    Potency two lower for the animal penalty. At "half" (BP 2) the half
    point is kept in Character.slake_carry and counted when a second half
    arrives (reviews/bp2-half-research.md: medium confidence).

    Returns:
        dict: {"source", "slaked", "old_hunger", "new_hunger", "kill", "penalty_note"}
    """
    data = FEEDING_SOURCES[source]
    row = BLOOD_POTENCY.get(character.blood_potency, BLOOD_POTENCY[0])
    old = character.hunger
    kill = bool(data.get("kill"))
    slaked = data["slake"] if amount is None else amount
    note = None
    if data["kind"] in ("animal", "bagged"):
        penalty_row = row
        if data["kind"] == "animal" and "Animal Succulence" in character.known_powers:
            slaked += 1
            penalty_row = BLOOD_POTENCY.get(max(0, character.blood_potency - 2), BLOOD_POTENCY[0])
        fraction = penalty_row["animal_bagged_slake"]
        if fraction != 1:
            note = penalty_row["feeding_penalty"]
        if fraction == 0.5:
            whole = slaked * 0.5 + character.slake_carry
            slaked = int(whole)
            character.slake_carry = whole - slaked
        else:
            slaked = int(slaked * fraction)
    elif row["human_slake_penalty"] and not kill:
        slaked = max(0, slaked - row["human_slake_penalty"])
        note = row["feeding_penalty"]

    if kill:
        new = 0
    else:
        floor = row["min_hunger_without_kill"]
        new = min(old, max(floor, old - slaked))
    if new != old:
        character.hunger = new
    return {"source": source, "slaked": old - new, "old_hunger": old, "new_hunger": new, "kill": kill,
            "penalty_note": note}


HUNT_WINDOW = 24 * 3600  # one +hunt per character per 24 hours (owner decision)


def hunt_refusal(character, now):
    """Why the character can't +hunt now, or None (cooldown, Hunger floor)."""
    floor = BLOOD_POTENCY.get(character.blood_potency, BLOOD_POTENCY[0])["min_hunger_without_kill"]
    if character.hunger <= floor:
        return (f"Your Hunger is {character.hunger}: you can't feed any further without a kill. "
                "Ask for a staff-run scene (+hunt/staffed).")
    last = character.last_hunt
    if last is not None and now - last < HUNT_WINDOW:
        hours = int((HUNT_WINDOW - (now - last)) // 3600) + 1
        return (f"You have already hunted in the last 24 hours (again in about {hours} hour(s)). "
                "For more, ask for a staff-run scene (+hunt/staffed).")
    return None


def hunt(character, ground, alternative=False, now=None):
    """
    Hunt on a hunting ground: the predator type's hunting roll against the
    ground's difficulty. A win feeds: a human vessel gives the maximum
    non-harmful drink ("drink", 2 Hunger), or the predator type's own
    blood source (Farmer: an animal, Bagger: a blood bag). Hunger never
    reaches 0 this way.

    One hunt per 24 hours, successful or not, and none at the no-kill
    Hunger floor (hunt_refusal). ``alternative`` rolls the type's
    ``alt_hunting_pool``. The resonance changes only when Hunger was slaked.

    Returns:
        dict: {"success", "refused" (a reason or None), "pool_text", "pool",
               "breakdown", "difficulty", "roll", "feeding" (slake result or
               None), "resonance", "complication", "message"}
    """
    import time

    now = time.time() if now is None else now
    refusal = hunt_refusal(character, now)
    if refusal:
        return {"success": False, "refused": refusal, "message": refusal}
    pool_text, refusal = hunting_pool(character, alternative)
    if refusal:
        return {"success": False, "refused": refusal, "message": refusal}
    try:
        pool, breakdown = pool_size(character, pool_text)
    except UnknownTrait:
        # e.g. a pool that names a Background; the Storyteller runs these hunts
        message = f"Your hunting roll ({pool_text}) needs the Storyteller (+hunt/staffed)."
        return {"success": False, "refused": message, "message": message}

    from world.room_rules import hunting_context

    room_context = hunting_context(character, ground)
    difficulty = room_context["difficulty"]
    penalty = min(0, character.dice_penalty(physical=_is_physical(pool_text)))
    if penalty:
        breakdown += f", {penalty} (impaired)"
    from dice.pool_modifiers import effect_modifiers_for_pool, resolve_pool_traits

    traits = resolve_pool_traits(part.strip() for part in pool_text.split("+"))
    effects = effect_modifiers_for_pool(character, traits, context="noncombat")
    for label, bonus in effects.items():
        breakdown += f", +{bonus} ({label})"
    roll = roll_v5_pool(max(1, min(MAX_POOL, pool + penalty + sum(effects.values()))), character.dice_hunger, difficulty)
    character.last_hunt = now
    result = {"success": roll.is_success, "refused": None, "pool_text": pool_text, "pool": pool,
              "breakdown": breakdown, "difficulty": difficulty, "roll": roll, "feeding": None,
              "resonance": None, "complication": None, "room_context": room_context}

    if roll.is_messy_critical:
        result["complication"] = random.choice([c for c in HUNTING_COMPLICATIONS if c["severity"] != "minor"])
    elif roll.is_bestial_failure:
        result["complication"] = random.choice([c for c in HUNTING_COMPLICATIONS if c["severity"] == "severe"])

    if not roll.is_success:
        result["message"] = f"You find no vessel on the {ground} hunting ground tonight."
        return result

    source = PREDATOR_TYPES.get(character.predator_type, {}).get("blood_source") or "drink"
    feeding = slake(character, source)
    result["feeding"] = feeding
    if feeding["slaked"] <= 0:
        found = "a vessel" if FEEDING_SOURCES[source]["kind"] == "human" else FEEDING_SOURCES[source]["description"].lower()
    elif FEEDING_SOURCES[source]["kind"] == "human":
        resonance = determine_resonance(ground)
        set_resonance(character, resonance["type"], resonance["intensity"])
        result["resonance"] = resonance
        found = resonance["description"]
    else:
        clear_resonance(character)  # animal and bagged blood carry no humour (QR p.12)
        found = FEEDING_SOURCES[source]["description"].lower()
    result["message"] = (
        f"You find {found} and feed: Hunger {feeding['old_hunger']} -> {feeding['new_hunger']}."
    )
    if feeding["penalty_note"]:
        result["message"] += f" (Blood Potency {character.blood_potency}: {feeding['penalty_note']}.)"
    return result



def serialize_hunt_outcome(result):
    """Copy a resolved hunt into JSON primitives; never persist the RollResult.

    The command supplies location and before/after Hunger, including on a
    failed hunt. Pool adjustment is the actual net dice change, including
    impairment and the existing pool bounds; breakdown retains its explanation.
    """
    import json

    roll = result["roll"]
    feeding = result.get("feeding") or {}
    rolled = len(roll.regular_dice) + len(roll.hunger_dice)
    base = result["pool"]
    snapshot = {
        "schema_version": 1,
        "hunting_success": bool(result["success"]),
        "location": result["location"],
        "hunger_before": result["hunger_before"],
        "hunger_after": result["hunger_after"],
        "hunger_reduction": feeding.get("slaked", 0),
        "resonance": result.get("resonance"),
        "complications": [result["complication"]] if result.get("complication") else [],
        "pool": {"text": result["pool_text"], "base": base, "rolled": rolled,
                 "breakdown": result["breakdown"]},
        "modifiers": {"net_dice": rolled - base, "breakdown": result["breakdown"],
                      "room": result.get("room_context")},
        "difficulty": result["difficulty"],
        "dice": {"regular": list(roll.regular_dice), "hunger": list(roll.hunger_dice)},
        "outcome": {name: getattr(roll, name) for name in (
            "total_successes", "margin", "result_type", "is_success", "is_critical",
            "is_messy_critical", "is_bestial_failure")},
        "feeding": result.get("feeding"),
        "message": result.get("message", ""),
    }
    return json.loads(json.dumps(snapshot))


def format_hunt_outcome(snapshot):
    """Present stored facts only, including partial legacy snapshots without dice."""
    from collections.abc import Mapping

    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    success = snapshot.get("hunting_success")
    title = "SUCCESSFUL HUNT" if success is True else "HUNT FAILED" if success is False else "HUNT RESULT"
    lines = [f"|w{title}|n"]
    pool = snapshot.get("pool")
    if isinstance(pool, Mapping):
        lines.append(f"Hunting roll: {pool.get('text', 'unavailable')} ({pool.get('breakdown', 'unavailable')})")
        lines.append(f"Pool: {pool.get('base', 'unavailable')} base; {pool.get('rolled', 'unavailable')} dice rolled")
    modifiers = snapshot.get("modifiers")
    if isinstance(modifiers, Mapping):
        lines.append(f"Modifiers (net dice, including pool bounds): {modifiers.get('net_dice', 'unavailable')}")
        room = modifiers.get("room")
        if isinstance(room, Mapping):
            modifier = room.get("modifier", 0)
            if type(modifier) is int and modifier:
                lines.append(f"Room hunting modifier: {modifier:+d}; difficulty "
                             f"{room.get('base_difficulty')} -> {room.get('difficulty')}")
            if room.get("warning"):
                lines.append(str(room["warning"]))
    lines.append(f"Difficulty: {snapshot.get('difficulty', 'unavailable')} ({snapshot.get('location', 'unavailable')})")
    dice = snapshot.get("dice")
    if isinstance(dice, Mapping) and isinstance(dice.get("regular"), list) and isinstance(dice.get("hunger"), list):
        lines.append(f"Regular dice: {', '.join(map(str, dice['regular'])) or 'none'}")
        lines.append(f"Hunger dice: {', '.join(map(str, dice['hunger'])) or 'none'}")
    else:
        lines.append("Original dice unavailable (legacy snapshot; not reconstructed).")
    outcome = snapshot.get("outcome")
    if isinstance(outcome, Mapping):
        lines.append(f"Successes: {outcome.get('total_successes', 'unavailable')}; margin: {outcome.get('margin', 'unavailable')}")
        lines.append("Outcome: " + str(outcome.get("result_type", "unavailable")).replace("_", " ").upper())
    if snapshot.get("message"):
        lines.append(str(snapshot["message"]))
    lines.append(f"Hunger {snapshot.get('hunger_before', 'unavailable')} -> {snapshot.get('hunger_after', 'unavailable')} "
                 f"(slaked {snapshot.get('hunger_reduction', 'unavailable')})")
    feeding = snapshot.get("feeding")
    if isinstance(feeding, Mapping):
        lines.append(f"Feeding source: {feeding.get('source', 'unavailable')}")
        if feeding.get("penalty_note"):
            lines.append(f"Feeding penalty: {feeding['penalty_note']}")
    resonance = snapshot.get("resonance")
    if isinstance(resonance, Mapping):
        lines.append(f"Resonance: {resonance.get('type', 'unavailable')} ({resonance.get('intensity_name', 'unavailable')})")
    else:
        lines.append("No resonance gained" if "resonance" in snapshot else "Resonance unavailable")
    complications = snapshot.get("complications")
    if isinstance(complications, list):
        for complication in complications:
            text = complication.get("desc", "Details unavailable") if isinstance(complication, Mapping) else str(complication)
            lines.append(f"Complication: {text} (the Storyteller decides what follows)")
        if not complications:
            lines.append("No complications recorded")
    else:
        lines.append("Complications unavailable")
    return "\n".join(lines)
