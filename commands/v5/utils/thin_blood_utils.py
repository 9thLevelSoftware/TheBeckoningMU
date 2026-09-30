"""
Thin-Blood Utility Functions

Helper functions for Thin-Blood mechanics and Alchemy.
"""

from world.v5_data import DISCIPLINES
from world.v5_dice import roll_pool
import random


def is_thin_blood(character):
    """Check if character is a Thin-Blood."""
    if not hasattr(character.db, 'vampire'):
        return False
    return character.db.vampire.get("clan") == "Thin-Blood"


def get_blood_potency(character):
    """Get character's Blood Potency (Thin-Bloods are always 0)."""
    if is_thin_blood(character):
        return 0
    if not hasattr(character.db, 'vampire'):
        return 0
    return character.db.vampire.get("blood_potency", 1)


def has_ingredients(character, formula):
    """Check if character has ingredients for a formula.

    Args:
        character: The character object
        formula: The formula dict from DISCIPLINES data

    Returns:
        tuple: (bool success, str message)
    """
    if "ingredients" not in formula:
        return True, "No ingredients required"

    # Check if character has ingredient tracking
    if not hasattr(character.db, "alchemy_ingredients"):
        character.db.alchemy_ingredients = {}

    ingredients = formula.get("ingredients", [])
    missing = []

    for ingredient in ingredients:
        count = character.db.alchemy_ingredients.get(ingredient, 0)
        if count < 1:
            missing.append(ingredient)

    if missing:
        return False, f"Missing ingredients: {', '.join(missing)}"

    return True, "All ingredients available"


def craft_formula(character, formula_name):
    """Attempt to craft an alchemical formula.

    Args:
        character: The character object
        formula_name: Name of the formula to craft

    Returns:
        dict: {"success": bool, "message": str, "formula": dict}
    """
    # Get Thin-Blood Alchemy level
    if not hasattr(character.db, 'disciplines'):
        character.db.disciplines = {}

    alchemy_level = character.db.disciplines.get("Thin-Blood Alchemy", 0)

    if alchemy_level == 0:
        return {
            "success": False,
            "message": "You don't know Thin-Blood Alchemy",
            "formula": None
        }

    # Find the formula
    formula = get_formula_by_name(formula_name, alchemy_level)
    if not formula:
        return {
            "success": False,
            "message": f"Unknown formula or level too low: {formula_name}",
            "formula": None
        }

    # Check ingredients
    has_ing, ing_msg = has_ingredients(character, formula)
    if not has_ing:
        return {
            "success": False,
            "message": ing_msg,
            "formula": formula
        }

    # Craft roll: Intelligence + Thin-Blood Alchemy vs difficulty
    difficulty = formula.get("craft_difficulty", 3)

    # Get attributes
    if not hasattr(character.db, 'attributes'):
        character.db.attributes = {}

    pool = character.db.attributes.get("intelligence", 1) + alchemy_level

    # Thin-Bloods don't use Hunger dice for Alchemy (Blood Potency 0)
    result = roll_pool(pool=pool, hunger=0, difficulty=difficulty)

    if result.is_success():
        # Consume ingredients
        for ingredient in formula.get("ingredients", []):
            character.db.alchemy_ingredients[ingredient] -= 1

        # Add formula to crafted formulae
        if not hasattr(character.db, "crafted_formulae"):
            character.db.crafted_formulae = []

        character.db.crafted_formulae.append({
            "name": formula_name,
            "level": formula.get("level", 1),
            "uses_remaining": 1
        })

        return {
            "success": True,
            "message": f"Successfully crafted {formula_name}!",
            "formula": formula,
            "roll_result": result
        }
    else:
        # Consume ingredients even on failure
        for ingredient in formula.get("ingredients", []):
            character.db.alchemy_ingredients[ingredient] -= 1

        return {
            "success": False,
            "message": f"Failed to craft {formula_name}. Ingredients consumed.",
            "formula": formula,
            "roll_result": result
        }


def use_alchemy(character, formula_name):
    """Activate a crafted alchemical formula.

    Args:
        character: The character object
        formula_name: Name of the formula to use

    Returns:
        dict: {"success": bool, "message": str, "effect": dict}
    """
    if not hasattr(character.db, "crafted_formulae"):
        character.db.crafted_formulae = []

    # Find the crafted formula
    crafted = None
    for idx, f in enumerate(character.db.crafted_formulae):
        if f["name"].lower() == formula_name.lower():
            crafted = (idx, f)
            break

    if not crafted:
        return {
            "success": False,
            "message": f"You don't have a crafted {formula_name} formula",
            "effect": None
        }

    idx, formula_data = crafted

    # Get formula details
    formula = get_formula_by_name(formula_name, formula_data["level"])

    # Remove from crafted (single use)
    character.db.crafted_formulae.pop(idx)

    # Apply effect (simplified - full implementation would use discipline_effects)
    effect = {
        "name": formula["name"],
        "description": formula["description"],
        "duration": formula["duration"],
        "dice_pool": formula["dice_pool"]
    }

    # Add effect to character
    if not hasattr(character.db, "active_effects"):
        character.db.active_effects = []

    character.db.active_effects.append({
        "type": "alchemy",
        "name": formula["name"],
        "duration": formula["duration"],
        "description": formula["description"]
    })

    return {
        "success": True,
        "message": f"Activated {formula_name}!",
        "effect": effect
    }


def get_thin_blood_powers(character):
    """Get all Thin-Blood Alchemy formulae available to character.

    Args:
        character: The character object

    Returns:
        list: List of formula dicts
    """
    if not hasattr(character.db, 'disciplines'):
        character.db.disciplines = {}

    alchemy_level = character.db.disciplines.get("Thin-Blood Alchemy", 0)

    if alchemy_level == 0:
        return []

    formulae = []
    disc_data = DISCIPLINES.get("Thin-Blood Alchemy", {})
    powers = disc_data.get("powers", {})

    for level in range(1, alchemy_level + 1):
        if level in powers:
            for power in powers[level]:
                power_copy = power.copy()
                power_copy["level"] = level
                formulae.append(power_copy)

    return formulae


def get_formula_by_name(formula_name, max_level):
    """Get a formula by name up to max level.

    Args:
        formula_name: Name of the formula
        max_level: Maximum level to search

    Returns:
        dict: Formula data or None
    """
    disc_data = DISCIPLINES.get("Thin-Blood Alchemy", {})
    powers = disc_data.get("powers", {})

    for level in range(1, max_level + 1):
        if level in powers:
            for power in powers[level]:
                if power["name"].lower() == formula_name.lower():
                    result = power.copy()
                    result["level"] = level
                    return result

    return None


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
    if not hasattr(character.db, 'vampire'):
        return False

    hunger = character.db.vampire.get("hunger", 1)
    if hunger <= 2:
        return True

    # Roll at higher Hunger
    if not hasattr(character.db, 'attributes'):
        return False

    composure = character.db.attributes.get("composure", 1)
    if random.randint(1, 10) <= composure + 3:
        return True

    return False


def add_ingredient(character, ingredient_name, quantity=1):
    """Add alchemy ingredients to character's inventory.

    Args:
        character: The character object
        ingredient_name: Name of the ingredient
        quantity: Amount to add (default 1)
    """
    if not hasattr(character.db, "alchemy_ingredients"):
        character.db.alchemy_ingredients = {}

    current = character.db.alchemy_ingredients.get(ingredient_name, 0)
    character.db.alchemy_ingredients[ingredient_name] = current + quantity
