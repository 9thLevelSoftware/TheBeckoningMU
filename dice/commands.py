"""
User-facing Dice Commands for V5 System

Provides Evennia MuxCommands for rolling dice, using discipline powers,
performing Rouse checks, and viewing dice mechanics.
"""

import time

from evennia import Command, default_cmds
from evennia.utils.utils import inherits_from

from . import dice_roller, rouse_checker

# A Willpower re-roll is made right after the roll it improves (QR p.3):
# the last roll can be re-rolled for this many seconds.
LAST_ROLL_WINDOW = 300

WILLPOWER_USAGE = "Usage: roll/willpower <die> [<die> <die>]  (the values shown on your regular dice)"


def _is_staff(caller) -> bool:
    """True if the caller (or the account puppeting it) has Builder permission."""
    return caller.locks.check_lockstring(caller, "staff:perm(Builder)")


def remember_roll(caller, result, label: str, secret: bool = False, power=None, effect_ids=None, uncontested=False):
    """Store a roll on caller.ndb.last_roll so `roll/willpower` can re-roll its dice.

    Shape: {"result": RollResult, "label": str, "secret": bool, "rerolled": bool,
    "time": float, "power": power name or None, "effect_ids": [...],
    "uncontested": bool}. A power's entry lets a re-roll re-resolve it.
    """
    caller.ndb.last_roll = {
        "result": result,
        "label": label,
        "secret": secret,
        "rerolled": False,
        "time": time.time(),
        "power": power,
        "effect_ids": list(effect_ids or []),
        "uncontested": uncontested,
    }


def forget_roll(caller) -> None:
    """Clear the stored last roll (another action happened since)."""
    caller.ndb.last_roll = None


class CmdRoll(default_cmds.MuxCommand):
    """
    Roll a V5 dice pool.

    Usage:
      roll <pool> [vs <difficulty>]
      roll/secret <pool> [vs <difficulty>]
      roll/willpower <die> [<die> <die>]

    Staff only:
      roll <pool> <hunger> [vs <difficulty>]
      roll/mortal <pool> [vs <difficulty>]

    Examples:
      roll 7                  roll 7 dice with your Hunger
      roll 5 vs 3             5 dice, 3 successes needed
      roll/secret 6 vs 2      only you see the result
      roll/willpower 2 3 10   re-roll your last roll's regular dice showing 2, 3 and 10

    Your Hunger dice replace regular dice: at Hunger 2, two of the dice are
    Hunger dice (all of them if the pool is smaller). Each die showing 6-10
    is a success, and each pair of 10s counts as four successes. A success
    with a pair of 10s is a critical; if a Hunger die shows one of the 10s
    it is a messy critical, and the Storyteller decides the complication. A
    failed roll with a Hunger die showing 1 is a bestial failure; a failed
    roll with no successes is a total failure, and a near miss may be turned
    into a win at a cost by the Storyteller.

    If you readied a bloodsurge, its dice are added to this roll and its
    Rouse check is made with it: the roll uses your Hunger from before, and
    a failed check raises Hunger afterwards.

    Willpower: once per roll, within five minutes of it, mark 1 Superficial
    Willpower damage to re-roll up to three of the last roll's regular
    (non-Hunger) dice, chosen by the value they show. Hunger dice can't be
    re-rolled. A re-rolled power roll re-resolves the power.

    Staff can set the Hunger dice (roll <pool> <hunger>) or roll with none
    (/mortal) for NPCs; those rolls don't use a Blood Surge.
    """

    key = "roll"
    aliases = ["r"]
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        """Execute the roll command."""
        caller = self.caller
        if not inherits_from(caller, "typeclasses.characters.Character"):
            caller.msg("|rYou must be in character to roll dice.|n")
            return

        if "willpower" in self.switches:
            self._willpower_reroll()
            return

        args = self.args.strip()
        if not args:
            caller.msg("Usage: roll <pool> [vs <difficulty>]")
            return

        try:
            pool_size, hunger_arg, difficulty = self._parse_args(args)
        except ValueError as e:
            caller.msg(f"|rError:|n {e}")
            return

        mortal = "mortal" in self.switches
        staff_override = hunger_arg is not None or mortal
        if staff_override and not _is_staff(caller):
            caller.msg(
                "|rOnly staff can set the Hunger dice.|n Your roll uses your own Hunger: roll <pool> [vs <difficulty>]"
            )
            return
        if mortal:
            hunger = 0
        elif hunger_arg is not None:
            hunger = hunger_arg
        else:
            hunger = caller.hunger

        from commands.v5.utils import blood_utils

        surge_dice = 0
        surge_note = ""
        surge = None if staff_override else blood_utils.get_blood_surge(caller)
        if surge:
            if caller.hunger >= rouse_checker.MAX_HUNGER:
                surge_note = "|xYour Blood Surge can't be used at Hunger 5; it stays ready.|n"
            else:
                surge_dice = surge.get("bonus", 0)

        total_pool = pool_size + surge_dice
        if total_pool > dice_roller.MAX_POOL:
            caller.msg(
                f"|rRoll error:|n Pool size cannot exceed {dice_roller.MAX_POOL} dice: {pool_size} plus "
                f"{surge_dice} Blood Surge dice. The surge is kept for your next roll."
            )
            return

        try:
            result = dice_roller.roll_v5_pool(total_pool, hunger, difficulty)
        except ValueError as e:
            caller.msg(f"|rRoll error:|n {e}")
            return

        rouse_result = None
        if surge_dice:
            blood_utils.consume_blood_surge(caller)
            rouse_result = rouse_checker.perform_rouse_check(caller, reason="Blood Surge")

        is_secret = "secret" in self.switches
        remember_roll(caller, result, f"{total_pool} dice", secret=is_secret)

        message = self._format_roll_message(result, total_pool, difficulty, surge_dice)
        if rouse_result is not None:
            message += "\n\n" + "\n".join(rouse_checker.format_rouse_lines(rouse_result))
        if surge_note:
            message += "\n" + surge_note
        if result.regular_dice:
            message += "\n|x(roll/willpower <dice> re-rolls up to 3 regular dice for 1 Willpower.)|n"

        if is_secret or not caller.location:
            caller.msg("|y[Secret Roll]|n\n" + message if is_secret else message)
        else:
            caller.location.msg_contents(f"|c{caller.name}|n rolls dice...\n{message}", exclude=[caller])
            caller.msg(message)

    def _parse_args(self, args):
        """
        Parse roll arguments into pool, hunger and difficulty.

        Returns:
            Tuple of (pool_size, hunger or None if not given, difficulty)

        Raises:
            ValueError: If arguments are invalid
        """
        if " vs " in args.lower():
            pool_args, diff_str = args.lower().split(" vs ", 1)
            try:
                difficulty = int(diff_str.strip())
            except ValueError:
                raise ValueError("Difficulty must be a number") from None
        else:
            pool_args = args
            difficulty = 0

        parts = pool_args.split()
        if len(parts) < 1:
            raise ValueError("Must specify at least pool size")
        if len(parts) > 2:
            raise ValueError("Usage: roll <pool> [vs <difficulty>]")

        try:
            pool_size = int(parts[0])
        except ValueError:
            raise ValueError("Pool size must be a number") from None

        hunger = None
        if len(parts) == 2:
            try:
                hunger = int(parts[1])
            except ValueError:
                raise ValueError("Hunger must be a number") from None
            if hunger < 0 or hunger > 5:
                raise ValueError("Hunger must be between 0 and 5")

        if pool_size < 1:
            raise ValueError("Pool size must be at least 1")
        if pool_size > dice_roller.MAX_POOL:
            raise ValueError(f"Pool size cannot exceed {dice_roller.MAX_POOL} dice")
        if not dice_roller.MIN_DIFFICULTY <= difficulty <= dice_roller.MAX_DIFFICULTY:
            raise ValueError(
                f"Difficulty must be between {dice_roller.MIN_DIFFICULTY} and {dice_roller.MAX_DIFFICULTY}"
            )

        return pool_size, hunger, difficulty

    def _format_roll_message(self, result, pool_size, difficulty, surge_dice=0):
        """Format a roll result for display."""
        lines = ["|c=== Dice Roll ===|n"]
        pool_line = f"Pool: {pool_size} dice ({len(result.hunger_dice)} Hunger)"
        if surge_dice:
            pool_line += f", including |y+{surge_dice}|n from Blood Surge"
        lines.append(pool_line)
        if difficulty > 0:
            lines.append(f"Difficulty: {difficulty}")
        lines.append("")
        lines.append(result.format_result(show_details=True))
        return "\n".join(lines)

    def _willpower_reroll(self):
        """roll/willpower <die> [<die> <die>]: re-roll chosen regular dice of the last roll."""
        caller = self.caller
        last = caller.ndb.last_roll
        if not last:
            caller.msg("|rYou have no roll to re-roll.|n Roll first, then use roll/willpower <dice>.")
            return
        if time.time() - last.get("time", 0) > LAST_ROLL_WINDOW:
            forget_roll(caller)
            caller.msg("|rYour last roll is too old to re-roll.|n Spend Willpower right after the roll.")
            return
        if last["rerolled"]:
            caller.msg("|rYou have already spent Willpower on that roll.|n")
            return

        try:
            values = [int(value) for value in self.args.replace(",", " ").split()]
        except ValueError:
            caller.msg(WILLPOWER_USAGE)
            return
        if not values:
            caller.msg(WILLPOWER_USAGE)
            return

        if caller.current_willpower < 1:
            caller.msg("|rYou have no Willpower left to spend.|n")
            return

        try:
            result, _ = dice_roller.apply_willpower_reroll(last["result"], values)
        except ValueError as e:
            caller.msg(f"|rError:|n {e}")
            return

        marks = caller.damage["willpower"]
        caller.set_damage("willpower", superficial=marks["superficial"] + 1)
        was_success = last["result"].is_success
        last.update(result=result, rerolled=True)

        dice_text = ", ".join(str(value) for value in values)
        lines = [
            f"|c=== Willpower Re-roll ({last['label']}) ===|n",
            f"Re-rolled regular dice showing: {dice_text}. 1 Superficial Willpower damage marked "
            f"(Willpower {caller.current_willpower}/{caller.willpower_max}).",
            "",
            result.format_result(show_details=True),
        ]
        if last.get("power") and result.is_success != was_success:
            lines.append("")
            lines.append(self._re_resolve_power(last, result.is_success))
        message = "\n".join(lines)
        if last["secret"] or not caller.location:
            caller.msg(message)
        else:
            caller.location.msg_contents(
                f"|c{caller.name}|n spends Willpower to re-roll...\n{message}", exclude=[caller]
            )
            caller.msg(message)

    def _re_resolve_power(self, last, now_success):
        """Start or end a re-rolled power's tracked effect; return a display line."""
        from commands.v5.utils import discipline_utils
        from world.v5_data import find_power

        caller = self.caller
        power = find_power(last["power"])
        if now_success:
            if last.get("uncontested") or not discipline_utils.power_effect_applies(power, {"success": True}):
                return f"|g{power['name']} now succeeds.|n"
            last["effect_ids"] = discipline_utils.start_power_effect(caller, power)
            return f"|g{power['name']} now succeeds:|n its effect starts. Use +effects to view."
        if last.get("effect_ids"):
            discipline_utils.stop_power_effect(caller, last["effect_ids"])
            last["effect_ids"] = []
            return f"|r{power['name']} now fails:|n its effect ends."
        return f"|r{power['name']} now fails.|n"


class CmdPower(default_cmds.MuxCommand):
    """
    Use a discipline power.

    Usage:
      power <power name> [vs <difficulty>]
      power <power name> = <target>

    Staff only:
      power/norouse <power name> ...

    Examples:
      power Scry the Soul
      power Scry the Soul vs 3
      power Dread Gaze = Bob
      +power presence/dread gaze

    You must know the power and have its discipline (and any amalgam
    discipline) at the power's level. The power's dice pool comes from your
    traits, plus the Blood Potency power bonus, a die from a matching
    Intense or Acute resonance, and a readied bloodsurge. You roll with your
    current Hunger; the power's Rouse checks (and the surge's) are rolled
    with the action, and the Hunger they cost is added afterwards. Some
    powers cost two or three Rouse checks; free powers cost none.

    At Hunger 5 you can't use a power that needs a Rouse check: feed first.
    Below Hunger 5 you can start any power. If its failed checks would take
    Hunger past 5, Hunger stops at 5 and you must test for hunger frenzy
    (Difficulty 4); the power still works.

    A contested power (one the target resists) rolls against the target's
    resistance pool when you name a target with = <target>; you need at
    least as many successes as they get (a tie goes to you). Without a
    target the Storyteller adjudicates, and no effect is tracked.

    Powers without a dice roll are used without rolling: you pay their Rouse
    checks and their effect starts.

    `+power <discipline>/<power name>` also works.
    """

    key = "power"
    aliases = ["+power", "+activate", "+use", "discipline", "disc"]
    locks = "cmd:all()"
    help_category = "Disciplines"

    def func(self):
        """Execute the power command."""
        caller = self.caller
        if not inherits_from(caller, "typeclasses.characters.Character"):
            caller.msg("|rYou must be in character to use discipline powers.|n")
            return

        args = (self.lhs or "").strip()
        if not args:
            caller.msg("Usage: power <power name> [vs <difficulty>] [= <target>]")
            return

        difficulty = 0
        has_difficulty = " vs " in args.lower()
        if has_difficulty:
            index = args.lower().index(" vs ")
            power_name, diff_str = args[:index].strip(), args[index + 4 :].strip()
            try:
                difficulty = int(diff_str)
            except ValueError:
                caller.msg("|rDifficulty must be a number.|n")
                return
            if not dice_roller.MIN_DIFFICULTY <= difficulty <= dice_roller.MAX_DIFFICULTY:
                caller.msg(
                    f"|rDifficulty must be between {dice_roller.MIN_DIFFICULTY} and {dice_roller.MAX_DIFFICULTY}.|n"
                )
                return
        else:
            power_name = args

        from world.v5_data import find_power

        discipline_name = None
        power = find_power(power_name)
        if power is None and "/" in power_name:
            # "+power <discipline>/<power name>"
            discipline_name, _, name = power_name.partition("/")
            discipline_name = discipline_name.strip()
            power = find_power(name)
        if power is None:
            caller.msg(f"|rError:|n Discipline power '{power_name}' not found.")
            return

        with_rouse = "norouse" not in self.switches
        if not with_rouse and not _is_staff(caller):
            caller.msg("|rOnly staff can skip a power's Rouse checks.|n")
            return

        if with_rouse and power.get("rouse", 0) > 0 and caller.hunger >= rouse_checker.MAX_HUNGER:
            caller.msg(f"|r{rouse_checker.HUNGER_5_REFUSAL}|n")
            return

        target = None
        if self.rhs:
            if not power.get("opposed_by"):
                caller.msg(f"|rError:|n {power['name']} isn't resisted by a target; leave out = <target>.")
                return
            if has_difficulty:
                caller.msg(
                    "|rError:|n Name a target or a difficulty, not both: against a target the "
                    "difficulty is their successes."
                )
                return
            target = caller.search(self.rhs.strip())
            if not target:
                return
            if not inherits_from(target, "typeclasses.characters.Character"):
                caller.msg(f"|rError:|n {target.key} can't resist a power; name a character.")
                return

        from commands.v5.utils.discipline_utils import activate_discipline_power

        result = activate_discipline_power(
            caller, discipline_name, power["name"], difficulty=difficulty, target=target, with_rouse=with_rouse
        )
        if not result["success"]:
            caller.msg(f"|rError:|n {result['message']}")
            return

        roll = result["roll"]
        if roll:
            caller.msg(roll["message"])
            remember_roll(
                caller,
                roll["roll_result"],
                power["name"],
                power=power["name"],
                effect_ids=result["effect_ids"],
                uncontested=result["uncontested"],
            )
        else:
            forget_roll(caller)
            caller.msg(self._format_unrolled(power, result))

        if result.get("effect_applied"):
            caller.msg(f"|xEffect active ({result['duration']}). Use +effects to view.|n")

        if roll and roll["defense"] is not None:
            self._tell_target(roll)

        if caller.location:
            caller.location.msg_contents(
                self._room_message(power, roll, result), exclude=[obj for obj in (caller, target) if obj]
            )

    def _tell_target(self, roll):
        """Tell the defender what was used on them and how their resistance went."""
        from .discipline_roller import format_defense

        caller = self.caller
        defense = roll["defense"]
        outcome = "It takes hold." if roll["success"] else "You resist it."
        defense["target"].msg(
            f"|c{caller.name}|n uses |w{roll['power_name']}|n on you.\n"
            f"{format_defense(defense)}\n"
            f"{caller.name} gets {roll['roll_result'].total_successes} successes. {outcome}"
        )

    def _room_message(self, power, roll, result):
        name = self.caller.name
        if roll is None:
            return f"|c{name}|n uses |w{power['name']}|n."
        if result["uncontested"]:
            return f"|c{name}|n uses |w{power['name']}|n (uncontested; the Storyteller adjudicates)."
        on_target = f" on {roll['defense']['target'].key}" if roll["defense"] is not None else ""
        if roll["success"]:
            return f"|c{name}|n uses |w{power['name']}|n{on_target}... |gSuccess!|n"
        return f"|c{name}|n attempts |w{power['name']}|n{on_target}... |rFailure.|n"

    @staticmethod
    def _format_unrolled(power, result):
        """Display for a power used without a dice roll."""
        lines = [f"|c=== {power['name']} ===|n", f"|w{power['discipline']} Level {power['level']}|n"]
        if power.get("description"):
            lines.append(f"|x{power['description']}|n")
        lines.append("")
        lines.append("No roll needed.")
        if result["rouse_result"] is not None:
            lines.extend(rouse_checker.format_rouse_lines(result["rouse_result"]))
        elif power.get("rouse", 0) == 0:
            lines.append("Free: no Rouse check.")
        return "\n".join(lines)


class CmdRouse(Command):
    """
    Perform a Rouse check.

    Usage:
      rouse [<reason>]

    Examples:
      rouse
      rouse Blush of Life

    Roll one die: on 6-10 nothing happens, on 1-5 your Hunger rises by 1.
    Rouse when the Storyteller asks (Blush of Life, rising for the night and
    so on). Discipline powers make their own Rouse checks through `power`,
    with the Blood Potency re-roll; a manual check gets no re-roll.

    At Hunger 5 you can't Rouse the Blood.
    """

    key = "rouse"
    locks = "cmd:all()"
    help_category = "Dice"

    def func(self):
        """Execute the rouse command."""
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to perform Rouse checks.|n")
            return

        if self.caller.hunger >= rouse_checker.MAX_HUNGER:
            self.caller.msg(f"|r{rouse_checker.HUNGER_5_REFUSAL}|n")
            return

        reason = self.args.strip() if self.args else "Manual Rouse check"
        result = rouse_checker.perform_rouse_check(self.caller, reason=reason)
        self.caller.msg(result.message)
        if result.refused:
            return

        self.caller.msg(f"\n{rouse_checker.format_hunger_display(self.caller)}")

        if self.caller.location:
            if result.success:
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

        lines.append("|c" + "=" * 60 + "|n")
        lines.append("|c" + " " * 15 + "V5 DICE MECHANICS" + " " * 15 + "|n")
        lines.append("|c" + "=" * 60 + "|n")
        lines.append("")

        # Basic Rules
        lines.append("|w=== Basic Rolling ===|n")
        lines.append("• Each die is a d10 (1-10)")
        lines.append("• |g6-10|n = 1 success")
        lines.append("• Each |ypair of 10s|n = 4 successes (critical)")
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
        lines.append("• A successful roll with a pair of |y10s|n = Critical")
        lines.append("• A pair is 4 successes; a third 10 adds 1 more")
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
        lines.append("• Failed roll with any |r|hHunger die|n showing 1")
        lines.append("• The Beast seizes control during failure")
        lines.append("• Storyteller introduces serious complication")
        lines.append("")

        # Willpower
        lines.append("|w=== Willpower Rerolls ===|n")
        lines.append("• Mark 1 Willpower to re-roll up to 3 regular dice (roll/willpower)")
        lines.append("• Can ONLY reroll |wregular dice|n (not Hunger dice)")
        lines.append("• You choose the dice, a 10 included; once per roll")
        lines.append("")

        lines.append("|c" + "=" * 60 + "|n")

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
        lines.append("• At Hunger 5 you cannot Rouse the Blood")
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
        lines.append("• Each pair of 10s counts as |y|h4 successes|n")
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
        lines.append("• Willpower re-rolls can't change Hunger dice")
        lines.append("• Blood Potency re-rolls Rouse checks for low-level powers")
        lines.append("")

        self.caller.msg("\n".join(lines))
