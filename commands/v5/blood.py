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

    Valid resonances: choleric, melancholic, phlegmatic, sanguine

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

        # 3. Validate resonance type if specified
        valid_resonances = ['choleric', 'melancholic', 'phlegmatic', 'sanguine']
        if resonance and resonance.lower() not in valid_resonances:
            self.caller.msg(f"|rInvalid resonance. Choose from: {', '.join(valid_resonances)}|n")
            return

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

        result = dice_roller.roll_v5_pool(pool, hunger, difficulty=2)

        # 6. Resolve feeding based on result
        if result.is_success:
            # Success - reduce Hunger
            hunger_reduction = 1 + (result.total_successes - 2) // 2  # 1-3 based on margin
            hunger_reduction = min(hunger_reduction, 3)  # Cap at 3

            new_hunger = blood_utils.reduce_hunger(self.caller, hunger_reduction)

            # Set resonance
            if resonance:
                blood_utils.set_resonance(self.caller, resonance.capitalize(), intensity=1)

            # Format message
            message = f"|gFeeding successful!|n\n\n"
            message += result.format_result(show_details=True)
            message += f"\n\nHunger reduced by {hunger_reduction}: {hunger} → {new_hunger}"

            if resonance:
                message += f"\nResonance: |y{resonance.capitalize()}|n (Fleeting)"

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
    Surge your blood to temporarily enhance a trait.

    Usage:
      bloodsurge <attribute or physical skill>

    Examples:
      bloodsurge strength         # Boost Strength by Blood Potency
      bloodsurge brawl            # Boost Brawl by Blood Potency

    Blood Surge adds dice equal to your Blood Potency to the
    specified trait for one scene (1 hour). Requires a Rouse check.

    Can only surge Attributes or Physical Skills (Athletics, Brawl, etc.).
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

        # 4. Activate Blood Surge
        from commands.v5.utils import blood_utils

        result = blood_utils.activate_blood_surge(self.caller, trait_type, trait_name)

        if result['success']:
            message = f"|yBlood Surge activated!|n\n\n"
            message += result['rouse_result']['message']
            message += f"\n\n|g{trait_name} boosted by +{result['bonus']} dice for one scene.|n"
            message += f"\n|x(Blood Surge expires in 1 hour)|n"
            self.caller.msg(message)
        else:
            self.caller.msg("|rBlood Surge activation failed.|n")


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
            lines.append(f"|yBlood Surge Active:|n +{surge['bonus']} dice to {surge['trait']}")
            remaining = int((surge['expires'] - time.time()) / 60)
            lines.append(f"|x({remaining} minutes remaining)|n")

        self.caller.msg("\n".join(lines))
