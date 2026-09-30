"""
Jobs command set for TheBeckoningMU.

Adds all jobs-related commands to characters.
"""

from evennia import CmdSet
from . import commands


class JobsCmdSet(CmdSet):
    """
    Command set for the Jobs system.
    Includes both player-facing and admin commands.
    """
    
    key = "JobsCmdSet"
    priority = 0
    
    def at_cmdset_creation(self):
        """
        Add all jobs commands to the set.
        """
        # Player commands
        self.add(commands.CmdJobs())
        self.add(commands.CmdJobView())
        self.add(commands.CmdJobClaim())
        self.add(commands.CmdJobDone())
        self.add(commands.CmdJobComment())
        self.add(commands.CmdJobPublic())
        self.add(commands.CmdMyJobs())
        self.add(commands.CmdJobSubmit())
        
        # Admin commands
        self.add(commands.CmdJobCreate())
        self.add(commands.CmdJobAssign())
        self.add(commands.CmdJobReopen())
        self.add(commands.CmdJobDelete())
        self.add(commands.CmdBuckets())
        self.add(commands.CmdBucketCreate())
        self.add(commands.CmdBucketView())
        self.add(commands.CmdBucketDelete())
