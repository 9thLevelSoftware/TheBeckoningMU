r"""
Evennia settings file.

The available options are found in the default settings file found
here:

https://www.evennia.com/docs/latest/Setup/Settings-Default.html

Remember:

Don't copy more from the default file than you actually intend to
change; this will make sure that you don't overload upstream updates
unnecessarily.

When changing a setting requiring a file system path (like
path/to/actual/file.py), use GAME_DIR and EVENNIA_DIR to reference
your game folder and the Evennia library folders respectively. Python
paths (path.to.module) should be given relative to the game's root
folder (typeclasses.foo) whereas paths within the Evennia library
needs to be given explicitly (evennia.foo).

If you want to share your game dir, including its settings, you can
put secret game- or server-specific settings in secret_settings.py.

"""

# Use the defaults from Evennia unless explicitly overridden
from evennia.contrib.base_systems import color_markups
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "Beckoning"

# Add custom Django apps (BBS, Jobs, Status, Boons, Traits, Web Builder)
INSTALLED_APPS += (
    "bbs",
    "jobs",
    "status",
    "boons",
    "traits",
    "web.builder.apps.BuilderConfig",
)

######################################################################
# MUX Color Markup Support
######################################################################

COLOR_ANSI_EXTRA_MAP = color_markups.MUX_COLOR_ANSI_EXTRA_MAP
COLOR_XTERM256_EXTRA_FG = color_markups.MUX_COLOR_XTERM256_EXTRA_FG
COLOR_XTERM256_EXTRA_BG = color_markups.MUX_COLOR_XTERM256_EXTRA_BG
COLOR_XTERM256_EXTRA_GFG = color_markups.MUX_COLOR_XTERM256_EXTRA_GFG
COLOR_XTERM256_EXTRA_GBG = color_markups.MUX_COLOR_XTERM256_EXTRA_GBG
COLOR_ANSI_XTERM256_BRIGHT_BG_EXTRA_MAP = color_markups.MUX_COLOR_ANSI_XTERM256_BRIGHT_BG_EXTRA_MAP

######################################################################
# Port Configuration
######################################################################

TELNET_PORTS = [6660]
WEBSERVER_PORTS = [(6665, 5001)]  # (external_port, internal_port)
WEBSOCKET_CLIENT_PORT = 6662
WEBSERVER_PROXY_PORT = 6661
AMP_PORT = 6670

######################################################################
# Client Settings
######################################################################

CLIENT_DEFAULT_WIDTH = 80

######################################################################
# Channel Configuration
######################################################################

# Channel that receives connection/disconnection messages for non-staff
CHANNEL_CONNECTINFO = {
    "key": "ConnInfo",
    "aliases": "",
    "desc": "Player Connect/Disconnect Log",
    "locks": "control:perm(Developer);listen:true();send:false()",
}

######################################################################
# Account Options (customizable per-account UI settings)
######################################################################

OPTIONS_ACCOUNT_DEFAULT = {
    "border_color": ("Headers, footers, table borders, etc.", "Color", "R"),
    "header_star_color": ("* inside Header lines.", "Color", "n"),
    "header_text_color": ("Text inside Header lines.", "Color", "w"),
    "header_fill": ("Fill for Header lines.", "Text", "="),
    "separator_star_color": ("* inside Separator lines.", "Color", "n"),
    "separator_text_color": ("Text inside Separator lines.", "Color", "w"),
    "separator_fill": ("Fill for Separator Lines.", "Text", "-"),
    "footer_star_color": ("* inside Footer lines.", "Color", "n"),
    "footer_text_color": ("Text inside Footer Lines.", "Color", "n"),
    "footer_fill": ("Fill for Footer Lines.", "Text", "="),
    "column_names_color": ("Table column header text.", "Color", "w"),
    "timezone": ("Timezone for dates.", "Timezone", "UTC"),
}

######################################################################
# Command System
######################################################################

COMMAND_DEFAULT_CLASS = "commands.command.Command"

######################################################################
# Session and Character Configuration
######################################################################

# Multiple sessions per account, multiple sessions per puppet (share output)
MULTISESSION_MODE = 3

# Max characters an account can create
MAX_NR_CHARACTERS = 10

# Max characters an account can puppet simultaneously
MAX_NR_SIMULTANEOUS_PUPPETS = 3

# Disable auto character creation - we use custom char creation
AUTO_CREATE_CHARACTER_WITH_ACCOUNT = False

######################################################################
# Help System Configuration
######################################################################

# Load help entries from text files in world/help/
FILE_HELP_ENTRY_MODULES = ["world.help_entries"]

# File-based news entries
FILE_NEWS_ENTRY_MODULES = ["world.news_entries"]

######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
