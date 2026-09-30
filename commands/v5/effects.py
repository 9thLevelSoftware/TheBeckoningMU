"""
V5 Discipline Effects Commands

Commands for viewing and managing active discipline effects.
"""

from evennia import Command
from evennia import default_cmds
from .utils.discipline_effects import (
    get_active_effects,
    remove_effect,
    clear_all_effects,
    get_effect_description,
    tick_effects
)
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, GOLD, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)
from datetime import datetime


class CmdEffects(default_cmds.MuxCommand):
    """
    View and manage active discipline effects.

    Usage:
        +effects
        +effects/clear <effect_id>
        +effects/clear all
        +effects/tick

    Shows all active discipline effects on your character.

    Switches:
        /clear <id> - Remove a specific effect (staff only)
        /clear all  - Remove all effects (staff only)
        /tick       - Decrement turn-based durations (staff only)

    Examples:
        +effects
        +effects/clear a3f2
        +effects/clear all
        +effects/tick
    """

    key = "+effects"
    aliases = ["+fx", "+activeeffects"]
    locks = "cmd:all()"
    help_category = "V5 - Disciplines"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # Handle switches
        if 'clear' in self.switches:
            self._handle_clear()
            return

        if 'tick' in self.switches:
            self._handle_tick()
            return

        # Default: Show effects
        self._show_effects()

    def _show_effects(self):
        """Display all active effects on the character."""
        caller = self.caller

        # Initialize if needed
        if not hasattr(caller.db, 'active_effects') or caller.db.active_effects is None:
            caller.db.active_effects = []

        effects = get_active_effects(caller)

        # Format output
        output = []
        output.append(self._format_header("Active Discipline Effects"))

        if not effects:
            output.append(f"{SHADOW_GREY}You have no active discipline effects.{RESET}\n")
        else:
            output.append(f"{PALE_IVORY}You currently have {len(effects)} active effect{'s' if len(effects) != 1 else ''}:{RESET}\n")

            for effect in effects:
                output.append(self._format_effect(effect))

        output.append(self._format_footer())

        caller.msg("\n".join(output))

    def _format_effect(self, effect):
        """Format a single effect for display."""
        effect_id = effect.get('id', 'unknown')
        power = effect.get('power', 'Unknown Power')
        discipline = effect.get('discipline', 'Unknown')
        duration = effect.get('duration', 'unknown')
        applied = effect.get('applied')

        lines = []

        # Header with ID
        lines.append(f"{GOLD}[{effect_id}]{RESET} {BLOOD_RED}{power}{RESET} {SHADOW_GREY}({discipline}){RESET}")

        # Duration info
        if duration == 'scene':
            duration_text = f"{PALE_IVORY}Duration:{RESET} Active until end of scene"
        elif duration == 'turn':
            turns = effect.get('turns_remaining', 0)
            duration_text = f"{PALE_IVORY}Duration:{RESET} {DARK_RED}{turns}{RESET} turn{'s' if turns != 1 else ''} remaining"
        elif duration == 'permanent':
            duration_text = f"{PALE_IVORY}Duration:{RESET} Permanent effect"
        else:
            duration_text = f"{PALE_IVORY}Duration:{RESET} {duration}"

        lines.append(f"  {duration_text}")

        # Applied time
        if applied:
            time_str = applied.strftime("%H:%M:%S")
            lines.append(f"  {SHADOW_GREY}Applied:{RESET} {time_str}")

        # Parameters (if any)
        params = effect.get('parameters', {})
        if params:
            param_strs = []
            for key, value in params.items():
                if key not in ['turns']:  # Skip internal params
                    param_strs.append(f"{key}: {value}")

            if param_strs:
                lines.append(f"  {SHADOW_GREY}Effects:{RESET} {', '.join(param_strs)}")

        lines.append("")  # Blank line between effects

        return "\n".join(lines)

    def _handle_clear(self):
        """Handle clearing effects (staff only)."""
        caller = self.caller

        # Check permissions
        if not caller.check_permstring("Builder"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} Only staff can clear effects.")
            return

        if not self.args.strip():
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +effects/clear <effect_id|all>")
            return

        target = self.args.strip().lower()

        # Clear all effects
        if target == 'all':
            count = clear_all_effects(caller)
            caller.msg(f"{GOLD}Cleared {count} effect{'s' if count != 1 else ''}.{RESET}")
            return

        # Clear specific effect
        success = remove_effect(caller, target)

        if success:
            caller.msg(f"{GOLD}Effect {target} removed.{RESET}")
        else:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Effect '{target}' not found.")

    def _handle_tick(self):
        """Handle ticking turn-based effects (staff only)."""
        caller = self.caller

        # Check permissions
        if not caller.check_permstring("Builder"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} Only staff can tick effects.")
            return

        expired = tick_effects(caller)

        if expired:
            caller.msg(f"{GOLD}Effect tick complete.{RESET}")
            caller.msg(f"{DARK_RED}{len(expired)} effect{'s' if len(expired) != 1 else ''} expired:{RESET}")

            for effect in expired:
                caller.msg(f"  - {effect.get('power')} ({effect.get('discipline')})")
        else:
            caller.msg(f"{GOLD}Effect tick complete.{RESET} No effects expired.")

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
