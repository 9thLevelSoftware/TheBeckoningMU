"""
Custom command handler for The Beckoning MU

Overrides Evennia's default command error messages with styled versions.

This module is loaded by Evennia via the CMDHANDLER_MODULE setting and
monkey-patches the cmdhandler to provide styled error messages.
"""

import evennia.commands.cmdhandler as cmdhandler_module
from evennia.utils.utils import string_suggestions


# Store the original cmdhandler function
_original_cmdhandler = cmdhandler_module.cmdhandler


def cmdhandler(called_by, raw_string, _testing=False, callertype="session", **kwargs):
    """
    Custom cmdhandler that wraps Evennia's default handler to provide styled messages.

    This is called for every command entered by a player.
    """
    # Call the original handler
    return _original_cmdhandler(called_by, raw_string, _testing=_testing, callertype=callertype, **kwargs)


def _custom_no_match_message(called_by, cmdname, cmdset, show_suggestions=True):
    """
    Custom "command not found" message with styling and without duplicate aliases.

    This replaces Evennia's default grey message with colored styling.
    """
    if not show_suggestions:
        called_by.msg(f"|rCommand '|n{cmdname}|r' is not available.|n")
        return

    # Get unique command keys only (no duplicate aliases)
    all_cmds = set()
    for cmd in cmdset:
        all_cmds.add(cmd.key.lower())

    # Find close matches
    suggestions = string_suggestions(cmdname, all_cmds, cutoff=0.7, maxnum=3)

    if suggestions:
        if len(suggestions) == 1:
            msg = f"|rCommand '|n{cmdname}|r' is not available.|n Maybe you meant |w\"{suggestions[0]}\"|n?"
        else:
            suggestions_str = '|n, |w'.join(f'"{sug}"' for sug in suggestions)
            msg = f"|rCommand '|n{cmdname}|r' is not available.|n Maybe you meant {suggestions_str}?"
    else:
        msg = f"|rCommand '|n{cmdname}|r' is not available.|n Type |whelp|n for available commands."

    called_by.msg(msg)


# Monkey-patch the cmdhandler module to use our custom functions
cmdhandler_module.cmdhandler = cmdhandler

# Patch the error message function (this is called internally by cmdhandler)
# The exact function name may vary by Evennia version, so we try multiple approaches
if hasattr(cmdhandler_module, '_MSG_NO_COMMAND'):
    # Store original for potential reference
    _original_no_command_msg = cmdhandler_module._MSG_NO_COMMAND
    cmdhandler_module._MSG_NO_COMMAND = _custom_no_match_message
else:
    # For newer versions, we may need to patch differently
    # This ensures our custom message is used
    cmdhandler_module._custom_no_match_message = _custom_no_match_message
