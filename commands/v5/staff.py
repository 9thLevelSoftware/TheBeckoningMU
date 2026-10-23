"""
Staff commands for running scenes: torpor and NPCs.
"""

import time

from evennia import create_object, default_cmds
from evennia.utils.utils import inherits_from

from typeclasses.characters import SPLATS

CHARACTER_TYPECLASS = "typeclasses.characters.Character"

# Staff NPCs belong to no account and have no CharacterBio (KD-4): the
# approval gate in CHARACTER_LOCKS never passes for them, so Builders get
# puppet, and edit/control/delete so they can @set, @desc and remove them.
NPC_LOCKS = "puppet:perm(Builder);edit:perm(Builder);control:perm(Builder);delete:perm(Builder)"


def _npc_lockstring(storage):
    """`storage` with its puppet/edit/control/delete locks swapped for NPC_LOCKS."""
    replaced = {part.split(":", 1)[0] for part in NPC_LOCKS.split(";")}
    kept = [
        part for part in str(storage or "").split(";") if part.strip() and part.split(":", 1)[0].strip() not in replaced
    ]
    return ";".join(kept + [NPC_LOCKS])


def _find_character(caller, name):
    """A Character anywhere in the game, or None (the caller is told why)."""
    target = caller.search(name, global_search=True)
    if not target:
        return None
    if not inherits_from(target, CHARACTER_TYPECLASS):
        caller.msg(f"{target.key} is not a character.")
        return None
    return target


def _torpor_from_damage(character):
    """True if a vampire's Health track is full of Aggravated damage."""
    if not character.is_kindred:
        return False
    return character.damage["health"]["aggravated"] >= character.health_max


class CmdTorpor(default_cmds.MuxCommand):
    """
    See or end a character's torpor (staff).

    Usage:
        +torpor <character>
        +torpor/end <character>

    A vampire falls into torpor when it fails to rise at Hunger 5
    (rouse/wake), which the game records, or when its Health track is
    full of Aggravated damage. +torpor shows both. The Storyteller decides
    how long torpor lasts; /end clears the recorded torpor. Torpor from
    damage ends when the damage is healed (+heal <character>=<n>/aggravated).
    """

    key = "+torpor"
    aliases = ["torpor"]
    locks = "cmd:perm(Builder)"
    help_category = "Admin"

    def func(self):
        caller = self.caller
        if not self.args.strip():
            caller.msg("Usage: +torpor <character>  or  +torpor/end <character>")
            return
        target = _find_character(caller, self.args.strip())
        if not target:
            return
        recorded = target.torpor
        from_damage = _torpor_from_damage(target)

        if "end" in self.switches:
            if not recorded:
                caller.msg(f"{target.key} has no recorded torpor to end.")
            else:
                target.torpor = None
                caller.msg(f"{target.key}'s torpor ({recorded.get('reason', 'no reason given')}) has ended.")
                target.msg("|yYou rise from torpor.|n")
            if from_damage:
                caller.msg(
                    f"{target.key}'s Health track is still full of Aggravated damage, which is torpor too: "
                    f"heal it with +heal {target.key}=<amount>/aggravated."
                )
            return

        if not recorded and not from_damage:
            caller.msg(f"{target.key} is not in torpor.")
            return
        if recorded:
            since = time.strftime("%Y-%m-%d %H:%M", time.localtime(recorded.get("time") or 0))
            caller.msg(f"{target.key} is in torpor: {recorded.get('reason', 'no reason given')} (since {since}).")
        if from_damage:
            caller.msg(f"{target.key}'s Health track is full of Aggravated damage (torpor until it is healed).")


class CmdNPC(default_cmds.MuxCommand):
    """
    Create a staff NPC (staff).

    Usage:
        +npc/create <name>[=<splat>]

    Splat: mortal (the default), ghoul or vampire.

    Creates a Character here that belongs to no account and needs no
    approval. Any Builder can puppet it (ic <name>), @set or @desc it,
    and remove it. The splat decides whether it rolls Hunger dice and
    halves Superficial damage (vampires only).

    Examples:
        +npc/create Old Tom
        +npc/create Marguerite=ghoul
    """

    key = "+npc"
    aliases = ["npc"]
    locks = "cmd:perm(Builder)"
    help_category = "Admin"

    def func(self):
        caller = self.caller
        if "create" not in self.switches or not self.lhs:
            caller.msg("Usage: +npc/create <name>[=<splat>]  (splat: mortal, ghoul or vampire)")
            return
        name = self.lhs.strip()
        splat = (self.rhs or "mortal").strip().lower()
        if splat not in SPLATS:
            caller.msg(f"Splat must be one of {', '.join(SPLATS)}.")
            return
        npc = create_object(CHARACTER_TYPECLASS, key=name, location=caller.location, home=caller.location)
        npc.locks.replace(_npc_lockstring(str(npc.locks)))
        npc.splat = splat
        npc.tags.add("npc", category="staff")
        caller.msg(f"Created NPC {npc.key} ({npc.dbref}, {splat}). Puppet it with: ic {npc.key}")
