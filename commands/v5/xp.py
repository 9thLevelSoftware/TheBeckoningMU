"""
V5 Experience Point Commands

Commands for viewing, spending, and awarding XP.
"""

from evennia import Command
from evennia import default_cmds
from .utils.xp_utils import (
    get_current_xp,
    get_total_earned_xp,
    get_total_spent_xp,
    get_xp_log,
    award_xp,
    spend_xp_on_attribute,
    spend_xp_on_skill,
    spend_xp_on_specialty,
    spend_xp_on_discipline,
    spend_xp_on_humanity,
    spend_xp_on_willpower,
    get_xp_cost_attribute,
    get_xp_cost_skill,
    get_xp_cost_discipline,
    get_xp_cost_humanity,
    get_xp_cost_willpower
)
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY,
    GOLD, RESET, BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
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
        """Show XP costs."""
        caller = self.caller

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {PALE_IVORY}XP COSTS FOR ADVANCEMENT{RESET}{' ' * 48}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")

        output.append(f"\n{PALE_IVORY}Attributes:{RESET}")
        output.append(f"  New Rating × 5 XP")
        output.append(f"  {SHADOW_GREY}(e.g., Strength 3 → 4 costs 20 XP){RESET}")

        output.append(f"\n{PALE_IVORY}Skills:{RESET}")
        output.append(f"  New Rating × 3 XP")
        output.append(f"  {SHADOW_GREY}(e.g., Brawl 2 → 3 costs 9 XP){RESET}")

        output.append(f"\n{PALE_IVORY}Specialties:{RESET}")
        output.append(f"  3 XP (flat)")

        output.append(f"\n{PALE_IVORY}Disciplines:{RESET}")
        output.append(f"  In-Clan: New Rating × 5 XP")
        output.append(f"  Out-of-Clan: New Rating × 7 XP")
        output.append(f"  {SHADOW_GREY}(e.g., in-clan Potence 1 → 2 costs 10 XP){RESET}")

        output.append(f"\n{PALE_IVORY}Other:{RESET}")
        output.append(f"  Humanity: New Rating × 10 XP")
        output.append(f"  Willpower (permanent): 8 XP")
        output.append(f"  Background: 3 XP per dot")
        output.append(f"  Merit: 3 XP per dot")

        output.append(f"\n{SHADOW_GREY}Use |w+spend <type> <name>|x to spend XP.{RESET}")

        caller.msg("\n".join(output))


class CmdSpend(Command):
    """
    Spend XP to improve your character.

    Usage:
        +spend attribute <name>
        +spend skill <name>
        +spend specialty <skill> = <specialty name>
        +spend discipline <name>
        +spend humanity
        +spend willpower

    Spends XP to raise traits according to V5 costs.

    Examples:
        +spend attribute strength
        +spend skill brawl
        +spend specialty brawl = Grappling
        +spend discipline potence
        +spend humanity
        +spend willpower
    """

    key = "+spend"
    aliases = ["spend"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        """Execute spend command."""
        caller = self.caller

        if not self.args:
            caller.msg("Usage: +spend <type> <name>")
            caller.msg("Types: attribute, skill, specialty, discipline, humanity, willpower")
            caller.msg("See: help +spend")
            return

        args = self.args.strip().split(None, 1)
        if len(args) < 1:
            caller.msg("Usage: +spend <type> <name>")
            return

        spend_type = args[0].lower()

        # Humanity and Willpower don't need a name
        if spend_type in ['humanity', 'willpower']:
            self._spend_special(spend_type)
            return

        if len(args) < 2 and spend_type != 'specialty':
            caller.msg(f"Usage: +spend {spend_type} <name>")
            return

        if spend_type == 'attribute':
            self._spend_attribute(args[1])
        elif spend_type == 'skill':
            self._spend_skill(args[1])
        elif spend_type == 'specialty':
            self._spend_specialty()
        elif spend_type == 'discipline':
            self._spend_discipline(args[1])
        else:
            caller.msg(f"|rInvalid type: {spend_type}|n")
            caller.msg("Types: attribute, skill, specialty, discipline, humanity, willpower")

    def _spend_attribute(self, attribute_name):
        """Spend XP on attribute."""
        caller = self.caller

        # Show cost first
        cost, new_rating = get_xp_cost_attribute(caller, attribute_name)
        if cost is None:
            caller.msg(f"|rCannot raise {attribute_name} further (max 5).|n")
            return

        current_xp = get_current_xp(caller)
        caller.msg(f"Raising {attribute_name} to {new_rating} will cost {GOLD}{cost} XP{RESET}.")
        caller.msg(f"You have {GOLD}{current_xp} XP{RESET}.")

        if current_xp < cost:
            caller.msg(f"|rInsufficient XP.|n")
            return

        # Confirm and spend
        success, message = spend_xp_on_attribute(caller, attribute_name)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _spend_skill(self, skill_name):
        """Spend XP on skill."""
        caller = self.caller

        # Show cost first
        cost, new_rating = get_xp_cost_skill(caller, skill_name)
        if cost is None:
            caller.msg(f"|rCannot raise {skill_name} further (max 5).|n")
            return

        current_xp = get_current_xp(caller)
        caller.msg(f"Raising {skill_name} to {new_rating} will cost {GOLD}{cost} XP{RESET}.")
        caller.msg(f"You have {GOLD}{current_xp} XP{RESET}.")

        if current_xp < cost:
            caller.msg(f"|rInsufficient XP.|n")
            return

        # Confirm and spend
        success, message = spend_xp_on_skill(caller, skill_name)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _spend_specialty(self):
        """Spend XP on specialty."""
        caller = self.caller

        if not self.rhs:
            caller.msg("Usage: +spend specialty <skill> = <specialty name>")
            return

        skill_name = self.lhs.strip().split()[-1]  # Get last word after 'specialty'
        specialty_name = self.rhs.strip()

        success, message = spend_xp_on_specialty(caller, skill_name, specialty_name)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _spend_discipline(self, discipline_name):
        """Spend XP on discipline."""
        caller = self.caller

        # Show cost first
        cost, new_rating, is_in_clan = get_xp_cost_discipline(caller, discipline_name)
        if cost is None:
            caller.msg(f"|rCannot raise {discipline_name} further (max 5).|n")
            return

        clan_str = " (in-clan)" if is_in_clan else " (out-of-clan)"
        current_xp = get_current_xp(caller)
        caller.msg(f"Raising {discipline_name} to {new_rating}{clan_str} will cost {GOLD}{cost} XP{RESET}.")
        caller.msg(f"You have {GOLD}{current_xp} XP{RESET}.")

        if current_xp < cost:
            caller.msg(f"|rInsufficient XP.|n")
            return

        # Confirm and spend
        success, message = spend_xp_on_discipline(caller, discipline_name)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _spend_special(self, spend_type):
        """Spend XP on humanity or willpower."""
        caller = self.caller

        if spend_type == 'humanity':
            cost, new_rating = get_xp_cost_humanity(caller)
            if cost is None:
                caller.msg("|rCannot raise Humanity further (max 10).|n")
                return

            current_xp = get_current_xp(caller)
            caller.msg(f"Raising Humanity to {new_rating} will cost {GOLD}{cost} XP{RESET}.")
            caller.msg(f"You have {GOLD}{current_xp} XP{RESET}.")

            if current_xp < cost:
                caller.msg("|rInsufficient XP.|n")
                return

            success, message = spend_xp_on_humanity(caller)

        elif spend_type == 'willpower':
            cost, new_rating = get_xp_cost_willpower(caller)
            if cost is None:
                caller.msg("|rCannot raise Willpower further (max 10).|n")
                return

            current_xp = get_current_xp(caller)
            caller.msg(f"Raising permanent Willpower to {new_rating} will cost {GOLD}{cost} XP{RESET}.")
            caller.msg(f"You have {GOLD}{current_xp} XP{RESET}.")

            if current_xp < cost:
                caller.msg("|rInsufficient XP.|n")
                return

            success, message = spend_xp_on_willpower(caller)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")


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
