"""
Social Commands for V5 System

Commands for managing coteries and viewing social standing.
"""

from evennia import Command
from evennia import default_cmds
from evennia.utils import search

from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, GOLD, BONE_WHITE, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR, BOX_L, BOX_R
)

from .utils import social_utils


class CmdCoterie(default_cmds.MuxCommand):
    """
    Manage your coterie (vampire group).

    Usage:
      +coterie                          - View your coterie
      +coterie/create <name>=<desc>     - Create a new coterie
      +coterie/invite <character>       - Invite someone to your coterie
      +coterie/join <leader>            - Accept a coterie invitation
      +coterie/leave                    - Leave your current coterie
      +coterie/promote <character>      - Promote member to lieutenant
      +coterie/demote <character>       - Demote lieutenant to member
      +coterie/kick <character>         - Remove member from coterie
      +coterie/disband                  - Disband your coterie (leader only)
      +coterie/resources                - View coterie resources
      +coterie/resource <type>=<value>  - Set resource value (leader only)

    Coteries are groups of vampires who share resources and work together.
    Resources include Domain, Haven, Herd, and Contacts (rated 0-5).

    Examples:
      +coterie/create Night Watch=Protectors of the Elysium
      +coterie/invite Bob
      +coterie/resource domain=3
      +coterie/promote Alice
    """

    key = "+coterie"
    aliases = ["coterie"]
    locks = "cmd:all()"
    help_category = "V5 Social"

    def func(self):
        """Execute command."""
        caller = self.caller

        # Parse switches
        if 'create' in self.switches:
            self.do_create()
        elif 'invite' in self.switches:
            self.do_invite()
        elif 'join' in self.switches:
            self.do_join()
        elif 'leave' in self.switches:
            self.do_leave()
        elif 'promote' in self.switches:
            self.do_promote()
        elif 'demote' in self.switches:
            self.do_demote()
        elif 'kick' in self.switches:
            self.do_kick()
        elif 'disband' in self.switches:
            self.do_disband()
        elif 'resources' in self.switches:
            self.do_view_resources()
        elif 'resource' in self.switches:
            self.do_set_resource()
        else:
            self.do_view()

    def do_create(self):
        """Create a new coterie."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +coterie/create <name>=<description>")
            return

        name, description = self.args.split('=', 1)
        name = name.strip()
        description = description.strip()

        success, message = social_utils.create_coterie(self.caller, name, description)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_invite(self):
        """Invite someone to the coterie."""
        if not self.args:
            self.caller.msg("Usage: +coterie/invite <character>")
            return

        target_name = self.args.strip()
        target = search.search_object(target_name, typeclass='typeclasses.characters.Character')

        if not target:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} Character '{target_name}' not found.")
            return

        target = target[0]

        success, message = social_utils.invite_to_coterie(self.caller, target)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
            target.msg(
                f"{GOLD}{self.caller.key} has invited you to join their coterie. "
                f"Use '+coterie/join {self.caller.key}' to accept.{RESET}"
            )
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_join(self):
        """Join a coterie."""
        if not self.args:
            self.caller.msg("Usage: +coterie/join <leader>")
            return

        leader_name = self.args.strip()

        success, message = social_utils.accept_invitation(self.caller, leader_name)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")

            # Notify leader
            leader = search.search_object(leader_name, typeclass='typeclasses.characters.Character')
            if leader:
                leader[0].msg(f"{GOLD}{self.caller.key} has joined your coterie.{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_leave(self):
        """Leave current coterie."""
        success, message = social_utils.leave_coterie(self.caller)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_promote(self):
        """Promote a member to lieutenant."""
        if not self.args:
            self.caller.msg("Usage: +coterie/promote <character>")
            return

        target_name = self.args.strip()
        target = search.search_object(target_name, typeclass='typeclasses.characters.Character')

        if not target:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} Character '{target_name}' not found.")
            return

        target = target[0]

        success, message = social_utils.set_member_rank(self.caller, target, 'lieutenant')

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
            target.msg(f"{GOLD}You have been promoted to lieutenant in the coterie!{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_demote(self):
        """Demote a lieutenant to member."""
        if not self.args:
            self.caller.msg("Usage: +coterie/demote <character>")
            return

        target_name = self.args.strip()
        target = search.search_object(target_name, typeclass='typeclasses.characters.Character')

        if not target:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} Character '{target_name}' not found.")
            return

        target = target[0]

        success, message = social_utils.set_member_rank(self.caller, target, 'member')

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
            target.msg(f"{GOLD}Your rank in the coterie has been changed to member.{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_kick(self):
        """Remove a member from the coterie."""
        if not self.args:
            self.caller.msg("Usage: +coterie/kick <character>")
            return

        target_name = self.args.strip()
        target = search.search_object(target_name, typeclass='typeclasses.characters.Character')

        if not target:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} Character '{target_name}' not found.")
            return

        target = target[0]

        success, message = social_utils.remove_coterie_member(self.caller, target)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
            target.msg(f"{BLOOD_RED}You have been removed from the coterie.{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_disband(self):
        """Disband the coterie."""
        success, message = social_utils.disband_coterie(self.caller)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_view_resources(self):
        """View coterie resources."""
        coterie = social_utils.get_coterie_info(self.caller)

        if not coterie:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} You are not in a coterie.")
            return

        resources = coterie.get('resources', {})

        lines = []
        lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 40}{BOX_TR}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}COTERIE RESOURCES{' ' * 22}{BOX_V}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 40}{BOX_R}{RESET}")

        for resource_type in ['domain', 'haven', 'herd', 'contacts']:
            value = resources.get(resource_type, 0)
            dots = f"{GOLD}{'●' * value}{SHADOW_GREY}{'○' * (5 - value)}{RESET}"
            resource_name = resource_type.capitalize()
            lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}{resource_name:<15}{RESET} {dots:<20} {SHADOW_GREY}{BOX_V}{RESET}")

        lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 40}{BOX_BR}{RESET}")

        self.caller.msg("\n".join(lines))

    def do_set_resource(self):
        """Set a coterie resource value."""
        if not self.args or '=' not in self.args:
            self.caller.msg("Usage: +coterie/resource <type>=<value>")
            self.caller.msg("Resource types: domain, haven, herd, contacts")
            self.caller.msg("Values: 0-5")
            return

        resource_type, value = self.args.split('=', 1)
        resource_type = resource_type.strip().lower()
        value = value.strip()

        success, message = social_utils.set_coterie_resources(self.caller, resource_type, value)

        if success:
            self.caller.msg(f"{GOLD}{message}{RESET}")
        else:
            self.caller.msg(f"{BLOOD_RED}Error:{RESET} {message}")

    def do_view(self):
        """View coterie information."""
        coterie = social_utils.get_coterie_info(self.caller)

        if not coterie:
            self.caller.msg(f"{SHADOW_GREY}You are not currently in a coterie.{RESET}")
            self.caller.msg(f"Use {GOLD}+coterie/create <name>=<description>{RESET} to create one.")
            return

        # Get role
        role = social_utils.get_character_role(self.caller)

        # Get members
        members = social_utils.get_coterie_members(self.caller) if role == 'leader' else []

        # Build display
        lines = []
        lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 78}{BOX_TR}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}COTERIE{' ' * 70}{BOX_V}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

        # Name and description
        lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}Name:{RESET} {DARK_RED}{coterie['name']:<69}{RESET} {SHADOW_GREY}{BOX_V}{RESET}")

        # Description (wrapped)
        desc = coterie.get('description', '')
        if len(desc) <= 70:
            lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}Description:{RESET} {desc:<63} {SHADOW_GREY}{BOX_V}{RESET}")
        else:
            words = desc.split()
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word])
                if len(test_line) <= 63:
                    current_line.append(word)
                else:
                    line_text = ' '.join(current_line)
                    label = f"{GOLD}Description:{RESET}" if not lines or 'Description' not in lines[-1] else " " * 12
                    lines.append(f"{SHADOW_GREY}{BOX_V} {label} {line_text:<63} {SHADOW_GREY}{BOX_V}{RESET}")
                    current_line = [word]
            if current_line:
                line_text = ' '.join(current_line)
                label = f"{GOLD}Description:{RESET}" if 'Description' not in lines[-1] else " " * 12
                lines.append(f"{SHADOW_GREY}{BOX_V} {label} {line_text:<63} {SHADOW_GREY}{BOX_V}{RESET}")

        # Your role
        role_display = role.capitalize() if role else "Member"
        lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}Your Role:{RESET} {role_display:<64} {SHADOW_GREY}{BOX_V}{RESET}")

        # Members (if leader)
        if role == 'leader' and members:
            lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}MEMBERS{' ' * 70}{BOX_V}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

            for member_data in members:
                member = member_data['character']
                rank = member_data['rank']
                rank_display = rank.capitalize()
                rank_color = DARK_RED if rank == 'leader' else GOLD if rank == 'lieutenant' else PALE_IVORY
                lines.append(
                    f"{SHADOW_GREY}{BOX_V} {rank_color}{member.key:<50}{RESET} "
                    f"{rank_color}({rank_display}){RESET}{' ' * (50 - len(member.key) - len(rank_display) - 3)} {SHADOW_GREY}{BOX_V}{RESET}"
                )

        # Resources (if leader)
        if role == 'leader':
            resources = coterie.get('resources', {})
            lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}RESOURCES{' ' * 68}{BOX_V}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

            for resource_type in ['domain', 'haven', 'herd', 'contacts']:
                value = resources.get(resource_type, 0)
                dots = f"{GOLD}{'●' * value}{SHADOW_GREY}{'○' * (5 - value)}{RESET}"
                resource_name = resource_type.capitalize()
                lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}{resource_name:<15}{RESET} {dots:<58} {SHADOW_GREY}{BOX_V}{RESET}")

        lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 78}{BOX_BR}{RESET}")

        self.caller.msg("\n".join(lines))


class CmdSocial(Command):
    """
    View comprehensive social standing.

    Usage:
      +social                - View your Status, Boons, and Coterie
      +social <character>    - View another character's social standing

    Displays Status (political standing), Boons (favors owed/held),
    and Coterie membership in one comprehensive view.

    Examples:
      +social
      +social Alice
    """

    key = "+social"
    aliases = ["social"]
    locks = "cmd:all()"
    help_category = "V5 Social"

    def func(self):
        """Execute command."""
        caller = self.caller

        # Determine target
        if self.args:
            target_name = self.args.strip()
            target = search.search_object(target_name, typeclass='typeclasses.characters.Character')

            if not target:
                caller.msg(f"{BLOOD_RED}Error:{RESET} Character '{target_name}' not found.")
                return

            target = target[0]
        else:
            target = caller

        # Build social display
        lines = []
        lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 78}{BOX_TR}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}SOCIAL STANDING: {target.key}{' ' * (58 - len(target.key))}{BOX_V}{RESET}")
        lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 78}{BOX_BR}{RESET}")
        lines.append("")

        # Status Section
        try:
            from status.utils import get_character_status
            char_status = get_character_status(target)

            if char_status:
                lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 78}{BOX_TR}{RESET}")
                lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}STATUS{' ' * 71}{BOX_V}{RESET}")
                lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

                total = char_status.total_status
                status_dots = f"{GOLD}{'●' * total}{SHADOW_GREY}{'○' * (5 - total)}{RESET}"

                lines.append(f"{SHADOW_GREY}{BOX_V} {PALE_IVORY}Total:{RESET} {status_dots} ({total}){' ' * 60} {SHADOW_GREY}{BOX_V}{RESET}")

                if char_status.position:
                    lines.append(f"{SHADOW_GREY}{BOX_V} {PALE_IVORY}Position:{RESET} {GOLD}{char_status.position.name:<61}{RESET} {SHADOW_GREY}{BOX_V}{RESET}")

                lines.append(f"{SHADOW_GREY}{BOX_V} {PALE_IVORY}Sect:{RESET} {char_status.sect:<67} {SHADOW_GREY}{BOX_V}{RESET}")

                lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 78}{BOX_BR}{RESET}")
                lines.append("")
        except ImportError:
            pass

        # Boons Section
        try:
            from boons.utils import get_or_create_ledger
            ledger = get_or_create_ledger(target)

            if ledger.total_debt_weight > 0 or ledger.total_credit_weight > 0:
                lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 78}{BOX_TR}{RESET}")
                lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}BOONS{' ' * 72}{BOX_V}{RESET}")
                lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

                # Debts
                debts = []
                if ledger.life_owed > 0:
                    debts.append(f"Life: {ledger.life_owed}")
                if ledger.blood_owed > 0:
                    debts.append(f"Blood: {ledger.blood_owed}")
                if ledger.major_owed > 0:
                    debts.append(f"Major: {ledger.major_owed}")
                if ledger.minor_owed > 0:
                    debts.append(f"Minor: {ledger.minor_owed}")
                if ledger.trivial_owed > 0:
                    debts.append(f"Trivial: {ledger.trivial_owed}")

                debt_str = ", ".join(debts) if debts else "None"
                lines.append(f"{SHADOW_GREY}{BOX_V} {PALE_IVORY}Debts:{RESET} {debt_str:<67} {SHADOW_GREY}{BOX_V}{RESET}")

                # Credits (only show if viewing self)
                if target == caller:
                    credits = []
                    if ledger.life_held > 0:
                        credits.append(f"Life: {ledger.life_held}")
                    if ledger.blood_held > 0:
                        credits.append(f"Blood: {ledger.blood_held}")
                    if ledger.major_held > 0:
                        credits.append(f"Major: {ledger.major_held}")
                    if ledger.minor_held > 0:
                        credits.append(f"Minor: {ledger.minor_held}")
                    if ledger.trivial_held > 0:
                        credits.append(f"Trivial: {ledger.trivial_held}")

                    credit_str = ", ".join(credits) if credits else "None"
                    lines.append(f"{SHADOW_GREY}{BOX_V} {PALE_IVORY}Credits:{RESET} {credit_str:<65} {SHADOW_GREY}{BOX_V}{RESET}")

                lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 78}{BOX_BR}{RESET}")
                lines.append("")
        except ImportError:
            pass

        # Coterie Section
        coterie = social_utils.get_coterie_info(target)
        if coterie:
            role = social_utils.get_character_role(target)

            lines.append(f"{SHADOW_GREY}{BOX_TL}{BOX_H * 78}{BOX_TR}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_V} {BONE_WHITE}COTERIE{' ' * 70}{BOX_V}{RESET}")
            lines.append(f"{SHADOW_GREY}{BOX_L}{BOX_H * 78}{BOX_R}{RESET}")

            lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}Name:{RESET} {DARK_RED}{coterie['name']:<69}{RESET} {SHADOW_GREY}{BOX_V}{RESET}")

            role_display = role.capitalize() if role else "Member"
            lines.append(f"{SHADOW_GREY}{BOX_V} {GOLD}Role:{RESET} {role_display:<70} {SHADOW_GREY}{BOX_V}{RESET}")

            lines.append(f"{SHADOW_GREY}{BOX_BL}{BOX_H * 78}{BOX_BR}{RESET}")

        caller.msg("\n".join(lines))
