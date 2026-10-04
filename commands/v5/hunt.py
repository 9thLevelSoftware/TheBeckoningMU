"""
V5 Hunting Commands

+hunt rolls the predator type's hunting pool on a hunting ground (QR p.12)
and feeds on a win; +hunt/staffed asks staff for a hunt scene, which they
finish with `feed`. These are the only ways to feed: `feed` itself is a
staff command.
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

from .utils.hunting_utils import find_ground, hunt, hunting_pool
from world.v5_data import HUNTING_GROUNDS, PREDATOR_TYPES

GROUND_LIST = ", ".join(f"{key} ({data['difficulty']})" for key, data in HUNTING_GROUNDS.items())


def _banner(title):
    return [
        f"\n{DARK_RED}{BOX_TL}{BOX_H * 76}{BOX_TR}{RESET}",
        f"{BOX_V} {PALE_IVORY}{title}{RESET}{' ' * (75 - len(title))}{BOX_V}",
        f"{DARK_RED}{BOX_BL}{BOX_H * 76}{BOX_BR}{RESET}",
    ]


class CmdHunt(default_cmds.MuxCommand):
    """
    Hunt for a vessel and feed.

    Usage:
        +hunt <hunting ground>
        +hunt <hunting ground>=alt          (your predator type's alternative pool)
        +hunt/staffed <hunting ground>
        +hunt/reset <character>             (staff: allow another hunt now)
        +hunt/story opt-in | opt-out
        +hunt/story start [location] [persona #dbref]
        +hunt/story resume [action] | complete
        +hunt/staffed [<location>]

    Hunting grounds and their difficulty (QR p.12):
        slum      2  slums, Skid Row, housing projects
        bohemian  3  bohemian, gentrifying or blighted neighborhoods
        downtown  4  working-class neighborhoods, downtown, tourist areas
        suburbs   5  industrial districts, parkland, suburban sprawl
        wealthy   6  wealthy neighborhoods

    You roll your predator type's hunting pool (see +huntinfo) against the
    ground's difficulty, with your Hunger dice. On a win you feed: a human
    vessel gives the most you can drink without harming them, which slakes
    2 Hunger (a Farmer feeds on an animal, a Bagger on a blood bag). Your
    Blood Potency may slake less, and without killing you can't go below
    Hunger 1 (2 or 3 at high Blood Potency). The vessel's resonance is set
    on your blood.
        /story - Opt-in, start, resume, act in, or complete a prose-only story hunt
        /quick - Quick automated hunt (single roll)
        /staffed - Request staff-run hunt scene (creates a Job)

    You can hunt once every 24 hours, whether or not you find a vessel, and
    not at all once your Hunger is as low as feeding without a kill can take
    it. Staff-run scenes (+hunt/staffed) are the way to feed more. Your
    resonance changes only when the hunt slakes Hunger.

    Blood Leeches and characters without a predator type have no hunting
    roll: use +hunt/staffed, which asks staff for a hunt scene.
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
        if "reset" in self.switches:
            self._reset()
            return
        if not caller.attributes.has("vampire") or not caller.is_kindred:
            caller.msg("|rOnly vampires hunt.|n")
            return

        alternative = (self.rhs or "").strip().lower() in ("alt", "alternative")
        if self.rhs and not alternative:
            caller.msg("Usage: +hunt <hunting ground>[=alt]")
            return
        ground = find_ground(self.lhs) if (self.lhs or "").strip() else None
        if ground is None:
            caller.msg(f"Usage: +hunt <hunting ground>. Grounds (difficulty): {GROUND_LIST}")
            return

        if "staffed" in self.switches:
            self._create_hunt_job(ground)
            return

        if caller.hunger == 0:
            caller.msg("|gYou are sated. You don't need to hunt.|n")
            return

        from dice.commands import forget_roll

        forget_roll(caller)  # a Willpower re-roll can't reach back past this roll
        result = hunt(caller, ground, alternative=alternative)
        if result["refused"]:
            caller.msg(f"|y{result['refused']}|n")
            return

        output = _banner("SUCCESSFUL HUNT" if result["success"] else "HUNT FAILED")
        output.append(
            f"{GOLD}Hunting roll:{RESET} {result['pool_text']} ({result['breakdown']}) vs Difficulty "
            f"{result['difficulty']} ({ground})"
        )
        output.append(result["roll"].format_result(show_details=True))
        output.append("")
        output.append(result["message"])
        if result["resonance"]:
            output.append(f"Resonance: |y{result['resonance']['type']}|n ({result['resonance']['intensity_name']})")
        if result["complication"]:
            output.append(f"|rComplication:|n {result['complication']['desc']} (the Storyteller decides what follows)")
        caller.msg("\n".join(output))

    def _story_hunt(self):
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
            location = find_ground(start_parts[0] if start_parts else "downtown")
            if location is None:
                caller.msg(f"|rInvalid location. Valid locations: {', '.join(HUNTING_GROUNDS)}|n")
                return
            persona = None
            if len(start_parts) > 1:
                dbref = start_parts[1].lstrip("#")
                if not dbref.isdigit():
                    caller.msg("Use a registered persona ObjectDB id, for example: +hunt/story start downtown #123.")
                    return
                persona = NarrativePersona.objects.filter(character_id=int(dbref)).first()
                if persona is None:
                    caller.msg("|rNo registered narrative persona has that ObjectDB id.|n")
                    return
            session = caller.narrative_sessions.filter(status=StorySession.Status.ACTIVE).first()
            if session is None:
                if not caller.attributes.has("vampire") or not caller.is_kindred:
                    caller.msg("|rOnly vampires can hunt.|n")
                    return
                if caller.hunger == 0:
                    caller.msg("|gYou are fully sated. You do not need to hunt right now.|n")
                    return
                result = hunt(caller, location)
                if result.get("refused"):
                    caller.msg(f"|y{result['refused']}|n")
                    return
                feeding = result.get("feeding") or {}
                narrative_result = {
                    "hunting_success": bool(result.get("success")),
                    "location": location,
                    "hunger_before": feeding.get("old_hunger"),
                    "hunger_after": feeding.get("new_hunger"),
                    "hunger_reduction": feeding.get("slaked", 0),
                    "resonance": result.get("resonance", {}).get("type") if result.get("resonance") else None,
                    "complications": [result["complication"]] if result.get("complication") else [],
                }
                session = start_session(caller, location, narrative_result, persona=persona)
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

    def _reset(self):
        from dice.commands import _is_staff

        caller = self.caller
        if not _is_staff(caller):
            caller.msg("|rOnly staff can reset a hunt.|n")
            return
        target = caller.search(self.args.strip()) if self.args.strip() else None
        if not target:
            caller.msg("Usage: +hunt/reset <character>")
            return
        target.last_hunt = None
        caller.msg(f"{target.key} may hunt again.")

    def _create_hunt_job(self, ground):
        """Create a Job for staff to run a hunt scene."""
        caller = self.caller
        try:
            from jobs.models import Bucket, Job
        except ImportError:
            caller.msg("|rJobs system not available. Please contact staff.|n")
            return

        pool_text, refusal = hunting_pool(caller)
        data = HUNTING_GROUNDS[ground]
        try:
            hunt_bucket, _created = Bucket.objects.get_or_create(
                name="Hunt Scenes",
                defaults={'description': 'Staff-run hunting scenes for players', 'created_by': caller.account},
            )
            description = (
                f"Hunt Scene Request from {caller.name}\n\n"
                f"**Hunting ground:** {data['description']} (Difficulty {data['difficulty']})\n"
                f"**Current Hunger:** {caller.hunger}/5\n"
                f"**Predator Type:** {caller.predator_type or 'none'}\n"
                f"**Hunting pool:** {pool_text or refusal}\n\n"
                "Run the hunt as a scene, then record the feeding with "
                f"'feed {caller.name}=<source>' (see 'help feed').\n\n"
                f"To view character sheet: +sheet {caller.name}"
            )
            job = Job.objects.create(
                title=f"Hunt Scene: {caller.name} ({ground})",
                description=description,
                creator=caller.account,
                bucket=hunt_bucket,
                priority='MEDIUM',
            )
            job.players.add(caller.account)
            job.save()
            from chronicle.services import record_event

            record_event(
                idempotency_key=f"jobs:{job.pk}:job.created:{job.created_at.isoformat()}",
                source_app="jobs",
                source_type="Job",
                source_id=str(job.pk),
                kind="job.created",
                title="Job created",
                summary="A staff-run hunt scene was requested.",
                payload={"job_state": job.status, "job_priority": job.priority},
                visibility="participants",
                actor=caller.account,
                participants=(caller,),
                occurred_at=job.created_at,
            )
        except Exception as err:
            caller.msg(f"|rError creating hunt scene job: {err}|n")
            caller.msg("|yPlease contact staff directly for hunt scenes.|n")
            return

        output = _banner("HUNT SCENE REQUESTED")
        output.append(f"{PALE_IVORY}Your hunt request has been submitted to staff.{RESET}")
        output.append(f"{PALE_IVORY}Job {job.ref}:{RESET} Hunt Scene at {GOLD}{ground}{RESET}")
        output.append(f"{SHADOW_GREY}Staff will contact you when they're ready to run the scene.{RESET}")
        output.append(f"{SHADOW_GREY}You can check the status with: |w+job {job.ref}|x{RESET}")
        caller.msg("\n".join(output))


class CmdHuntingInfo(Command):
    """
    Show your hunting roll, the hunting grounds and your Hunger.

    Usage:
        +huntinfo
    """

    key = "+huntinfo"
    aliases = ["huntinfo"]
    locks = "cmd:all()"
    help_category = "V5"

    def func(self):
        caller = self.caller
        if not caller.attributes.has("vampire"):
            caller.msg("|rYou are not a vampire!|n")
            return

        output = _banner("HUNTING INFORMATION")
        hunger = caller.hunger
        output.append(f"\n{PALE_IVORY}Current Hunger:{RESET} {BLOOD_RED}{'●' * hunger}{SHADOW_GREY}{'○' * (5 - hunger)}{RESET} ({hunger}/5)")

        predator = caller.predator_type
        pool_text, refusal = hunting_pool(caller)
        output.append(f"\n{PALE_IVORY}Predator Type:{RESET} {GOLD}{predator or 'none'}{RESET}")
        if predator:
            output.append(f"  {PREDATOR_TYPES[predator]['description']}")
        output.append(f"{PALE_IVORY}Hunting roll:{RESET} {pool_text or refusal}")
        alt_pool, _ = hunting_pool(caller, alternative=True)
        if alt_pool:
            output.append(f"{PALE_IVORY}Alternative roll:{RESET} {alt_pool} (+hunt <ground>=alt)")

        output.append(f"\n{PALE_IVORY}Hunting grounds (QR p.12):{RESET}")
        for key, data in HUNTING_GROUNDS.items():
            output.append(f"  {GOLD}{key:<10}{RESET} Difficulty {data['difficulty']}  {SHADOW_GREY}{data['description']}{RESET}")
        output.append(f"\n{SHADOW_GREY}Use |w+hunt <ground>|x to hunt.{RESET}")
        caller.msg("\n".join(output))
