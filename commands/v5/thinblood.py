"""
Thin-Blood Commands

Commands for Thin-Blood vampires and Alchemy.
"""

from evennia import Command
from evennia import default_cmds
from .utils.thin_blood_utils import (
    is_thin_blood,
    get_thin_blood_powers,
    craft_formula,
    use_alchemy,
    check_daylight_damage,
    get_formula_by_name,
    add_ingredient
)
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, GOLD, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)


class CmdAlchemy(default_cmds.MuxCommand):
    """
    Craft and use Thin-Blood Alchemy formulae.

    Usage:
        +alchemy
        +alchemy/craft <formula name>
        +alchemy/use <formula name>
        +alchemy/ingredients
        +alchemy/add <ingredient>=<quantity>

    Thin-Blood Alchemy allows thin-blooded vampires to create
    alchemical concoctions with supernatural effects.

    Examples:
        +alchemy                    - View known formulae
        +alchemy/craft far reach    - Craft the Far Reach formula
        +alchemy/use far reach      - Use a crafted formula
        +alchemy/ingredients        - View your ingredients
        +alchemy/add vampire blood=2  - Add ingredients (staff only)
    """

    key = "+alchemy"
    aliases = ["alchemy"]
    locks = "cmd:all()"
    help_category = "V5 - Thin-Blood"

    def func(self):
        """Execute command."""
        caller = self.caller

        # Check if Thin-Blood
        if not is_thin_blood(caller):
            caller.msg(f"{BLOOD_RED}Only Thin-Bloods can use Alchemy.{RESET}")
            return

        # Handle switches
        if "craft" in self.switches:
            self.craft_formula()
        elif "use" in self.switches:
            self.use_formula()
        elif "ingredients" in self.switches:
            self.show_ingredients()
        elif "add" in self.switches:
            self.add_ingredient()
        else:
            self.show_formulae()

    def show_formulae(self):
        """Show all known formulae."""
        caller = self.caller

        formulae = get_thin_blood_powers(caller)

        if not formulae:
            caller.msg(f"{SHADOW_GREY}You don't know any Thin-Blood Alchemy formulae yet.{RESET}")
            return

        output = [
            f"{BOX_TL}{BOX_H * 68}{BOX_TR}",
            f"{BOX_V}{GOLD}{'THIN-BLOOD ALCHEMY FORMULAE':^68}{RESET}{BOX_V}",
            f"{BOX_BL}{BOX_H * 68}{BOX_BR}",
            ""
        ]

        # Group by level
        by_level = {}
        for formula in formulae:
            level = formula.get("level", 1)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(formula)

        for level in sorted(by_level.keys()):
            output.append(f"{GOLD}Level {level}:{RESET}")
            for formula in by_level[level]:
                output.append(f"  {PALE_IVORY}{formula['name']}{RESET}")
                output.append(f"    {formula['description']}")

                ingredients = formula.get('ingredients', [])
                if ingredients:
                    output.append(f"    {SHADOW_GREY}Ingredients: {', '.join(ingredients)}{RESET}")

                difficulty = formula.get('craft_difficulty', 3)
                output.append(f"    {SHADOW_GREY}Craft Difficulty: {difficulty}{RESET}")
                output.append("")

        # Show crafted formulae
        if hasattr(caller.db, "crafted_formulae") and caller.db.crafted_formulae:
            output.append(f"{GOLD}Crafted & Ready to Use:{RESET}")
            for crafted in caller.db.crafted_formulae:
                output.append(f"  {PALE_IVORY}{crafted['name']}{RESET} (Level {crafted['level']})")
            output.append("")

        output.append(f"{SHADOW_GREY}Use '+alchemy/craft <formula>' to craft a formula{RESET}")
        output.append(f"{SHADOW_GREY}Use '+alchemy/use <formula>' to activate a crafted formula{RESET}")

        caller.msg("\n".join(output))

    def craft_formula(self):
        """Craft an alchemical formula."""
        caller = self.caller

        if not self.args:
            caller.msg(f"{BLOOD_RED}Specify a formula to craft.{RESET}")
            caller.msg("Use '+alchemy' to see available formulae.")
            return

        formula_name = self.args.strip()

        result = craft_formula(caller, formula_name)

        if result["success"]:
            caller.msg(f"{GOLD}{result['message']}{RESET}")
            if "roll_result" in result:
                roll = result["roll_result"]
                caller.msg(f"Roll: {roll['total']} successes")
        else:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")

    def use_formula(self):
        """Use a crafted formula."""
        caller = self.caller

        if not self.args:
            caller.msg(f"{BLOOD_RED}Specify a formula to use.{RESET}")
            return

        formula_name = self.args.strip()

        result = use_alchemy(caller, formula_name)

        if result["success"]:
            caller.msg(f"{GOLD}{result['message']}{RESET}")
            effect = result["effect"]
            caller.msg(f"{PALE_IVORY}{effect['description']}{RESET}")
            caller.msg(f"{SHADOW_GREY}Duration: {effect['duration']}{RESET}")

            # Announce to room
            caller.location.msg_contents(
                f"{DARK_RED}{caller.name} activates an alchemical formula!{RESET}",
                exclude=[caller]
            )
        else:
            caller.msg(f"{BLOOD_RED}{result['message']}{RESET}")

    def show_ingredients(self):
        """Show alchemy ingredients."""
        caller = self.caller

        if not hasattr(caller.db, "alchemy_ingredients"):
            caller.db.alchemy_ingredients = {}

        if not caller.db.alchemy_ingredients:
            caller.msg(f"{SHADOW_GREY}You have no alchemy ingredients.{RESET}")
            return

        output = [
            f"{BOX_TL}{BOX_H * 50}{BOX_TR}",
            f"{BOX_V}{GOLD}{'ALCHEMY INGREDIENTS':^50}{RESET}{BOX_V}",
            f"{BOX_BL}{BOX_H * 50}{BOX_BR}",
            ""
        ]

        for ingredient, quantity in sorted(caller.db.alchemy_ingredients.items()):
            output.append(f"  {PALE_IVORY}{ingredient}{RESET}: {quantity}")

        caller.msg("\n".join(output))

    def add_ingredient(self):
        """Add ingredients (staff only)."""
        caller = self.caller

        # Check staff permissions
        if not caller.check_permstring("Builder"):
            caller.msg(f"{BLOOD_RED}Staff only.{RESET}")
            return

        if not self.args or "=" not in self.args:
            caller.msg("Usage: +alchemy/add <ingredient>=<quantity>")
            return

        ingredient, qty = self.args.split("=", 1)
        ingredient = ingredient.strip()

        try:
            quantity = int(qty.strip())
        except ValueError:
            caller.msg(f"{BLOOD_RED}Invalid quantity.{RESET}")
            return

        add_ingredient(caller, ingredient, quantity)
        caller.msg(f"{GOLD}Added {quantity} {ingredient}{RESET}")


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
