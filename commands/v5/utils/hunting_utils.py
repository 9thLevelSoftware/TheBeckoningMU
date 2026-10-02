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


def hunting_pool(character):
    """The character's hunting roll from PREDATOR_TYPES, as (pool text, None) or (None, reason).

    Blood Leech has no single hunting roll in the book, and characters
    without a predator type (thin-bloods, fledglings) have none either:
    their hunts are run by the Storyteller.
    """
    predator = character.predator_type
    if not predator:
        return None, "You have no predator type, so your hunts are run by the Storyteller (+hunt/staffed)."
    pool = PREDATOR_TYPES.get(predator, {}).get("hunting_pool")
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
        reduced = int(slaked * row["animal_bagged_slake"])
        if reduced != slaked:
            note = row["feeding_penalty"]
        slaked = reduced
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


def hunt(character, ground):
    """
    Hunt on a hunting ground: the predator type's hunting roll against the
    ground's difficulty. A win feeds: a human vessel gives the maximum
    non-harmful drink ("drink", 2 Hunger), or the predator type's own
    blood source (Farmer: an animal, Bagger: a blood bag). Hunger never
    reaches 0 this way.

    Returns:
        dict: {"success", "refused" (a reason or None), "pool_text", "pool",
               "breakdown", "difficulty", "roll", "feeding" (slake result or
               None), "resonance", "complication", "message"}
    """
    pool_text, refusal = hunting_pool(character)
    if refusal:
        return {"success": False, "refused": refusal, "message": refusal}
    try:
        pool, breakdown = pool_size(character, pool_text)
    except UnknownTrait:
        # e.g. a pool that names a Background; the Storyteller runs these hunts
        message = f"Your hunting roll ({pool_text}) needs the Storyteller (+hunt/staffed)."
        return {"success": False, "refused": message, "message": message}

    difficulty = HUNTING_GROUNDS[ground]["difficulty"]
    roll = roll_v5_pool(max(1, min(MAX_POOL, pool)), character.dice_hunger, difficulty)
    result = {"success": roll.is_success, "refused": None, "pool_text": pool_text, "pool": pool,
              "breakdown": breakdown, "difficulty": difficulty, "roll": roll, "feeding": None,
              "resonance": None, "complication": None}

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
    if FEEDING_SOURCES[source]["kind"] == "human":
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
