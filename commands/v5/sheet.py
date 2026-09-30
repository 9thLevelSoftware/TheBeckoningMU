"""V5 Character Sheet Commands

Enhanced character sheet display using gothic V:tM theming.
"""

from evennia.commands.command import Command
from evennia.utils.utils import inherits_from
from .utils.display_utils import format_character_sheet, format_short_sheet


class CmdSheet(Command):
    """
    Display your comprehensive character sheet.

    Usage:
        +sheet
        sheet

    Shows your complete character sheet with all V5 information including:
    - Vampire vitals (generation, blood potency, hunger, humanity)
    - Clan information (bane, compulsion)
    - Attributes (Physical, Social, Mental)
    - Skills (with specialties)
    - Disciplines (with known powers)
    - Backgrounds, Merits, and Flaws
    - Humanity (convictions, touchstones, stains)
    - Health, Willpower, and Experience

    For a quick one-line status, use '+st' instead.
    """

    key = "+sheet"
    aliases = ["sheet"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Execute sheet command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to view a sheet.|n")
            return

        # Generate and display the full character sheet
        sheet = format_character_sheet(self.caller)
        self.caller.msg(sheet)


class CmdSheetShort(Command):
    """
    Display abbreviated character stats.

    Usage:
        +st
        st
        status

    Shows vital statistics in a compact one-line format.
    Perfect for quick status checks during play.
    """

    key = "+st"
    aliases = ["st", "status"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Execute short status command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to view stats.|n")
            return

        # Generate and display the short status
        status = format_short_sheet(self.caller)
        self.caller.msg(f"\n{status}\n")
