"""
Combat utilities for V5 combat system.

This module provides functions for:
- Attack resolution
- Damage application and healing
- Health tracking and visualization
- Defense calculation with discipline bonuses
- Impairment penalties
"""

from world.v5_dice import roll_pool, DiceResult
from .blood_utils import mend_damage
from .discipline_effects import get_active_effects
from .trait_utils import get_trait_value
from world.ansi_theme import BLOOD_RED, DARK_RED, RESET, GOLD, PALE_IVORY, SHADOW_GREY


def calculate_attack(attacker, defender, attack_pool_desc):
    """
    Calculate attack roll against defender's defense.

    Args:
        attacker: The attacking character
        defender: The defending character
        attack_pool_desc: String describing the attack pool (e.g., "Strength + Brawl")

    Returns:
        dict with keys:
            - success: bool
            - result: DiceResult object
            - defense: int
            - margin: int (successes - defense)
            - message: str
    """
    # Parse attack pool description
    pool_parts = [p.strip() for p in attack_pool_desc.split('+')]

    # Calculate total dice pool
    total_pool = 0
    for part in pool_parts:
        trait_value = get_trait_value(attacker, part)
        if trait_value is None:
            return {
                "success": False,
                "result": None,
                "defense": 0,
                "margin": 0,
                "message": f"Invalid trait: {part}"
            }
        total_pool += trait_value

    # Get attacker's hunger
    hunger = attacker.db.vampire_stats.get("hunger", 0) if hasattr(attacker.db, "vampire_stats") else 0

    # Calculate defender's defense
    defense = calculate_defense(defender)

    # Check for Potence damage bonus (from active effects)
    potence_bonus = 0
    attacker_effects = get_active_effects(attacker)
    for effect in attacker_effects:
        if effect.get("discipline") == "Potence" and "damage_bonus" in effect:
            potence_bonus = effect.get("damage_bonus", 0)
            break

    # Roll the attack
    result = roll_pool(pool=total_pool, hunger=hunger, difficulty=defense)

    # Calculate margin of success
    margin = max(0, result.successes - defense)

    # Build response message
    if result.successes >= defense:
        message = f"{BLOOD_RED}Attack succeeds!{RESET} {result.successes} successes vs {defense} defense.\n"
        message += f"Margin of success: {GOLD}{margin}{RESET}"
        if potence_bonus > 0:
            message += f"\n{DARK_RED}Potence active:{RESET} +{potence_bonus} damage bonus"
        success = True
    else:
        message = f"{SHADOW_GREY}Attack fails.{RESET} {result.successes} successes vs {defense} defense."
        success = False

    return {
        "success": success,
        "result": result,
        "defense": defense,
        "margin": margin,
        "potence_bonus": potence_bonus,
        "message": message
    }


def apply_damage(character, damage_amount, damage_type="superficial"):
    """
    Apply damage to a character.

    Args:
        character: The character receiving damage
        damage_amount: Amount of damage to apply
        damage_type: "superficial", "aggravated", or "lethal"

    Returns:
        dict with keys:
            - success: bool
            - message: str
            - health_status: str
    """
    if damage_amount <= 0:
        return {
            "success": False,
            "message": "Damage amount must be positive.",
            "health_status": ""
        }

    # Check for Fortitude damage reduction
    fortitude_soak = 0
    effects = get_active_effects(character)
    for effect in effects:
        if effect.get("discipline") == "Fortitude" and "damage_reduction" in effect:
            fortitude_soak = effect.get("damage_reduction", 0)
            break

    # Apply Fortitude soak
    actual_damage = max(0, damage_amount - fortitude_soak)

    if actual_damage == 0:
        message = f"{GOLD}Fortitude{RESET} soaks all damage!"
        return {
            "success": True,
            "message": message,
            "health_status": get_health_status(character)
        }

    # Get current damage values
    pools = character.db.pools
    max_health = pools.get("health", 3)
    superficial = pools.get("superficial_damage", 0)
    aggravated = pools.get("aggravated_damage", 0)

    # Apply damage based on type
    if damage_type == "aggravated":
        new_aggravated = min(max_health, aggravated + actual_damage)
        pools["aggravated_damage"] = new_aggravated
        damage_word = f"{BLOOD_RED}Aggravated{RESET}"
    elif damage_type in ["superficial", "lethal"]:
        # Lethal damage becomes superficial for vampires
        new_superficial = superficial + actual_damage

        # Check for overflow - superficial converts to aggravated when full
        total_damage = new_superficial + aggravated
        if total_damage > max_health:
            overflow = total_damage - max_health
            new_aggravated = min(max_health, aggravated + overflow)
            new_superficial = max_health - new_aggravated
            pools["aggravated_damage"] = new_aggravated
            pools["superficial_damage"] = new_superficial
            damage_word = f"{DARK_RED}Superficial{RESET} (overflow to {BLOOD_RED}Aggravated{RESET})"
        else:
            pools["superficial_damage"] = new_superficial
            damage_word = f"{DARK_RED}Superficial{RESET}"
    else:
        return {
            "success": False,
            "message": f"Invalid damage type: {damage_type}",
            "health_status": ""
        }

    # Update current health
    total_damage = pools["superficial_damage"] + pools["aggravated_damage"]
    pools["current_health"] = max(0, max_health - total_damage)

    # Build message
    message = f"You take {GOLD}{actual_damage}{RESET} {damage_word} damage."
    if fortitude_soak > 0:
        message += f" ({GOLD}Fortitude{RESET} soaked {fortitude_soak})"

    # Check for death/torpor
    if pools["current_health"] == 0:
        if aggravated >= max_health:
            message += f"\n{BLOOD_RED}You have been destroyed!{RESET}"
        else:
            message += f"\n{DARK_RED}You fall into Torpor!{RESET}"

    return {
        "success": True,
        "message": message,
        "health_status": get_health_status(character)
    }


def heal_damage(character, heal_amount, damage_type="superficial"):
    """
    Heal damage on a character.

    Args:
        character: The character to heal
        heal_amount: Amount of damage to heal
        damage_type: "superficial" or "aggravated"

    Returns:
        dict with keys:
            - success: bool
            - message: str
            - health_status: str
    """
    if heal_amount <= 0:
        return {
            "success": False,
            "message": "Heal amount must be positive.",
            "health_status": ""
        }

    pools = character.db.pools

    if damage_type == "superficial":
        current_superficial = pools.get("superficial_damage", 0)
        if current_superficial == 0:
            return {
                "success": False,
                "message": "No superficial damage to heal.",
                "health_status": get_health_status(character)
            }

        healed = min(heal_amount, current_superficial)
        pools["superficial_damage"] -= healed
        damage_word = f"{DARK_RED}Superficial{RESET}"

    elif damage_type == "aggravated":
        current_aggravated = pools.get("aggravated_damage", 0)
        if current_aggravated == 0:
            return {
                "success": False,
                "message": "No aggravated damage to heal.",
                "health_status": get_health_status(character)
            }

        healed = min(heal_amount, current_aggravated)
        pools["aggravated_damage"] -= healed
        damage_word = f"{BLOOD_RED}Aggravated{RESET}"
    else:
        return {
            "success": False,
            "message": f"Invalid damage type: {damage_type}",
            "health_status": ""
        }

    # Update current health
    max_health = pools.get("health", 3)
    total_damage = pools["superficial_damage"] + pools["aggravated_damage"]
    pools["current_health"] = max(0, max_health - total_damage)

    message = f"You heal {GOLD}{healed}{RESET} {damage_word} damage."

    return {
        "success": True,
        "message": message,
        "health_status": get_health_status(character)
    }


def get_health_status(character):
    """
    Get a visual representation of character's health.

    Returns a formatted string showing health boxes:
    - X = Aggravated damage
    - / = Superficial damage
    - O = Healthy

    Args:
        character: The character to check

    Returns:
        str: Formatted health display
    """
    pools = character.db.pools
    max_health = pools.get("health", 3)
    superficial = pools.get("superficial_damage", 0)
    aggravated = pools.get("aggravated_damage", 0)
    current = pools.get("current_health", max_health)

    # Build health boxes visualization
    # Aggravated fills from right, superficial from left
    boxes = []

    # Fill aggravated from right
    agg_boxes = min(aggravated, max_health)
    # Fill superficial from left
    sup_boxes = min(superficial, max_health - agg_boxes)
    # Remaining are healthy
    healthy_boxes = max_health - agg_boxes - sup_boxes

    # Build the display
    for i in range(healthy_boxes):
        boxes.append(f"{PALE_IVORY}O{RESET}")
    for i in range(sup_boxes):
        boxes.append(f"{DARK_RED}/{RESET}")
    for i in range(agg_boxes):
        boxes.append(f"{BLOOD_RED}X{RESET}")

    health_display = f"[{' '.join(boxes)}]"

    # Add impairment warning
    impairment = get_impairment_penalty(character)
    if impairment < 0:
        health_display += f" {SHADOW_GREY}(Impaired: {impairment} dice){RESET}"

    return health_display


def calculate_defense(character):
    """
    Calculate a character's defense value.

    Defense = Dexterity + Athletics + Celerity bonus (if active)

    Args:
        character: The character to calculate defense for

    Returns:
        int: Defense value
    """
    # Base defense: Dexterity + Athletics
    dexterity = get_trait_value(character, "Dexterity") or 0
    athletics = get_trait_value(character, "Athletics") or 0

    defense = dexterity + athletics

    # Check for Celerity defense bonus
    celerity_bonus = 0
    effects = get_active_effects(character)
    for effect in effects:
        if effect.get("discipline") == "Celerity" and "defense_bonus" in effect:
            celerity_bonus = effect.get("defense_bonus", 0)
            break

    return defense + celerity_bonus


def get_impairment_penalty(character):
    """
    Calculate impairment penalty from injuries.

    When at or below half health, characters suffer -2 dice penalty.

    Args:
        character: The character to check

    Returns:
        int: Penalty to dice pools (0 or -2)
    """
    pools = character.db.pools
    max_health = pools.get("health", 3)
    current_health = pools.get("current_health", max_health)

    # Impaired at half health or less
    if current_health <= max_health / 2:
        return -2

    return 0


def get_combat_pool(character, pool_desc, include_impairment=True):
    """
    Calculate a dice pool for combat, including impairment.

    Args:
        character: The character
        pool_desc: Description like "Strength + Brawl"
        include_impairment: Whether to apply impairment penalty

    Returns:
        dict with keys:
            - pool: int (final dice pool)
            - base_pool: int (before impairment)
            - impairment: int (penalty applied)
            - breakdown: str (explanation)
    """
    # Parse pool description
    pool_parts = [p.strip() for p in pool_desc.split('+')]

    base_pool = 0
    breakdown_parts = []

    for part in pool_parts:
        value = get_trait_value(character, part)
        if value is None:
            return {
                "pool": 0,
                "base_pool": 0,
                "impairment": 0,
                "breakdown": f"Invalid trait: {part}"
            }
        base_pool += value
        breakdown_parts.append(f"{part} {value}")

    # Apply impairment if requested
    impairment = get_impairment_penalty(character) if include_impairment else 0
    final_pool = max(0, base_pool + impairment)  # impairment is negative

    # Build breakdown
    breakdown = " + ".join(breakdown_parts)
    breakdown += f" = {base_pool}"
    if impairment < 0:
        breakdown += f" {impairment} (impaired) = {final_pool}"

    return {
        "pool": final_pool,
        "base_pool": base_pool,
        "impairment": impairment,
        "breakdown": breakdown
    }
