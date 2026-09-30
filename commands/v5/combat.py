"""
V5 Combat Commands

Commands for combat resolution:
- +attack: Perform attack roll
- +damage: Apply damage to target
- +heal: Heal damage on target
"""

from evennia import Command
from .utils.combat_utils import (
    calculate_attack,
    apply_damage,
    heal_damage,
    get_health_status,
    get_combat_pool
)
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY, GOLD, RESET,
    BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)


class CmdAttack(Command):
    """
    Perform an attack roll against a target.

    Usage:
        +attack <target>=<dice pool description>
        +attack <target>

    Rolls an attack using the specified dice pool against the target's defense.
    On success, displays the margin of success for damage calculation.

    The dice pool description should be in the format "Attribute + Skill",
    for example: "Strength + Brawl" or "Dexterity + Firearms"

    If no dice pool is specified, defaults to "Strength + Brawl".

    Examples:
        +attack Bob=Strength + Brawl
        +attack Alice=Dexterity + Firearms
        +attack Charlie=Strength + Melee
        +attack Bob

    The system will:
    1. Calculate your total dice pool from specified traits
    2. Roll against target's Defense (Dexterity + Athletics + Celerity)
    3. Display success/failure and margin
    4. Apply discipline bonuses (Potence, Celerity)
    5. Factor in impairment penalties if injured
    """

    key = "+attack"
    aliases = ["attack", "+att"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # Check for character validity
        if not hasattr(caller.db, 'pools'):
            caller.msg(f"{BLOOD_RED}Error:{RESET} You must have a character sheet to attack.")
            return

        # Parse arguments
        if not self.args:
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +attack <target>=<dice pool>")
            caller.msg(f"Example: +attack Bob=Strength + Brawl")
            return

        # Split target and pool description
        if "=" in self.args:
            target_name, pool_desc = [x.strip() for x in self.args.split("=", 1)]
        else:
            target_name = self.args.strip()
            pool_desc = "Strength + Brawl"  # Default attack pool

        # Find target
        target = caller.search(target_name)
        if not target:
            return

        # Verify target has health
        if not hasattr(target.db, 'pools'):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {target.name} cannot be attacked.")
            return

        # Get attack pool with impairment
        pool_info = get_combat_pool(caller, pool_desc, include_impairment=True)

        if pool_info["pool"] == 0:
            caller.msg(f"{BLOOD_RED}Error:{RESET} {pool_info['breakdown']}")
            return

        # Calculate attack
        result = calculate_attack(caller, target, pool_desc)

        # Build output
        output = f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        output += f"{BOX_V} {BLOOD_RED}ATTACK ROLL{RESET}"
        output += " " * (76 - len("ATTACK ROLL") - 3) + f"{BOX_V}\n"
        output += f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"

        output += f"{GOLD}Attacker:{RESET} {caller.name}\n"
        output += f"{GOLD}Target:{RESET} {target.name}\n"
        output += f"{GOLD}Attack Pool:{RESET} {pool_info['breakdown']}\n"
        output += f"{GOLD}Defense:{RESET} {result['defense']}\n\n"

        # Show dice result details
        dice_result = result['result']
        output += f"{GOLD}Roll:{RESET} {dice_result}\n\n"

        # Show result message
        output += result['message'] + "\n"

        if result['success']:
            output += f"\n{GOLD}Damage:{RESET} Base weapon damage + {result['margin']} (margin)"
            if result.get('potence_bonus', 0) > 0:
                output += f" + {result['potence_bonus']} (Potence)"

            output += f"\n\n{SHADOW_GREY}Use +damage {target.name}=<amount>/<type> to apply damage.{RESET}"

        output += f"\n{BOX_H * 78}\n"

        # Send to attacker and target
        caller.msg(output)

        # Notify target
        target_msg = f"\n{BLOOD_RED}{caller.name} attacks you!{RESET}\n"
        target_msg += f"Their attack roll: {dice_result.successes} successes vs your defense of {result['defense']}\n"
        if result['success']:
            target_msg += f"{DARK_RED}The attack succeeds!{RESET} Margin: {result['margin']}\n"
        else:
            target_msg += f"{PALE_IVORY}You successfully defend!{RESET}\n"
        target.msg(target_msg)


class CmdDamage(Command):
    """
    Apply damage to a target.

    Usage:
        +damage <target>=<amount>/<type>
        +damage <target>=<amount>

    Applies damage to the target. Damage types:
    - superficial: Normal damage, heals quickly (default)
    - aggravated: Serious damage, hard to heal
    - lethal: Lethal damage (becomes superficial for vampires)

    If no type is specified, defaults to superficial damage.

    Examples:
        +damage Bob=3/superficial
        +damage Alice=2/aggravated
        +damage Charlie=5/lethal
        +damage Bob=3

    Effects:
    - Superficial damage fills from left
    - Aggravated damage fills from right
    - When superficial fills all boxes, it converts to aggravated
    - Fortitude can reduce incoming damage
    - At half health, -2 dice penalty (impaired)
    - At zero health, torpor (for vampires) or death
    """

    key = "+damage"
    aliases = ["damage", "+dmg"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # Parse arguments
        if not self.args or "=" not in self.args:
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +damage <target>=<amount>/<type>")
            caller.msg(f"Example: +damage Bob=3/superficial")
            caller.msg(f"Types: superficial (default), aggravated, lethal")
            return

        # Split target and damage info
        target_name, damage_info = [x.strip() for x in self.args.split("=", 1)]

        # Find target
        target = caller.search(target_name)
        if not target:
            return

        # Verify target has health
        if not hasattr(target.db, 'pools'):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {target.name} cannot take damage.")
            return

        # Parse damage amount and type
        if "/" in damage_info:
            amount_str, damage_type = [x.strip() for x in damage_info.split("/", 1)]
        else:
            amount_str = damage_info.strip()
            damage_type = "superficial"

        # Validate damage amount
        try:
            damage_amount = int(amount_str)
        except ValueError:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid damage amount '{amount_str}'.")
            return

        if damage_amount <= 0:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Damage amount must be positive.")
            return

        # Validate damage type
        valid_types = ["superficial", "aggravated", "lethal"]
        if damage_type.lower() not in valid_types:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid damage type '{damage_type}'.")
            caller.msg(f"Valid types: {', '.join(valid_types)}")
            return

        # Apply damage
        result = apply_damage(target, damage_amount, damage_type.lower())

        if not result['success']:
            caller.msg(f"{BLOOD_RED}Error:{RESET} {result['message']}")
            return

        # Build output
        output = f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        output += f"{BOX_V} {DARK_RED}DAMAGE APPLIED{RESET}"
        output += " " * (76 - len("DAMAGE APPLIED") - 3) + f"{BOX_V}\n"
        output += f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"

        output += f"{GOLD}Target:{RESET} {target.name}\n"
        output += result['message'] + "\n\n"
        output += f"{GOLD}Health:{RESET} {result['health_status']}\n"
        output += f"\n{BOX_H * 78}\n"

        # Send to both parties
        caller.msg(output)
        if target != caller:
            target.msg(output)


class CmdHeal(Command):
    """
    Heal damage on a target.

    Usage:
        +heal <target>=<amount>/<type>
        +heal <target>=<amount>
        +heal self=<amount>/<type>

    Heals damage on the target. Damage types:
    - superficial: Normal damage (default)
    - aggravated: Aggravated damage

    If no type is specified, defaults to superficial damage.

    For vampires, healing superficial damage through Blood Surge uses
    the mend damage mechanics (requires Rouse check, amount based on
    Blood Potency).

    Examples:
        +heal self=2/superficial
        +heal Bob=1/aggravated
        +heal Alice=3

    Note: This command is primarily for Storytellers to manage health,
    or for characters using healing powers. Vampires should use blood
    surge mechanics for natural healing.

    Permissions: Generally requires ST permission except for self-healing
    with appropriate powers or between combat scenes.
    """

    key = "+heal"
    aliases = ["heal"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # Parse arguments
        if not self.args or "=" not in self.args:
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +heal <target>=<amount>/<type>")
            caller.msg(f"Example: +heal self=2/superficial")
            caller.msg(f"Types: superficial (default), aggravated")
            return

        # Split target and heal info
        target_name, heal_info = [x.strip() for x in self.args.split("=", 1)]

        # Find target (handle "self")
        if target_name.lower() == "self" or target_name.lower() == "me":
            target = caller
        else:
            target = caller.search(target_name)
            if not target:
                return

        # Verify target has health
        if not hasattr(target.db, 'pools'):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {target.name} cannot be healed.")
            return

        # Parse heal amount and type
        if "/" in heal_info:
            amount_str, damage_type = [x.strip() for x in heal_info.split("/", 1)]
        else:
            amount_str = heal_info.strip()
            damage_type = "superficial"

        # Validate heal amount
        try:
            heal_amount = int(amount_str)
        except ValueError:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid heal amount '{amount_str}'.")
            return

        if heal_amount <= 0:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Heal amount must be positive.")
            return

        # Validate damage type
        valid_types = ["superficial", "aggravated"]
        if damage_type.lower() not in valid_types:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid damage type '{damage_type}'.")
            caller.msg(f"Valid types: {', '.join(valid_types)}")
            return

        # Apply healing
        result = heal_damage(target, heal_amount, damage_type.lower())

        if not result['success']:
            caller.msg(f"{BLOOD_RED}Error:{RESET} {result['message']}")
            return

        # Build output
        output = f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        output += f"{BOX_V} {PALE_IVORY}HEALING APPLIED{RESET}"
        output += " " * (76 - len("HEALING APPLIED") - 3) + f"{BOX_V}\n"
        output += f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"

        output += f"{GOLD}Target:{RESET} {target.name}\n"
        output += result['message'] + "\n\n"
        output += f"{GOLD}Health:{RESET} {result['health_status']}\n"
        output += f"\n{BOX_H * 78}\n"

        # Send to both parties
        caller.msg(output)
        if target != caller:
            target.msg(output)


class CmdHealth(Command):
    """
    Display current health status.

    Usage:
        +health
        +health <target>

    Shows your current health status including:
    - Health boxes (O = healthy, / = superficial, X = aggravated)
    - Impairment status
    - Current vs maximum health

    Examples:
        +health
        +health Bob
    """

    key = "+health"
    aliases = ["health", "+hp"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        """Execute the command."""
        caller = self.caller

        # Determine target
        if self.args:
            target = caller.search(self.args.strip())
            if not target:
                return
        else:
            target = caller

        # Verify target has health
        if not hasattr(target.db, 'pools'):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {target.name} has no health tracker.")
            return

        # Get health status
        health_status = get_health_status(target)
        pools = target.db.pools

        # Build output
        output = f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        output += f"{BOX_V} {GOLD}HEALTH STATUS{RESET}"
        output += " " * (76 - len("HEALTH STATUS") - 3) + f"{BOX_V}\n"
        output += f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"

        output += f"{GOLD}Character:{RESET} {target.name}\n\n"
        output += f"{GOLD}Health:{RESET} {health_status}\n\n"

        # Detailed breakdown
        max_health = pools.get("health", 3)
        current_health = pools.get("current_health", max_health)
        superficial = pools.get("superficial_damage", 0)
        aggravated = pools.get("aggravated_damage", 0)

        output += f"{GOLD}Details:{RESET}\n"
        output += f"  Maximum Health: {max_health}\n"
        output += f"  Current Health: {current_health}\n"
        output += f"  Superficial Damage: {DARK_RED}{superficial}{RESET}\n"
        output += f"  Aggravated Damage: {BLOOD_RED}{aggravated}{RESET}\n"

        # Legend
        output += f"\n{GOLD}Legend:{RESET}\n"
        output += f"  {PALE_IVORY}O{RESET} = Healthy\n"
        output += f"  {DARK_RED}/{RESET} = Superficial Damage\n"
        output += f"  {BLOOD_RED}X{RESET} = Aggravated Damage\n"

        output += f"\n{BOX_H * 78}\n"

        caller.msg(output)
