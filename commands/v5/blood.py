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
    Record a feeding from a staff-run scene (staff only).

    Usage:
      feed <character>=<source>[/<resonance>[/<intensity>]]

    Sources (QR p.12; Hunger slaked):
      small animals 1, animal 1, large animal 2, bag 1,
      sip 1, drink 2 (most a human can give unharmed),
      harmful <1-4> (risks the vessel's death), kill (drains a human: Hunger 0)

    Resonance: choleric, melancholy, phlegmatic or sanguine, with an
    intensity of 1 (Fleeting, the default), 2 (Intense) or 3 (Acute).
    Animal and bagged blood carry no resonance.

    The character's Blood Potency applies (animal and bagged blood slake
    less or nothing; high Blood Potency slakes less per human), and only a
    kill takes Hunger below 1 (2 or 3 at high Blood Potency). Killing and
    harming vessels may cost Stains; mark those with +stain.

    Players feed with +hunt, or ask for a hunt scene with +hunt/staffed.

    Examples:
      feed Bob=drink/choleric
      feed Bob=harmful 3/sanguine/2
      feed Bob=animal
      feed Bob=kill/melancholy/3
    """

    key = "feed"
    locks = "cmd:perm(Builder)"
    help_category = "Blood"

    def func(self):
        from commands.v5.utils import hunting_utils
        from world.v5_data import FEEDING_SOURCES, RESONANCE_INTENSITIES, RESONANCES

        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: feed <character>=<source>[/<resonance>[/<intensity>]]")
            caller.msg(f"Sources: {', '.join(FEEDING_SOURCES)}")
            return

        target = caller.search(self.lhs.strip(), global_search=True)
        if not target:
            return
        if not inherits_from(target, "typeclasses.characters.Character") or not target.is_kindred:
            caller.msg(f"|r{target.key} isn't a vampire.|n")
            return

        fields = [field.strip() for field in self.rhs.split("/")]
        source_text = fields[0].lower()
        amount = None
        if source_text.startswith("harmful"):
            number = source_text[len("harmful"):].strip()
            source_text = "harmful"
            if number:
                if not number.isdigit() or not 1 <= int(number) <= 4:
                    caller.msg("|rA harmful drink slakes 1 to 4 Hunger.|n")
                    return
                amount = int(number)
        if source_text not in FEEDING_SOURCES:
            caller.msg(f"|rUnknown source. Choose from: {', '.join(FEEDING_SOURCES)}|n")
            return

        resonance = None
        intensity = 1
        if len(fields) > 1 and fields[1]:
            names = {name.lower(): name for name in RESONANCES}
            if fields[1].lower() not in names:
                caller.msg(f"|rInvalid resonance. Choose from: {', '.join(names)}|n")
                return
            if FEEDING_SOURCES[source_text]["kind"] != "human":
                caller.msg("|rAnimal and bagged blood carry no resonance.|n")
                return
            resonance = names[fields[1].lower()]
        if len(fields) > 2 and fields[2]:
            if fields[2] not in ("1", "2", "3"):
                caller.msg("|rIntensity is 1 (Fleeting), 2 (Intense) or 3 (Acute).|n")
                return
            intensity = int(fields[2])

        from commands.v5.utils import blood_utils

        result = hunting_utils.slake(target, source_text, amount)
        if resonance:
            blood_utils.set_resonance(target, resonance, intensity)
        elif FEEDING_SOURCES[source_text]["kind"] != "human":
            blood_utils.clear_resonance(target)

        line = (
            f"{target.key} feeds ({FEEDING_SOURCES[source_text]['description']}): "
            f"Hunger {result['old_hunger']} -> {result['new_hunger']}."
        )
        if result["penalty_note"]:
            line += f" Blood Potency {target.blood_potency}: {result['penalty_note']}."
        if resonance:
            line += f" Resonance: {resonance} ({RESONANCE_INTENSITIES[intensity]['name']})."
        caller.msg(f"|g{line}|n")
        if target != caller:
            target.msg(f"|g{line}|n")


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
            lines.append(
                "|r|hYou are RAVENOUS!|n You can't Rouse the Blood: no powers that need a Rouse check, "
                "no Blood Surge, no mending."
            )

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

        # A hunger frenzy test still owed (a Rouse past Hunger 5)
        from commands.v5.utils.humanity_utils import pending_frenzy_test

        pending = pending_frenzy_test(self.caller)
        if pending:
            lines.append(
                f"|r|hYou owe a hunger frenzy test (Difficulty {pending.get('difficulty', 4)}):|n "
                "roll it with +frenzy/pending."
            )

        self.caller.msg("\n".join(lines))
