"""
Builder text must not carry MXP link markup.

Evennia strips MXP from everything players type (`MXP_OUTGOING_ONLY`),
because `|lc<command>|lt<text>|le` renders as a link that makes whoever
clicks it run `<command>` as themselves, and `|lu<url>|lt<text>|le` links
out of the game. The web builder is a second way to put text in front of
players, so every builder-controlled string (room and exit names, aliases,
descriptions, trigger messages and `set_attribute` text) is refused if it
contains MXP markup, and the build strips it again defensively. Colour codes
are fine.
"""

from evennia.utils.ansi import strip_mxp


def contains_mxp(value) -> bool:
    """True if `value` is text that carries MXP link markup."""
    return isinstance(value, str) and strip_mxp(value) != value


MXP_ERROR = "may not contain link markup (|lc, |lu, |lt, |le)"
