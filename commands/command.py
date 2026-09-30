"""
Base Command class for The Beckoning MU

Provides styled command output and error messages.
"""

from evennia.commands.default.muxcommand import MuxCommand


class Command(MuxCommand):
    """
    Inherit from this base to get styled command messages throughout the game.

    This provides:
    - MuxCommand parsing (switches, lhs/rhs, etc.)
    - Styled error messages (red)
    - Styled usage messages (yellow/white)
    - Consistent formatting across all commands
    """

    def msg(self, text=None, **kwargs):
        """
        Override msg to ensure it goes through to the caller properly.
        """
        if self.caller:
            self.caller.msg(text=text, **kwargs)

    def styled_error(self, message):
        """
        Send a styled error message to the caller.

        Args:
            message (str): The error message to display

        Example:
            self.styled_error("You don't have permission for that.")
        """
        self.caller.msg(f"|r{message}|n")

    def styled_usage(self):
        """
        Display styled usage/syntax information.

        Uses the command's __doc__ string if available, otherwise uses
        self.syntax if defined.
        """
        if self.__doc__:
            usage_text = self.__doc__.strip()
        elif hasattr(self, 'syntax'):
            usage_text = self.syntax
        else:
            usage_text = f"Usage: {self.key}"

        self.caller.msg(f"|yUsage:|n {usage_text}")

    def syntax_error(self, custom_message=None):
        """
        Display a syntax error with usage information.

        Args:
            custom_message (str, optional): Additional error context

        Example:
            self.syntax_error("Missing required argument: <board name>")
        """
        if custom_message:
            self.caller.msg(f"|rError:|n {custom_message}")
        self.styled_usage()
