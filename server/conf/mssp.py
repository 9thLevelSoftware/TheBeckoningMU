"""

MSSP (Mud Server Status Protocol) meta information

Modify this file to specify what MUD listing sites will report about your game.
All fields are static. The number of currently active players and your game's
current uptime will be added automatically by Evennia.

You don't have to fill in everything (and most fields are not shown/used by all
crawlers anyway); leave the default if so needed. You need to reload the server
before the updated information is made available to crawlers (reloading does
not affect uptime).

After changing the values in this file, you must register your game with the
MUD website list you want to track you. The listing crawler will then regularly
connect to your server to get the latest info. No further configuration is
needed on the Evennia side.

"""

MSSPTable = {
    # Required fields
    "NAME": "Beckoning",
    # Generic
    "CRAWL DELAY": "-1",
    "HOSTNAME": "play.thebeckoning.net",
    "PORT": ["6660"],
    "CODEBASE": "Evennia",
    "CONTACT": "",  # email for contacting the mud
    "CREATED": "2024",
    "ICON": "",
    "IP": "",
    "LANGUAGE": "English",
    "LOCATION": "",
    "MINIMUM AGE": "18",
    "WEBSITE": "https://thebeckoning.net",
    # Categorisation
    "FAMILY": "Custom",
    "GENRE": "Horror",
    "GAMEPLAY": "Roleplaying",
    "STATUS": "Open Beta",
    "GAMESYSTEM": "World of Darkness",
    "SUBGENRE": "Vampire: The Masquerade 5th Edition",
    # World
    "AREAS": "0",
    "HELPFILES": "0",
    "MOBILES": "0",
    "OBJECTS": "0",
    "ROOMS": "0",
    "CLASSES": "0",
    "LEVELS": "0",
    "RACES": "0",
    "SKILLS": "0",
    # Protocols (set to 1 or 0; should usually not be changed)
    "ANSI": "1",
    "GMCP": "1",
    "MSDP": "1",
    "MXP": "1",
    "SSL": "1",
    "UTF-8": "1",
    "MCCP": "1",
    "XTERM 256 COLORS": "1",
    "XTERM TRUE COLORS": "0",
    "ATCP": "0",
    "MCP": "0",
    "MSP": "0",
    "VT100": "0",
    "PUEBLO": "0",
    "ZMP": "0",
    # Commercial (set to 1 or 0)
    "PAY TO PLAY": "0",
    "PAY FOR PERKS": "0",
    # Hiring (set to 1 or 0)
    "HIRING BUILDERS": "0",
    "HIRING CODERS": "0",
    # Extended variables
    "DBSIZE": "0",
    "EXITS": "0",
    "EXTRA DESCRIPTIONS": "0",
    "MUDPROGS": "0",
    "MUDTRIGS": "0",
    "RESETS": "0",
    # Game (set to 1 or 0, or one of the given alternatives)
    "ADULT MATERIAL": "1",
    "MULTICLASSING": "0",
    "NEWBIE FRIENDLY": "1",
    "PLAYER CITIES": "0",
    "PLAYER CLANS": "1",
    "PLAYER CRAFTING": "0",
    "PLAYER GUILDS": "0",
    "EQUIPMENT SYSTEM": "None",
    "MULTIPLAYING": "Restricted",
    "PLAYERKILLING": "Restricted",
    "QUEST SYSTEM": "Immortal Run",
    "ROLEPLAYING": "Enforced",
    "TRAINING SYSTEM": "None",
    "WORLD ORIGINALITY": "All Original",
}
