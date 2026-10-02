"""
Blood System Commands for Vampire: The Masquerade 5th Edition

Provides commands for managing vampire blood mechanics including feeding,
Blood Surge, and Hunger tracking.
"""

from evennia import Command
from evennia import default_cmds
from evennia.utils.utils import inherits_from


class CmdFeed(default_cmds.MuxCommand):
    """
    Feed on a mortal to reduce Hunger.

    Usage:
      feed <target> [<resonance>]
      feed/slake <target>

    Examples:
      feed mortal                  # Hunt generic mortal
      feed mortal choleric         # Hunt for choleric resonance
      feed/slake mortal            # Feed to Hunger 0 (dangerous!)

    Feeding requires a roll to hunt successfully. On success, your
    Hunger is reduced. Feeding also sets your resonance based on the
    victim's emotional state.

    Valid resonances: choleric, melancholy, phlegmatic, sanguine

    Switches:
      slake - Feed until Hunger 0 (multiple rolls, risky)
    """

    key = "feed"
    locks = "cmd:all()"
    help_category = "Blood"

    def func(self):
        # 1. Validate caller is a Character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to feed.|n")
            return

        # 2. Parse arguments
        args = self.args.strip()
        if not args:
            self.caller.msg("Usage: feed <target> [<resonance>]")
            return

        parts = args.split()
        target = parts[0]
        resonance = parts[1] if len(parts) > 1 else None

        # 3. Validate resonance type if specified, before anything changes.
        # The names come from world.v5_data.RESONANCES, so they can't drift.
        from world.v5_data import RESONANCES

        valid_resonances = {name.lower(): name for name in RESONANCES}
        if resonance:
            if resonance.lower() not in valid_resonances:
                self.caller.msg(f"|rInvalid resonance. Choose from: {', '.join(valid_resonances)}|n")
                return
            resonance = valid_resonances[resonance.lower()]

        # 4. Check slake switch
        slake_mode = 'slake' in self.switches

        # 5. Perform feeding roll
        # Get pool based on Predator Type
        from dice import dice_roller
        from commands.v5.utils.trait_utils import get_trait_value
        from commands.v5.utils import blood_utils
        from commands.v5.utils.predator_utils import get_feeding_pool

        pool_str, bonus_dice = get_feeding_pool(self.caller)
        pool_parts = pool_str.split('+')
        pool = 0
        for part in pool_parts:
            trait_value = get_trait_value(self.caller, part.capitalize())
            pool += trait_value
        pool += bonus_dice  # Add predator type bonus

        hunger = blood_utils.get_hunger_level(self.caller)

        from dice.commands import forget_roll

        forget_roll(self.caller)  # a Willpower re-roll can't reach back past this roll
        result = dice_roller.roll_v5_pool(pool, hunger, difficulty=2)

        # 6. Resolve feeding based on result
        if result.is_success:
            # Success - reduce Hunger
            hunger_reduction = 1 + (result.total_successes - 2) // 2  # 1-3 based on margin
            hunger_reduction = min(hunger_reduction, 3)  # Cap at 3

            new_hunger = blood_utils.reduce_hunger(self.caller, hunger_reduction)

            # Set resonance
            if resonance:
                blood_utils.set_resonance(self.caller, resonance, intensity=1)

            # Format message
            message = f"|gFeeding successful!|n\n\n"
            message += result.format_result(show_details=True)
            message += f"\n\nHunger reduced by {hunger_reduction}: {hunger} → {new_hunger}"

            if resonance:
                message += f"\nResonance: |y{resonance}|n (Fleeting)"

            # Check for Messy Critical
            if result.is_messy_critical:
                message += "\n\n|y|hMessy Critical!|n"
                message += "\n|rYour feeding was successful but drew attention or left evidence...|n"

            self.caller.msg(message)

            # Broadcast to room
            if self.caller.location:
                self.caller.location.msg_contents(
                    f"|x{self.caller.name} feeds...|n",
                    exclude=[self.caller]
                )

        elif result.is_bestial_failure:
            # Bestial Failure - feeding goes wrong
            message = f"|r|hBestial Failure!|n\n\n"
            message += result.format_result(show_details=True)
            message += "\n\n|rYour Beast takes control during the feeding...|n"
            message += "\n|x(This may trigger frenzy or cause a Humanity stain)|n"
            self.caller.msg(message)

        else:
            # Regular failure
            message = f"|rFeeding failed.|n\n\n"
            message += result.format_result(show_details=True)
            message += "\n\nYou were unable to successfully hunt."
            self.caller.msg(message)


class CmdBloodSurge(Command):
    """
    Surge your blood to add dice to your next roll.

    Usage:
      bloodsurge <attribute or physical skill>

    Examples:
      bloodsurge strength
      bloodsurge brawl

    Your next roll whose pool includes an Attribute (a `roll`, or a `power`
    roll) gets the Blood Surge dice from the Blood Potency table (BP 0: +1,
    BP 1-2: +2, BP 3-4: +3, and so on), then the surge is used up. Its one
    Rouse check is made with that roll: the roll uses the Hunger you had
    before it, and a failed check raises Hunger by 1 afterwards (core
    pp.211-212, p.218). One surge at a time; an unused surge lapses after an
    hour and costs nothing.

    At Hunger 5 you can't Rouse the Blood, so you can't surge.
    """

    key = "bloodsurge"
    aliases = ["surge"]
    locks = "cmd:all()"
    help_category = "Blood"

    def func(self):
        # 1. Validate caller
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to use Blood Surge.|n")
            return

        # 2. Parse trait name
        trait_name = self.args.strip().capitalize()
        if not trait_name:
            self.caller.msg("Usage: bloodsurge <attribute or skill>")
            return

        # 3. Validate trait type - Blood Surge only works on Attributes or Physical Skills
        VALID_ATTRIBUTES = [
            'Strength', 'Dexterity', 'Stamina',  # Physical
            'Charisma', 'Manipulation', 'Composure',  # Social
            'Intelligence', 'Wits', 'Resolve'  # Mental
        ]

        VALID_PHYSICAL_SKILLS = [
            'Athletics', 'Brawl', 'Craft', 'Drive', 'Firearms',
            'Larceny', 'Melee', 'Stealth', 'Survival'
        ]

        trait_type = None
        if trait_name in VALID_ATTRIBUTES:
            trait_type = 'attribute'
        elif trait_name in VALID_PHYSICAL_SKILLS:
            trait_type = 'physical_skill'
        else:
            self.caller.msg(
                f"|rBlood Surge can only be used on Attributes or Physical Skills.|n\n"
                f"|wValid Attributes:|n Strength, Dexterity, Stamina, Charisma, "
                f"Manipulation, Composure, Intelligence, Wits, Resolve\n"
                f"|wValid Physical Skills:|n Athletics, Brawl, Craft, Drive, Firearms, "
                f"Larceny, Melee, Stealth, Survival"
            )
            return

        # 4. A Rouse check is impossible at Hunger 5 (QR p.4).
        from commands.v5.utils import blood_utils
        from dice.rouse_checker import HUNGER_5_REFUSAL, MAX_HUNGER

        if self.caller.hunger >= MAX_HUNGER:
            self.caller.msg(f"|r{HUNGER_5_REFUSAL}|n")
            return

        # 5. Activate Blood Surge
        result = blood_utils.activate_blood_surge(self.caller, trait_type, trait_name)

        if result['success']:
            message = "|yBlood Surge activated!|n\n\n"
            message += f"|g+{result['bonus']} dice to your next roll ({trait_name}).|n"
            message += "\nIts Rouse check is made with that roll; any Hunger it costs comes after."
            message += "\n|x(Used up by your next roll; lapses unused after one hour.)|n"
            self.caller.msg(message)
        else:
            self.caller.msg(f"|rBlood Surge failed.|n {result['message']}")


class CmdHunger(Command):
    """
    View your current Hunger level and blood status.

    Usage:
      hunger

    Displays:
    - Current Hunger level (0-5)
    - Visual Hunger bar
    - Hunger effects
    - Current resonance (if any)
    - Blood Surge status (if active)
    """

    key = "hunger"
    locks = "cmd:all()"
    help_category = "Blood"

    def func(self):
        # 1. Validate caller
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to check Hunger.|n")
            return

        # 2. Get blood status
        from commands.v5.utils import blood_utils

        hunger = blood_utils.get_hunger_level(self.caller)
        hunger_display = blood_utils.format_hunger_display(self.caller)
        resonance_display = blood_utils.format_resonance_display(self.caller)

        # 3. Build display
        lines = []
        lines.append("|c=== Blood Status ===|n")
        lines.append("")
        lines.append(hunger_display)
        lines.append("")

        # Hunger effects
        if hunger == 0:
            lines.append("|gYou are well-fed and sated.|n")
        elif hunger <= 2:
            lines.append("|yYou feel minor cravings for blood.|n")
        elif hunger == 3:
            lines.append("|yYour Hunger is moderate. You need to feed soon.|n")
        elif hunger == 4:
            lines.append("|rYour Hunger is severe. The Beast stirs within.|n")
        elif hunger >= 5:
            lines.append("|r|hYou are RAVENOUS! You cannot use most discipline powers.|n")

        lines.append("")

        # Resonance
        if resonance_display:
            lines.append(resonance_display)
            lines.append("")

        # Blood Surge
        surge = blood_utils.get_blood_surge(self.caller)
        if surge:
            import time
            lines.append(f"|yBlood Surge Active:|n +{surge['bonus']} dice to {surge['trait']}, on your next roll")
            remaining = int((surge['expires'] - time.time()) / 60)
            lines.append(f"|x({remaining} minutes remaining)|n")

        self.caller.msg("\n".join(lines))
