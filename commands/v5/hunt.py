"""
V5 Hunting Commands

Commands for hunting and feeding mechanics with staff-run hunt scenes.
"""

from evennia import Command
from evennia import default_cmds
from .utils.hunting_utils import (
    hunt_prey,
    get_predator_hunting_bonus,
    generate_hunting_opportunity,
    HUNTING_DIFFICULTIES
)
from .utils.blood_utils import get_hunger
from world.ansi_theme import (
    BLOOD_RED, DARK_RED, PALE_IVORY, SHADOW_GREY,
    GOLD, RESET, BOX_H, BOX_V, BOX_TL, BOX_TR, BOX_BL, BOX_BR
)


class CmdHunt(default_cmds.MuxCommand):
    """
    Hunt for prey to feed upon.

    Usage:
        +hunt [<location>]
        +hunt/quick [<location>]
        +hunt/staffed [<location>]

    Locations:
        club       - Nightclubs, bars, scenes (Difficulty 3)
        street     - Streets, alleys (Difficulty 4)
        residential - Residential areas (Difficulty 5)
        hospital   - Hospitals, medical facilities (Difficulty 6)
        secured    - Gated communities (Difficulty 7)
        rural      - Rural/wilderness areas (Difficulty 4)

    Switches:
        /quick - Quick automated hunt (single roll)
        /staffed - Request staff-run hunt scene (creates a Job)

    Examples:
        +hunt club
        +hunt/quick street
        +hunt/staffed residential
    """

    key = "+hunt"
    aliases = ["hunt"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        """Execute hunt command."""
        caller = self.caller

        # Check if character has vampire data
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("|rYou are not a vampire!|n")
            return

        # Parse location
        location = self.args.strip().lower() if self.args else "street"
        if location not in HUNTING_DIFFICULTIES:
            valid_locations = ", ".join(HUNTING_DIFFICULTIES.keys())
            caller.msg(f"|rInvalid location. Valid locations: {valid_locations}|n")
            return

        # Check Hunger level (no need to hunt if not hungry)
        hunger = get_hunger(caller)
        if hunger == 0:
            caller.msg("|gYou are fully sated. You do not need to hunt right now.|n")
            return

        # Get Predator Type bonuses
        predator_info = get_predator_hunting_bonus(caller)

        # Check if using /staffed switch for staff-run hunt scene
        if "staffed" in self.switches:
            self._create_hunt_job(location, predator_info, hunger)
            return

        # Quick hunt (default)
        self._quick_hunt(location, predator_info)

    def _quick_hunt(self, location, predator_info):
        """Quick automated hunting (single roll)."""
        caller = self.caller

        # Determine skill to use (based on Predator Type or default to Streetwise)
        vamp = caller.db.vampire if hasattr(caller.db, 'vampire') else {}
        predator_type = vamp.get('predator_type', None)

        # Map predator types to skills
        predator_skills = {
            "Alleycat": "stealth",
            "Sandman": "stealth",
            "Scene Queen": "streetwise",
            "Siren": "persuasion",
            "Consensualist": "persuasion",
            "Bagger": "streetwise",
            "Farmer": "animal_ken"
        }

        skill_name = predator_skills.get(predator_type, "streetwise")

        # Perform hunt
        result = hunt_prey(
            caller,
            location=location,
            skill_name=skill_name,
            predator_type_bonus=predator_info.get("bonus_dice", 0),
            kill=False  # Default: don't kill
        )

        # Display results
        self._display_hunt_result(result, location)

    def _create_hunt_job(self, location, predator_info, hunger):
        """Create a Job for staff to run a hunt scene."""
        caller = self.caller

        # Import Jobs system
        try:
            from jobs.models import Job, Bucket
        except ImportError:
            caller.msg("|rJobs system not available. Please contact staff.|n")
            return

        # Get vampire data for job context
        vamp = caller.db.vampire if hasattr(caller.db, 'vampire') else {}
        predator_type = vamp.get('predator_type', 'Unknown')

        # Get or create Hunt Scenes bucket
        try:
            hunt_bucket, created = Bucket.objects.get_or_create(
                name="Hunt Scenes",
                defaults={
                    'description': 'Staff-run hunting scenes for players',
                    'created_by': caller.account
                }
            )

            # Build job description with hunt context
            description = f"""Hunt Scene Request from {caller.name}

**Location:** {location.title()} (Difficulty {HUNTING_DIFFICULTIES[location]})
**Current Hunger:** {hunger}/5
**Predator Type:** {predator_type}
**Hunting Bonus:** +{predator_info.get('bonus_dice', 0)} dice
**Preferred Locations:** {', '.join(predator_info.get('preferred_locations', ['none']))}

Player has requested a staff-run hunt scene at this location. Staff should:
1. Run an interactive hunt scene via @tel or +summon
2. Use the hunting difficulty for this location
3. Consider the character's Predator Type for roleplay
4. Use 'feed' command to finalize the feeding result

To view character sheet: +sheet {caller.name}"""

            # Create the job
            job = Job.objects.create(
                title=f"Hunt Scene: {caller.name} at {location.title()}",
                description=description,
                creator=caller.account,
                bucket=hunt_bucket,
                priority='NORMAL'
            )

            job.players.add(caller.account)
            job.save()

            # Notify player
            output = []
            output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
            output.append(f"{BOX_V} {BLOOD_RED}{RESET} {PALE_IVORY}HUNT SCENE REQUESTED{RESET}{' ' * 51}{BOX_V}")
            output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")
            output.append("")
            output.append(f"{PALE_IVORY}Your hunt request has been submitted to staff.{RESET}")
            output.append(f"{PALE_IVORY}Job #{job.sequence_number}:{RESET} Hunt Scene at {GOLD}{location.title()}{RESET}")
            output.append("")
            output.append(f"{SHADOW_GREY}Staff will contact you when they're ready to run the scene.{RESET}")
            output.append(f"{SHADOW_GREY}You can check the status with: |w+job {job.sequence_number}|x{RESET}")

            caller.msg("\n".join(output))

        except Exception as e:
            caller.msg(f"|rError creating hunt scene job: {e}|n")
            caller.msg("|yPlease contact staff directly for hunt scenes.|n")

    def _display_hunting_scene(self, opportunity):
        """Display the hunting opportunity scene."""
        caller = self.caller

        output = []
        output.append(f"{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {BLOOD_RED}{RESET} {PALE_IVORY}HUNTING SCENE{RESET}{' ' * 60}{BOX_V}")
        output.append(f"{BOX_V} {GOLD}Location:{RESET} {opportunity['location'].title()}{' ' * (67 - len(opportunity['location']))}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")
        output.append("")
        output.append(f"{PALE_IVORY}You spot a potential vessel:{RESET}")
        output.append(f"  {opportunity['prey_description']}")
        output.append(f"  {opportunity['hook']}")
        output.append("")
        output.append(f"{PALE_IVORY}Resonance:{RESET} {GOLD}{opportunity['resonance']['type']}{RESET} ({opportunity['resonance']['intensity_name']})")
        output.append(f"{PALE_IVORY}Difficulty:{RESET} {opportunity['difficulty']}")
        output.append("")
        output.append(f"{SHADOW_GREY}Potential Risks:{RESET}")
        for risk in opportunity['risks']:
            output.append(f"  {SHADOW_GREY}- {risk['desc']} ({risk['severity']}){RESET}")

        caller.msg("\n".join(output))

    def _display_hunt_result(self, result, location):
        """Display hunting results."""
        caller = self.caller

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")

        if result["hunting_success"]:
            output.append(f"{BOX_V} {BLOOD_RED}{RESET} {PALE_IVORY}SUCCESSFUL HUNT{RESET}{' ' * 58}{BOX_V}")
        else:
            output.append(f"{BOX_V} {SHADOW_GREY}{RESET} {PALE_IVORY}HUNT FAILED{RESET}{' ' * 62}{BOX_V}")

        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")
        output.append("")
        output.append(result["message"])

        caller.msg("\n".join(output))


class CmdHuntingInfo(Command):
    """
    Display information about hunting and feeding.

    Usage:
        +huntinfo
        +huntinfo <location>

    Shows hunting difficulties, your Predator Type bonuses, and current Hunger.
    """

    key = "+huntinfo"
    aliases = ["huntinfo"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        """Execute huntinfo command."""
        caller = self.caller

        # Check if character has vampire data
        if not hasattr(caller.db, 'vampire') or not caller.db.vampire:
            caller.msg("|rYou are not a vampire!|n")
            return

        output = []
        output.append(f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}")
        output.append(f"{BOX_V} {BLOOD_RED}{RESET} {PALE_IVORY}HUNTING INFORMATION{RESET}{' ' * 54}{BOX_V}")
        output.append(f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}")

        # Current Hunger
        hunger = get_hunger(caller)
        output.append(f"\n{PALE_IVORY}Current Hunger:{RESET} {BLOOD_RED}{'●' * hunger}{SHADOW_GREY}{'○' * (5 - hunger)}{RESET} ({hunger}/5)")

        # Predator Type Info
        vamp = caller.db.vampire if hasattr(caller.db, 'vampire') else {}
        predator_type = vamp.get('predator_type', 'Unknown')
        predator_info = get_predator_hunting_bonus(caller)

        output.append(f"\n{PALE_IVORY}Predator Type:{RESET} {GOLD}{predator_type}{RESET}")
        output.append(f"{PALE_IVORY}Hunting Bonus:{RESET} +{predator_info.get('bonus_dice', 0)} dice")
        output.append(f"{PALE_IVORY}Preferred Locations:{RESET} {', '.join(predator_info.get('preferred_locations', ['none']))}")

        if predator_info.get('special_ability'):
            output.append(f"{PALE_IVORY}Special:{RESET} {predator_info['special_ability']}")

        # Hunting Difficulties
        output.append(f"\n{PALE_IVORY}Hunting Difficulties by Location:{RESET}")
        for location, diff in sorted(HUNTING_DIFFICULTIES.items()):
            if location != "default":
                output.append(f"  {GOLD}{location.title():<15}{RESET} Difficulty {diff}")

        output.append(f"\n{SHADOW_GREY}Use |w+hunt <location>|x to hunt for prey.{RESET}")

        caller.msg("\n".join(output))


