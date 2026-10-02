"""
V5 Experience Point Commands

Commands for viewing, spending, and awarding XP.
"""

from evennia import default_cmds

from typeclasses.characters import SPEND_KINDS
from world.ansi_theme import (
    BLOOD_RED,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_TL,
    BOX_TR,
    BOX_V,
    DARK_RED,
    GOLD,
    PALE_IVORY,
    RESET,
    SHADOW_GREY,
)
from world.v5_data import XP_COSTS

from .utils.xp_utils import (
    award_xp,
    get_current_xp,
    get_total_earned_xp,
    get_total_spent_xp,
    get_xp_log,
    spend_xp,
)


class CmdXP(default_cmds.MuxCommand):
    """
    View your experience points and spending log.

    Usage:
        +xp
        +xp/log
        +xp/costs

    Displays your current XP, total earned, and total spent.

    Switches:
        /log - View detailed XP log
        /costs - View XP costs for advancement

    Examples:
        +xp
        +xp/log
        +xp/costs
    """

    key = "+xp"
    aliases = ["xp"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        """Execute XP command."""
        caller = self.caller

        if "log" in self.switches:
            self._show_log()
        elif "costs" in self.switches:
            self._show_costs()
        else:
            self._show_summary()

    def _show_summary(self):
        """Show XP summary."""
        caller = self.caller

        current = get_current_xp(caller)
        earned = get_total_earned_xp(caller)
        spent = get_total_spent_xp(caller)

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {GOLD}{RESET} {PALE_IVORY}EXPERIENCE POINTS{RESET}{' ' * 56}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")

        output.append(f"\n{PALE_IVORY}Current XP:{RESET} {GOLD}{current}{RESET}")
        output.append(f"{PALE_IVORY}Total Earned:{RESET} {earned}")
        output.append(f"{PALE_IVORY}Total Spent:{RESET} {spent}")

        output.append(f"\n{SHADOW_GREY}Use |w+xp/log|x to view spending history.{RESET}")
        output.append(f"{SHADOW_GREY}Use |w+xp/costs|x to view advancement costs.{RESET}")
        output.append(f"{SHADOW_GREY}Use |w+spend <type> <name>|x to spend XP.{RESET}")

        caller.msg("\n".join(output))

    def _show_log(self):
        """Show XP log."""
        caller = self.caller
        log = get_xp_log(caller, limit=20)

        if not log:
            caller.msg("|yNo XP transactions yet.|n")
            return

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {PALE_IVORY}XP LOG{RESET}{' ' * 67}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}\n")

        for entry in reversed(log):  # Most recent first
            entry_type = entry.get('type', 'unknown')
            amount = entry.get('amount', 0)
            reason = entry.get('reason', 'No reason given')
            date = entry.get('date', 'Unknown')[:10]  # Just date
            balance = entry.get('balance', 0)

            if entry_type == 'award':
                color = GOLD
                symbol = "+"
            else:
                color = BLOOD_RED
                symbol = ""

            output.append(f"{SHADOW_GREY}{date}{RESET} - {color}{symbol}{amount} XP{RESET} → Balance: {balance}")
            output.append(f"  {PALE_IVORY}{reason}{RESET}")

            if 'awarded_by' in entry:
                output.append(f"  {SHADOW_GREY}Awarded by: {entry['awarded_by']}{RESET}")

            output.append("")

        caller.msg("\n".join(output))

    def _show_costs(self):
        """Show XP costs (QR p.1, world.v5_data.XP_COSTS)."""
        caller = self.caller
        costs = {kind: multiplier for kind, (_basis, multiplier) in XP_COSTS.items()}

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {PALE_IVORY}XP COSTS FOR ADVANCEMENT{RESET}{' ' * 48}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")

        rows = [
            ("Attribute", f"New level x {costs['attribute']}"),
            ("Skill", f"New level x {costs['skill']}"),
            ("Specialty", f"{costs['specialty']}"),
            ("Clan Discipline", f"New level x {costs['clan_discipline']}"),
            ("Other Discipline", f"New level x {costs['other_discipline']}"),
            ("Caitiff Discipline", f"New level x {costs['caitiff_discipline']}"),
            ("Blood Sorcery Ritual", f"Ritual level x {costs['ritual']}"),
            ("Thin-blood Formula", f"Formula level x {costs['formula']}"),
            ("Advantage (background or merit)", f"{costs['advantage']} per dot"),
            ("Blood Potency", f"New level x {costs['blood_potency']} (up to your Generation's maximum)"),
        ]
        output.append("")
        for label, cost in rows:
            output.append(f"  {PALE_IVORY}{label:<34}{RESET}{cost}")
        output.append(f"\n{SHADOW_GREY}Willpower is Composure + Resolve, and Humanity changes only at the "
                      f"Storyteller's discretion; neither is bought.{RESET}")
        output.append(f"{SHADOW_GREY}Use |w+spend <type> <name>|x to spend XP.{RESET}")

        caller.msg("\n".join(output))


class CmdSpend(default_cmds.MuxCommand):
    """
    Spend XP to improve your character.

    Usage:
        +spend attribute <name>
        +spend skill <name>
        +spend specialty <skill> = <specialty name>
        +spend discipline <name>
        +spend advantage <background or merit>
        +spend advantage <background> = <who or what>   (Allies, Contacts, ...)
        +spend bp
        +spend ritual <name>
        +spend formula <name>

    Costs (V5 core, QR p.1; see +xp/costs): attribute new level x 5, skill
    new level x 3, specialty 3, clan discipline new level x 5, other
    discipline x 7, Caitiff discipline x 6, ritual or formula level x 3,
    advantage 3 per dot, Blood Potency new level x 10 (up to your
    Generation's maximum).

    The name must be a real trait of that type: '+spend skill strength'
    is refused, and nothing is charged when a spend is refused. Willpower
    (Composure + Resolve) and Humanity can't be bought.

    Examples:
        +spend attribute strength
        +spend skill brawl
        +spend specialty brawl = Grappling
        +spend discipline potence
        +spend advantage Resources
        +spend advantage Allies = street gang
        +spend ritual Ward against Ghouls
    """

    key = "+spend"
    aliases = ["spend"]
    locks = "cmd:all()"
    help_category = "V5"

    TYPES = "attribute, skill, specialty, discipline, advantage, bp, ritual, formula"

    def func(self):
        """Execute spend command."""
        caller = self.caller

        lhs = (self.lhs or "").strip()
        if not lhs:
            caller.msg("Usage: +spend <type> <name>")
            caller.msg(f"Types: {self.TYPES}")
            return

        parts = lhs.split(None, 1)
        spend_type = parts[0].lower()
        name = parts[1].strip() if len(parts) > 1 else ""
        note = self.rhs.strip() if self.rhs else None

        if spend_type in ("humanity", "willpower"):
            caller.msg(
                "|rWillpower is Composure + Resolve, and Humanity changes only at the Storyteller's "
                "discretion; neither is bought with XP.|n"
            )
            return
        if spend_type not in SPEND_KINDS:
            caller.msg(f"|rInvalid type: {spend_type}|n")
            caller.msg(f"Types: {self.TYPES}")
            return
        if not name and SPEND_KINDS[spend_type] != "blood_potency":
            caller.msg(f"Usage: +spend {spend_type} <name>")
            return
        if SPEND_KINDS[spend_type] == "specialty" and not note:
            caller.msg("Usage: +spend specialty <skill> = <specialty name>")
            return

        success, message = spend_xp(caller, name, spend_type, note=note)
        if success:
            caller.msg(f"|g{message}|n You have {GOLD}{get_current_xp(caller)} XP{RESET} left.")
        else:
            caller.msg(f"|r{message}|n Nothing was spent.")


class CmdXPAward(default_cmds.MuxCommand):
    """
    Award XP to a character (staff only).

    Usage:
        +xpaward <character> = <amount>
        +xpaward <character> = <amount>/<reason>

    Awards experience points to a character with optional reason.

    Examples:
        +xpaward Marcus = 3
        +xpaward Elena = 5/Exceptional roleplay during Elysium scene
        +xpaward All = 2/Weekly XP award
    """

    key = "+xpaward"
    aliases = ["xpaward"]
    locks = "cmd:perm(Builder)"
    help_category = "Admin"

    def func(self):
        """Execute XP award command."""
        caller = self.caller

        if not self.lhs or not self.rhs:
            caller.msg("Usage: +xpaward <character> = <amount> or <amount>/<reason>")
            return

        target_name = self.lhs.strip()
        rhs_parts = self.rhs.strip().split('/', 1)

        try:
            amount = int(rhs_parts[0].strip())
        except ValueError:
            caller.msg("|rAmount must be a number.|n")
            return

        reason = rhs_parts[1].strip() if len(rhs_parts) > 1 else "Staff award"

        # Check for "All" to award everyone
        if target_name.lower() == 'all':
            self._award_all(amount, reason)
            return

        # Award to specific character
        target = caller.search(target_name)
        if not target:
            return

        success, message = award_xp(target, amount, reason, caller)

        if success:
            caller.msg(f"|g{message}|n")

            # Notify target
            if target.sessions.all():
                target.msg(
                    f"\n{GOLD}[XP Award]{RESET}\n"
                    f"You have been awarded {GOLD}{amount} XP{RESET}!\n"
                    f"Reason: {reason}\n"
                    f"Current XP: {GOLD}{get_current_xp(target)}{RESET}"
                )
        else:
            caller.msg(f"|r{message}|n")

    def _award_all(self, amount, reason):
        """Award XP to all connected players."""
        from evennia import ObjectDB

        caller = self.caller

        # Get all connected player characters
        connected_characters = []
        for session in caller.server.sessions:
            if session.puppet:
                connected_characters.append(session.puppet)

        if not connected_characters:
            caller.msg("|yNo connected characters to award XP to.|n")
            return

        # Award to each
        awarded_count = 0
        for character in connected_characters:
            success, _ = award_xp(character, amount, reason, caller)
            if success:
                awarded_count += 1

                # Notify
                if character.sessions.all():
                    character.msg(
                        f"\n{GOLD}[XP Award]{RESET}\n"
                        f"You have been awarded {GOLD}{amount} XP{RESET}!\n"
                        f"Reason: {reason}\n"
                        f"Current XP: {GOLD}{get_current_xp(character)}{RESET}"
                    )

        caller.msg(f"|gAwarded {amount} XP to {awarded_count} connected character(s).|n")
        caller.msg(f"Reason: {reason}")
