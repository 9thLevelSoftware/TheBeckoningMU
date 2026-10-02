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
from world.v5_data import HUNTING_GROUNDS, PREDATOR_TYPES

from .utils.hunting_utils import find_ground, hunt, hunting_pool

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
        except Exception as err:
            caller.msg(f"|rError creating hunt scene job: {err}|n")
            caller.msg("|yPlease contact staff directly for hunt scenes.|n")
            return

        output = _banner("HUNT SCENE REQUESTED")
        output.append(f"{PALE_IVORY}Your hunt request has been submitted to staff.{RESET}")
        output.append(f"{PALE_IVORY}Job #{job.sequence_number}:{RESET} Hunt Scene at {GOLD}{ground}{RESET}")
        output.append(f"{SHADOW_GREY}Staff will contact you when they're ready to run the scene.{RESET}")
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
