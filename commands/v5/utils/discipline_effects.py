"""
Discipline Effect Tracking System

Manages active discipline powers with durations, ongoing effects,
and Blood Sorcery rituals for V5.
"""

from datetime import datetime
import uuid
from typing import Optional, Dict, List, Any


def apply_effect(character, power_dict: Dict[str, Any], duration: str,
                 parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Apply a discipline power effect to a character.

    Args:
        character: The character object
        power_dict: Dictionary containing power data (name, discipline, etc)
        duration: Duration type - 'scene', 'turn', 'permanent', or 'instant'
        parameters: Optional dict of effect-specific parameters

    Returns:
        Dict containing the created effect
    """
    # Initialize active_effects if needed
    if not hasattr(character.db, 'active_effects') or character.db.active_effects is None:
        character.db.active_effects = []

    # Don't track instant effects
    if duration == 'instant':
        return None

    # Create effect dict
    effect = {
        'id': str(uuid.uuid4())[:8],  # Short unique ID
        'power': power_dict.get('name', 'Unknown Power'),
        'discipline': power_dict.get('discipline', 'Unknown'),
        'duration': duration,
        'turns_remaining': parameters.get('turns', 0) if duration == 'turn' else None,
        'applied': datetime.now(),
        'parameters': parameters or {}
    }

    # Add effect to character
    character.db.active_effects.append(effect)

    return effect


def remove_effect(character, effect_id: str) -> bool:
    """
    Remove an active effect from a character.

    Args:
        character: The character object
        effect_id: The ID of the effect to remove

    Returns:
        bool: True if effect was removed, False if not found
    """
    if not hasattr(character.db, 'active_effects') or not character.db.active_effects:
        return False

    initial_count = len(character.db.active_effects)
    character.db.active_effects = [
        e for e in character.db.active_effects if e['id'] != effect_id
    ]

    return len(character.db.active_effects) < initial_count


def get_active_effects(character, filter_discipline: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all active effects on a character.

    Args:
        character: The character object
        filter_discipline: Optional discipline name to filter by

    Returns:
        List of effect dicts
    """
    if not hasattr(character.db, 'active_effects') or not character.db.active_effects:
        return []

    effects = character.db.active_effects

    if filter_discipline:
        effects = [e for e in effects if e.get('discipline', '').lower() == filter_discipline.lower()]

    return effects


def tick_effects(character) -> List[Dict[str, Any]]:
    """
    Decrement turn-based effect durations and remove expired effects.

    Args:
        character: The character object

    Returns:
        List of expired effects that were removed
    """
    if not hasattr(character.db, 'active_effects') or not character.db.active_effects:
        return []

    expired = []
    remaining = []

    for effect in character.db.active_effects:
        if effect['duration'] == 'turn' and effect['turns_remaining'] is not None:
            effect['turns_remaining'] -= 1

            if effect['turns_remaining'] <= 0:
                expired.append(effect)
            else:
                remaining.append(effect)
        else:
            remaining.append(effect)

    character.db.active_effects = remaining

    return expired


def get_effect_description(effect: Dict[str, Any]) -> str:
    """
    Get a formatted description of an effect.

    Args:
        effect: The effect dict

    Returns:
        str: Formatted description
    """
    power = effect.get('power', 'Unknown')
    discipline = effect.get('discipline', 'Unknown')
    duration = effect.get('duration', 'unknown')

    desc = f"{power} ({discipline})"

    if duration == 'scene':
        desc += " - Active until end of scene"
    elif duration == 'turn':
        turns = effect.get('turns_remaining', 0)
        desc += f" - {turns} turn{'s' if turns != 1 else ''} remaining"
    elif duration == 'permanent':
        desc += " - Permanent effect"

    return desc


def has_active_effect(character, power_name: str) -> Optional[Dict[str, Any]]:
    """
    Check if character has a specific power effect active.

    Args:
        character: The character object
        power_name: Name of the power to check

    Returns:
        Effect dict if active, None otherwise
    """
    effects = get_active_effects(character)

    for effect in effects:
        if effect.get('power', '').lower() == power_name.lower():
            return effect

    return None


def clear_all_effects(character) -> int:
    """
    Remove all active effects from a character.

    Args:
        character: The character object

    Returns:
        int: Number of effects removed
    """
    if not hasattr(character.db, 'active_effects') or not character.db.active_effects:
        return 0

    count = len(character.db.active_effects)
    character.db.active_effects = []

    return count


# Power-specific effect handlers

def apply_obfuscate_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Obfuscate power effects (invisibility, disguise, etc).

    Args:
        character: The character object
        power_name: Name of the Obfuscate power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    # Map power names to effects
    if 'cloak' in power_name_lower or 'silence' in power_name_lower:
        # Cloak of Shadows - invisibility
        params = parameters or {}
        params['visibility'] = 'invisible'
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Obfuscate'},
                    'scene', params)

    elif 'vanish' in power_name_lower:
        # Vanish from Mind's Eye - enhanced invisibility
        params = parameters or {}
        params['visibility'] = 'vanished'
        params['enhanced'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Obfuscate'},
                    'scene', params)

    elif 'mask' in power_name_lower:
        # Mask of a Thousand Faces - disguise
        params = parameters or {}
        params['disguised'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Obfuscate'},
                    'scene', params)


def apply_dominate_effect(character, power_name: str, target=None, parameters: Optional[Dict] = None):
    """
    Apply Dominate power effects (mental commands, memory alteration).

    Args:
        character: The character object (user of power)
        power_name: Name of the Dominate power
        target: Target of the domination (if applicable)
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'compel' in power_name_lower:
        # Compel - simple command
        params = parameters or {}
        params['type'] = 'command'
        params['target'] = str(target) if target else 'unknown'
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Dominate'},
                    'scene', params)

    elif 'mesmerize' in power_name_lower:
        # Mesmerize - implant false emotion
        params = parameters or {}
        params['type'] = 'emotion'
        params['target'] = str(target) if target else 'unknown'
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Dominate'},
                    'scene', params)


def apply_auspex_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Auspex power effects (heightened senses, telepathy).

    Args:
        character: The character object
        power_name: Name of the Auspex power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'heightened' in power_name_lower or 'senses' in power_name_lower:
        # Heightened Senses - enhanced perception
        params = parameters or {}
        params['perception_bonus'] = 2
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Auspex'},
                    'scene', params)

    elif 'share' in power_name_lower:
        # Share the Senses - see through another's eyes
        params = parameters or {}
        params['shared_senses'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Auspex'},
                    'scene', params)


def apply_celerity_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Celerity power effects (speed boosts, defense bonuses).

    Args:
        character: The character object
        power_name: Name of the Celerity power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'fleetness' in power_name_lower:
        # Fleetness - movement speed
        params = parameters or {}
        params['speed_boost'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Celerity'},
                    'scene', params)

    elif 'draught' in power_name_lower or 'elegance' in power_name_lower:
        # Draught of Elegance - defense bonus
        params = parameters or {}
        params['defense_bonus'] = 2
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Celerity'},
                    'scene', params)


def apply_fortitude_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Fortitude power effects (damage resistance, resilience).

    Args:
        character: The character object
        power_name: Name of the Fortitude power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'resilience' in power_name_lower:
        # Resilience - damage reduction
        params = parameters or {}
        params['damage_reduction'] = 2
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Fortitude'},
                    'scene', params)

    elif 'enduring' in power_name_lower:
        # Enduring Beasts - enhanced toughness
        params = parameters or {}
        params['health_levels'] = 2
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Fortitude'},
                    'scene', params)


def apply_presence_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Presence power effects (awe, majesty, emotional influence).

    Args:
        character: The character object
        power_name: Name of the Presence power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'awe' in power_name_lower:
        # Awe - attract attention
        params = parameters or {}
        params['attraction'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Presence'},
                    'scene', params)

    elif 'majesty' in power_name_lower:
        # Majesty - cannot be attacked
        params = parameters or {}
        params['untouchable'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Presence'},
                    'scene', params)


def apply_protean_effect(character, power_name: str, parameters: Optional[Dict] = None):
    """
    Apply Protean power effects (transformations, animal features).

    Args:
        character: The character object
        power_name: Name of the Protean power
        parameters: Optional effect parameters
    """
    power_name_lower = power_name.lower()

    if 'eyes' in power_name_lower and 'beast' in power_name_lower:
        # Eyes of the Beast - night vision
        params = parameters or {}
        params['night_vision'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Protean'},
                    'scene', params)

    elif 'feral' in power_name_lower or 'weapons' in power_name_lower:
        # Feral Weapons - claws
        params = parameters or {}
        params['claws'] = True
        params['damage_bonus'] = 2
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Protean'},
                    'scene', params)

    elif 'shapechange' in power_name_lower or 'earth' in power_name_lower:
        # Shapechange forms
        params = parameters or {}
        params['transformed'] = True
        apply_effect(character,
                    {'name': power_name, 'discipline': 'Protean'},
                    'scene', params)


# Blood Sorcery Ritual System

def perform_ritual(character, ritual_name: str, ingredients: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Perform a Blood Sorcery ritual.

    Args:
        character: The character object
        ritual_name: Name of the ritual
        ingredients: Optional list of required ingredients

    Returns:
        Dict with success status and message
    """
    # Check if character has Blood Sorcery
    blood_sorcery_level = character.db.disciplines.get('Blood Sorcery', 0)

    if blood_sorcery_level == 0:
        return {
            'success': False,
            'message': "You do not know Blood Sorcery."
        }

    # Placeholder ritual system
    # In full implementation, would check ritual level requirements,
    # ingredients, casting time, etc.

    result = {
        'success': True,
        'message': f"You begin the ritual of {ritual_name}...",
        'ritual': ritual_name,
        'casting_time': 'varies',
        'ingredients_used': ingredients or []
    }

    # Apply ritual effect (basic placeholder)
    ritual_lower = ritual_name.lower()

    if 'ward' in ritual_lower or 'protection' in ritual_lower:
        params = {'type': 'protective', 'ritual': ritual_name}
        apply_effect(character,
                    {'name': ritual_name, 'discipline': 'Blood Sorcery'},
                    'scene', params)
    elif 'scrying' in ritual_lower or 'clairvoyance' in ritual_lower:
        params = {'type': 'divination', 'ritual': ritual_name}
        apply_effect(character,
                    {'name': ritual_name, 'discipline': 'Blood Sorcery'},
                    'scene', params)
    else:
        # Generic ritual effect
        params = {'type': 'ritual', 'ritual': ritual_name}
        apply_effect(character,
                    {'name': ritual_name, 'discipline': 'Blood Sorcery'},
                    'permanent', params)

    return result


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
