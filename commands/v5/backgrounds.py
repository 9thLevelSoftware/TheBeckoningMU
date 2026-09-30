"""
Background Commands

Commands for using Background advantages.
"""

from evennia import Command
from evennia import default_cmds
from .utils.background_utils import (
    get_all_backgrounds,
    get_background_benefits,
    use_background,
    use_herd_to_feed,
    use_resources_to_acquire,
    reset_background_uses
)
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, GOLD, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)
from world.v5_data import BACKGROUNDS


class CmdBackground(default_cmds.MuxCommand):
    """
    View and use Background advantages.

    Usage:
        +background
        +background <name>
        +background/use <name>=<task description>
        +background/herd
        +background/resources <item>=<rating>
        +background/reset (staff only)

    Backgrounds provide mechanical benefits like bonus dice,
    resources, or special actions.

    Examples:
        +background                              - List your backgrounds
        +background contacts                     - View Contacts details
        +background/use contacts=investigate gang  - Use Contacts
        +background/herd                         - Feed from Herd
        +background/resources pistol=2           - Acquire item
    """

    key = "+background"
    aliases = ["bg", "backgrounds"]
    locks = "cmd:all()"
    help_category = "V5 - Backgrounds"

    def func(self):
        """Execute command."""
        caller = self.caller

        # Handle switches
        if "use" in self.switches:
            self.use_background()
        elif "herd" in self.switches:
            self.use_herd()
        elif "resources" in self.switches:
            self.use_resources()
        elif "reset" in self.switches:
            self.reset_backgrounds()
        else:
            if self.args:
                self.show_background_detail()
            else:
                self.show_all_backgrounds()

    def show_all_backgrounds(self):
        """Show all backgrounds."""
        caller = self.caller

        backgrounds = get_all_backgrounds(caller)

        if not backgrounds:
            caller.msg(f"{SHADOW_GREY}You don't have any backgrounds yet.{RESET}")
            return

        output = [
            f"{BOX_TL}{BOX_H * 68}{BOX_TR}",
            f"{BOX_V}{GOLD}{'YOUR BACKGROUNDS':^68}{RESET}{BOX_V}",
            f"{BOX_BL}{BOX_H * 68}{BOX_BR}",
            ""
        ]

        for bg_name, level in sorted(backgrounds.items()):
            if level > 0:
                bg_name_title = bg_name.title()
                benefits = get_background_benefits(caller, bg_name_title)

                dots = "|y" + "●" * level + "|x" + "○" * (5 - level) + "|n"
                output.append(f"{PALE_IVORY}{bg_name_title}{RESET} {dots}")
                output.append(f"  {benefits['benefit']}")

                if benefits['uses_remaining'] >= 0:
                    output.append(f"  {SHADOW_GREY}Uses remaining: {benefits['uses_remaining']}{RESET}")
                output.append("")

        output.append(f"{SHADOW_GREY}Use '+background <name>' for details{RESET}")
        output.append(f"{SHADOW_GREY}Use '+background/use <name>=<task>' to use a background{RESET}")

        caller.msg("\n".join(output))

    def show_background_detail(self):
        """Show details of a specific background."""
        caller = self.caller
        bg_name = self.args.strip().title()

        if bg_name not in BACKGROUNDS:
            caller.msg(f"{BLOOD_RED}Unknown background: {bg_name}{RESET}")
            return

        benefits = get_background_benefits(caller, bg_name)
        bg_data = BACKGROUNDS[bg_name]

        output = [
            f"{BOX_TL}{BOX_H * 68}{BOX_TR}",
            f"{BOX_V}{GOLD}{bg_name:^68}{RESET}{BOX_V}",
            f"{BOX_BL}{BOX_H * 68}{BOX_BR}",
            "",
            f"{PALE_IVORY}Level:{RESET} {benefits['level']}",
            "",
            f"{PALE_IVORY}Description:{RESET}",
            f"  {bg_data['description']}",
            "",
            f"{PALE_IVORY}Mechanical Benefit:{RESET}",
            f"  {benefits['benefit']}",
            ""
        ]

        if benefits['uses_remaining'] >= 0:
            output.append(f"{PALE_IVORY}Uses Remaining:{RESET} {benefits['uses_remaining']}")
        elif benefits['uses_remaining'] == -1:
            output.append(f"{PALE_IVORY}Uses:{RESET} Unlimited")

        caller.msg("\n".join(output))

    def use_background(self):
        """Use a background for a task."""
        caller = self.caller

        if not self.args or "=" not in self.args:
            caller.msg("Usage: +background/use <name>=<task description>")
            return

        bg_name, task = self.args.split("=", 1)
        bg_name = bg_name.strip().title()
        task = task.strip()

        result = use_background(caller, bg_name, task)

        if result["success"]:
            caller.msg(f"{GOLD}{result['message']}{RESET}")
            caller.msg(f"{PALE_IVORY}Bonus: +{result['bonus']} dice{RESET}")

            if result['uses_remaining'] >= 0:
                caller.msg(f"{SHADOW_GREY}Uses remaining: {result['uses_remaining']}{RESET}")
        else:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")

    def use_herd(self):
        """Feed from Herd background."""
        caller = self.caller

        result = use_herd_to_feed(caller)

        if result["success"]:
            caller.msg(f"{GOLD}{result['message']}{RESET}")
            caller.msg(f"{PALE_IVORY}New Hunger: {caller.db.vampire.get('hunger', 1)}{RESET}")
        else:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")

    def use_resources(self):
        """Acquire item with Resources."""
        caller = self.caller

        if not self.args or "=" not in self.args:
            caller.msg("Usage: +background/resources <item description>=<rating>")
            return

        item_desc, rating_str = self.args.split("=", 1)
        item_desc = item_desc.strip()

        try:
            rating = int(rating_str.strip())
        except ValueError:
            caller.msg(f"{BLOOD_RED}Invalid rating. Must be 1-5.{RESET}")
            return

        result = use_resources_to_acquire(caller, item_desc, rating)

        if result["success"]:
            caller.msg(f"{GOLD}{result['message']}{RESET}")
        else:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")

    def reset_backgrounds(self):
        """Reset background uses (staff only)."""
        caller = self.caller

        if not caller.check_permstring("Builder"):
            caller.msg(f"{BLOOD_RED}Staff only.{RESET}")
            return

        reset_background_uses(caller)
        caller.msg(f"{GOLD}Background uses reset for new session.{RESET}")
