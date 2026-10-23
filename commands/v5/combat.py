"""
V5 Combat Commands

- +attack: a contested attack roll (reports the damage; staff mark it)
- +damage: mark damage (on someone else: staff only)
- +heal: mend your own Superficial damage with the Blood, or (staff) heal anyone
- +health: show a Health track
"""

from evennia import Command, default_cmds
from evennia.utils.utils import inherits_from

from dice.commands import _is_staff, forget_roll
from world.ansi_theme import BLOOD_RED, BOX_BL, BOX_BR, BOX_H, BOX_TL, BOX_TR, BOX_V, DARK_RED, GOLD, PALE_IVORY, RESET

from .utils.combat_utils import (
    DAMAGE_TYPES,
    DEFAULT_ATTACK_POOL,
    apply_damage,
    calculate_attack,
    check_attack_pool,
    get_health_status,
    heal_damage,
    mend_superficial,
)


def _banner(title, color=PALE_IVORY):
    return (
        f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        f"{BOX_V} {color}{title}{RESET}" + " " * (76 - len(title) - 1) + f"{BOX_V}\n"
        f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"
    )


def _dice_line(roll):
    """A defender's roll as dice and successes (it has no difficulty of its own)."""
    line = f"[{' '.join(str(d) for d in roll.regular_dice)}]"
    if roll.hunger_dice:
        line += f" Hunger [{' '.join(str(d) for d in roll.hunger_dice)}]"
    return f"{line} - {roll.total_successes} successes"


def _find_character(caller, name):
    """caller.search for a Character; messages the caller and returns None otherwise."""
    target = caller.search(name)
    if not target:
        return None
    if not inherits_from(target, "typeclasses.characters.Character"):
        caller.msg(f"{BLOOD_RED}Error:{RESET} {target.key} has no Health track.")
        return None
    return target


class CmdAttack(default_cmds.MuxCommand):
    """
    Make a contested attack roll against a target.

    Usage:
        +attack <target>
        +attack <target>=<attack pool>
        +attack <target>=<attack pool>/<weapon damage>
        +attack <target>=<attack pool>/<weapon damage> vs <defense pool>   (staff)

    Attacks are contested (V5 core p.123-126). You roll your attack pool,
    one Attribute plus one Skill (default Strength + Brawl). The target
    automatically rolls their best standard defense: Dexterity + Athletics
    to dodge, or against a close-combat attack Strength or Dexterity +
    Brawl or Melee, plus an active Celerity bonus. Only staff can name the
    defense pool. You hit if you get at least as many successes as the
    target (a tie goes to the attacker). The damage is your margin (at least
    1; a tie does 1) plus the weapon's damage (and an active Potence bonus).
    In a two-sided brawl the Storyteller applies any damage the defender
    deals back.

    Each side rolls its own Hunger dice (mortals and ghouls roll none) and
    loses 2 dice while its Health track is full (Impaired). The pool shown
    is the pool rolled.

    The attack only reports the damage: the Storyteller marks it with
    +damage. A vampire halves mundane Superficial damage (rounding up) when
    it is marked.

    Examples:
        +attack Bob
        +attack Bob=Dexterity + Firearms/2
        +attack Bob=Strength + Melee/2 vs Strength + Melee
    """

    key = "+attack"
    aliases = ["attack", "+att"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        caller = self.caller
        if not inherits_from(caller, "typeclasses.characters.Character"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} You must be in character to attack.")
            return
        if not self.lhs:
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +attack <target>[=<attack pool>[/<weapon damage>][ vs <defense pool>]]")
            return

        attack_desc, weapon, defense_desc = DEFAULT_ATTACK_POOL, 0, None
        spec = (self.rhs or "").strip()
        if spec:
            if " vs " in spec.lower():
                index = spec.lower().index(" vs ")
                spec, defense_desc = spec[:index].strip(), spec[index + 4:].strip()
            if "/" in spec:
                spec, weapon_str = (part.strip() for part in spec.split("/", 1))
                try:
                    weapon = int(weapon_str)
                except ValueError:
                    caller.msg(f"{BLOOD_RED}Error:{RESET} Weapon damage must be a number.")
                    return
                if not 0 <= weapon <= 10:
                    caller.msg(f"{BLOOD_RED}Error:{RESET} Weapon damage must be between 0 and 10.")
                    return
            attack_desc = spec or DEFAULT_ATTACK_POOL
        staff = _is_staff(caller)
        if defense_desc and not staff:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Only staff can choose the defender's pool; they defend with their best.")
            return
        if not staff:
            error = check_attack_pool(attack_desc)
            if error:
                caller.msg(f"{BLOOD_RED}Error:{RESET} {error}")
                return

        target = _find_character(caller, self.lhs.strip())
        if not target:
            return
        if target == caller:
            caller.msg(f"{BLOOD_RED}Error:{RESET} You can't attack yourself.")
            return

        forget_roll(caller)  # a Willpower re-roll can't reach back past this roll
        result = calculate_attack(caller, target, attack_desc, weapon, defense_desc)
        if result.get("error"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {result['error']}")
            return
        defense_desc = result["defense_pool"]

        output = _banner("ATTACK ROLL", BLOOD_RED)
        output += f"{GOLD}Attacker:{RESET} {caller.name} - {attack_desc}: {result['attack']['breakdown']}\n"
        output += f"{GOLD}Defender:{RESET} {target.name} - {defense_desc}: {result['defense']['breakdown']}\n\n"
        output += f"{GOLD}Your roll:{RESET} {result['result'].format_result(show_details=True)}\n"
        output += f"{GOLD}Their roll:{RESET} {_dice_line(result['defense_result'])}\n\n"
        output += result["message"] + "\n"
        if result["success"]:
            output += f"\nThe Storyteller marks it: +damage {target.name}={result['damage']}/<superficial|aggravated>\n"
        output += f"\n{BOX_H * 78}\n"
        caller.msg(output)

        target_msg = f"\n{BLOOD_RED}{caller.name} attacks you!{RESET} ({attack_desc} vs your {defense_desc})\n"
        target_msg += (
            f"Their successes: {result['result'].total_successes}; yours: "
            f"{result['defense_result'].total_successes}.\n"
        )
        if result["success"]:
            target_msg += f"{DARK_RED}The attack hits for {result['damage']} damage (before any halving).{RESET}\n"
        else:
            target_msg += f"{PALE_IVORY}You avoid the attack.{RESET}\n"
        target.msg(target_msg)
        if caller.location:
            outcome = f"hits for {result['damage']}" if result["success"] else "misses"
            caller.location.msg_contents(
                f"|c{caller.name}|n attacks |c{target.name}|n ({attack_desc} {result['attack']['pool']} dice, "
                f"weapon {weapon} vs {defense_desc} {result['defense']['pool']} dice) and {outcome}.",
                exclude=[caller, target],
            )


class CmdDamage(default_cmds.MuxCommand):
    """
    Mark damage on a Health track.

    Usage:
        +damage <amount>[/<type>]               (yourself)
        +damage <target>=<amount>[/<type>]      (staff only, unless the target is you)
        +damage/unhalved <target>=<amount>      (staff: Superficial damage that isn't halved)

    Types: superficial (default) or aggravated.

    A vampire halves mundane Superficial damage, rounding up, before it is
    marked (mortals, ghouls and thin-bloods without Vampiric Resilience
    don't). When the track is full, each further Superficial point turns a
    Superficial box into Aggravated. A full track is Impaired (-2 dice to
    Physical tests); a vampire whose track is full of Aggravated damage
    falls into torpor.

    Only staff can damage another character.

    Examples:
        +damage 2
        +damage Bob=3
        +damage Bob=2/aggravated
    """

    key = "+damage"
    aliases = ["damage", "+dmg"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        caller = self.caller
        if not self.args:
            caller.msg(f"{BLOOD_RED}Usage:{RESET} +damage [<target>=]<amount>[/superficial|aggravated]")
            return

        if self.rhs is not None:
            target = _find_character(caller, self.lhs.strip())
            if not target:
                return
            damage_info = self.rhs.strip()
        else:
            target, damage_info = caller, self.args.strip()

        if target != caller and not _is_staff(caller):
            caller.msg(f"{BLOOD_RED}Only staff can damage another character.{RESET}")
            return
        if "unhalved" in self.switches and not _is_staff(caller):
            caller.msg(f"{BLOOD_RED}Only staff can mark unhalved damage.{RESET}")
            return
        if not inherits_from(target, "typeclasses.characters.Character"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} You must be in character.")
            return

        amount_str, _, damage_type = damage_info.partition("/")
        damage_type = (damage_type.strip() or "superficial").lower()
        try:
            amount = int(amount_str.strip())
        except ValueError:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid damage amount '{amount_str.strip()}'.")
            return
        if amount <= 0:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Damage amount must be positive.")
            return
        if damage_type not in DAMAGE_TYPES:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Damage type must be {' or '.join(DAMAGE_TYPES)}.")
            return

        result = apply_damage(target, amount, damage_type, halve="unhalved" not in self.switches)
        if not result["success"]:
            caller.msg(f"{BLOOD_RED}Error:{RESET} {result['message']}")
            return

        output = _banner("DAMAGE", DARK_RED)
        output += result["message"] + "\n\n"
        output += f"{GOLD}Health:{RESET} {result['health_status']}\n"
        output += f"\n{BOX_H * 78}\n"
        caller.msg(output)
        if target != caller:
            target.msg(output)


class CmdHeal(default_cmds.MuxCommand):
    """
    Mend your Superficial damage with the Blood, or (staff) heal a character.

    Usage:
        +heal                                (mend: one Rouse check)
        +heal <target>=<amount>[/<type>]     (staff only)

    Mending (QR p.13): once per turn a vampire may Rouse the Blood to mend
    Superficial damage, as much as their Blood Potency allows (BP 0-1: 1,
    BP 2-3: 2, BP 4-7: 3, BP 8-9: 4, BP 10: 5). A failed Rouse check raises
    your Hunger; at Hunger 5 you can't Rouse, so you can't mend.

    Aggravated damage mends at nightfall with three Rouse checks per point,
    and Willpower recovers at the start of a session; ask the Storyteller.
    Only staff can heal another character or heal without a Rouse check.

    Examples:
        +heal
        +heal Bob=2
        +heal Bob=1/aggravated
    """

    key = "+heal"
    aliases = ["heal", "+mend", "mend"]
    locks = "cmd:all()"
    help_category = "V5 - Combat"

    def func(self):
        caller = self.caller
        if not inherits_from(caller, "typeclasses.characters.Character") and self.rhs is None:
            caller.msg(f"{BLOOD_RED}Error:{RESET} You must be in character to mend.")
            return

        if self.rhs is None:
            if self.args.strip().lower() not in ("", "self", "me"):
                caller.msg(f"{BLOOD_RED}Usage:{RESET} +heal  (mend your own Superficial damage)")
                return
            self._mend()
            return

        if not _is_staff(caller):
            caller.msg(
                f"{BLOOD_RED}Only staff can heal a character directly.{RESET} Use +heal to mend your own "
                "Superficial damage with a Rouse check."
            )
            return

        name = self.lhs.strip()
        target = caller if name.lower() in ("self", "me") else _find_character(caller, name)
        if not target:
            return

        amount_str, _, damage_type = self.rhs.strip().partition("/")
        damage_type = (damage_type.strip() or "superficial").lower()
        try:
            amount = int(amount_str.strip())
        except ValueError:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Invalid heal amount '{amount_str.strip()}'.")
            return
        if amount <= 0:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Heal amount must be positive.")
            return
        if damage_type not in DAMAGE_TYPES:
            caller.msg(f"{BLOOD_RED}Error:{RESET} Damage type must be {' or '.join(DAMAGE_TYPES)}.")
            return

        result = heal_damage(target, amount, damage_type)
        if not result["success"]:
            caller.msg(f"{BLOOD_RED}Error:{RESET} {result['message']}")
            return
        output = _banner("HEALING")
        output += result["message"] + "\n\n"
        output += f"{GOLD}Health:{RESET} {result['health_status']}\n"
        output += f"\n{BOX_H * 78}\n"
        caller.msg(output)
        if target != caller:
            target.msg(output)

    def _mend(self):
        from dice.rouse_checker import format_rouse_lines

        caller = self.caller
        result = mend_superficial(caller)
        lines = [_banner("MENDING").rstrip("\n")]
        if result["rouse_result"] is not None and not result["rouse_result"].refused:
            lines.extend(format_rouse_lines(result["rouse_result"]))
        color = GOLD if result["success"] else BLOOD_RED
        lines.append(f"{color}{result['message']}{RESET}")
        lines.append(f"{GOLD}Health:{RESET} {get_health_status(caller)}")
        caller.msg("\n".join(lines))


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
        if not target.attributes.has("pools"):
            caller.msg(f"{BLOOD_RED}Error:{RESET} {target.name} has no health tracker.")
            return

        # Get health status
        health_status = get_health_status(target)

        # Build output
        output = f"\n{BOX_TL}{BOX_H * 76}{BOX_TR}\n"
        output += f"{BOX_V} {GOLD}HEALTH STATUS{RESET}"
        output += " " * (76 - len("HEALTH STATUS") - 3) + f"{BOX_V}\n"
        output += f"{BOX_BL}{BOX_H * 76}{BOX_BR}\n\n"

        output += f"{GOLD}Character:{RESET} {target.name}\n\n"
        output += f"{GOLD}Health:{RESET} {health_status}\n\n"

        # Detailed breakdown
        max_health = target.health_max
        current_health = target.current_health
        superficial = target.damage["health"]["superficial"]
        aggravated = target.damage["health"]["aggravated"]

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
