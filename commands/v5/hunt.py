"""
V5 Hunting Commands

Commands for hunting and feeding mechanics with staff-run hunt scenes.
"""

from evennia import Command, default_cmds

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

from .utils.blood_utils import get_hunger
from .utils.hunting_utils import (
    HUNTING_DIFFICULTIES,
    get_predator_hunting_bonus,
    hunt_prey,
)


class CmdHunt(default_cmds.MuxCommand):
    """
    Hunt for prey to feed upon.

        +hunt/story opt-in | opt-out
        +hunt/story start [location] [persona #dbref]
        +hunt/story resume [action] | complete
        +hunt/staffed [<location>]

    Locations:
        club       - Nightclubs, bars, scenes (Difficulty 3)
        street     - Streets, alleys (Difficulty 4)
        residential - Residential areas (Difficulty 5)
        hospital   - Hospitals, medical facilities (Difficulty 6)
        secured    - Gated communities (Difficulty 7)
        rural      - Rural/wilderness areas (Difficulty 4)

        /story - Opt-in, start, resume, act in, or complete a prose-only story hunt
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
        if "story" in self.switches:
            self._story_hunt()
            return

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

    def _story_hunt(self):
        """Run the opt-in prose-only hunt flow with deterministic mechanics."""
        from narrative.models import NarrativeConsent, NarrativePersona, StorySession
        from narrative.services import configured_provider, generate_story, set_consent, start_session

        caller = self.caller
        account = getattr(caller, "account", None)
        if not account or not getattr(caller, "id", None):
            caller.msg("|rA logged-in character is required for story hunting.|n")
            return
        words = self.args.strip().split(maxsplit=1) if self.args else []
        verb = words[0].lower() if words else "resume"
        rest = words[1] if len(words) > 1 else ""

        if verb in ("opt-in", "optin", "on"):
            set_consent(account, caller, True)
            caller.msg("Story hunting is enabled. Use |w+ hunt/story start [location]|n to begin; no AI request was made.")
            return
        if verb in ("opt-out", "optout", "off"):
            set_consent(account, caller, False)
            caller.msg("Story hunting is disabled and your active story session is closed.")
            return
        consent = NarrativeConsent.objects.filter(account=account, character=caller, opted_in=True).first()
        if consent is None:
            caller.msg("Story hunting is opt-in. Use |w+ hunt/story opt-in|n before any story request.")
            return

        if verb == "complete":
            session = caller.narrative_sessions.filter(status=StorySession.Status.ACTIVE).first()
            if session is None:
                caller.msg("You have no active story session.")
                return
            session.complete()
            caller.msg("Your story session is complete; its raw player action text was expired.")
            return
        if configured_provider() is None:
            caller.msg("|rNarrative AI is not configured. No story request was sent.|n")
            return

        if verb == "start":
            start_parts = rest.split()
            location = start_parts[0].lower() if start_parts else "street"
            persona = None
            if len(start_parts) > 1:
                dbref = start_parts[1].lstrip("#")
                if not dbref.isdigit():
                    caller.msg("Use a registered persona ObjectDB id, for example: +hunt/story start street #123.")
                    return
                persona = NarrativePersona.objects.filter(character_id=int(dbref)).first()
                if persona is None:
                    caller.msg("|rNo registered narrative persona has that ObjectDB id.|n")
                    return
            if location not in HUNTING_DIFFICULTIES:
                caller.msg(f"|rInvalid location. Valid locations: {', '.join(HUNTING_DIFFICULTIES)}|n")
                return
            session = caller.narrative_sessions.filter(status=StorySession.Status.ACTIVE).first()
            if session is None:
                if not getattr(caller.db, "vampire", None):
                    caller.msg("|rYou are not a vampire!|n")
                    return
                hunger = get_hunger(caller)
                if hunger == 0:
                    caller.msg("|gYou are fully sated. You do not need to hunt right now.|n")
                    return
                predator_info = get_predator_hunting_bonus(caller)
                result = self._resolve_story_hunt(location, predator_info)
                session = start_session(caller, location, result, persona=persona)
            action = f"Begin the hunt scene at {location}."
        else:
            session = caller.narrative_sessions.filter(status=StorySession.Status.ACTIVE).first()
            if session is None:
                caller.msg("You have no active story session. Use |w+ hunt/story start [location]|n.")
                return
            action = rest if verb == "resume" and rest else (
                "Resume the scene." if verb == "resume" else self.args.strip()
            )
        session.current_action = action
        session.save(update_fields=("current_action", "updated_at"))
        try:
            deferred = generate_story(session, action)
        except (RuntimeError, PermissionError, ValueError) as exc:
            session.current_action = ""
            session.save(update_fields=("current_action", "updated_at"))
            caller.msg(f"|r{exc}|n")
            return
        caller.msg("|wYour action is being woven into the hunt scene...|n")

        def show_prose(prose):
            caller.msg("|w[AI-generated narrative]|n")
            caller.msg(f"|c{prose.replace('|', '||')}|n")
            return prose

        def show_error(_failure):
            caller.msg("|rThe story request failed; it has been recorded and no additional hunt mechanics were changed.|n")
            return None

        deferred.addCallbacks(show_prose, show_error)

    def _resolve_story_hunt(self, location, predator_info):
        """Resolve through the existing deterministic hunt mechanics exactly once."""
        caller = self.caller
        vamp = caller.db.vampire or {}
        predator_skills = {
            "Alleycat": "stealth", "Sandman": "stealth", "Scene Queen": "streetwise",
            "Siren": "persuasion", "Consensualist": "persuasion", "Bagger": "streetwise",
            "Farmer": "animal_ken",
        }
        result = hunt_prey(
            caller, location=location,
            skill_name=predator_skills.get(vamp.get("predator_type"), "streetwise"),
            predator_type_bonus=predator_info.get("bonus_dice", 0), kill=False,
        )
        return {
            "hunting_success": bool(result.get("hunting_success")),
            "location": location,
            "hunger_before": result.get("old_hunger"),
            "hunger_after": result.get("new_hunger"),
            "hunger_reduction": result.get("hunger_reduction", 0),
            "resonance": result.get("resonance"),
            "complications": result.get("complications", []),
        }
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
            from jobs.models import Bucket, Job
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


