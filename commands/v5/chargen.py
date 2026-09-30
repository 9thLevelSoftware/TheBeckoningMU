"""
Character Generation Commands for V5

Provides a comprehensive character creation system following V5 rules.
"""

from evennia.commands.command import Command
from evennia import default_cmds
from evennia.utils.utils import inherits_from
from .utils import chargen_utils, clan_utils, trait_utils, blood_utils
from world.v5_data import PREDATOR_TYPES
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY,
    BONE_WHITE, GOLD, SUCCESS, RESET,
    DBOX_H, DBOX_V, DBOX_TL, DBOX_TR, DBOX_BL, DBOX_BR
)


class CmdChargen(default_cmds.MuxCommand):
    """
    Character generation system for V5.

    Usage:
      +chargen                  - Show character creation progress
      +chargen/start            - Begin character creation (resets character!)
      +chargen/clan <name>      - Select your clan
      +chargen/predator <type>  - Select your predator type
      +chargen/finalize         - Complete character creation (submit for approval)
      +chargen/reset            - Reset character (WARNING: deletes all data!)

    Examples:
      +chargen
      +chargen/clan Brujah
      +chargen/predator Scene Queen
      +chargen/finalize

    Character creation follows V5 rules:
    - Choose clan and predator type
    - Allocate attributes (7/5/3)
    - Allocate skills (13/9/5)
    - Select starting disciplines (2-3 dots)
    - Choose specialties

    See 'help chargen' for detailed character creation guide.
    """

    key = "+chargen"
    aliases = ["chargen"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Execute chargen command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to use chargen.|n")
            return

        # Handle switches
        if "start" in self.switches:
            self.start_chargen()
        elif "clan" in self.switches:
            self.select_clan()
        elif "predator" in self.switches:
            self.select_predator()
        elif "finalize" in self.switches:
            self.finalize_chargen()
        elif "reset" in self.switches:
            self.reset_chargen()
        else:
            self.show_progress()

    def start_chargen(self):
        """Start or restart character creation."""
        # Warn if character has data
        clan = clan_utils.get_clan(self.caller)
        if clan:
            self.caller.msg(f"{GOLD}Warning:{RESET} This will reset your character to a blank slate!")
            self.caller.msg("If you're sure, use '+chargen/reset' to confirm.")
            return

        result = chargen_utils.start_chargen(self.caller)
        self.caller.msg(result["message"])
        self.caller.msg("\n" + chargen_utils.format_chargen_progress(self.caller))
        self.caller.msg(f"\n{GOLD}Next step:{RESET} {chargen_utils.get_recommended_next_step(self.caller)}")

    def select_clan(self):
        """Select character's clan."""
        if not self.args:
            # Show available clans
            self.caller.msg(clan_utils.list_all_clans())
            self.caller.msg(f"\n{GOLD}Usage:{RESET} +chargen/clan <name>")
            return

        clan_name = self.args.strip()

        # Check for Thin-Blood option
        if clan_name.lower() in ["thin-blood", "thinblood", "thin blood"]:
            # Set as Thin-Blood
            if not hasattr(self.caller.db, 'vampire'):
                self.caller.db.vampire = {}

            self.caller.db.vampire["clan"] = "Thin-Blood"
            self.caller.db.vampire["blood_potency"] = 0  # Thin-Bloods always BP 0

            self.caller.msg(f"\n|gClan set to Thin-Blood!|n\n")
            self.caller.msg("|yThin-Blood Traits:|n")
            self.caller.msg("  - Blood Potency: 0 (cannot create Blood Bonds or ghouls)")
            self.caller.msg("  - Sunlight: Takes bashing damage (not aggravated)")
            self.caller.msg("  - Disciplines: Choose 1 Discipline with flaw OR Thin-Blood Alchemy")
            self.caller.msg("  - Blush of Life: Easier to maintain mortal appearance")
            self.caller.msg(f"\n{GOLD}Next:{RESET} Use '+setdisc thin-blood alchemy = 1' to learn Alchemy")
            self.caller.msg("       OR choose a standard discipline with a Thin-Blood flaw")

            chargen_utils.set_chargen_step(self.caller, "disciplines")
            return

        # Validate clan selection
        valid, error_msg = clan_utils.validate_clan_selection(self.caller, clan_name)
        if not valid:
            self.caller.msg(f"|rError:|n {error_msg}")
            return

        # Set clan
        try:
            success = clan_utils.set_clan(self.caller, clan_name)
            if success:
                self.caller.msg(f"\n|gClan set to {clan_name}!|n\n")
                self.caller.msg(clan_utils.format_clan_display(self.caller))
                self.caller.msg(f"\n{GOLD}Next step:{RESET} {chargen_utils.get_recommended_next_step(self.caller)}")
                chargen_utils.set_chargen_step(self.caller, "predator")
            else:
                self.caller.msg(f"|rFailed to set clan.|n")
        except ValueError as e:
            self.caller.msg(f"|rError:|n {e}")

    def select_predator(self):
        """Select character's predator type."""
        if not self.args:
            # Show available predator types with colored header
            lines = []
            lines.append(f"{DARK_RED}{DBOX_TL}{DBOX_H * 70}{DBOX_TR}")
            lines.append(f"{DBOX_V} {BONE_WHITE}PREDATOR TYPES{RESET}{' ' * 54}{DARK_RED}{DBOX_V}")
            lines.append(f"{DBOX_BL}{DBOX_H * 70}{DBOX_BR}{RESET}")
            lines.append("")

            for predator_name, predator_data in sorted(PREDATOR_TYPES.items()):
                lines.append(f"{BONE_WHITE}{predator_name}{RESET}")
                lines.append(f"  {PALE_IVORY}{predator_data['description']}{RESET}")
                lines.append(f"  {SHADOW_GREY}Specialty:{RESET} {GOLD}{predator_data['specialty']}{RESET}")
                lines.append("")

            lines.append(f"{GOLD}Usage:{RESET} +chargen/predator <type>")
            self.caller.msg("\n".join(lines))
            return

        predator_name = self.args.strip()

        # Validate predator type
        if predator_name not in PREDATOR_TYPES:
            self.caller.msg(f"|rInvalid predator type:|n {predator_name}")
            self.caller.msg("Use '+chargen/predator' to see available types.")
            return

        # Set predator type
        self.caller.db.vampire["predator_type"] = predator_name
        predator_data = PREDATOR_TYPES[predator_name]

        self.caller.msg(f"\n|gPredator Type set to {predator_name}!|n")
        self.caller.msg(f"Description: {predator_data['description']}")
        self.caller.msg(f"Specialty: {predator_data['specialty']}")
        self.caller.msg(f"\n{GOLD}Next step:{RESET} {chargen_utils.get_recommended_next_step(self.caller)}")
        chargen_utils.set_chargen_step(self.caller, "attributes")

    def finalize_chargen(self):
        """Finalize character creation and submit for approval."""
        # Check if character is complete
        success, message = chargen_utils.mark_chargen_complete(self.caller)

        if not success:
            self.caller.msg(f"|rCannot finalize character creation:|n\n{message}")
            self.caller.msg("\n" + chargen_utils.format_chargen_progress(self.caller))
            return

        self.caller.msg(f"|g{message}|n")
        self.caller.msg(f"\n{GOLD}Your character has been submitted for staff approval.|n")
        self.caller.msg("Staff will review your character and approve or provide feedback.")
        self.caller.msg("\nYou can view your character with '+sheet'.")

        # Create approval job in Jobs system
        try:
            from jobs.models import Job, Bucket

            # Get or create Approval bucket
            approval_bucket, created = Bucket.objects.get_or_create(
                name="Approval",
                defaults={
                    'description': 'Character approval requests',
                    'created_by': self.caller.account
                }
            )

            # Create character sheet summary for job description
            clan = clan_utils.get_clan(self.caller)
            predator = self.caller.db.vampire.get("predator_type", "Unknown")

            description = f"""New character approval request for {self.caller.name}

Clan: {clan}
Predator Type: {predator}

Please review the character sheet using: +sheet {self.caller.name}

To approve: +approve {self.caller.name}
To reject: +reject {self.caller.name} <reason>"""

            # Create the job
            job = Job.objects.create(
                title=f"Character Approval: {self.caller.name}",
                description=description,
                creator=self.caller.account,
                bucket=approval_bucket,
                priority='MEDIUM'
            )

            # Add player to the job
            job.players.add(self.caller.account)
            job.save()

            self.caller.msg(f"\n|gApproval request created as Job #{job.sequence_number} in {approval_bucket.name} bucket.|n")
            self.caller.msg(f"{GOLD}Staff have been notified and will review your character.|n")

        except Exception as e:
            # If job creation fails, don't block character creation
            self.caller.msg(f"\n{GOLD}Warning:{RESET} Could not create approval job: {e}")
            self.caller.msg(f"{GOLD}Please notify staff that your character is ready for approval.|n")

    def reset_chargen(self):
        """Reset character creation (WARNING: deletes all data)."""
        self.caller.msg("|r!!! WARNING !!!|n")
        self.caller.msg("This will completely reset your character, deleting all data.")
        self.caller.msg("To confirm, type: |y+chargen/reset confirm|n")

        if "confirm" in self.args.lower():
            chargen_utils.reset_chargen(self.caller)
            self.caller.msg("|gCharacter reset complete.|n")
            self.caller.msg("Use '+chargen/start' to begin character creation.")
        else:
            return

    def show_progress(self):
        """Show character creation progress."""
        self.caller.msg(chargen_utils.format_chargen_progress(self.caller))
        self.caller.msg(f"\n{GOLD}Recommendation:{RESET} {chargen_utils.get_recommended_next_step(self.caller)}")


class CmdSetStat(default_cmds.MuxCommand):
    """
    Set an attribute, skill, or discipline during character creation.

    Usage:
      +setstat <trait> = <value>
      +setstat/specialty <skill> = <specialty name>

    Examples:
      +setstat strength = 3
      +setstat brawl = 2
      +setstat celerity = 2
      +setstat/specialty brawl = Grappling

    This command is used during character creation to allocate dots.
    You must follow V5 allocation rules:
    - Attributes: 7/5/3 distribution (minimum 1, maximum 5)
    - Skills: 13/9/5 distribution (minimum 0, maximum 5)
    - Disciplines: 2-3 dots total at creation

    See 'help chargen' for detailed rules.
    """

    key = "+setstat"
    aliases = ["setstat"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Execute setstat command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to use this command.|n")
            return

        # Check if in character creation
        if chargen_utils.is_character_approved(self.caller):
            self.caller.msg("|rYou cannot modify stats after approval. Use +xp to spend experience.|n")
            return

        # Parse arguments
        if not self.args or "=" not in self.args:
            self.caller.msg("Usage: +setstat <trait> = <value>")
            return

        trait_name, value_str = self.args.split("=", 1)
        trait_name = trait_name.strip().lower()
        value_str = value_str.strip()

        # Handle specialty
        if "specialty" in self.switches:
            success = trait_utils.set_specialty(self.caller, trait_name, value_str)
            if success:
                self.caller.msg(f"|gSpecialty set:|n {trait_name.title()} ({value_str})")
                chargen_utils.set_chargen_step(self.caller, "specialties")
            else:
                self.caller.msg(f"|rCannot set specialty.|n Skill must have at least 1 dot.")
            return

        # Parse value
        try:
            value = int(value_str)
        except ValueError:
            self.caller.msg(f"|rInvalid value:|n '{value_str}' is not a number.")
            return

        # Try to set the trait
        try:
            success = trait_utils.set_trait_value(self.caller, trait_name, value)
            if success:
                self.caller.msg(f"|gSet {trait_name.title()} to {value}|n")

                # Show progress for relevant category
                if value > 0:
                    # Determine what was modified and show appropriate feedback
                    progress = chargen_utils.get_chargen_progress(self.caller)
                    self.caller.msg(f"Attributes: {progress['attributes'][0]}/{progress['attributes'][1]}/{progress['attributes'][2]}")
                    self.caller.msg(f"Skills: {progress['skills'][0]}/{progress['skills'][1]}/{progress['skills'][2]}")
                    self.caller.msg(f"Disciplines: {progress['disciplines']} dots")
            else:
                self.caller.msg(f"|rFailed to set {trait_name}.|n Trait not found.")
                self.caller.msg("Use '+sheet' to see available traits.")
        except ValueError as e:
            self.caller.msg(f"|rError:|n {e}")


class CmdSetDiscipline(Command):
    """
    Set a discipline during character creation.

    Usage:
      +setdisc <discipline> = <level>

    Examples:
      +setdisc celerity = 2
      +setdisc potence = 1

    During character creation, you may allocate 2-3 discipline dots.
    In-clan disciplines are recommended for starting characters.

    Your clan's in-clan disciplines are shown on your character sheet.
    """

    key = "+setdisc"
    aliases = ["setdisc"]
    locks = "cmd:all()"
    help_category = "Character"

    def func(self):
        """Execute setdisc command."""
        # Validate caller is a character
        if not inherits_from(self.caller, "typeclasses.characters.Character"):
            self.caller.msg("|rYou must be in character to use this command.|n")
            return

        # Check if in character creation
        if chargen_utils.is_character_approved(self.caller):
            self.caller.msg("|rYou cannot modify disciplines after approval. Use +xp to spend experience.|n")
            return

        # Parse arguments
        if not self.args or "=" not in self.args:
            # Show in-clan disciplines
            inclan = clan_utils.get_inclan_disciplines(self.caller)
            if inclan:
                self.caller.msg(f"|wYour in-clan disciplines:|n {', '.join(inclan)}")
            else:
                self.caller.msg("Select a clan first with '+chargen/clan <name>'")
            self.caller.msg(f"\n{GOLD}Usage:{RESET} +setdisc <discipline> = <level>")
            return

        discipline_name, value_str = self.args.split("=", 1)
        discipline_name = discipline_name.strip()
        value_str = value_str.strip()

        # Parse value
        try:
            value = int(value_str)
        except ValueError:
            self.caller.msg(f"|rInvalid value:|n '{value_str}' is not a number.")
            return

        # Validate value
        if value < 0 or value > 3:
            self.caller.msg("|rDiscipline level must be between 0 and 3 during character creation.|n")
            return

        # Check if in-clan
        inclan = clan_utils.is_discipline_inclan(self.caller, discipline_name)
        if not inclan:
            self.caller.msg(f"{GOLD}Warning:{RESET} {discipline_name} is not in-clan for you.")
            self.caller.msg("Starting with out-of-clan disciplines requires staff approval.")

        # Set discipline
        disciplines = self.caller.db.stats.get("disciplines", {})
        disciplines[discipline_name.lower()] = {
            "level": value,
            "powers": []  # Powers will be selected later or automatically granted
        }

        self.caller.msg(f"|gSet {discipline_name} to {value}|n")

        # Show total discipline dots
        total = trait_utils.get_total_discipline_dots(self.caller)
        self.caller.msg(f"Total discipline dots: {total} (need 2-3)")

        chargen_utils.set_chargen_step(self.caller, "disciplines")
