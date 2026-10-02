"""
Thin-Blood utility functions: Thin-Blood Alchemy and daylight.

Thin-Blood Alchemy (V5 core p.282-288; world.v5_data.DISCIPLINES
["Thin-Blood Alchemy"]["formulas"]) works in two steps, kept apart from
Discipline powers:

1. Distil a formula you know (learned with +spend formula, or the one the
   Thin-blood Alchemist merit gives). Distilling costs 1 Rouse check and
   rolls a method pool with your Hunger dice (Athanor Corporis: Stamina +
   Alchemy; Calcinatio: Manipulation + Alchemy; Fixatio: Intelligence +
   Alchemy). A success gives one dose.
2. Use a dose: pay the formula's own activation cost (its "rouse" Rouse
   checks) and, if it has a dice pool, roll it.

Rolls go through dice.dice_roller.roll_v5_pool and Rouse checks through
dice.rouse_checker.perform_rouse_check; the Hunger they cost is added after
the roll (core pp.211-212).
"""

import random

from dice.dice_roller import MAX_POOL, roll_v5_pool
from dice.discipline_roller import calculate_pool_from_traits, parse_dice_pool
from dice.rouse_checker import HUNGER_5_REFUSAL, MAX_HUNGER, perform_rouse_check
from world.v5_data import DISCIPLINES

ALCHEMY = "Thin-Blood Alchemy"

# Distillation methods and their pools (core p.283; v5_data comment).
DISTILLATION_METHODS = {
    "athanor": ("Athanor Corporis", "Stamina + Thin-Blood Alchemy"),
    "calcinatio": ("Calcinatio", "Manipulation + Thin-Blood Alchemy"),
    "fixatio": ("Fixatio", "Intelligence + Thin-Blood Alchemy"),
}
# UNVERIFIED: the difficulty of a distillation roll. The book's text wasn't
# available; the Storyteller may set another with "vs <difficulty>".
DEFAULT_DISTILL_DIFFICULTY = 3


def is_thin_blood(character):
    """Check if character is a Thin-Blood."""
    return character.clan == "Thin-Blood"


def get_blood_potency(character):
    """Get character's Blood Potency (Thin-Bloods are always 0)."""
    if is_thin_blood(character):
        return 0
    return character.blood_potency


def all_formulas():
    """Every formula in v5_data, each a copy with its "level"."""
    formulas = []
    for level, entries in DISCIPLINES[ALCHEMY].get("formulas", {}).items():
        for formula in entries:
            formulas.append(dict(formula, level=level))
    return formulas


def get_formula_by_name(formula_name, max_level=5):
    """The formula (with "level") named ``formula_name`` at or below ``max_level``, or None."""
    wanted = str(formula_name or "").strip().lower()
    for formula in all_formulas():
        if formula["name"].lower() == wanted and formula["level"] <= max_level:
            return formula
    return None


def get_thin_blood_powers(character):
    """The formulas the character knows (Character.known_formulas), each with its level."""
    known = {name.lower() for name in character.known_formulas}
    return [formula for formula in all_formulas() if formula["name"].lower() in known]


def _pool(character, pool_text):
    size, breakdown = calculate_pool_from_traits(character, parse_dice_pool(pool_text))
    return max(1, min(MAX_POOL, size)), breakdown


def craft_formula(character, formula_name, method="athanor", difficulty=DEFAULT_DISTILL_DIFFICULTY):
    """
    Distil one dose of a known formula.

    Refused (nothing rolled or charged) without Thin-Blood Alchemy, for a
    formula the character doesn't know or whose level is above their
    Alchemy rating, for an unknown method, or at Hunger 5 (the Rouse can't
    be made). Otherwise rolls the method pool with the character's Hunger
    dice, then makes the Rouse check.

    Returns:
        dict: {"success", "message", "formula", "roll_result", "rouse_result", "method"}
    """
    def refused(message, formula=None):
        return {"success": False, "message": message, "formula": formula, "roll_result": None,
                "rouse_result": None, "method": None}

    alchemy_level = character.get_trait(ALCHEMY)
    if alchemy_level == 0:
        return refused("You don't know Thin-Blood Alchemy.")
    formula = get_formula_by_name(formula_name)
    if formula is None or formula["name"] not in character.known_formulas:
        return refused(f"You don't know a formula called {formula_name}. Learn one with +spend formula <name>.")
    if formula["level"] > alchemy_level:
        return refused(f"{formula['name']} is a level {formula['level']} formula; your Alchemy is {alchemy_level}.",
                       formula)
    if method not in DISTILLATION_METHODS:
        return refused(f"Unknown method. Choose from: {', '.join(DISTILLATION_METHODS)}.", formula)
    if character.hunger >= MAX_HUNGER:
        return refused(HUNGER_5_REFUSAL, formula)

    method_name, pool_text = DISTILLATION_METHODS[method]
    pool, _breakdown = _pool(character, pool_text)
    result = roll_v5_pool(pool, character.dice_hunger, difficulty)
    rouse = perform_rouse_check(character, reason=f"Distilling {formula['name']}")

    if result.is_success:
        crafted = list(character.db.crafted_formulae or [])
        crafted.append({"name": formula["name"], "level": formula["level"], "method": method_name,
                        "successes": result.total_successes})
        character.db.crafted_formulae = crafted
        message = f"You distil a dose of {formula['name']} ({method_name}, {pool_text})."
    else:
        message = f"Your distillation of {formula['name']} fails ({method_name}, {pool_text})."
    return {"success": result.is_success, "message": message, "formula": formula, "roll_result": result,
            "rouse_result": rouse, "method": method_name}


def use_alchemy(character, formula_name):
    """
    Use a distilled dose: pay the formula's activation Rouse checks and roll
    its dice pool, if it has one (with the character's Hunger dice).

    Refused, keeping the dose, at Hunger 5 if the formula costs a Rouse.

    Returns:
        dict: {"success", "message", "effect", "roll_result", "rouse_result"}
    """
    crafted = list(character.db.crafted_formulae or [])
    index = next((i for i, dose in enumerate(crafted) if dose["name"].lower() == str(formula_name).strip().lower()),
                 None)
    if index is None:
        return {"success": False, "message": f"You have no distilled dose of {formula_name}.", "effect": None,
                "roll_result": None, "rouse_result": None}
    formula = get_formula_by_name(crafted[index]["name"])
    if formula is None:
        return {"success": False, "message": f"{crafted[index]['name']} is no longer a formula.", "effect": None,
                "roll_result": None, "rouse_result": None}
    if formula.get("rouse", 0) and character.hunger >= MAX_HUNGER:
        return {"success": False, "message": HUNGER_5_REFUSAL, "effect": None, "roll_result": None,
                "rouse_result": None}

    crafted.pop(index)
    character.db.crafted_formulae = crafted

    roll_result = None
    if formula.get("dice_pool"):
        pool, _breakdown = _pool(character, formula["dice_pool"])
        roll_result = roll_v5_pool(pool, character.dice_hunger, 0)
    rouse = None
    if formula.get("rouse", 0):
        rouse = perform_rouse_check(character, reason=formula["name"], count=formula["rouse"])

    effect = {"name": formula["name"], "description": formula["description"],
              "duration": formula.get("duration_text", formula.get("duration")),
              "dice_pool": formula.get("dice_pool"), "opposed_by": formula.get("opposed_by")}
    effects = list(character.db.active_effects or [])
    effects.append({"type": "alchemy", "name": formula["name"], "duration": formula.get("duration"),
                    "description": formula["description"]})
    character.db.active_effects = effects
    return {"success": True, "message": f"You use {formula['name']}.", "effect": effect,
            "roll_result": roll_result, "rouse_result": rouse}


def check_daylight_damage(character):
    """Check if Thin-Blood takes damage from sunlight.

    Thin-Bloods take bashing damage from sun, not aggravated.

    Args:
        character: The character object

    Returns:
        dict: {"takes_damage": bool, "damage_type": str, "amount": int}
    """
    if not is_thin_blood(character):
        # Regular vampires take aggravated
        return {
            "takes_damage": True,
            "damage_type": "aggravated",
            "amount": 3
        }

    # Thin-Bloods take bashing
    return {
        "takes_damage": True,
        "damage_type": "bashing",
        "amount": 2
    }


def can_pass_as_mortal(character):
    """Check if Thin-Blood can pass as mortal.

    Thin-Bloods can sometimes pass as human (Blush of Life easier).

    Args:
        character: The character object

    Returns:
        bool: True if can pass as mortal
    """
    if not is_thin_blood(character):
        return False

    # Automatic at low Hunger
    if character.hunger <= 2:
        return True

    # Roll at higher Hunger
    composure = character.get_trait("composure")
    if random.randint(1, 10) <= composure + 3:
        return True

    return False
