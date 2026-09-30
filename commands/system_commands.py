"""
System Commands for The Beckoning MU

These commands handle special system events like command-not-found errors.
"""

from evennia import Command, syscmdkeys
from evennia.utils.utils import string_suggestions


class SystemNoMatch(Command):
    """
    Custom command-not-found handler with styled messages.

    This is called when no matching command is found. It provides
    styled error messages and removes duplicate alias suggestions.
    """

    key = syscmdkeys.CMD_NOMATCH
    locks = "cmd:all()"

    def func(self):
        """
        Handle command-not-found with styled error messages.
        """
        # Get the invalid command that was typed
        cmd = self.raw_string.strip()

        # Get unique command keys only (not aliases)
        cmdset = self.caller.cmdset.current
        all_cmds = set()
        for command in cmdset:
            # Only add the primary key, not aliases
            all_cmds.add(command.key.lower())

        # Find suggestions
        suggestions = string_suggestions(cmd, all_cmds, cutoff=0.7, maxnum=3)

        # Build styled error message
        if suggestions:
            if len(suggestions) == 1:
                msg = f"|rCommand '|n{cmd}|r' is not available.|n Maybe you meant |w{suggestions[0]}|n?"
            else:
                # Format multiple suggestions with proper coloring
                colored_suggestions = [f"|w{sug}|n" for sug in suggestions]
                if len(colored_suggestions) == 2:
                    suggestions_str = f"{colored_suggestions[0]} or {colored_suggestions[1]}"
                else:
                    suggestions_str = ", ".join(colored_suggestions[:-1]) + f" or {colored_suggestions[-1]}"
                msg = f"|rCommand '|n{cmd}|r' is not available.|n Maybe you meant {suggestions_str}?"
        else:
            msg = f"|rCommand '|n{cmd}|r' is not available.|n Type |whelp|n for available commands."

        self.caller.msg(msg)
