"""
Blood System Command Set for Vampire: The Masquerade 5th Edition

Groups all blood-related commands for easy integration into character command sets.
"""

from evennia import CmdSet
from .blood import CmdFeed, CmdBloodSurge, CmdHunger


class BloodCmdSet(CmdSet):
    """
    Blood system commands for vampire resource management.

    Includes commands for:
    - Feeding on mortals (feed)
    - Blood Surge activation (bloodsurge, surge)
    - Hunger status display (hunger)
    """

    key = "BloodCmdSet"
    priority = 1

    def at_cmdset_creation(self):
        """
        Add all blood-related commands to the set.
        """
        self.add(CmdFeed())
        self.add(CmdBloodSurge())
        self.add(CmdHunger())
