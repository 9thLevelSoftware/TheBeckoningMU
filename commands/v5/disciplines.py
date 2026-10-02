"""
V5 Discipline Commands

Commands for viewing discipline powers. Using a power is the `power`
command (alias `+power`) in dice/commands.py.
"""

from evennia import Command
from .utils.discipline_utils import (
    get_character_disciplines,
    get_discipline_powers,
    get_all_discipline_powers_summary,
    get_power_by_name,
    can_use_power
)
from world.ansi_theme import (
    BLOOD_RED, PALE_IVORY, SHADOW_GREY, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)
from world.v5_data import DISCIPLINES


class CmdDisciplines(Command):
    """
    View your known disciplines and powers.

    Usage:
        +disciplines
        +disciplines <discipline name>
        +disc
        +disc <discipline name>

    Shows all your known disciplines and their powers.
    Specify a discipline name to see only that discipline's powers.

    Examples:
        +disciplines
        +disciplines animalism
        +disc celerity
    """

    key = "+disciplines"
    aliases = ["+disc", "+powers"]
    locks = "cmd:all()"
    help_category = "V5 - Disciplines"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # If no argument, show all disciplines
        if not self.args.strip():
            output = self._format_header("Your Disciplines")
            output += get_all_discipline_powers_summary(caller)
            output += self._format_footer()
            caller.msg(output)
            return

        # Show specific discipline
        disc_name = self.args.strip().title()

        # Try to find matching discipline (case-insensitive)
        matched_disc = None
        for key in DISCIPLINES.keys():
            if key.lower() == disc_name.lower():
                matched_disc = key
                break

        if not matched_disc:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Unknown discipline '{disc_name}'.")
            return

        # Check if character has this discipline
        char_level = caller.get_trait(matched_disc)
        if char_level == 0:
            caller.msg(f"{SHADOW_GREY}You do not know {matched_disc}.{RESET}")
            return

        # Display discipline
        output = self._format_header(f"{matched_disc} {'●' * char_level}")

        disc_data = DISCIPLINES[matched_disc]
        output += f"{SHADOW_GREY}{disc_data['description']}{RESET}\n\n"

        powers = get_discipline_powers(caller, matched_disc)

        if powers:
            from .utils.discipline_utils import format_power_display
            for power in powers:
                output += format_power_display(power, power["level"])
                output += "\n"
        else:
            output += f"{SHADOW_GREY}No powers available.{RESET}\n"

        output += self._format_footer()
        caller.msg(output)

    def _format_header(self, title):
        """Format a header box."""
        width = 78
        title_line = f"{BOX_V} {BLOOD_RED}{title}{RESET}"
        padding = width - len(title) - 3
        title_line += " " * padding + BOX_V

        return f"""
{BOX_TL}{BOX_H * (width - 2)}{BOX_TR}
{title_line}
{BOX_BL}{BOX_H * (width - 2)}{BOX_BR}

"""

    def _format_footer(self):
        """Format a footer."""
        width = 78
        return f"\n{SHADOW_GREY}{BOX_H * width}{RESET}\n"


class CmdDisciplineInfo(Command):
    """
    Get information about a specific discipline power.

    Usage:
        +powerinfo <discipline>/<power name>
        +pinfo <discipline>/<power name>

    Shows detailed information about a discipline power.

    Examples:
        +powerinfo animalism/bond famulus
        +pinfo celerity/cat's grace
    """

    key = "+powerinfo"
    aliases = ["+pinfo"]
    locks = "cmd:all()"
    help_category = "V5 - Disciplines"

    def func(self):
        """Execute the command."""
        caller = self.caller

        if not self.args.strip():
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +powerinfo <discipline>/<power name>")
            return

        # Parse discipline and power name
        if "/" not in self.args:
            caller.msg(f"{BLOOD_RED}Error:{RESET} You must specify both discipline and power.")
            caller.msg(f"Format: +powerinfo <discipline>/<power name>")
            return

        parts = self.args.split("/", 1)
        disc_name = parts[0].strip().title()
        power_name = parts[1].strip()

        # Try to find matching discipline
        matched_disc = None
        for key in DISCIPLINES.keys():
            if key.lower() == disc_name.lower():
                matched_disc = key
                break

        if not matched_disc:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Unknown discipline '{disc_name}'.")
            return

        # Get the power
        power, level = get_power_by_name(matched_disc, power_name)

        if not power:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Unknown power '{power_name}' in {matched_disc}.")
            return

        # Format display
        from .utils.discipline_utils import format_power_display

        output = []
        output.append(f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}")
        output.append(f"{BOX_V} {BLOOD_RED}{matched_disc}{RESET} - Level {level}" + " " * (76 - len(matched_disc) - len(str(level)) - 11) + BOX_V)
        output.append(f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n")

        output.append(format_power_display(power, level, include_level=True))

        # Check if character can use it
        can_use, reason = can_use_power(caller, matched_disc, power_name)

        if can_use:
            output.append(f"\n{PALE_IVORY}You can use this power.{RESET}")
        else:
            output.append(f"\n{SHADOW_GREY}You cannot use this power: {reason}{RESET}")

        output.append(f"\n{SHADOW_GREY}{BOX_H * 78}{RESET}\n")

        caller.msg("\n".join(output))
