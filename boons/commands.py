"""
Boons System Commands

Commands for managing political favors and debts (Prestation) in Kindred society.
"""

from evennia import default_cmds

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

from .models import Boon
from .utils import (
    accept_boon,
    acknowledge_boon,
    call_in_boon,
    cancel_boon,
    decline_boon,
    dispute_boon,
    force_fulfill_boon,
    format_boon_ledger,
    format_boons_with_character,
    format_pending_boons,
    fulfill_boon,
    get_boon_totals,
    get_boons_between,
    get_net_boon_position,
    get_pending_boons_for,
    is_character,
    offer_boon,
)


class CmdBoon(default_cmds.MuxCommand):
    """
    View boons (favors and debts).

    Usage:
        +boon
        +boon <character>
        +boon/pending
        +boon/dispute <boon #> = <reason>

    Displays your boons or boons with a specific character.

    Switches:
        /pending - View boons requiring your action
        /dispute - Dispute an accepted or called-in boon you are party to.
                   It stays owed until staff or a Harpy rules on it.

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

        if "dispute" in self.switches:
            self._dispute()
            return

        if self.args:
            self._show_with_character()
            return

        self._show_summary()

    def _show_summary(self):
        """Show boon summary."""
        output = format_boon_ledger(self.caller, get_boon_totals(self.caller))
        self.caller.msg(output)

    def _show_with_character(self):
        """Show boons with a specific character."""
        target = self.caller.search(self.args.strip())
        if not target:
            return
        if not is_character(target):
            self.caller.msg("|rBoons are only owed between characters.|n")
            return

        boons = get_boons_between(self.caller, target)
        net_position = get_net_boon_position(self.caller, target)
        output = format_boons_with_character(self.caller, target, boons, net_position)
        self.caller.msg(output)

    def _dispute(self):
        """Dispute a boon you are party to."""
        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: +boon/dispute <boon #> = <reason>")
            return
        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        success, message = dispute_boon(boon_id, self.rhs.strip(), caller)
        caller.msg(f"|g{message}|n" if success else f"|r{message}|n")
        if success:
            boon = Boon.objects.get(id=boon_id)
            other = boon.creditor if boon.debtor == caller else boon.debtor
            if other.sessions.all():
                other.msg(f"\n{GOLD}[Boon Disputed]{RESET}\n{caller.key} disputes boon #{boon_id}: {self.rhs.strip()}")

    def _show_pending(self):
        """Show boons pending action."""
        pending = get_pending_boons_for(self.caller)
        output = format_pending_boons(self.caller, pending)
        self.caller.msg(output)


class CmdBoonGive(default_cmds.MuxCommand):
    """
    Offer to owe someone a boon.

    Usage:
        +boongive <character> <type> = <description>

    Types: trivial, minor, major, blood, life

    You offer to owe <character> a boon. Once they accept it with
    +boonaccept, you are in their debt until they call it in and you both
    confirm it repaid with +boonfulfill.

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
        if not is_character(target):
            caller.msg("|rBoons are only owed between characters.|n")
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
                    f"{caller.key} offers to owe you a {PALE_IVORY}{boon.get_boon_type_display()}{RESET} boon.\n"
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

    Accepts a boon someone has offered to owe you, formalizing the debt.
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

            # Notify the debtor who offered it
            try:
                boon = Boon.objects.get(id=boon_id)
                if boon.debtor.sessions.all():
                    boon.debtor.msg(
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

            # Notify the debtor who offered it
            try:
                boon = Boon.objects.get(id=boon_id)
                if boon.debtor.sessions.all():
                    boon.debtor.msg(
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
                        f"When it is repaid, you both confirm with |w+boonfulfill {boon_id} = <description>|n."
                    )
            except Boon.DoesNotExist:
                pass
        else:
            caller.msg(f"|r{message}|n")


class CmdBoonFulfill(default_cmds.MuxCommand):
    """
    Confirm that a called-in boon has been repaid.

    Usage:
        +boonfulfill <boon #> = <description of how it was repaid>

    Both the debtor and the creditor must confirm. The boon is fulfilled
    when the second of them does.
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
                if boon.status == "fulfilled":
                    note = f"The {boon.get_boon_type_display()} boon with {caller.key} is fulfilled."
                else:
                    note = (
                        f"{caller.key} confirms the {boon.get_boon_type_display()} boon was repaid. "
                        f"Use |w+boonfulfill {boon_id} = <description>|n to confirm it too."
                    )
                if other_party.sessions.all():
                    other_party.msg(
                        f"\n{GOLD}[Boon Fulfilment]{RESET}\n{note}\n"
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
        +boonadmin/fulfill <boon #> = <reason>
        +boonadmin/list

    Switches:
        /acknowledge - Officially acknowledge a boon (Harpy only)
        /cancel - Cancel a boon (also resolves a dispute)
        /fulfill - Mark an outstanding or disputed boon fulfilled without
                   both confirmations
        /list - List all public boons

    Staff (Builder+) may fulfil or cancel any boon. A Harpy may not
    fulfil or cancel a boon they are the debtor or creditor of.

    Harpies can acknowledge boons to make them official in Kindred society.
    """

    key = "+boonadmin"
    aliases = ["boonadmin"]
    locks = "cmd:perm(Builder) or pperm(Harpy)"
    help_category = "Admin"

    def func(self):
        caller = self.caller

        if "acknowledge" in self.switches:
            self._acknowledge_boon()
        elif "cancel" in self.switches:
            self._cancel_boon()
        elif "fulfill" in self.switches:
            self._force_fulfill()
        elif "list" in self.switches:
            self._list_boons()
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

        success, message = cancel_boon(boon_id, reason, caller)

        if success:
            caller.msg(f"|g{message}|n")
        else:
            caller.msg(f"|r{message}|n")

    def _force_fulfill(self):
        """Staff override: fulfil an outstanding boon."""
        caller = self.caller

        if not self.lhs:
            caller.msg("Usage: +boonadmin/fulfill <boon #> = <reason>")
            return

        try:
            boon_id = int(self.lhs.strip())
        except ValueError:
            caller.msg("|rBoon ID must be a number.|n")
            return

        reason = self.rhs.strip() if self.rhs else "Ruled fulfilled without both confirmations"
        success, message = force_fulfill_boon(boon_id, reason, caller)
        caller.msg(f"|g{message}|n" if success else f"|r{message}|n")

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
