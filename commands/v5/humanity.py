"""
V5 Humanity System Commands

Commands for managing Humanity, Convictions, Touchstones, Stains, Remorse, and Frenzy.
"""

from evennia import default_cmds
from evennia.commands.command import Command

from commands.v5.utils.display_utils import (
    BLOOD_RED,
    BOX_BL,
    BOX_BR,
    BOX_H,
    BOX_TL,
    BOX_TR,
    BOX_V,
    RESET,
    SHADOW_GREY,
    VAMPIRE_GOLD,
)
from commands.v5.utils.humanity_utils import (
    add_conviction,
    add_stain,
    add_touchstone,
    frenzy_pool,
    frenzy_provocations,
    get_humanity_status,
    get_stains,
    pending_frenzy_test,
    remorse_roll,
    remove_conviction,
    remove_touchstone,
    resist_frenzy,
)
from dice.commands import _is_staff
from dice.dice_roller import MAX_DIFFICULTY


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
        /touchstone - Add a new Touchstone, tied to a Conviction
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
        if not caller.attributes.has("vampire"):
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
            room = 10 - humanity
            stain_dots = "✗" * stains + "○" * max(0, room - stains)
            lines.append(f"  {BLOOD_RED}Stains:{RESET}   {stain_dots} ({stains}/{room})")
            lines.append(f"  {BLOOD_RED}>>> Make a Remorse test at the end of the session (+remorse).{RESET}")
        else:
            lines.append(f"  {SHADOW_GREY}Stains:   none ({10 - humanity} unmarked boxes){RESET}")

        # Convictions
        lines.append(f"\n  {VAMPIRE_GOLD}Convictions:{RESET} (max 3)")
        convictions = status['convictions']
        if convictions:
            for i, conviction in enumerate(convictions, 1):
                lines.append(f"    {i}. {conviction}")
        else:
            lines.append(f"    {SHADOW_GREY}None set. Use +humanity/conviction to add one.{RESET}")

        # Touchstones
        lines.append(f"\n  {VAMPIRE_GOLD}Touchstones:{RESET}")
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


class CmdStain(default_cmds.MuxCommand):
    """
    Mark Stains on yourself, or (staff) on another character.

    Usage:
        +stain [<count>]
        +stain <target>=<count>     (staff only)

    Examples:
        +stain              (add 1 Stain to yourself)
        +stain 2            (add 2 Stains to yourself)
        +stain Vampire=3    (staff: add 3 Stains to a character)

    Stains come from breaking Chronicle Tenets and your Convictions (QR p.3).
    They fill the unmarked boxes of your Humanity tracker (10 - Humanity).
    A Stain that would overfill the tracker becomes one Aggravated Willpower
    damage instead. At the end of the session make a Remorse test (+remorse).

    Only staff can mark Stains on someone else.
    """

    key = "+stain"
    aliases = ["stain"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not caller.attributes.has("vampire"):
            caller.msg("This command is only available to vampires.")
            return

        if self.rhs is not None:
            if not _is_staff(caller):
                caller.msg("|rOnly staff can mark Stains on another character.|n")
                return
            target = caller.search(self.lhs.strip())
            if not target:
                return
            if not target.attributes.has("vampire"):
                caller.msg(f"{target.key} has no Humanity tracker.")
                return
            count_str = self.rhs.strip() or "1"
        else:
            target = caller
            count_str = self.args.strip() or "1"

        try:
            count = int(count_str)
        except ValueError:
            caller.msg(f"Invalid stain count: {count_str}")
            return
        if count < 1:
            caller.msg("Stain count must be at least 1.")
            return

        result = add_stain(target, count)

        if target == caller:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")
        else:
            caller.msg(f"You add {count} Stain(s) to {target.name}.")
            target.msg(f"{BLOOD_RED}{result['message']}{RESET}")


class CmdRemorse(Command):
    """
    Make your end-of-session Remorse test.

    Usage:
        +remorse

    Roll one die for each unmarked box on your Humanity tracker: 10 minus
    your Humanity minus your Stains, with a minimum of one die (QR p.3).
    Any success keeps your Humanity; no successes loses 1 Humanity. Either
    way all your Stains are cleared. Remorse uses no Hunger dice.

    Example:
        Humanity 7 with 2 Stains: 10 - 7 - 2 = 1 die. A 6 or higher keeps
        your Humanity at 7.
    """

    key = "+remorse"
    aliases = ["remorse"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not caller.attributes.has("vampire"):
            caller.msg("This command is only available to vampires.")
            return

        stains = get_stains(caller)
        if stains == 0:
            caller.msg("You have no Stains. No Remorse roll is needed.")
            return

        from dice.commands import forget_roll

        forget_roll(caller)  # a Willpower re-roll can't reach back past this roll
        result = remorse_roll(caller)

        lines = []
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")
        lines.append(f"{VAMPIRE_GOLD}  REMORSE ROLL{RESET}")
        lines.append(f"{VAMPIRE_GOLD}{BOX_H * 78}{RESET}\n")

        humanity = result['old_humanity']
        pool = result['pool']
        lines.append(
            f"  You have {VAMPIRE_GOLD}Humanity {humanity}{RESET} and "
            f"{BLOOD_RED}{result['stains_cleared']} Stains{RESET}."
        )
        lines.append(
            f"  Rolling {pool} {'die' if pool == 1 else 'dice'} (your unmarked Humanity boxes): "
            "any success keeps your Humanity.\n"
        )
        if result['roll_result']:
            lines.append(result['roll_result'].format_result(show_details=True))
            lines.append("")

        if result['humanity_lost']:
            lines.append(f"  {BLOOD_RED}FAILURE:{RESET} You lose 1 Humanity (now {result['new_humanity']}).")
        else:
            lines.append(f"  {VAMPIRE_GOLD}SUCCESS:{RESET} You keep your Humanity at {result['new_humanity']}.")

        lines.append("\n  All Stains have been cleared.")
        lines.append(f"\n{VAMPIRE_GOLD}{BOX_H * 78}{RESET}")

        caller.msg("\n".join(lines))


class CmdFrenzy(default_cmds.MuxCommand):
    """
    Test to resist frenzy, or see what provokes it.

    Usage:
        +frenzy
        +frenzy/resist <difficulty> [<type>]
        +frenzy/check <type>
        +frenzy/pending

    Switches:
        /resist  - Roll to resist frenzy at the Storyteller's difficulty.
                   <type> is fury, hunger or terror (it matters for clan banes).
        /check   - List the book's provocations and difficulties for a type.
        /pending - Roll a hunger frenzy test you owe (see below).

    Examples:
        +frenzy/resist 3 fury
        +frenzy/check terror
        +frenzy/pending

    The frenzy test (QR p.4) rolls your current Willpower + Humanity / 3
    (rounded down) against the provocation's difficulty (2-4; QR p.13). It
    is a Willpower test, so it uses no Hunger dice. Brujah subtract their
    Bane Severity in dice from tests to resist fury frenzy.

    When a Rouse check would take your Hunger past 5 (a power with several
    Rouse checks, or rising for the night at Hunger 5), you owe an immediate
    hunger frenzy test at Difficulty 4 for each check past 5. The command
    that caused it rolls the test at once; +frenzy/pending rolls one that is
    still owed.

    Fail and the Storyteller runs your frenzy: fury destroys the source of
    the provocation, hunger seeks fresh human blood, terror flees. You may
    choose not to resist and ride the wave instead.
    """

    key = "+frenzy"
    aliases = ["frenzy"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller

        if not caller.attributes.has("vampire"):
            caller.msg("This command is only available to vampires.")
            return

        if "pending" in self.switches:
            self._roll_pending()
        elif "resist" in self.switches:
            self._resist()
        elif "check" in self.switches:
            self._check()
        else:
            self._status()

    def _roll_pending(self):
        from dice.commands import forget_roll, roll_owed_frenzy_tests

        caller = self.caller
        pending = pending_frenzy_test(caller)
        if not pending:
            caller.msg("You don't owe a hunger frenzy test.")
            return
        forget_roll(caller)
        roll_owed_frenzy_tests(caller, pending.get("reason"))

    def _resist(self):
        caller = self.caller
        parts = self.args.split()
        if not parts:
            caller.msg("Usage: +frenzy/resist <difficulty> [fury|hunger|terror]")
            return
        try:
            difficulty = int(parts[0])
        except ValueError:
            caller.msg(f"Invalid difficulty: {parts[0]}")
            return
        if not 1 <= difficulty <= MAX_DIFFICULTY:
            caller.msg(f"Difficulty must be between 1 and {MAX_DIFFICULTY}.")
            return
        frenzy_type = parts[1].lower() if len(parts) > 1 else None
        if frenzy_type and frenzy_provocations(frenzy_type) is None:
            caller.msg("The frenzy type must be fury, hunger or terror.")
            return

        from dice.commands import forget_roll

        forget_roll(caller)  # a Willpower re-roll can't reach back past this roll
        result = resist_frenzy(caller, difficulty, frenzy_type)

        lines = [f"{BLOOD_RED}{BOX_H * 78}{RESET}", f"{BLOOD_RED}  FRENZY TEST{RESET}", f"{BLOOD_RED}{BOX_H * 78}{RESET}\n"]
        lines.append(result['roll_result'].format_result(show_details=True))
        lines.append("")
        lines.append(f"  {result['message']}")
        lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
        caller.msg("\n".join(lines))
        if caller.location and not result['success']:
            caller.location.msg_contents(f"|r{caller.name}'s Beast breaks loose!|n", exclude=[caller])

    def _check(self):
        caller = self.caller
        frenzy_type = self.args.strip().lower()
        data = frenzy_provocations(frenzy_type)
        if data is None:
            caller.msg("Usage: +frenzy/check <fury|hunger|terror>")
            return
        pool, breakdown = frenzy_pool(caller, frenzy_type)
        lines = [f"{BLOOD_RED}{BOX_H * 78}{RESET}", f"{BLOOD_RED}  FRENZY: {frenzy_type.upper()}{RESET}", f"{BLOOD_RED}{BOX_H * 78}{RESET}\n"]
        lines.append(f"  {VAMPIRE_GOLD}In frenzy you:{RESET} {data['goal']}")
        lines.append(f"\n  {VAMPIRE_GOLD}Provocation{RESET}{' ' * 60}{VAMPIRE_GOLD}Difficulty{RESET}")
        for provocation, difficulty in data['provocations'].items():
            lines.append(f"  {provocation:<70} {difficulty}")
        lines.append(f"\n  Your test: {pool} dice ({breakdown}).")
        lines.append(f"  Use {VAMPIRE_GOLD}+frenzy/resist <difficulty> {frenzy_type}{RESET} when the Storyteller calls for it.")
        lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
        caller.msg("\n".join(lines))

    def _status(self):
        caller = self.caller
        pool, breakdown = frenzy_pool(caller)
        hunger = caller.hunger
        lines = [f"{BLOOD_RED}{BOX_H * 78}{RESET}", f"{BLOOD_RED}  FRENZY STATUS{RESET}", f"{BLOOD_RED}{BOX_H * 78}{RESET}\n"]
        lines.append(f"  {VAMPIRE_GOLD}Humanity:{RESET} {caller.humanity}")
        lines.append(f"  {BLOOD_RED}Hunger:{RESET} {hunger}")
        lines.append(f"  Frenzy test: {pool} dice ({breakdown}).")
        if hunger >= 4:
            lines.append(f"\n  {BLOOD_RED}At Hunger 4+ you are prone to hunger frenzy (QR p.4).{RESET}")
        pending = pending_frenzy_test(caller)
        if pending:
            lines.append(
                f"\n  {BLOOD_RED}You owe a hunger frenzy test (Difficulty {pending.get('difficulty', 4)}):"
                f"{RESET} +frenzy/pending"
            )
        lines.append(f"\n  Use {VAMPIRE_GOLD}+frenzy/check <type>{RESET} to see the provocations.")
        lines.append(f"  Use {VAMPIRE_GOLD}+frenzy/resist <difficulty> [type]{RESET} to resist frenzy.")
        lines.append(f"\n{BLOOD_RED}{BOX_H * 78}{RESET}")
        caller.msg("\n".join(lines))
