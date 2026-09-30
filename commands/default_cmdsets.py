"""
Command sets

All commands in the game must be grouped in a cmdset.  A given command
can be part of any number of cmdsets and cmdsets can be added/removed
and merged onto entities at runtime.

To create new commands to populate the cmdset, see
`commands/command.py`.

This module wraps the default command sets of Evennia; overloads them
to add/remove commands from the default lineup. You can create your
own cmdsets by inheriting from them or directly from `evennia.CmdSet`.

"""

from evennia import default_cmds


class CharacterCmdSet(default_cmds.CharacterCmdSet):
    """
    The `CharacterCmdSet` contains general in-game commands like `look`,
    `get`, etc available on in-game Character objects. It is merged with
    the `AccountCmdSet` when an Account puppets a Character.
    """

    key = "DefaultCharacter"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #

        # Add custom system commands (styled error messages)
        from commands.system_commands import SystemNoMatch

        self.add(SystemNoMatch)

        # Add V5 Character Sheet commands
        from commands.v5.sheet import CmdSheet, CmdSheetShort

        self.add(CmdSheet)
        self.add(CmdSheetShort)

        # Add V5 Character Generation commands
        from commands.v5.chargen import CmdChargen

        self.add(CmdChargen)

        # Add V5 hunting commands
        from commands.v5.hunt import CmdHunt, CmdHuntingInfo

        self.add(CmdHunt)
        self.add(CmdHuntingInfo)

        # Add V5 XP commands
        from commands.v5.xp import CmdXP, CmdSpend, CmdXPAward

        self.add(CmdXP)
        self.add(CmdSpend)
        self.add(CmdXPAward)

        # Add V5 Discipline commands
        from commands.v5.disciplines import (
            CmdDisciplines,
            CmdActivatePower,
            CmdDisciplineInfo,
        )

        self.add(CmdDisciplines)
        self.add(CmdActivatePower)
        self.add(CmdDisciplineInfo)

        # Add V5 Effects command
        from commands.v5.effects import CmdEffects

        self.add(CmdEffects)

        # Add V5 Humanity commands
        from commands.v5.humanity import (
            CmdHumanity,
            CmdStain,
            CmdRemorse,
            CmdFrenzy,
        )

        self.add(CmdHumanity)
        self.add(CmdStain)
        self.add(CmdRemorse)
        self.add(CmdFrenzy)

        # Add V5 Combat commands
        from commands.v5.combat import CmdAttack, CmdDamage, CmdHeal, CmdHealth

        self.add(CmdAttack)
        self.add(CmdDamage)
        self.add(CmdHeal)
        self.add(CmdHealth)

        # Add V5 Thin-Blood commands
        from commands.v5.thinblood import CmdAlchemy, CmdDaylight

        self.add(CmdAlchemy)
        self.add(CmdDaylight)

        # Add V5 Background commands
        from commands.v5.backgrounds import CmdBackground

        self.add(CmdBackground)

        # Add V5 dice system
        from dice.cmdset import DiceCmdSet

        self.add(DiceCmdSet)

        # Add Status system commands
        from status.commands import (
            CmdStatus,
            CmdPositions,
            CmdStatusRequest,
            CmdStatusAdmin,
        )

        self.add(CmdStatus)
        self.add(CmdPositions)
        self.add(CmdStatusRequest)
        self.add(CmdStatusAdmin)

        # Add Boons system commands
        from boons.commands import (
            CmdBoon,
            CmdBoonGive,
            CmdBoonAccept,
            CmdBoonDecline,
            CmdBoonCall,
            CmdBoonFulfill,
            CmdBoonAdmin,
        )

        self.add(CmdBoon)
        self.add(CmdBoonGive)
        self.add(CmdBoonAccept)
        self.add(CmdBoonDecline)
        self.add(CmdBoonCall)
        self.add(CmdBoonFulfill)
        self.add(CmdBoonAdmin)

        # Add V5 Social commands (Coteries)
        from commands.v5.social import CmdCoterie, CmdSocial

        self.add(CmdCoterie)
        self.add(CmdSocial)

        # Add BBS commands
        from bbs.commands import BBSCmdSet

        self.add(BBSCmdSet)

        # Add Jobs commands
        from jobs.cmdset import JobsCmdSet

        self.add(JobsCmdSet)

        # Add V5 blood system (feeding, Blood Surge, Hunger tracking)
        from commands.v5.blood_cmdset import BloodCmdSet

        self.add(BloodCmdSet)

        # Add News command
        from commands.news import CmdNews

        self.add(CmdNews)

        # Add Builder commands
        from commands.builder import CmdPromote, CmdAbandon

        self.add(CmdPromote)
        self.add(CmdAbandon)

        # Add Sandbox commands
        from commands.builder.sandbox import (
            CmdGotoSandbox,
            CmdListSandboxes,
            CmdCleanupSandbox,
        )

        self.add(CmdGotoSandbox)
        self.add(CmdListSandboxes)
        self.add(CmdCleanupSandbox)


class AccountCmdSet(default_cmds.AccountCmdSet):
    """
    This is the cmdset available to the Account at all times. It is
    combined with the `CharacterCmdSet` when the Account puppets a
    Character. It holds game-account-specific commands, channel
    commands, etc.
    """

    key = "DefaultAccount"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #


class UnloggedinCmdSet(default_cmds.UnloggedinCmdSet):
    """
    Command set available to the Session before being logged in.  This
    holds commands like creating a new account, logging in, etc.
    """

    key = "DefaultUnloggedin"

    def at_cmdset_creation(self):
        """
        Populates the cmdset
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #


class SessionCmdSet(default_cmds.SessionCmdSet):
    """
    This cmdset is made available on Session level once logged in. It
    is empty by default.
    """

    key = "DefaultSession"

    def at_cmdset_creation(self):
        """
        This is the only method defined in a cmdset, called during
        its creation. It should populate the set with command instances.

        As and example we just add the empty base `Command` object.
        It prints some info.
        """
        super().at_cmdset_creation()
        #
        # any commands you add below will overload the default ones.
        #
