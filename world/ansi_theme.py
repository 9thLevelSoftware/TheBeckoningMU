"""
V:tM Gothic ANSI Color Theme

This module defines the color palette and theming standards for TheBeckoningMU.
All user-facing output should use these constants for consistent gothic atmosphere.

See: THEMING_GUIDE.md for complete aesthetics specification
"""

# ============================================================================
# PRIMARY COLORS (V:tM Gothic Theme)
# ============================================================================

BLOOD_RED = "|r"           # Hunger, damage, warnings
DARK_RED = "|[R"           # Clan names, disciplines
PALE_IVORY = "|w"          # Text, descriptions
SHADOW_GREY = "|x"         # Borders, separators
DEEP_PURPLE = "|m"         # Mystical (Auspex, Blood Sorcery)
MIDNIGHT_BLUE = "|b"       # Night, status, nobility
BONE_WHITE = "|W"          # Headers, emphasis
DECAY_GREEN = "|g"         # Necromancy, decay (Oblivion)
GOLD = "|y"                # Status, boons, highlights
VAMPIRE_GOLD = "|y"        # Alias for GOLD (used in humanity commands)

# ============================================================================
# SEMANTIC COLORS (Context-Specific)
# ============================================================================

SUCCESS = "|g"             # Successful actions
FAILURE = "|r"             # Failed actions
MESSY = "|[R|h"            # Messy critical (bright red, hilite)
BESTIAL = "|[r|h"          # Bestial failure (dark red, hilite)
CRITICAL = "|y|h"          # Critical success (gold, hilite)

# ============================================================================
# HUNGER LEVEL COLORS (Gradient from white to red)
# ============================================================================

HUNGER_0 = "|W"            # Sated (white)
HUNGER_1_2 = "|w"          # Peckish/Hungry (pale)
HUNGER_3_4 = "|y"          # Ravenous/Famished (gold)
HUNGER_5 = "|[R|h"         # Starving (bright red, hilite)

def get_hunger_color(hunger_level):
    """
    Returns the appropriate color code for a given Hunger level.

    Args:
        hunger_level (int): Hunger level (0-5)

    Returns:
        str: ANSI color code
    """
    if hunger_level == 0:
        return HUNGER_0
    elif hunger_level in (1, 2):
        return HUNGER_1_2
    elif hunger_level in (3, 4):
        return HUNGER_3_4
    else:  # hunger_level == 5
        return HUNGER_5

# ============================================================================
# RESET CODE
# ============================================================================

RESET = "|n"               # Reset all formatting

# ============================================================================
# BOX DRAWING CHARACTERS (ASCII-only for client compatibility)
# ============================================================================

# Single line (ASCII)
BOX_H = "-"                # Horizontal
BOX_V = "|"                # Vertical
BOX_TL = "+"               # Top-left corner
BOX_TR = "+"               # Top-right corner
BOX_BL = "+"               # Bottom-left corner
BOX_BR = "+"               # Bottom-right corner
BOX_T = "+"                # T-junction top
BOX_B = "+"                # T-junction bottom
BOX_L = "+"                # T-junction left
BOX_R = "+"                # T-junction right
BOX_X = "+"                # Cross

# Double line (ASCII - uses = for emphasis)
DBOX_H = "="               # Horizontal
DBOX_V = "|"               # Vertical
DBOX_TL = "+"              # Top-left corner
DBOX_TR = "+"              # Top-right corner
DBOX_BL = "+"              # Bottom-left corner
DBOX_BR = "+"              # Bottom-right corner
DBOX_T = "+"               # T-junction top
DBOX_B = "+"               # T-junction bottom
DBOX_L = "+"               # T-junction left
DBOX_R = "+"               # T-junction right
DBOX_X = "+"               # Cross

# ============================================================================
# THEMATIC SYMBOLS
# ============================================================================

# Vampire/Gothic

CROWN = "♛"                # Royalty, Prince
QUEEN = "♕"                # Alternative crown
ROSE = "❦"                 # Toreador, romance
COFFIN = "⚰"               # Death
CROSS = "†"                # Faith
CROSS_ALT = "✝"            # Alternative cross

# Status/Power

# Warning/Danger
WARNING = "⚠"              # Warnings, caution
NO_ENTRY = "⛔"            # Forbidden
LIGHTNING = "⚡"           # Power, Brujah

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def colorize(text, account=None):
    """
    Apply color codes to text, respecting user's color preference.

    Args:
        text (str): Text with ANSI codes
        account (Account): Evennia account object

    Returns:
        str: Colored text or plain text if colors disabled
    """
    if account and hasattr(account.db, 'use_color') and not account.db.use_color:
        # Strip ANSI codes for users with color disabled
        import re
        return re.sub(r'\|[xrRgGbBmMcCyYwW\[\]]|\|h|\|n', '', text)
    return text

def make_header(title, width=65, style="double"):
    """
    Create a themed header box.

    Args:
        title (str): Header text
        width (int): Total width of header
        style (str): "single" or "double"

    Returns:
        str: Formatted header
    """
    if style == "double":
        tl, tr, bl, br = DBOX_TL, DBOX_TR, DBOX_BL, DBOX_BR
        h, v = DBOX_H, DBOX_V
        color = DARK_RED
    else:
        tl, tr, bl, br = BOX_TL, BOX_TR, BOX_BL, BOX_BR
        h, v = BOX_H, BOX_V
        color = SHADOW_GREY

    line = h * (width - 2)
    title_line = f" {BONE_WHITE}{title}{color}"
    padding = " " * (width - len(title) - 3)

    return f"""{color}{tl}{line}{tr}
{v}{title_line}{padding}{v}
{bl}{line}{br}{RESET}"""

def make_separator(width=65):
    """
    Create a horizontal separator line.

    Args:
        width (int): Total width

    Returns:
        str: Separator line
    """
    return f"{SHADOW_GREY}{BOX_H * width}{RESET}"

def trait_dots(current, maximum=5, filled_symbol='●', empty_symbol='○'):
    """
    Create a visual representation of trait dots.

    Args:
        current (int): Current dots
        maximum (int): Maximum dots
        filled_symbol (str): Symbol for filled dots
        empty_symbol (str): Symbol for empty dots

    Returns:
        str: Dot representation (e.g., "●●●○○")
    """
    filled = filled_symbol * current
    empty = empty_symbol * (maximum - current)
    return f"{filled}{empty}"

# ============================================================================
# DICE SYMBOLS
# ============================================================================

DICE_SUCCESS_NORMAL = f"{BONE_WHITE}{RESET}"
DICE_CRITICAL_NORMAL = f"{GOLD}{RESET}"
DICE_SUCCESS_HUNGER = f"{BLOOD_RED}{RESET}"
DICE_CRITICAL_HUNGER = f"{MESSY}{RESET}"
DICE_FAILURE = f"{SHADOW_GREY}{RESET}"

# V5 Dice Symbols (Simple text-based, for dice rolling output)
DICE_CRITICAL = "|g(X)|n"  # Critical Success (10)
DICE_SUCCESS = "|g(V)|n"  # Normal Success (6-9)
DICE_FAIL = "|x(-)|n"  # Failure (1-5)

# V5 Hunger Dice Symbols (text-based)
DICE_HUNGER_CRITICAL = "|r(X)|n"  # Hunger Critical (10)
DICE_HUNGER_SUCCESS = "|r(V)|n"  # Hunger Success (6-9)
DICE_HUNGER_FAILURE = "|r(-)|n"  # Hunger Failure (1-5)

# V5 Result Banners
MESSY_CRITICAL_BANNER = r"|r\/\/\ MESSY CRITICAL \/\/\|n"
BESTIAL_FAILURE_BANNER = r"|R\/\/\ BESTIAL FAILURE \/\/\|n"
CRITICAL_SUCCESS_BANNER = "|G*** CRITICAL SUCCESS ***|n"
SUCCESS_BANNER = "|g** SUCCESS **|n"
FAILURE_BANNER = "|x** FAILURE **|n"

# ============================================================================
# ADDITIONAL THEMATIC SYMBOLS (Phase 3 Expansion)
# ============================================================================

# Death and occult
ANKH = "☥"              # Eternal life
SKULL = "☠"             # Death
PENTAGRAM = "⛤"         # Occult
CRESCENT_MOON = "☾"     # Night
DAGGER = "†"            # Violence/sacrifice

# Status symbols for different contexts
CHECK_MARK = "✓"        # Success
X_MARK = "✗"            # Failure  
HOURGLASS = "⏳"        # Pending/waiting
PROHIBITED = "⛔"        # Blocked/forbidden
GEAR = "⚙"              # In progress/working
ARROW_RIGHT = "→"       # Navigation/forward
ARROW_LEFT = "←"        # Back
ARROW_UP = "↑"          # Increase
ARROW_DOWN = "↓"        # Decrease

# ============================================================================
# ASCII ART ELEMENTS (Phase 3 Expansion)
# ============================================================================

# Vampire fangs (small decorative element)
VAMPIRE_FANGS = """
        __   __
     .-'  "."  '-.
   .'   ___,___   '.
  ;__.-; | | | ;-.__;
  | \\  | | | | |  / |
   \\ \\/`""`""`"` \\/ /
    \\_.,-,-,-,-,._ /
     \\`-:_|_|_:-'/
"""

# Gothic border elements
GOTHIC_BORDER_LIGHT = "─" * 80
GOTHIC_BORDER_HEAVY = "━" * 80

# Decorative vampire section divider
VAMPIRE_DIVIDER = f"{BLOOD_RED}◤──•~❉᯽❉~•──◥{RESET}"

# Gothic corner decorations
CORNER_ORNAMENT_TL = "◤"
CORNER_ORNAMENT_TR = "◥"
CORNER_ORNAMENT_BL = "◣"
CORNER_ORNAMENT_BR = "◢"

# ============================================================================
# HELPER FUNCTION ENHANCEMENTS (Phase 3 Expansion)
# ============================================================================

def format_vampire_header(title, subtitle=None, width=80):
    """
    Create a themed vampire header with double-line box.

    Args:
        title (str): Main title text
        subtitle (str, optional): Subtitle text
        width (int): Total width of header

    Returns:
        str: Formatted header with ANSI colors
    """
    output = []
    output.append(f"{DARK_RED}{DBOX_TL}{DBOX_H * (width - 2)}{DBOX_TR}")

    # Title line with fleur-de-lis symbols
    title_padding = (width - len(title) - 8) // 2
    output.append(f"{DBOX_V} {BLOOD_RED}{RESET}  "
                 f"{BONE_WHITE}{title}{RESET}"
                 f"{' ' * (width - len(title) - 8)}"
                 f"{BLOOD_RED}{RESET}  "
                 f"{DARK_RED}{DBOX_V}")

    # Subtitle line (if provided)
    if subtitle:
        subtitle_padding = (width - len(subtitle) - 4) // 2
        output.append(f"{DBOX_V} {' ' * subtitle_padding}"
                     f"{SHADOW_GREY}{subtitle}{RESET}"
                     f"{' ' * (width - len(subtitle) - subtitle_padding - 4)}"
                     f"{DARK_RED}{DBOX_V}")

    output.append(f"{DBOX_BL}{DBOX_H * (width - 2)}{DBOX_BR}{RESET}")

    return "\n".join(output)


def format_info_box(title, content, width=80):
    """
    Create a themed info box with title and content.

    Args:
        title (str): Box title
        content (str): Box content (can be multi-line)
        width (int): Box width

    Returns:
        str: Formatted box with ANSI colors
    """
    output = []
    output.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * (width - 2)}{BOX_TR}")
    output.append(f"{BOX_V} {BONE_WHITE}{title}{RESET}"
                 f"{' ' * (width - len(title) - 4)}"
                 f"{SHADOW_GREY}{BOX_V}")
    output.append(f"{BOX_BL}{BOX_H * (width - 2)}{BOX_BR}{RESET}")

    # Content (word wrap if needed)
    for line in content.split('\n'):
        output.append(f"{PALE_IVORY}{line}{RESET}")

    return "\n".join(output)


def format_status_indicator(status, text=""):
    """
    Create a colored status indicator with optional text.

    Args:
        status (str): Status type (success, failure, warning, info, pending, blocked)
        text (str): Optional text to display after indicator

    Returns:
        str: Formatted status indicator with color
    """
    indicators = {
        "success": (SUCCESS, CHECK_MARK),
        "failure": (FAILURE, X_MARK),
        "warning": (GOLD, WARNING),
        "info": ("|b", "ℹ"),
        "pending": (GOLD, HOURGLASS),
        "blocked": (FAILURE, PROHIBITED),
    }

    color, symbol = indicators.get(status.lower(), (PALE_IVORY, "●"))

    if text:
        return f"{color}{symbol}{RESET} {text}"
    return f"{color}{symbol}{RESET}"


def trait_dots_colored(current, maximum=5, filled_color=None, empty_color=None):
    """
    Create a colored dot representation of a trait.

    Args:
        current (int): Current trait value
        maximum (int): Maximum trait value
        filled_color (str): Color for filled dots (default: GOLD)
        empty_color (str): Color for empty dots (default: SHADOW_GREY)

    Returns:
        str: Colored dot string (e.g., "●●●○○")
    """
    if filled_color is None:
        filled_color = GOLD
    if empty_color is None:
        empty_color = SHADOW_GREY

    filled = f"{filled_color}{'●' * current}{RESET}"
    empty = f"{empty_color}{'○' * (maximum - current)}{RESET}"
    return filled + empty


def format_progress_bar(current, maximum, width=40, show_numbers=True):
    """
    Create a visual progress bar.

    Args:
        current (int): Current progress value
        maximum (int): Maximum value
        width (int): Width of progress bar in characters
        show_numbers (bool): Whether to show numerical progress

    Returns:
        str: Formatted progress bar
    """
    if maximum == 0:
        percentage = 0
    else:
        percentage = min(100, int((current / maximum) * 100))

    filled_width = int((percentage / 100) * width)
    empty_width = width - filled_width

    # Color gradient based on completion
    if percentage >= 75:
        bar_color = SUCCESS
    elif percentage >= 50:
        bar_color = GOLD
    elif percentage >= 25:
        bar_color = "|y"
    else:
        bar_color = BLOOD_RED

    bar = f"{bar_color}{'█' * filled_width}{SHADOW_GREY}{'░' * empty_width}{RESET}"

    if show_numbers:
        return f"{bar} {PALE_IVORY}{current}/{maximum}{RESET} ({percentage}%)"
    return bar

