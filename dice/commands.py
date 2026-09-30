"""
User-facing Dice Commands for V5 System

Provides Evennia MuxCommands for rolling dice, using discipline powers,
performing Rouse checks, and viewing dice mechanics.
"""

from evennia import Command
from evennia import default_cmds
from evennia.utils.utils import inherits_from
from . import dice_roller, discipline_roller, rouse_checker
from .roll_result import RollResult


class CmdRoll(default_cmds.MuxCommand):
    """
    Roll a V5 dice pool with optional Hunger dice.

    Usage:
      roll <pool> [<hunger>] [vs <difficulty>]
      roll/willpower <pool> [<hunger>] [vs <difficulty>]
      roll/secret <pool> [<hunger>] [vs <difficulty>]

    Examples:
      roll 7                      # Roll 7 dice
      roll 5 2 vs 3              # Roll 5 dice with Hunger 2 vs difficulty 3
      roll/willpower 4 3         # Roll with option for Willpower reroll
      roll/secret 6 vs 2         # Secret roll (only show to roller)

    Switches:
      willpower - Offer Willpower reroll on failure (costs 1 Willpower)
      secret    - Only show result to the roller (no room broadcast)

    V5 Dice Rules:
    - Each die is a d10 (1-10)
    - 6-9 = 1 success, 10 = 2 successes
    - Pair of 10s = critical (4 successes total from pair)
    - Hunger dice replace regular dice (marked in red)
    - Success if total successes >= difficulty
    """

    key = "roll"
    aliases = ["r"]
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        """Execute the roll command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to roll dice.|n")
            return

        # Parse arguments
        args = self.args.strip()
        if not args:
            self.caller.msg("Usage: roll <pool> [<hunger>] [vs <difficulty>]")
            return

        try:
            pool_size, hunger, difficulty = self._parse_args(args)
        except ValueError as e:
            self.caller.msg(f"|rError:|n {e}")
            return

        # Validate pool size
        if pool_size < 1:
            self.caller.msg("|rPool size must be at least 1.|n")
            return

        # Check switches
        use_willpower = 'willpower' in self.switches
        is_secret = 'secret' in self.switches

        # Perform the roll
        try:
            result = dice_roller.roll_v5_pool(pool_size, hunger, difficulty)
        except ValueError as e:
            self.caller.msg(f"|rRoll error:|n {e}")
            return

        # Format the output
        message = self._format_roll_message(result, pool_size, hunger, difficulty)

        # Handle Messy Critical - automatically add Stain
        if result.is_messy_critical:
            try:
                from commands.v5.utils import humanity_utils
                stain_result = humanity_utils.add_stain(self.caller, 1)
                message += f"\n\n|r*** MESSY CRITICAL ***|n"
                message += f"\n|yYour Beast influenced your success!|n"
                message += f"\n{stain_result['message']}"
            except (ValueError, AttributeError, KeyError) as e:
                # Don't block the roll if stain addition fails
                message += f"\n\n|r*** MESSY CRITICAL ***|n"
                message += f"\n|yYour Beast influenced your success! (Stain addition failed: {e})|n"

        # Handle Willpower reroll offer
        if use_willpower and not result.is_success:
            willpower = self._get_willpower()
            if willpower and willpower > 0:
                message += "\n\n|yYou may spend 1 Willpower to reroll up to 3 failed dice.|n"
                message += "\n|x(Use 'willpower reroll' to attempt reroll)|n"

        # Send message
        if is_secret:
            self.caller.msg("|y[Secret Roll]|n\n" + message)
        else:
            # Broadcast to room
            self.caller.location.msg_contents(
                f"|c{self.caller.name}|n rolls dice...\n{message}",
                exclude=[self.caller]
            )
            self.caller.msg(message)

    def _parse_args(self, args):
        """
        Parse roll arguments into pool, hunger, and difficulty.

        Args:
            args: Raw argument string

        Returns:
            Tuple of (pool_size, hunger, difficulty)

        Raises:
            ValueError: If arguments are invalid
        """
        # Split on 'vs' to separate difficulty
        if ' vs ' in args.lower():
            pool_args, diff_str = args.lower().split(' vs ', 1)
            try:
                difficulty = int(diff_str.strip())
            except ValueError:
                raise ValueError("Difficulty must be a number")
        else:
            pool_args = args
            difficulty = 0

        # Parse pool and hunger
        parts = pool_args.split()
        if len(parts) < 1:
            raise ValueError("Must specify at least pool size")

        try:
            pool_size = int(parts[0])
        except ValueError:
            raise ValueError("Pool size must be a number")

        hunger = 0
        if len(parts) >= 2:
            try:
                hunger = int(parts[1])
            except ValueError:
                raise ValueError("Hunger must be a number")

        # Validate ranges
        if pool_size < 1:
            raise ValueError("Pool size must be at least 1")
        if hunger < 0 or hunger > 5:
            raise ValueError("Hunger must be between 0 and 5")
        if hunger > pool_size:
            raise ValueError("Hunger cannot exceed pool size")
        if difficulty < 0:
            raise ValueError("Difficulty must be 0 or greater")

        return pool_size, hunger, difficulty

    def _format_roll_message(self, result, pool_size, hunger, difficulty):
        """
        Format roll result for display.

        Args:
            result: RollResult object
            pool_size: Total dice rolled
            hunger: Hunger dice count
            difficulty: Target successes

        Returns:
            Formatted message string
        """
        lines = []

        # Header
        lines.append("|c=== Dice Roll ===|n")
        lines.append(f"Pool: {pool_size} dice (Hunger: {hunger})")
        if difficulty > 0:
            lines.append(f"Difficulty: {difficulty}")
        lines.append("")

        # Use RollResult's built-in formatting
        lines.append(result.format_result(show_details=True))

        return "\n".join(lines)

    def _get_willpower(self):
        """Get character's current Willpower."""
        return getattr(self.caller.db, 'willpower', None)


class CmdRollPower(default_cmds.MuxCommand):
    """
    Roll a discipline power automatically.

    Usage:
      power <power name> [vs <difficulty>]
      power/willpower <power name> [vs <difficulty>]
      power/norouse <power name> [vs <difficulty>]

    Examples:
      power Corrosive Vitae           # Auto-calculate pool, perform Rouse
      power Corrosive Vitae vs 3      # vs difficulty 3
      power/willpower Awe             # With Willpower reroll option
      power/norouse Heightened Senses # Skip Rouse check (free powers)

    Switches:
      willpower - Offer Willpower reroll on failure (costs 1 Willpower)
      norouse   - Skip Rouse check (for Free powers or testing)

    This command automatically:
    - Looks up the discipline power
    - Calculates dice pool from your traits
    - Applies Blood Potency bonuses
    - Performs Rouse check (unless /norouse)
    - Rolls with your current Hunger
    """

    key = "power"
    aliases = ["discipline", "disc"]
    locks = "cmd:all()"
    help_category = "Disciplines"

    def func(self):
        """Execute the power roll command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to use discipline powers.|n")
            return

        # Parse arguments
        args = self.args.strip()
        if not args:
            self.caller.msg("Usage: power <power name> [vs <difficulty>]")
            return

        # Parse power name and difficulty
        if ' vs ' in args.lower():
            power_name, diff_str = args.split(' vs ', 1)
            power_name = power_name.strip()
            try:
                difficulty = int(diff_str.strip())
            except ValueError:
                self.caller.msg("|rDifficulty must be a number.|n")
                return
        else:
            power_name = args
            difficulty = 0

        # Check switches
        with_rouse = 'norouse' not in self.switches
        use_willpower = 'willpower' in self.switches

        # Perform the discipline roll
        try:
            result = discipline_roller.roll_discipline_power(
                character=self.caller,
                power_name=power_name,
                difficulty=difficulty,
                with_rouse=with_rouse
            )
        except (ValueError, AttributeError, KeyError) as e:
            self.caller.msg(f"|rError:|n {e}")
            return

        # Display result (pre-formatted by discipline_roller)
        self.caller.msg(result['message'])

        # Handle Messy Critical - automatically add Stain
        roll_result = result.get('roll_result')
        if roll_result and roll_result.is_messy_critical:
            try:
                from commands.v5.utils import humanity_utils
                stain_result = humanity_utils.add_stain(self.caller, 1)
                self.caller.msg(f"\n|r*** MESSY CRITICAL ***|n")
                self.caller.msg(f"|yYour Beast influenced your power!|n")
                self.caller.msg(f"{stain_result['message']}")
            except (ValueError, AttributeError, KeyError) as e:
                # Don't block the roll if stain addition fails
                self.caller.msg(f"\n|r*** MESSY CRITICAL ***|n")
                self.caller.msg(f"|yYour Beast influenced your power! (Stain addition failed: {e})|n")

        # Handle Willpower reroll offer
        if use_willpower and not result['success']:
            willpower = self._get_willpower()
            if willpower and willpower > 0:
                self.caller.msg("\n|yYou may spend 1 Willpower to reroll up to 3 failed dice.|n")
                self.caller.msg("|x(Use 'willpower reroll' to attempt reroll)|n")

        # Broadcast to room (simplified version)
        if self.caller.location:
            power_display_name = result['power_name']
            if result['success']:
                room_msg = f"|c{self.caller.name}|n activates |w{power_display_name}|n... |gSuccess!|n"
            else:
                room_msg = f"|c{self.caller.name}|n attempts |w{power_display_name}|n... |rFailure.|n"

            self.caller.location.msg_contents(room_msg, exclude=[self.caller])

    def _get_willpower(self):
        """Get character's current Willpower."""
        return getattr(self.caller.db, 'willpower', None)


class CmdRouse(Command):
    """
    Perform a Rouse check.

    Usage:
      rouse [<reason>]

    Examples:
      rouse                    # Basic Rouse check
      rouse Blood Surge        # Rouse with reason

    Rouse checks are made when using vampiric powers, healing damage,
    or performing blood-powered actions. On a failure (1-5), your
    Hunger increases by 1.

    Blood Potency may allow rerolling failed checks for low-level powers.
    """

    key = "rouse"
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        """Execute the rouse command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to perform Rouse checks.|n")
            return

        # Parse reason (optional)
        reason = self.args.strip() if self.args else "Manual Rouse check"

        # Perform the Rouse check
        try:
            result = rouse_checker.perform_rouse_check(
                character=self.caller,
                reason=reason,
                power_level=1  # Default to level 1 for manual checks
            )
        except (ValueError, AttributeError, KeyError) as e:
            self.caller.msg(f"|rError:|n {e}")
            return

        # Display result (pre-formatted by rouse_checker)
        self.caller.msg(result['message'])

        # Display Hunger visual
        hunger_display = rouse_checker.format_hunger_display(self.caller)
        self.caller.msg(f"\n{hunger_display}")

        # Broadcast to room
        if self.caller.location:
            if result['success']:
                room_msg = f"|c{self.caller.name}|n performs a Rouse check... |gSuccess.|n"
            else:
                room_msg = f"|c{self.caller.name}|n performs a Rouse check... |rHunger increases.|n"

            self.caller.location.msg_contents(room_msg, exclude=[self.caller])


class CmdShowDice(Command):
    """
    Display V5 dice mechanics reference.

    Usage:
      showdice
      showdice hunger
      showdice criticals
      showdice bestial

    Shows reference information about V5 dice rolling mechanics,
    including success thresholds, critical wins, Hunger dice,
    and special failure conditions.
    """

    key = "showdice"
    aliases = ["dicestats", "dicehelp"]
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        """Execute the showdice command."""
        topic = self.args.strip().lower() if self.args else "all"

        if topic in ["all", ""]:
            self._show_all()
        elif topic in ["hunger", "hunger dice"]:
            self._show_hunger()
        elif topic in ["critical", "criticals", "crit"]:
            self._show_criticals()
        elif topic in ["bestial", "bestial failure"]:
            self._show_bestial()
        else:
            self.caller.msg(f"|rUnknown topic:|n {topic}")
            self.caller.msg("Available topics: hunger, criticals, bestial")

    def _show_all(self):
        """Show complete dice mechanics reference."""
        lines = []

        lines.append("|c" + "="*60 + "|n")
        lines.append("|c" + " "*15 + "V5 DICE MECHANICS" + " "*15 + "|n")
        lines.append("|c" + "="*60 + "|n")
        lines.append("")

        # Basic Rules
        lines.append("|w=== Basic Rolling ===|n")
        lines.append("• Each die is a d10 (1-10)")
        lines.append("• |g6-9|n = 1 success")
        lines.append("• |y10|n = 2 successes (critical)")
        lines.append("• |x1-5|n = no success (failure)")
        lines.append("• Compare total successes to difficulty")
        lines.append("")

        # Hunger Dice
        lines.append("|w=== Hunger Dice ===|n")
        lines.append("• |rHunger dice|n replace regular dice (not added)")
        lines.append("• Hunger = your current Hunger level (0-5)")
        lines.append("• Hunger dice count successes normally")
        lines.append("• |r|hHunger 1s|n can cause Bestial Failures")
        lines.append("• |r|hHunger 10s|n can cause Messy Criticals")
        lines.append("")

        # Criticals
        lines.append("|w=== Critical Wins ===|n")
        lines.append("• Pair of |y10s|n = Critical Success")
        lines.append("• Each pair adds 4 total successes (2+2)")
        lines.append("• May grant additional benefits (Storyteller discretion)")
        lines.append("")

        # Messy Criticals
        lines.append("|w=== Messy Criticals ===|n")
        lines.append("• Critical win with at least one |r|hHunger 10|n")
        lines.append("• You succeed dramatically, but...")
        lines.append("• Your Beast influences the outcome")
        lines.append("• Storyteller introduces vampiric complication")
        lines.append("")

        # Bestial Failures
        lines.append("|w=== Bestial Failures ===|n")
        lines.append("• Failed roll with |r|honly Hunger dice|n showing 1s")
        lines.append("• The Beast seizes control during failure")
        lines.append("• Storyteller introduces serious complication")
        lines.append("")

        # Willpower
        lines.append("|w=== Willpower Rerolls ===|n")
        lines.append("• Spend 1 Willpower to reroll up to 3 failed dice")
        lines.append("• Can ONLY reroll |wregular dice|n (not Hunger dice)")
        lines.append("• Each die can only be rerolled once")
        lines.append("")

        lines.append("|c" + "="*60 + "|n")

        self.caller.msg("\n".join(lines))

    def _show_hunger(self):
        """Show Hunger dice mechanics."""
        lines = []

        lines.append("|c=== Hunger Dice ===|n")
        lines.append("")
        lines.append("|rHunger dice|n represent your vampiric nature bleeding through.")
        lines.append("")
        lines.append("|wBasic Rules:|n")
        lines.append("• Hunger dice |rreplace|n regular dice in your pool")
        lines.append("• Number of Hunger dice = your current Hunger level")
        lines.append("• Hunger dice count successes the same as regular dice")
        lines.append("• Hunger dice are shown in |rred|n in roll results")
        lines.append("")
        lines.append("|wSpecial Effects:|n")
        lines.append("• |r|h1|n on a Hunger die can cause |r|hBestial Failure|n")
        lines.append("• |r|h10|n on a Hunger die can cause |y|hMessy Critical|n")
        lines.append("")
        lines.append("|wManaging Hunger:|n")
        lines.append("• Hunger increases when you fail Rouse checks")
        lines.append("• Hunger decreases when you feed on humans")
        lines.append("• Maximum Hunger is 5 (you cannot use most powers)")
        lines.append("")

        self.caller.msg("\n".join(lines))

    def _show_criticals(self):
        """Show critical mechanics."""
        lines = []

        lines.append("|c=== Critical Wins ===|n")
        lines.append("")
        lines.append("A |y|hCritical Win|n occurs when you roll a pair of 10s.")
        lines.append("")
        lines.append("|wEffects:|n")
        lines.append("• Each pair of 10s counts as |y|h4 successes|n (not just 4)")
        lines.append("• Storyteller may grant additional benefits")
        lines.append("• Exceptional success, dramatic effect")
        lines.append("")
        lines.append("|c=== Messy Criticals ===|n")
        lines.append("")
        lines.append("A |y|hMessy Critical|n is a critical that includes")
        lines.append("at least one |r|h10 on a Hunger die|n.")
        lines.append("")
        lines.append("|wEffects:|n")
        lines.append("• You succeed spectacularly (full critical successes)")
        lines.append("• BUT your Beast influences the outcome")
        lines.append("• Storyteller introduces vampiric complication:")
        lines.append("  - Excessive violence or gore")
        lines.append("  - Witnesses see something inhuman")
        lines.append("  - You gain Stains on your Humanity")
        lines.append("  - Masquerade breach or attention")
        lines.append("")

        self.caller.msg("\n".join(lines))

    def _show_bestial(self):
        """Show Bestial Failure mechanics."""
        lines = []

        lines.append("|c=== Bestial Failures ===|n")
        lines.append("")
        lines.append("A |r|hBestial Failure|n occurs when:")
        lines.append("1. Your roll fails (doesn't meet difficulty)")
        lines.append("2. At least one |r|hHunger die shows a 1|n")
        lines.append("3. |wNO regular dice|n show 1s")
        lines.append("")
        lines.append("|wEffects:|n")
        lines.append("• You fail catastrophically")
        lines.append("• The Beast seizes control")
        lines.append("• Storyteller introduces serious complication:")
        lines.append("  - Lose control (possible frenzy)")
        lines.append("  - Hurt allies or innocents")
        lines.append("  - Reveal vampiric nature")
        lines.append("  - Compulsion activates")
        lines.append("")
        lines.append("|wPrevention:|n")
        lines.append("• Keep Hunger low by feeding regularly")
        lines.append("• Use Willpower rerolls carefully")
        lines.append("• High Blood Potency allows rerolling Rouse checks")
        lines.append("")

        self.caller.msg("\n".join(lines))
