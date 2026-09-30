"""
Dice Command Set for V5 Mechanics

Provides a command set containing all dice rolling commands for
Vampire: The Masquerade 5th Edition mechanics.

To integrate with your game:
1. Import this command set in your character default cmdsets
2. Add it to the CharacterCmdSet in commands/default_cmdsets.py:

    from dice.cmdset import DiceCmdSet

    class CharacterCmdSet(default_cmds.CharacterCmdSet):
        def at_cmdset_creation(self):
            super().at_cmdset_creation()
            self.add(DiceCmdSet)
"""

from evennia import CmdSet
from .commands import CmdRoll, CmdRollPower, CmdRouse, CmdShowDice


class DiceCmdSet(CmdSet):
    """
    Dice rolling command set for V5 mechanics.

    Contains commands for:
    - roll: Basic dice pool rolling with Hunger
    - power: Discipline power rolling with automatic pool calculation
    - rouse: Rouse checks with Blood Potency rerolls
    - showdice: Dice mechanics reference

    Priority is set to 1 to ensure these commands are available but
    can be overridden by higher-priority command sets if needed.
    """

    key = "DiceCmdSet"
    priority = 1

    def at_cmdset_creation(self):
        """
        Populate the command set with dice commands.
        """
        self.add(CmdRoll())
        self.add(CmdRollPower())
        self.add(CmdRouse())
        self.add(CmdShowDice())
