"""
Hunting System Utility Functions for V5

Handles hunting mechanics, prey selection, resonance determination, and complications.
"""

import random
from .blood_utils import get_blood_potency_bonus, get_hunger_level, reduce_hunger, set_resonance
from .clan_utils import get_clan


# Hunting difficulties by location type
HUNTING_DIFFICULTIES = {
    "club": 3,          # Nightclubs, bars, scenes
    "street": 4,        # Streets, alleys, homeless areas
    "residential": 5,   # Residential areas
    "hospital": 6,      # Hospitals, medical facilities
    "secured": 7,       # Gated communities, secured buildings
    "rural": 4,         # Rural/wilderness areas
    "default": 4        # Default difficulty
}

# Resonance types and their emotional states
RESONANCE_TYPES = {
    "Choleric": {
        "emotions": ["angry", "violent", "passionate", "envious", "competitive"],
        "prey_types": ["bar fighter", "road rager", "abusive partner", "gang member", "sports fanatic"],
        "disciplines": ["Celerity", "Potence"]
    },
    "Melancholic": {
        "emotions": ["sad", "depressed", "intellectual", "contemplative", "grieving"],
        "prey_types": ["mourner", "depressed artist", "struggling student", "lonely academic", "heartbroken lover"],
        "disciplines": ["Fortitude", "Obfuscate"]
    },
    "Phlegmatic": {
        "emotions": ["calm", "lazy", "apathetic", "controlling", "medicated"],
        "prey_types": ["bureaucrat", "security guard", "exhausted worker", "stoner", "meditation practitioner"],
        "disciplines": ["Auspex", "Dominate"]
    },
    "Sanguine": {
        "emotions": ["happy", "lustful", "enthusiastic", "high", "flirty"],
        "prey_types": ["partygoer", "lover", "drug user", "optimist", "seducer"],
        "disciplines": ["Presence", "Blood Sorcery"]
    }
}

# Hunting complications
HUNTING_COMPLICATIONS = [
    {"type": "witness", "severity": "minor", "desc": "Someone sees you feed"},
    {"type": "struggle", "severity": "minor", "desc": "The vessel struggles more than expected"},
    {"type": "police", "severity": "moderate", "desc": "Police are nearby"},
    {"type": "rival", "severity": "moderate", "desc": "Another vampire is hunting nearby"},
    {"type": "hunter", "severity": "severe", "desc": "A hunter spots you"},
    {"type": "messy", "severity": "moderate", "desc": "You lose control and feed messily"},
    {"type": "disease", "severity": "minor", "desc": "The vessel has tainted blood"},
]


def determine_resonance(prey_description=None, location="street"):
    """
    Determine resonance type based on prey or location.

    Args:
        prey_description (str, optional): Description of the prey
        location (str): Hunting location

    Returns:
        dict: Resonance information
            - type: Resonance type
            - intensity: 1-3 (fleeting, intense, dyscrasia)
            - description: Narrative description
    """
    # Location-based resonance tendencies
    location_resonance_map = {
        "club": {"Choleric": 30, "Sanguine": 50, "Phlegmatic": 10, "Melancholic": 10},
        "street": {"Choleric": 40, "Sanguine": 20, "Phlegmatic": 20, "Melancholic": 20},
        "hospital": {"Melancholic": 50, "Phlegmatic": 30, "Choleric": 10, "Sanguine": 10},
        "residential": {"Phlegmatic": 40, "Melancholic": 30, "Sanguine": 20, "Choleric": 10},
        "rural": {"Phlegmatic": 40, "Melancholic": 40, "Choleric": 10, "Sanguine": 10},
    }

    # Get weighted probabilities for this location
    weights = location_resonance_map.get(location, {"Choleric": 25, "Melancholic": 25, "Phlegmatic": 25, "Sanguine": 25})

    # Choose resonance type based on weights
    res_type = random.choices(
        list(weights.keys()),
        weights=list(weights.values())
    )[0]

    # Determine intensity (fleeting=1, intense=2, dyscrasia=3)
    # Base: 70% fleeting, 25% intense, 5% dyscrasia
    intensity_roll = random.randint(1, 100)
    if intensity_roll <= 70:
        intensity = 1  # Fleeting
    elif intensity_roll <= 95:
        intensity = 2  # Intense
    else:
        intensity = 3  # Dyscrasia

    # Generate prey description
    prey_list = RESONANCE_TYPES[res_type]["prey_types"]
    if not prey_description:
        prey_description = random.choice(prey_list)

    intensity_names = {1: "Fleeting", 2: "Intense", 3: "Dyscrasia"}

    return {
        "type": res_type,
        "intensity": intensity,
        "intensity_name": intensity_names[intensity],
        "prey_description": prey_description,
        "description": f"A {prey_description} with {res_type} resonance ({intensity_names[intensity]})"
    }


def roll_hunting(character, location="street", skill_bonus=0, predator_bonus=0):
    """
    Perform a hunting roll to find prey.

    Args:
        character: Character object
        location (str): Location type
        skill_bonus (int): Bonus from relevant skills
        predator_bonus (int): Bonus from Predator Type

    Returns:
        dict: Hunting results
            - success: Boolean
            - successes: Number of successes
            - difficulty: Hunting difficulty
            - complications: List of complications (if any)
            - message: Narrative message
    """
    from world.v5_dice import V5DiceRoller

    # Get hunting difficulty
    difficulty = HUNTING_DIFFICULTIES.get(location, HUNTING_DIFFICULTIES["default"])

    # Build dice pool (Wits + appropriate skill + bonuses)
    wits = character.db.stats.get('attributes', {}).get('mental', {}).get('wits', 1)
    pool = wits + skill_bonus + predator_bonus

    # Roll dice
    hunger = get_hunger_level(character)
    roller = V5DiceRoller(pool, hunger, difficulty)
    result = roller.roll()

    # Check for complications (messy critical or bestial failure)
    complications = []
    if result["messy_critical"]:
        complications.append(random.choice([c for c in HUNTING_COMPLICATIONS if c["severity"] in ["moderate", "severe"]]))
    elif result["bestial_failure"]:
        complications.append(random.choice([c for c in HUNTING_COMPLICATIONS if c["severity"] == "severe"]))
    elif result["success"] and random.randint(1, 100) <= 20:  # 20% chance of minor complication even on success
        complications.append(random.choice([c for c in HUNTING_COMPLICATIONS if c["severity"] == "minor"]))

    return {
        "success": result["success"],
        "successes": result["total_successes"],
        "difficulty": difficulty,
        "complications": complications,
        "messy_critical": result.get("messy_critical", False),
        "bestial_failure": result.get("bestial_failure", False),
        "dice_result": result
    }


def hunt_prey(character, location="street", skill_name=None, predator_type_bonus=0, kill=False):
    """
    Full hunting sequence: roll to hunt, determine prey, feed.

    Args:
        character: Character object
        location (str): Where to hunt
        skill_name (str, optional): Skill used for hunting (Streetwise, Persuasion, etc.)
        predator_type_bonus (int): Bonus from Predator Type
        kill (bool): Whether vampire intends to kill the vessel

    Returns:
        dict: Complete hunting results
            - hunting_success: Boolean
            - prey: Prey description
            - resonance: Resonance data
            - feeding_result: Feeding results
            - complications: List of complications
            - message: Full narrative
    """
    # Get skill bonus
    skill_bonus = 0
    if skill_name:
        from .trait_utils import get_trait_value
        skill_bonus = get_trait_value(character, skill_name, category='skills')

    # Roll for hunting
    hunt_result = roll_hunting(character, location, skill_bonus, predator_type_bonus)

    if not hunt_result["success"]:
        return {
            "hunting_success": False,
            "prey": None,
            "resonance": None,
            "feeding_result": None,
            "complications": hunt_result["complications"],
            "message": f"You fail to find suitable prey in the {location}. " +
                      (f"Complication: {hunt_result['complications'][0]['desc']}" if hunt_result['complications'] else "")
        }

    # Determine prey and resonance
    resonance_data = determine_resonance(location=location)

    # Reduce hunger based on hunting success
    hunger_reduction = 1 + (hunt_result["successes"] // 2)  # More successes = better feeding
    if kill:
        hunger_reduction += 1  # Killing allows more feeding
    hunger_reduction = min(hunger_reduction, 3)  # Cap at 3

    old_hunger = get_hunger_level(character)
    new_hunger = reduce_hunger(character, hunger_reduction)

    # Set resonance from the prey
    set_resonance(
        character,
        resonance_data["type"],
        resonance_data["intensity"]
    )

    # Build narrative message
    message = f"You hunt in the {location} and find: {resonance_data['description']}.\n"
    message += f"|gSuccessful hunt!|n Hunger reduced from {old_hunger} to {new_hunger}.\n"
    message += f"Resonance: |y{resonance_data['type']}|n (intensity {resonance_data['intensity']})"

    if hunt_result["complications"]:
        message += f"\n|rComplication:|n {hunt_result['complications'][0]['desc']}"

    return {
        "hunting_success": True,
        "prey": resonance_data,
        "resonance": resonance_data,
        "hunger_reduction": hunger_reduction,
        "old_hunger": old_hunger,
        "new_hunger": new_hunger,
        "complications": hunt_result["complications"],
        "message": message,
        "hunt_roll": hunt_result
    }


def get_predator_hunting_bonus(character):
    """
    Get hunting bonuses based on Predator Type.

    Args:
        character: Character object

    Returns:
        dict: Predator Type hunting bonuses
            - bonus_dice: Bonus dice to hunting roll
            - preferred_locations: List of preferred hunting locations
            - special_ability: Special hunting ability (if any)
    """
    vamp = character.db.vampire if hasattr(character.db, 'vampire') else {}
    predator_type = vamp.get('predator_type', None)

    predator_bonuses = {
        "Alleycat": {
            "bonus_dice": 1,
            "preferred_locations": ["street", "club"],
            "special_ability": "Can hunt in dangerous areas with less risk"
        },
        "Sandman": {
            "bonus_dice": 2,
            "preferred_locations": ["residential"],
            "special_ability": "Can feed from sleeping victims without waking them"
        },
        "Scene Queen": {
            "bonus_dice": 1,
            "preferred_locations": ["club"],
            "special_ability": "Can feed openly in scene without Masquerade risk"
        },
        "Siren": {
            "bonus_dice": 2,
            "preferred_locations": ["club", "residential"],
            "special_ability": "Can seduce prey easily"
        },
        "Consensualist": {
            "bonus_dice": 0,
            "preferred_locations": ["residential", "hospital"],
            "special_ability": "Cannot feed from unwilling vessels"
        },
        "Bagger": {
            "bonus_dice": 0,
            "preferred_locations": ["hospital"],
            "special_ability": "Can acquire blood bags instead of hunting"
        },
        "Farmer": {
            "bonus_dice": 1,
            "preferred_locations": ["rural"],
            "special_ability": "Can only feed from animals"
        }
    }

    return predator_bonuses.get(predator_type, {
        "bonus_dice": 0,
        "preferred_locations": ["street"],
        "special_ability": None
    })


def generate_hunting_opportunity(location="street"):
    """
    Generate a specific hunting opportunity for AI Storyteller use.

    Args:
        location (str): Hunting location

    Returns:
        dict: Hunting opportunity
            - prey_description: Description of prey
            - resonance: Resonance data
            - difficulty: Base difficulty
            - hooks: Narrative hooks for roleplay
            - risks: Potential risks
    """
    resonance_data = determine_resonance(location=location)

    # Generate narrative hooks based on resonance
    hooks = {
        "Choleric": [
            "They're in a heated argument with someone",
            "They're clearly spoiling for a fight",
            "They're cursing loudly at their phone"
        ],
        "Melancholic": [
            "They're crying quietly on a bench",
            "They're staring listlessly into the distance",
            "They're visiting a grave alone"
        ],
        "Phlegmatic": [
            "They're half-asleep on public transit",
            "They're methodically working through paperwork",
            "They're meditating in a quiet corner"
        ],
        "Sanguine": [
            "They're laughing and dancing",
            "They're flirting with everyone they meet",
            "They're clearly intoxicated and euphoric"
        ]
    }

    hook = random.choice(hooks[resonance_data["type"]])

    # Generate potential risks
    risk_pool = HUNTING_COMPLICATIONS.copy()
    potential_risks = random.sample(risk_pool, k=min(3, len(risk_pool)))

    return {
        "prey_description": resonance_data["description"],
        "resonance": resonance_data,
        "difficulty": HUNTING_DIFFICULTIES.get(location, 4),
        "hook": hook,
        "risks": potential_risks,
        "location": location
    }
