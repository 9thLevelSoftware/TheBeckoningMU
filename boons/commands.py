"""
Boons System Commands

Commands for managing political favors and debts (Prestation) in Kindred society.
"""

from evennia import Command, default_cmds
from .utils import (
    get_or_create_ledger,
    offer_boon,
    accept_boon,
    decline_boon,
    call_in_boon,
    fulfill_boon,
    cancel_boon,
    dispute_boon,
    acknowledge_boon,
    get_boons_owed_by,
    get_boons_held_by,
    get_boons_between,
    get_pending_boons_for,
    get_net_boon_position,
    check_harpy_permissions,
    update_ledger,
    format_boon_ledger,
    format_boons_with_character,
    format_pending_boons
)
from .models import Boon
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY,
    GOLD, RESET, BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)


class CmdBoon(default_cmds.MuxCommand):
    """
    View boons (favors and debts).

    Usage:
        +boon
        +boon <character>
        +boon/pending

    Displays your boons or boons with a specific character.

    Switches:
        /pending - View boons requiring your action

    Examples:
        +boon
        +boon Marcus
        +boon/pending
    """

    key = "+boon"
    aliases = ["boon", "boons"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if "pending" in self.switches:
            self._show_pending()
            return

        if self.args:
            self._show_with_character()
            return

        self._show_summary()

    def _show_summary(self):
        """Show boon summary."""
        ledger = get_or_create_ledger(self.caller)
        output = format_boon_ledger(self.caller, ledger)
        self.caller.msg(output)

    def _show_with_character(self):
        """Show boons with a specific character."""
        target = self.caller.search(self.args.strip())
        if not target:
            return

        boons = get_boons_between(self.caller, target)
        net_position = get_net_boon_position(self.caller, target)
        output = format_boons_with_character(self.caller, target, boons, net_position)
        self.caller.msg(output)

    def _show_pending(self):
        """Show boons pending action."""
        pending = get_pending_boons_for(self.caller)
        output = format_pending_boons(self.caller, pending)
        self.caller.msg(output)


class CmdBoonGive(default_cmds.MuxCommand):
    """
    Offer a boon to someone.

    Usage:
        +boongive <character> <type> = <description>

    Types: trivial, minor, major, blood, life

    Creates a boon offer that the other character must accept.

    Examples:
        +boongive Marcus minor = Saved me from a hunter
        +boongive Elena major = She covered up my Masquerade breach
    """

    key = "+boongive"
    aliases = ["boongive"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not self.args or not self.rhs:
            caller.msg("Usage: +boongive <character> <type> = <description>")
            caller.msg("Types: trivial, minor, major, blood, life")
            return

        # Parse target and type
        parts = self.lhs.strip().split()
        if len(parts) < 2:
            caller.msg("Usage: +boongive <character> <type> = <description>")
            return

        target_name = " ".join(parts[:-1])
        boon_type = parts[-1].lower()

        target = caller.search(target_name)
        if not target:
            return

        description = self.rhs.strip()

        # Offer boon
        success, boon, message = offer_boon(caller, target, boon_type, description)

        if success:
            caller.msg(f"|g{message}|n")
            caller.msg(f"Boon ID: #{boon.id}")

            # Notify target
            if target.sessions.all():
                target.msg(
                    f"\n{GOLD}[New Boon Offer]{RESET}\n"
                    f"{caller.key} has offered you a {PALE_IVORY}{boon.get_boon_type_display()}{RESET} boon.\n"
                    f"Reason: {description}\n\n"
                    f"Use |w+boonaccept {boon.id}|n to accept or |w+boondecline {boon.id}|n to decline."
                )
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonAccept(default_cmds.MuxCommand):
    """
    Accept a boon offer.

    Usage:
        +boonaccept <boon #>

    Accepts a boon that has been offered to you, formalizing the debt.
    """

    key = "+boonaccept"
    aliases = ["boonaccept"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not self.args:
            caller.msg("Usage: +boonaccept <boon #>")
            return

        try:
            boon_id = int(self.args.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        success, message = accept_boon(boon_id, caller)

        if success:
            caller.msg(f"|g{message}|n")

            # Notify creditor
            try:
                boon = Boon.objects.get(id=boon_id)
                if boon.creditor.sessions.all():
                    boon.creditor.msg(
                        f"\n{GOLD}[Boon Accepted]{RESET}\n"
                        f"{caller.key} has accepted the {boon.get_boon_type_display()} boon you offered."
                    )
            except Boon.DoesNotExist:
                pass
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonDecline(default_cmds.MuxCommand):
    """
    Decline a boon offer.

    Usage:
        +boondecline <boon #>
        +boondecline <boon #> = <reason>

    Declines a boon that has been offered to you.
    """

    key = "+boondecline"
    aliases = ["boondecline"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not self.args:
            caller.msg("Usage: +boondecline <boon #> = <reason>")
            return

        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        reason = self.rhs.strip() if self.rhs else ""

        success, message = decline_boon(boon_id, reason, caller)

        if success:
            caller.msg(f"|g{message}|n")

            # Notify creditor
            try:
                boon = Boon.objects.get(id=boon_id)
                if boon.creditor.sessions.all():
                    boon.creditor.msg(
                        f"\n{GOLD}[Boon Declined]{RESET}\n"
                        f"{caller.key} has declined the {boon.get_boon_type_display()} boon you offered."
                        + (f"\nReason: {reason}" if reason else "")
                    )
            except Boon.DoesNotExist:
                pass
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonCall(default_cmds.MuxCommand):
    """
    Call in a boon owed to you.

    Usage:
        +booncall <boon #> = <description>

    Calls in a boon that is owed to you, specifying what you need.
    """

    key = "+booncall"
    aliases = ["booncall"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not self.args or not self.rhs:
            caller.msg("Usage: +booncall <boon #> = <description of what you need>")
            return

        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        description = self.rhs.strip()

        success, message = call_in_boon(boon_id, description, caller)

        if success:
            caller.msg(f"|g{message}|n")

            # Notify debtor
            try:
                boon = Boon.objects.get(id=boon_id)
                if boon.debtor.sessions.all():
                    boon.debtor.msg(
                        f"\n{BLOOD_RED}[Boon Called In]{RESET}\n"
                        f"{caller.key} has called in the {boon.get_boon_type_display()} boon you owe.\n"
                        f"Request: {description}\n\n"
                        f"Use |w+boonfulfill {boon_id} = <description>|n when fulfilled."
                    )
            except Boon.DoesNotExist:
                pass
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonFulfill(default_cmds.MuxCommand):
    """
    Mark a boon as fulfilled.

    Usage:
        +boonfulfill <boon #> = <description of how you fulfilled it>

    Marks a boon as fulfilled after you've completed the requested favor.
    """

    key = "+boonfulfill"
    aliases = ["boonfulfill"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not self.args or not self.rhs:
            caller.msg("Usage: +boonfulfill <boon #> = <description>")
            return

        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        description = self.rhs.strip()

        success, message = fulfill_boon(boon_id, description, caller)

        if success:
            caller.msg(f"|g{message}|n")

            # Notify other party
            try:
                boon = Boon.objects.get(id=boon_id)
                other_party = boon.creditor if boon.debtor == caller else boon.debtor
                if other_party.sessions.all():
                    other_party.msg(
                        f"\n{GOLD}[Boon Fulfilled]{RESET}\n"
                        f"The {boon.get_boon_type_display()} boon with {caller.key} has been marked as fulfilled.\n"
                        f"Description: {description}"
                    )
            except Boon.DoesNotExist:
                pass
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonAdmin(default_cmds.MuxCommand):
    """
    Admin/Harpy commands for managing boons.

    Usage:
        +boonadmin/acknowledge <boon #>
        +boonadmin/cancel <boon #> = <reason>
        +boonadmin/list
        +boonadmin/refresh <character>

    Switches:
        /acknowledge - Officially acknowledge a boon (Harpy only)
        /cancel - Cancel a boon
        /list - List all public boons
        /refresh - Refresh a character's boon ledger

    Harpies can acknowledge boons to make them official in Kindred society.
    """

    key = "+boonadmin"
    aliases = ["boonadmin"]
    locks = "cmd:perm(Builder) or cmd:pperm(Harpy)"
    help_category = "Admin"

    def func(self):
        caller = self.caller

        if "acknowledge" in self.switches:
            self._acknowledge_boon()
        elif "cancel" in self.switches:
            self._cancel_boon()
        elif "list" in self.switches:
            self._list_boons()
        elif "refresh" in self.switches:
            self._refresh_ledger()
        else:
            caller.msg("Usage: +boonadmin/<switch>. See help for switches.")

    def _acknowledge_boon(self):
        """Acknowledge a boon (Harpy function)."""
        caller = self.caller

        if not self.args:
            caller.msg("Usage: +boonadmin/acknowledge <boon #>")
            return

        try:
            boon_id = int(self.args.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        success, message = acknowledge_boon(boon_id, caller)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _cancel_boon(self):
        """Cancel a boon."""
        caller = self.caller

        if not self.lhs or not self.rhs:
            caller.msg("Usage: +boonadmin/cancel <boon #> = <reason>")
            return

        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        reason = self.rhs.strip()

        success, message = cancel_boon(boon_id, reason)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _list_boons(self):
        """List all public boons."""
        from .utils import get_all_public_boons

        caller = self.caller
        boons = get_all_public_boons()[:20]  # Last 20

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {PALE_IVORY}PUBLIC BOONS{RESET}{' ' * 61}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}\n")

        for boon in boons:
            output.append(f"#{boon.id} - {boon.debtor.key} → {boon.creditor.key} - {boon.get_boon_type_display()}")
            output.append(f"  Status: {boon.status.title()}")
            output.append(f"  {SHADOW_GREY}{boon.description[:60]}{RESET}")
            if boon.acknowledged_by_harpy:
                output.append(f"  {GOLD}✓ Acknowledged by {boon.harpy.key if boon.harpy else 'Harpy'}{RESET}")
            output.append("")

        caller.msg("\n".join(output))

    def _refresh_ledger(self):
        """Refresh a character's boon ledger."""
        caller = self.caller

        if not self.args:
            caller.msg("Usage: +boonadmin/refresh <character>")
            return

        target = caller.search(self.args.strip())
        if not target:
            return

        ledger = update_ledger(target)
        caller.msg(f"|gRefreshed boon ledger for {target.key}.|n")
        caller.msg(f"Debts: {ledger.total_debt_weight} | Credits: {ledger.total_credit_weight} | Net: {ledger.net_weight}")
