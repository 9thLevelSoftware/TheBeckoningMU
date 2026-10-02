"""
Builder text must not carry MXP link markup.

Evennia strips MXP from everything players type (`MXP_OUTGOING_ONLY`),
because `|lc<command>|lt<text>|le` renders as a link that makes whoever
clicks it run `<command>` as themselves, and `|lu<url>|lt<text>|le` links
out of the game. The web builder is a second way to put text in front of
players.

Evennia parses links over the whole outgoing message, so a link can be split
across fields that are shown together (a room description ending in
`|lc...|ltthe old`, an exit named `door|le`). Checking each field for a
complete link is therefore not enough: any MXP token (`|lc`, `|lu`, `|lt`,
`|le`, as Evennia's case-sensitive parser reads them, including after an
escaped `||`) is refused in every builder-controlled string (room and exit
names, aliases, descriptions, trigger messages and `set_attribute` text), and
the build removes any that an older snapshot still carries. Colour codes are
fine.
"""

import re

# Evennia's parser (evennia.utils.ansi: `\|lc(.*?)\|lt(.*?)\|le`,
# `\|lu(.*?)\|lt(.*?)\|le`) is case-sensitive; any pipes before the token are
# swallowed with it so `||lc` can't leave a token behind.
MXP_TOKEN_RE = re.compile(r"\|+l[cute]")

MXP_ERROR = "may not contain link markup (|lc, |lu, |lt, |le)"


def contains_mxp(value) -> bool:
    """True if `value` is text containing any MXP link token."""
    return isinstance(value, str) and MXP_TOKEN_RE.search(value) is not None


def remove_mxp(value: str) -> str:
    """`value` with every MXP link token removed (repeated until none is left)."""
    while MXP_TOKEN_RE.search(value):
        value = MXP_TOKEN_RE.sub("", value)
    return value
