"""
Vampire: The Masquerade 5th Edition Dice Rolling System

This package provides the core dice rolling mechanics for V5, including:
- Basic dice pool rolling with Hunger dice
- Rouse checks with Blood Potency rerolls
- Contested rolls
- Willpower rerolls
- Success counting and critical detection
- Discipline power rolling with trait integration
"""

from .dice_roller import (
    roll_v5_pool,
    roll_rouse_check,
    roll_contested,
    apply_willpower_reroll
)
from .roll_result import RollResult
from .rouse_checker import (
    perform_rouse_check,
    can_reroll_rouse,
    get_hunger_level,
    set_hunger_level,
    format_hunger_display
)
from .discipline_roller import (
    roll_discipline_power,
    parse_dice_pool,
    calculate_pool_from_traits,
    get_blood_potency_bonus,
    can_use_power,
    get_character_discipline_powers
)
from .commands import (
    CmdRoll,
    CmdRollPower,
    CmdRouse,
    CmdShowDice
)
from .cmdset import DiceCmdSet

__all__ = [
    # Core dice rolling
    'roll_v5_pool',
    'roll_rouse_check',
    'roll_contested',
    'apply_willpower_reroll',
    'RollResult',
    # Rouse checks
    'perform_rouse_check',
    'can_reroll_rouse',
    'get_hunger_level',
    'set_hunger_level',
    'format_hunger_display',
    # Discipline powers
    'roll_discipline_power',
    'parse_dice_pool',
    'calculate_pool_from_traits',
    'get_blood_potency_bonus',
    'can_use_power',
    'get_character_discipline_powers',
    # Commands
    'CmdRoll',
    'CmdRollPower',
    'CmdRouse',
    'CmdShowDice',
    'DiceCmdSet',
]
