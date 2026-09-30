"""
V5 Humanity System Commands

Commands for managing Humanity, Convictions, Touchstones, Stains, Remorse, and Frenzy.
"""

from evennia.commands.command import Command
from evennia import default_cmds
from commands.v5.utils.humanity_utils import (
    get_humanity_status, add_stain, add_conviction, add_touchstone,
    remove_conviction, remove_touchstone, remorse_roll, check_frenzy_risk,
    resist_frenzy, get_stains, get_humanity
)
from commands.v5.utils.display_utils import (
    BLOOD_RED, VAMPIRE_GOLD, RESET, SHADOW_GREY,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)
from world.v5_dice import format_dice_result


class CmdHumanity(default_cmds.MuxCommand):
    """
    View and manage Humanity, Convictions, and Touchstones.

    Usage:
        +humanity
        +humanity/conviction <text>
        +humanity/touchstone <name>=<description>
        +humanity/conviction/remove <number>
        +humanity/touchstone/remove <number>

    Switches:
        /conviction - Add a new Conviction (max 3)
        /touchstone - Add a new Touchstone (max = Humanity ÷ 2)
        /conviction/remove - Remove a Conviction by number
        /touchstone/remove - Remove a Touchstone by number

    Examples:
        +humanity
        +humanity/conviction Never harm children
        +humanity/touchstone Sarah=My sister who keeps me grounded
        +humanity/conviction/remove 1
        +humanity/touchstone/remove 0

    Convictions are your personal moral code. Violating them adds Stains.
    Touchstones are mortals who anchor your Humanity. Losing them risks
    Humanity loss.
    """

    key = "+humanity"
    aliases = ["humanity"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        # Check if character is a vampire
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("This command is only available to vampires.")
            return

        # Handle /conviction switch
        if "conviction" in self.switches:
            if "remove" in self.switches:
                # Remove conviction
                if not self.args.strip():
                    caller.msg("Usage: +humanity/conviction/remove <number>")
                    return
                try:
                    index = int(self.args.strip()) - 1  # Convert to 0-indexed
                    result = remove_conviction(caller, index)
                    caller.msg(result['message'])
                except ValueError:
                    caller.msg("Please provide a valid conviction number.")
            else:
                # Add conviction
                if not self.args.strip():
                    caller.msg("Usage: +humanity/conviction <conviction text>")
                    caller.msg("Example: +humanity/conviction Never harm children")
                    return
                result = add_conviction(caller, self.args.strip())
                caller.msg(result['message'])
            return

        # Handle /touchstone switch
        if "touchstone" in self.switches:
            if "remove" in self.switches:
                # Remove touchstone
                if not self.args.strip():
                    caller.msg("Usage: +humanity/touchstone/remove <number>")
                    return
                try:
                    index = int(self.args.strip()) - 1  # Convert to 0-indexed
                    result = remove_touchstone(caller, index)
                    caller.msg(result['message'])
                except ValueError:
                    caller.msg("Please provide a valid touchstone number.")
            else:
                # Add touchstone
                if "=" not in self.args:
                    caller.msg("Usage: +humanity/touchstone <name>=<description>")
                    caller.msg("Example: +humanity/touchstone Sarah=My sister who keeps me grounded")
                    return
                name, description = self.args.split("=", 1)
                result = add_touchstone(caller, name.strip(), description.strip())
                caller.msg(result['message'])
            return

        # No switches - display Humanity status
        self._display_humanity(caller)

    def _display_humanity(self, character):
        """Display full Humanity status."""
        status = get_humanity_status(character)

        lines = []
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")
        lines.append(f"{VAMPIRE_GOLD}  HUMANITY & CONSCIENCE{RESET}")
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}\n")

        # Humanity rating
        humanity = status['humanity']
        humanity_dots = "●" * humanity + "○" * (10 - humanity)
        lines.append(f"  {VAMPIRE_GOLD}Humanity:{RESET} {humanity_dots} ({humanity}/10)")

        # Stains
        stains = status['stains']
        if stains > 0:
            stain_dots = "✗" * stains + "○" * (10 - stains)
            lines.append(f"  {BLOOD_RED}Stains:{RESET}   {stain_dots} ({stains}/10)")
            if stains >= 5:
                lines.append(f"  {BLOOD_RED}>>> You should perform a Remorse roll soon! (+remorse){RESET}")
        else:
            lines.append(f"  {SHADOW_GREY}Stains:   ○○○○○○○○○○ (0/10){RESET}")

        # Convictions
        lines.append(f"\n  {VAMPIRE_GOLD}Convictions:{RESET} (max 3)")
        convictions = status['convictions']
        if convictions:
            for i, conviction in enumerate(convictions, 1):
                lines.append(f"    {i}. {conviction}")
        else:
            lines.append(f"    {SHADOW_GREY}None set. Use +humanity/conviction to add one.{RESET}")

        # Touchstones
        max_touchstones = status['max_touchstones']
        lines.append(f"\n  {VAMPIRE_GOLD}Touchstones:{RESET} (max {max_touchstones})")
        touchstones = status['touchstones']
        if touchstones:
            for i, ts in enumerate(touchstones, 1):
                lines.append(f"    {i}. {ts['name']} - {ts['description']}")
        else:
            lines.append(f"    {SHADOW_GREY}None set. Use +humanity/touchstone to add one.{RESET}")

        lines.append(f"\n{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")
        lines.append(f"  Use {VAMPIRE_GOLD}+help humanity{RESET} for more information.")
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")

        character.msg("\n".join(lines))


class CmdStain(Command):
    """
    Add Stains to yourself or others.

    Usage:
        +stain [<count>]
        +stain <target>=<count>

    Examples:
        +stain              (add 1 Stain to yourself)
        +stain 2            (add 2 Stains to yourself)
        +stain Vampire=3    (add 3 Stains to target - ST only)

    Stains represent moral transgressions and Humanity degradation.
    When you accumulate Stains, you must eventually perform a Remorse
    roll (+remorse) to determine if you lose Humanity.

    Common sources of Stains:
    - Violating Chronicle Tenets (1-3 Stains depending on severity)
    - Violating personal Convictions (1-2 Stains)
    - Messy Criticals during feeding or violence (1 Stain)
    """

    key = "+stain"
    aliases = ["stain"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        # Check if character is a vampire
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("This command is only available to vampires.")
            return

        # Parse arguments
        if "=" in self.args:
            # Targeting someone else (ST command)
            target_name, count_str = self.args.split("=", 1)
            target = caller.search(target_name.strip())
            if not target:
                return
            # Could add permission check here for ST-only
        else:
            # Targeting self
            target = caller
            count_str = self.args.strip() if self.args.strip() else "1"

        # Parse count
        try:
            count = int(count_str)
            if count < 1:
                caller.msg("Stain count must be at least 1.")
                return
        except ValueError:
            caller.msg(f"Invalid stain count: {count_str}")
            return

        # Add stains
        result = add_stain(target, count)

        # Message to caller
        if target == caller:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")
        else:
            caller.msg(f"You add {count} Stain(s) to {target.name}.")
            target.msg(f"{BLOOD_RED}{result['message']}{RESET}")


class CmdRemorse(Command):
    """
    Perform a Remorse roll to resist Humanity loss.

    Usage:
        +remorse

    Mechanics:
    - Roll a dice pool equal to your current Humanity rating
    - If you get more successes than your current Stains, you keep your Humanity
    - If you get equal or fewer successes, you lose 1 Humanity
    - Either way, all Stains are cleared after the roll

    This roll is typically performed at the end of a game session when you
    have accumulated Stains from moral transgressions during play.

    Example:
        You have Humanity 6 and 4 Stains.
        You roll 6 dice and get 5 successes.
        Since 5 > 4, you maintain Humanity and clear all Stains.

        If you had rolled only 3 successes (3 < 4), you would lose 1 Humanity
        (dropping to 5) and still clear all Stains.
    """

    key = "+remorse"
    aliases = ["remorse"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        # Check if character is a vampire
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("This command is only available to vampires.")
            return

        # Check if character has Stains
        stains = get_stains(caller)
        if stains == 0:
            caller.msg("You have no Stains. No Remorse roll is needed.")
            return

        # Perform remorse roll
        result = remorse_roll(caller)

        # Display roll result
        lines = []
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")
        lines.append(f"{VAMPIRE_GOLD}  REMORSE ROLL{RESET}")
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}\n")

        humanity = result['old_humanity']
        lines.append(f"  You have {VAMPIRE_GOLD}Humanity {humanity}{RESET} and {BLOOD_RED}{result['stains_cleared']} Stains{RESET}.")
        lines.append(f"  Rolling {humanity} dice... You need more than {result['stains_cleared']} successes to keep your Humanity.\n")

        if result['roll_result']:
            # Format dice results
            dice_display = format_dice_result(result['roll_result'], caller.name)
            lines.append(dice_display)
            lines.append("")

        # Outcome
        if result['humanity_lost']:
            lines.append(f"  {BLOOD_RED}FAILURE:{RESET} You lose 1 Humanity (now {result['new_humanity']}).")
            lines.append(f"  {BLOOD_RED}The Beast grows stronger...{RESET}")
        else:
            lines.append(f"  {VAMPIRE_GOLD}SUCCESS:{RESET} You maintain your Humanity at {result['new_humanity']}.")
            lines.append(f"  {VAMPIRE_GOLD}Your conscience remains intact.{RESET}")

        lines.append(f"\n  All Stains have been cleared.")
        lines.append(f"\n{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")

        caller.msg("\n".join(lines))


class CmdFrenzy(default_cmds.MuxCommand):
    """
    Check frenzy status or attempt to resist frenzy.

    Usage:
        +frenzy
        +frenzy/resist <difficulty>
        +frenzy/check <type>

    Switches:
        /resist - Roll to resist frenzy (Willpower + Composure vs Difficulty)
        /check  - Check frenzy risk for a trigger type (hunger, fury, terror)

    Examples:
        +frenzy
        +frenzy/resist 4
        +frenzy/check hunger
        +frenzy/check fury

    Frenzy Types:
        Hunger - Triggered by blood scent, Hunger 5, failed Rouse checks
        Fury   - Triggered by provocation, humiliation, attacks
        Terror - Triggered by fire, sunlight, True Faith

    When you fail to resist frenzy, the Beast takes over and you lose control.
    Brujah have +2 difficulty to resist fury frenzy due to their clan bane.
    """

    key = "+frenzy"
    aliases = ["frenzy"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        # Check if character is a vampire
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("This command is only available to vampires.")
            return

        # Handle /resist switch
        if "resist" in self.switches:
            if not self.args.strip():
                caller.msg("Usage: +frenzy/resist <difficulty>")
                caller.msg("Example: +frenzy/resist 3")
                return

            try:
                difficulty = int(self.args.strip())
            except ValueError:
                caller.msg(f"Invalid difficulty: {self.args.strip()}")
                return

            # Perform resistance roll
            result = resist_frenzy(caller, difficulty)

            # Display result
            lines = []
            lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}")
            lines.append(f"{BLOOD_RED}  FRENZY RESISTANCE{RESET}")
            lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}\n")

            # Show dice results
            if result['roll_result']:
                dice_display = format_dice_result(result['roll_result'], caller.name)
                lines.append(dice_display)
                lines.append("")

            # Outcome
            if result['success']:
                lines.append(f"  {VAMPIRE_GOLD}SUCCESS:{RESET} You resist the frenzy!")
                if result['roll_result'] and result['roll_result'].is_messy:
                    lines.append(f"  {BLOOD_RED}(Messy Critical - you may have revealed your vampiric nature){RESET}")
            else:
                lines.append(f"  {BLOOD_RED}FAILURE:{RESET} The Beast takes over!")
                if result['roll_result'] and result['roll_result'].is_bestial:
                    lines.append(f"  {BLOOD_RED}(Bestial Failure - your frenzy is particularly savage!){RESET}")

            lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
            caller.msg("\n".join(lines))
            return

        # Handle /check switch
        if "check" in self.switches:
            if not self.args.strip():
                caller.msg("Usage: +frenzy/check <type>")
                caller.msg("Types: hunger, fury, terror")
                return

            trigger_type = self.args.strip().lower()
            if trigger_type not in ['hunger', 'fury', 'terror']:
                caller.msg(f"Unknown trigger type: {trigger_type}")
                caller.msg("Valid types: hunger, fury, terror")
                return

            # Check frenzy risk
            risk = check_frenzy_risk(caller, trigger_type)

            # Display risk assessment
            lines = []
            lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}")
            lines.append(f"{BLOOD_RED}  FRENZY RISK: {trigger_type.upper()}{RESET}")
            lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}\n")
            lines.append(f"  {risk['message']}")
            lines.append(f"\n  {VAMPIRE_GOLD}Difficulty to resist:{RESET} {risk['difficulty']}")
            lines.append(f"    Base difficulty: {risk['base_difficulty']}")
            lines.append(f"    Hunger modifier: +{risk['hunger_modifier']}")
            lines.append(f"\n  Use {VAMPIRE_GOLD}+frenzy/resist {risk['difficulty']}{RESET} to attempt resistance.")
            lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
            caller.msg("\n".join(lines))
            return

        # No switches - show frenzy status
        from commands.v5.utils.blood_utils import get_hunger
        humanity = get_humanity(caller)
        hunger = get_hunger(caller)

        lines = []
        lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}")
        lines.append(f"{BLOOD_RED}  FRENZY STATUS{RESET}")
        lines.append(f"{BLOOD_RED}{BOX_H * 78}{RESET}\n")
        lines.append(f"  {VAMPIRE_GOLD}Humanity:{RESET} {humanity}")
        lines.append(f"  {BLOOD_RED}Hunger:{RESET} {hunger}")

        if hunger >= 4:
            lines.append(f"\n  {BLOOD_RED}WARNING:{RESET} High Hunger increases frenzy risk!")

        lines.append(f"\n  Use {VAMPIRE_GOLD}+frenzy/check <type>{RESET} to assess frenzy risk.")
        lines.append(f"  Use {VAMPIRE_GOLD}+frenzy/resist <difficulty>{RESET} to resist frenzy.")
        lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
        caller.msg("\n".join(lines))
