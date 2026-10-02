"""
Combat utilities for the V5 combat system.

- Attacks are contested (core p.123-126): the attacker's pool against the
  defender's pool. The attacker needs at least as many successes as the
  defender (a tie goes to the acting character, as for contested powers);
  the damage is the margin plus the weapon's damage.
- Vampires halve mundane Superficial damage, rounding up, before it is
  marked (QR p.3; core p.126). Mortals, ghouls and thin-bloods without
  Vampiric Resilience don't.
- A track is Impaired when it is full (QR p.3: Health -2 to Physical tests,
  Willpower -2 to Mental and Social tests). A vampire whose Health track
  is full of Aggravated damage falls into torpor.

Only vampires roll Hunger dice (Character.dice_hunger).
"""

from dice.dice_roller import MAX_DIFFICULTY, MAX_POOL, roll_v5_pool
from world.ansi_theme import BLOOD_RED, DARK_RED, GOLD, PALE_IVORY, RESET, SHADOW_GREY
from world.v5_data import UnknownTrait

from .discipline_effects import get_active_effects

DAMAGE_TYPES = ("superficial", "aggravated")
DEFAULT_ATTACK_POOL = "Strength + Brawl"
DEFAULT_DEFENSE_POOL = "Dexterity + Athletics"
IMPAIRMENT_PENALTY = -2


def _effect_bonus(character, discipline, key):
    """The first active effect bonus of ``key`` from ``discipline`` (0 if none)."""
    for effect in get_active_effects(character):
        if effect.get("discipline") == discipline and key in effect:
            return effect.get(key, 0)
    return 0


def get_combat_pool(character, pool_desc, include_impairment=True):
    """
    A combat dice pool from "Attribute + Skill", less Health impairment.

    Returns:
        dict: {"pool": int, "base_pool": int, "impairment": int,
               "breakdown": str, "error": str or None}
    """
    base_pool = 0
    breakdown_parts = []
    for part in (p.strip() for p in pool_desc.split('+')):
        try:
            value = character.get_trait(part)
        except UnknownTrait:
            return {"pool": 0, "base_pool": 0, "impairment": 0, "breakdown": "",
                    "error": f"Unknown trait: {part or pool_desc}"}
        base_pool += value
        breakdown_parts.append(f"{part} {value}")

    impairment = get_impairment_penalty(character) if include_impairment else 0
    final_pool = max(1, min(MAX_POOL, base_pool + impairment))

    breakdown = " + ".join(breakdown_parts) + f" = {base_pool}"
    if impairment < 0:
        breakdown += f", {impairment} (impaired)"
    if final_pool != base_pool + impairment:
        breakdown += f" -> {final_pool}"
    return {"pool": final_pool, "base_pool": base_pool, "impairment": impairment,
            "breakdown": breakdown, "error": None}


def calculate_attack(attacker, defender, attack_pool_desc=DEFAULT_ATTACK_POOL, weapon=0,
                     defense_pool_desc=DEFAULT_DEFENSE_POOL):
    """
    Resolve a contested attack (core p.123-126).

    The attacker rolls ``attack_pool_desc`` and the defender rolls
    ``defense_pool_desc`` (plus an active Celerity defense bonus), each less
    their Health impairment and each with their own Hunger dice. The attack
    hits when the attacker's successes are at least the defender's (and at
    least 1). Damage = margin + weapon damage (+ an active Potence bonus).

    Returns:
        dict: {"success", "attack", "defense" (pool dicts), "result",
               "defense_result" (RollResult), "margin", "weapon",
               "potence_bonus", "damage", "message", "error"}
    """
    attack = get_combat_pool(attacker, attack_pool_desc)
    defense = get_combat_pool(defender, defense_pool_desc)
    for pool in (attack, defense):
        if pool["error"]:
            return {"success": False, "error": pool["error"], "message": pool["error"]}

    celerity = _effect_bonus(defender, "Celerity", "defense_bonus")
    if celerity:
        defense["pool"] = min(MAX_POOL, defense["pool"] + celerity)
        defense["breakdown"] += f", +{celerity} (Celerity)"

    defense_result = roll_v5_pool(defense["pool"], defender.dice_hunger, 0)
    difficulty = min(MAX_DIFFICULTY, max(1, defense_result.total_successes))
    result = roll_v5_pool(attack["pool"], attacker.dice_hunger, difficulty)

    potence_bonus = _effect_bonus(attacker, "Potence", "damage_bonus")
    success = result.is_success
    margin = max(0, result.total_successes - defense_result.total_successes) if success else 0
    damage = margin + weapon + potence_bonus if success else 0

    if success:
        message = (
            f"{BLOOD_RED}The attack hits!{RESET} {result.total_successes} successes vs "
            f"{defense_result.total_successes}. Margin {GOLD}{margin}{RESET}"
        )
        if weapon:
            message += f" + weapon {weapon}"
        if potence_bonus:
            message += f" + Potence {potence_bonus}"
        message += f" = {GOLD}{damage}{RESET} damage."
    else:
        message = (
            f"{SHADOW_GREY}The attack misses.{RESET} {result.total_successes} successes vs "
            f"{defense_result.total_successes}."
        )

    return {
        "success": success,
        "error": None,
        "attack": attack,
        "defense": defense,
        "result": result,
        "defense_result": defense_result,
        "margin": margin,
        "weapon": weapon,
        "potence_bonus": potence_bonus,
        "damage": damage,
        "message": message,
    }


def apply_damage(character, damage_amount, damage_type="superficial", halve=True):
    """
    Mark damage on a character's Health track.

    Superficial damage is halved, rounding up, for a character who halves
    it (Character.halves_superficial) unless ``halve`` is False (a source
    the Storyteller rules isn't mundane). When the track is full, each
    further Superficial point turns a Superficial box into Aggravated. A
    vampire whose track is full of Aggravated damage falls into torpor.

    Returns:
        dict: {"success", "message", "health_status", "marked",
               "impaired", "torpor"}
    """
    if damage_amount <= 0:
        return {"success": False, "message": "Damage amount must be positive.", "health_status": ""}
    if damage_type not in DAMAGE_TYPES:
        return {"success": False, "message": f"Invalid damage type: {damage_type}", "health_status": ""}

    soak = _effect_bonus(character, "Fortitude", "damage_reduction")
    amount = max(0, damage_amount - soak)
    halved = False
    if damage_type == "superficial" and halve and character.halves_superficial:
        amount = (amount + 1) // 2
        halved = True

    if amount == 0:
        return {"success": True, "message": f"{GOLD}Fortitude{RESET} soaks all the damage.",
                "health_status": get_health_status(character), "marked": 0, "impaired": False, "torpor": False}

    maximum = character.health_max
    marks = character.damage["health"]
    superficial, aggravated = marks["superficial"], marks["aggravated"]
    if damage_type == "aggravated":
        aggravated = min(maximum, aggravated + amount)
        superficial = min(superficial, maximum - aggravated)
        word = f"{BLOOD_RED}Aggravated{RESET}"
    else:
        superficial += amount
        overflow = max(0, superficial + aggravated - maximum)
        aggravated = min(maximum, aggravated + overflow)
        superficial = maximum - aggravated if overflow else superficial
        word = f"{DARK_RED}Superficial{RESET}"
        if overflow:
            word += f" ({overflow} upgraded to {BLOOD_RED}Aggravated{RESET}: the track is full)"
    character.set_damage("health", superficial=superficial, aggravated=aggravated)

    message = f"{character.key} takes {GOLD}{amount}{RESET} {word} damage."
    notes = []
    if halved:
        notes.append(f"halved from {max(0, damage_amount - soak)}")
    if soak:
        notes.append(f"Fortitude soaked {soak}")
    if notes:
        message += f" ({'; '.join(notes)})"

    after = character.damage["health"]
    torpor = after["aggravated"] >= maximum
    impaired = is_impaired(character)
    if torpor:
        if character.is_kindred:
            message += f"\n{BLOOD_RED}The Health track is full of Aggravated damage: {character.key} falls into torpor.{RESET}"
        else:
            message += f"\n{BLOOD_RED}The Health track is full of Aggravated damage: {character.key} is dying.{RESET}"
    elif impaired:
        message += f"\n{DARK_RED}The Health track is full: {character.key} is Impaired (-2 to Physical tests).{RESET}"

    return {"success": True, "message": message, "health_status": get_health_status(character),
            "marked": amount, "impaired": impaired, "torpor": torpor}


def heal_damage(character, heal_amount, damage_type="superficial"):
    """
    Remove damage from a character's Health track (no cost; staff use, and
    the mending helper below once its Rouse is paid).

    Returns:
        dict: {"success", "message", "health_status", "healed"}
    """
    if heal_amount <= 0:
        return {"success": False, "message": "Heal amount must be positive.", "health_status": ""}
    if damage_type not in DAMAGE_TYPES:
        return {"success": False, "message": f"Invalid damage type: {damage_type}", "health_status": ""}

    current = character.damage["health"][damage_type]
    if current == 0:
        return {"success": False, "message": f"No {damage_type} damage to heal.",
                "health_status": get_health_status(character), "healed": 0}
    healed = min(heal_amount, current)
    character.set_damage("health", **{damage_type: current - healed})
    color = DARK_RED if damage_type == "superficial" else BLOOD_RED
    return {"success": True, "message": f"{character.key} heals {GOLD}{healed}{RESET} {color}{damage_type.title()}{RESET} damage.",
            "health_status": get_health_status(character), "healed": healed}


def mend_superficial(character):
    """
    Mend Superficial damage by Rousing the Blood (QR p.13; core p.218).

    One Rouse check heals the Blood Potency table's mend_amount of
    Superficial damage. At Hunger 5 the Rouse is refused and nothing is
    healed. Vampires only; a thin-blood with Mortal Frailty can't mend.

    Returns:
        dict: {"success", "message", "rouse_result" (or None), "healed"}
    """
    from dice.rouse_checker import HUNGER_5_REFUSAL, perform_rouse_check
    from world.v5_data import BLOOD_POTENCY

    if not character.is_kindred:
        return {"success": False, "message": "Only vampires mend damage with the Blood.", "rouse_result": None,
                "healed": 0}
    if "Mortal Frailty" in character.advantages["flaws"]:
        return {"success": False, "message": "Mortal Frailty: you can't Rouse the Blood to mend.",
                "rouse_result": None, "healed": 0}
    if character.damage["health"]["superficial"] == 0:
        return {"success": False, "message": "You have no Superficial damage to mend.", "rouse_result": None,
                "healed": 0}

    rouse = perform_rouse_check(character, reason="Mending")
    if rouse.refused:
        return {"success": False, "message": HUNGER_5_REFUSAL, "rouse_result": rouse, "healed": 0}

    amount = BLOOD_POTENCY.get(character.blood_potency, {}).get("mend_amount", 1)
    healed = heal_damage(character, amount, "superficial").get("healed", 0)
    return {"success": True, "message": f"You mend {healed} Superficial damage.", "rouse_result": rouse,
            "healed": healed}


def is_impaired(character, track="health"):
    """True when the track is fully marked (QR p.3)."""
    maximum = character.health_max if track == "health" else character.willpower_max
    marks = character.damage[track]
    return marks["superficial"] + marks["aggravated"] >= maximum


def get_impairment_penalty(character):
    """Health impairment: -2 dice to Physical tests while the Health track is full (QR p.3), else 0."""
    return IMPAIRMENT_PENALTY if is_impaired(character, "health") else 0


def get_health_status(character):
    """
    The Health track: O healthy, / Superficial, X Aggravated, with Impaired or torpor noted.
    """
    maximum = character.health_max
    marks = character.damage["health"]
    aggravated = min(marks["aggravated"], maximum)
    superficial = min(marks["superficial"], maximum - aggravated)
    healthy = maximum - aggravated - superficial

    boxes = [f"{PALE_IVORY}O{RESET}"] * healthy + [f"{DARK_RED}/{RESET}"] * superficial + [f"{BLOOD_RED}X{RESET}"] * aggravated
    display = f"[{' '.join(boxes)}]"
    if aggravated >= maximum:
        display += f" {BLOOD_RED}(torpor){RESET}" if character.is_kindred else f" {BLOOD_RED}(dying){RESET}"
    elif healthy == 0:
        display += f" {SHADOW_GREY}(Impaired: {IMPAIRMENT_PENALTY} dice to Physical tests){RESET}"
    return display
