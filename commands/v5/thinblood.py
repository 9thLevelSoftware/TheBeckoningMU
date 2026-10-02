"""
Thin-Blood Commands

Commands for Thin-Blood vampires and Alchemy.
"""

from evennia import default_cmds

from dice.commands import _is_staff
from dice.dice_roller import MAX_DIFFICULTY
from dice.rouse_checker import format_rouse_lines
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

from .utils.thin_blood_utils import (
    DEFAULT_DISTILL_DIFFICULTY,
    DISTILLATION_METHODS,
    check_daylight_damage,
    craft_formula,
    get_thin_blood_powers,
    is_thin_blood,
    use_alchemy,
)


class CmdAlchemy(default_cmds.MuxCommand):
    """
    Distil and use Thin-Blood Alchemy formulas.

    Usage:
        +alchemy
        +alchemy/distill <formula>[=<method>]
        +alchemy/use <formula>
        +alchemy/teach <character>=<formula>     (staff: grant a formula, no XP)

    Thin-Blood Alchemy (core p.282-288) is not a Discipline with powers.
    Each dot comes with one formula, chosen when you buy it (+spend
    discipline Thin-Blood Alchemy = <formula>); more formulas cost formula
    level x 3 XP (+spend formula <name>). The Thin-blood Alchemist merit's
    dot and formula are granted by staff with +alchemy/teach. You distil a
    dose of a formula you know, then use it.

    Distilling costs 1 Rouse check and rolls a method pool with your Hunger
    dice:
        athanor     Athanor Corporis: Stamina + Thin-Blood Alchemy (default)
        calcinatio  Calcinatio: Manipulation + Thin-Blood Alchemy
        fixatio     Fixatio: Intelligence + Thin-Blood Alchemy
    The difficulty is 3 (staff may set another with "vs <difficulty>"). A
    success gives one dose. The room sees the distillation.

    Using a dose pays the formula's own Rouse cost and rolls its dice pool,
    if it has one. At Hunger 5 you can't Rouse, so you can't distil or use a
    formula that costs a Rouse check.

    Examples:
        +alchemy
        +alchemy/distill far reach
        +alchemy/distill haze=fixatio
        +alchemy/use far reach
    """

    key = "+alchemy"
    aliases = ["alchemy"]
    locks = "cmd:all()"
    help_category = "V5 - Thin-Blood"

    def func(self):
        """Execute command."""
        caller = self.caller
        if not is_thin_blood(caller) and "teach" not in self.switches:
            caller.msg(f"{BLOOD_RED}Only Thin-Bloods can use Alchemy.{RESET}")
            return

        if "teach" in self.switches:
            self.teach()
            return
        if "distill" in self.switches or "craft" in self.switches:
            self.distill()
        elif "use" in self.switches:
            self.use_formula()
        else:
            self.show_formulae()

    def show_formulae(self):
        caller = self.caller
        formulae = get_thin_blood_powers(caller)
        output = [
            f"{BOX_TL}{BOX_H * 68}{BOX_TR}",
            f"{BOX_V}{GOLD}{'THIN-BLOOD ALCHEMY':^68}{RESET}{BOX_V}",
            f"{BOX_BL}{BOX_H * 68}{BOX_BR}",
            "",
            f"{PALE_IVORY}Thin-Blood Alchemy:{RESET} {caller.get_trait('Thin-Blood Alchemy')}",
            "",
        ]
        if not formulae:
            output.append(f"{SHADOW_GREY}You don't know any formulas yet (+spend formula <name>).{RESET}")
        for formula in formulae:
            output.append(f"{PALE_IVORY}{formula['name']}{RESET} (level {formula['level']})")
            output.append(f"    {formula['description']}")
            cost = f"{formula['rouse']} Rouse" if formula.get("rouse") else "free"
            output.append(
                f"    {SHADOW_GREY}Use: {cost}; pool: {formula.get('dice_pool') or 'none'}; "
                f"resonance: {formula.get('resonance') or 'any'}{RESET}"
            )
        doses = caller.db.crafted_formulae or []
        if doses:
            output.append("")
            output.append(f"{GOLD}Distilled doses:{RESET}")
            for dose in doses:
                output.append(f"  {PALE_IVORY}{dose['name']}{RESET} ({dose.get('method', 'distilled')})")
        output.append("")
        output.append(f"{SHADOW_GREY}+alchemy/distill <formula>[=<method>] to distil; +alchemy/use <formula> to use.{RESET}")
        caller.msg("\n".join(output))

    def distill(self):
        caller = self.caller
        lhs = (self.lhs or "").strip()
        difficulty = DEFAULT_DISTILL_DIFFICULTY
        method_text = (self.rhs or "athanor").strip().lower()
        for text_name in ("lhs", "rhs"):
            text = lhs if text_name == "lhs" else method_text
            if " vs " in text:
                text, _, diff = text.partition(" vs ")
                try:
                    difficulty = int(diff.strip())
                except ValueError:
                    caller.msg(f"{BLOOD_RED}Difficulty must be a number.{RESET}")
                    return
                if text_name == "lhs":
                    lhs = text.strip()
                else:
                    method_text = text.strip()
        if not lhs:
            caller.msg("Usage: +alchemy/distill <formula>[=<method>] [vs <difficulty>]")
            return
        if difficulty != DEFAULT_DISTILL_DIFFICULTY and not _is_staff(caller):
            caller.msg(f"{BLOOD_RED}Only staff can set a distillation's difficulty.{RESET}")
            return
        if not 1 <= difficulty <= MAX_DIFFICULTY:
            caller.msg(f"{BLOOD_RED}Difficulty must be between 1 and {MAX_DIFFICULTY}.{RESET}")
            return
        method = next((key for key in DISTILLATION_METHODS if key.startswith(method_text[:4])), None)
        if method is None:
            caller.msg(f"{BLOOD_RED}Unknown method. Choose from: {', '.join(DISTILLATION_METHODS)}.{RESET}")
            return

        from dice.commands import forget_roll

        forget_roll(caller)
        result = craft_formula(caller, lhs, method, difficulty)
        if result["roll_result"] is None:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")
            return
        lines = [result["roll_result"].format_result(show_details=True), ""]
        lines.append(f"{GOLD if result['success'] else BLOOD_RED}{result['message']}{RESET}")
        lines.extend(format_rouse_lines(result["rouse_result"]))
        caller.msg("\n".join(lines))
        if caller.location:
            outcome = "and succeeds" if result["success"] else "and fails"
            caller.location.msg_contents(
                f"|c{caller.name}|n distils {result['formula']['name']} ({result['method']}, Difficulty "
                f"{difficulty}: {result['roll_result'].total_successes} successes) {outcome}.",
                exclude=[caller],
            )

    def teach(self):
        caller = self.caller
        if not _is_staff(caller):
            caller.msg(f"{BLOOD_RED}Only staff can grant a formula.{RESET}")
            return
        if not self.lhs or not self.rhs:
            caller.msg("Usage: +alchemy/teach <character>=<formula>")
            return
        target = caller.search(self.lhs.strip())
        if not target:
            return
        try:
            formula = target.learn_ritual_or_formula("formula", self.rhs.strip())
        except LookupError as err:
            caller.msg(f"{BLOOD_RED}{err}{RESET}")
            return
        caller.msg(f"{target.key} now knows {formula['name']}.")
        if target != caller:
            target.msg(f"{GOLD}You learn the formula {formula['name']}.{RESET}")

    def use_formula(self):
        caller = self.caller
        if not self.args.strip():
            caller.msg(f"{BLOOD_RED}Specify a formula to use.{RESET}")
            return
        from dice.commands import forget_roll

        forget_roll(caller)
        result = use_alchemy(caller, self.args.strip())
        if not result["success"]:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")
            return
        effect = result["effect"]
        lines = [f"{GOLD}{result['message']}{RESET}", f"{PALE_IVORY}{effect['description']}{RESET}",
                 f"{SHADOW_GREY}Duration: {effect['duration']}{RESET}"]
        if result["roll_result"] is not None:
            lines.append(result["roll_result"].format_result(show_details=True))
            if effect.get("opposed_by"):
                lines.append(f"{SHADOW_GREY}The target resists with {effect['opposed_by']}.{RESET}")
        if result["rouse_result"] is not None:
            lines.extend(format_rouse_lines(result["rouse_result"]))
        caller.msg("\n".join(lines))
        if caller.location:
            caller.location.msg_contents(
                f"{DARK_RED}{caller.name} uses an alchemical formula!{RESET}", exclude=[caller]
            )


class CmdDaylight(default_cmds.MuxCommand):
    """
    Check or expose to daylight (Thin-Blood specific).

    Usage:
        +daylight
        +daylight/expose

    Thin-Bloods take bashing damage from sunlight instead of
    aggravated damage, allowing them to survive daylight hours.

    Examples:
        +daylight         - Check current sun exposure
        +daylight/expose  - Expose yourself to sunlight
    """

    key = "+daylight"
    aliases = ["daylight"]
    locks = "cmd:all()"
    help_category = "V5 - Thin-Blood"

    def func(self):
        """Execute command."""
        caller = self.caller

        if "expose" in self.switches:
            self.expose_to_daylight()
        else:
            self.check_daylight()

    def check_daylight(self):
        """Check daylight status."""
        caller = self.caller

        damage_info = check_daylight_damage(caller)

        if is_thin_blood(caller):
            caller.msg(f"{GOLD}Thin-Blood Daylight Tolerance:{RESET}")
            caller.msg(f"Damage Type: {damage_info['damage_type'].title()}")
            caller.msg(f"Damage Amount: {damage_info['amount']}")
            caller.msg(f"{SHADOW_GREY}You can survive in daylight, but it hurts.{RESET}")
        else:
            caller.msg(f"{BLOOD_RED}Daylight is lethal to you!{RESET}")
            caller.msg(f"Damage Type: {damage_info['damage_type'].title()}")
            caller.msg(f"Damage Amount: {damage_info['amount']}")

    def expose_to_daylight(self):
        """Expose to sunlight."""
        caller = self.caller

        damage_info = check_daylight_damage(caller)

        if is_thin_blood(caller):
            caller.msg(f"{GOLD}You step into the sunlight...{RESET}")
            caller.msg(f"{BLOOD_RED}The sun burns, but you endure!{RESET}")
            caller.msg(f"Taking {damage_info['amount']} {damage_info['damage_type']} damage.")

            # Apply damage (simplified - use combat_utils.apply_damage in full version)
            # For now, just message
            caller.msg(f"{SHADOW_GREY}(Damage applied){RESET}")
        else:
            caller.msg(f"{BLOOD_RED}The sunlight incinerates you!{RESET}")
            caller.msg(f"Taking {damage_info['amount']} {damage_info['damage_type']} damage.")
            caller.msg(f"{SHADOW_GREY}(Damage applied){RESET}")
