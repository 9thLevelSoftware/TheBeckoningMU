"""
Predator Type utilities for V5 feeding mechanics.
"""

PREDATOR_BONUSES = {
    'alleycat': {'pool': 'strength+brawl', 'bonus_dice': 1},
    'bagger': {'pool': 'intelligence+streetwise', 'bonus_dice': 0},
    'blood_leech': {'pool': 'strength+brawl', 'bonus_dice': 0, 'vs_vampire': True},
    'cleaver': {'pool': 'manipulation+subterfuge', 'bonus_dice': 1},
    'consensualist': {'pool': 'charisma+persuasion', 'bonus_dice': 1},
    'farmer': {'pool': 'composure+animal_ken', 'bonus_dice': 1},
    'osiris': {'pool': 'charisma+performance', 'bonus_dice': 2},
    'sandman': {'pool': 'dexterity+stealth', 'bonus_dice': 1},
    'scene_queen': {'pool': 'manipulation+persuasion', 'bonus_dice': 0, 'fame_bonus': True},
    'siren': {'pool': 'charisma+subterfuge', 'bonus_dice': 2},
}

def get_feeding_pool(character):
    """Get dice pool for feeding based on predator type."""
    stats = character.db.stats or {}
    predator_type = stats.get('predator_type', '').lower()

    if predator_type not in PREDATOR_BONUSES:
        # Default pool if no/unknown predator type
        return 'strength+brawl', 0

    bonus_info = PREDATOR_BONUSES[predator_type]
    return bonus_info['pool'], bonus_info.get('bonus_dice', 0)
