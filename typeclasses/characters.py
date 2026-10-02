"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

"""

from collections.abc import Mapping
from datetime import datetime

from evennia.objects.objects import DefaultCharacter
from evennia.utils.dbserialize import deserialize

from world.v5_data import (
    BACKGROUNDS,
    CLANS,
    DISCIPLINES,
    FLAWS,
    GENERATION_BLOOD_POTENCY,
    GENERATION_BY_AGE,
    MERITS,
    PREDATOR_TYPES,
    RESONANCES,
    TRAIT_RANGES,
    UnknownTrait,
    WrongCategory,
    find_power,
    resolve_trait,
    xp_cost,
)

from .objects import ObjectParent

__all__ = ["Character", "UnknownTrait", "WrongCategory"]

DAMAGE_TRACKS = ("health", "willpower")
GENERATION_RANGE = (4, 16)
MAX_CONVICTIONS = 3
ADVANTAGE_TABLES = {"merits": MERITS, "flaws": FLAWS}

# Every Character carries these locks, however it was created (Character.create,
# the `create` command, a raw create_object, a stock Evennia web view):
# only the owning account may puppet it, and only once it is approved; the
# owner may delete it (e.g. a pending application); only Admins edit it.
# char_owner()/char_approved() are in server/conf/lockfuncs.py and read
# traits.CharacterBio. Staff NPCs get `lock <obj> = puppet:perm(Builder)`.
CHARACTER_LOCKS = (
    "puppet:(char_owner() and char_approved()) or perm(Admin);"
    "delete:char_owner() or perm(Admin);"
    "edit:perm(Admin)"
)
GATED_ACCESS_TYPES = ("puppet", "delete", "edit")


def gated_lockstring(storage):
    """`storage` (a stored lockstring) with its puppet/delete/edit locks replaced
    by CHARACTER_LOCKS. Used at creation and by the traits 0003 re-lock."""
    kept = [
        part
        for part in str(storage or "").split(";")
        if part.strip() and part.split(":", 1)[0].strip() not in GATED_ACCESS_TYPES
    ]
    return ";".join(kept + [CHARACTER_LOCKS])

# What a character is (Character.splat). Only vampires roll Hunger dice and
# halve mundane Superficial damage; staff set "mortal" or "ghoul" on NPCs.
SPLATS = ("vampire", "ghoul", "mortal")

# Character.spend_xp purchase kinds, by the names +spend accepts.
SPEND_KINDS = {
    "attribute": "attribute", "attributes": "attribute",
    "skill": "skill", "skills": "skill",
    "specialty": "specialty", "specialties": "specialty",
    "discipline": "discipline", "disciplines": "discipline",
    "advantage": "advantage", "advantages": "advantage", "background": "advantage", "merit": "advantage",
    "bp": "blood_potency", "blood_potency": "blood_potency", "blood potency": "blood_potency",
    "ritual": "ritual", "rituals": "ritual",
    "formula": "formula", "formulas": "formula",
}
# Learned rituals and formulas are kept on their discipline's entry.
LEARNED_LISTS = {"ritual": ("Blood Sorcery", "rituals"), "formula": ("Thin-Blood Alchemy", "formulas")}


def _new_stats():
    """The one db.stats shape: nested attributes and skills, keyed lower_snake_case."""
    return {
        "attributes": {
            "physical": {"strength": 1, "dexterity": 1, "stamina": 1},
            "social": {"charisma": 1, "manipulation": 1, "composure": 1},
            "mental": {"intelligence": 1, "wits": 1, "resolve": 1},
        },
        "skills": {
            "physical": {
                "athletics": 0,
                "brawl": 0,
                "craft": 0,
                "drive": 0,
                "firearms": 0,
                "melee": 0,
                "larceny": 0,
                "stealth": 0,
                "survival": 0,
            },
            "social": {
                "animal_ken": 0,
                "etiquette": 0,
                "insight": 0,
                "intimidation": 0,
                "leadership": 0,
                "performance": 0,
                "persuasion": 0,
                "streetwise": 0,
                "subterfuge": 0,
            },
            "mental": {
                "academics": 0,
                "awareness": 0,
                "finance": 0,
                "investigation": 0,
                "medicine": 0,
                "occult": 0,
                "politics": 0,
                "science": 0,
                "technology": 0,
            },
        },
        "specialties": {},  # {"skill_key": ["Specialty name", ...]}
        # {"discipline_key": {"level": n, "powers": [...]}}; Blood Sorcery and
        # Thin-Blood Alchemy entries also hold "rituals" / "formulas" lists.
        "disciplines": {},
    }


def _new_vampire():
    return {
        "clan": None,  # a key of world.v5_data.CLANS
        "generation": 13,
        # V5 QR p.3: a 12th or 13th Generation fledgling starts at Blood Potency 1.
        "blood_potency": 1,
        "hunger": 1,  # 0-5
        "humanity": 7,  # 0-10
        "predator_type": None,  # a key of world.v5_data.PREDATOR_TYPES
        "age_category": None,  # a key of world.v5_data.GENERATION_BY_AGE (set at creation)
        "current_resonance": None,  # a key of world.v5_data.RESONANCES
        "resonance_intensity": 0,
        "resonance_expires": None,
    }


def _new_pools():
    """Damage counters only. Maximums and current values are derived."""
    return {track: {"superficial": 0, "aggravated": 0} for track in DAMAGE_TRACKS}


def _new_humanity_data():
    return {
        "convictions": [],  # ["Conviction text", ...]
        "touchstones": [],  # [{"name", "description", "conviction_index"}]
        "stains": 0,
        "chronicle_tenets": [],
    }


def _new_advantages():
    # backgrounds: {"key": dots} or, for instanced backgrounds,
    #              {"key": [{"dots": n, "note": "..."}, ...]}
    # merits/flaws: {"Canonical Name": dots}
    # notes: {"merits"|"flaws": {"Canonical Name": "note"}}
    return {"backgrounds": {}, "merits": {}, "flaws": {}, "notes": {"merits": {}, "flaws": {}}}


def _new_experience():
    return {"total_earned": 0, "total_spent": 0, "log": []}


def _as_int(value, label="value"):
    """Accept only whole numbers (int, or an integral float); reject bool and None."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be a whole number, got {value!r}")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{label} must be a whole number, got {value!r}")
        return int(value)
    if not isinstance(value, int):
        raise ValueError(f"{label} must be a whole number, got {value!r}")
    return value


def _clamp(value, low, high):
    return max(low, min(high, int(value)))


def _is_instanced(ref):
    return ref.category == "backgrounds" and bool(BACKGROUNDS[ref.name].get("instanced"))


class Character(ObjectParent, DefaultCharacter):
    """
    A V5 vampire character.

    All V5 state lives in Attributes and is read and written through the
    accessors below (never by poking `self.db.<key>` from other modules):

    - db.stats: attributes/skills (nested by physical/social/mental),
      specialties ({"skill_key": [names]}), disciplines
      ({"level": n, "powers": [...]})
    - db.vampire: clan, generation, blood_potency, hunger, humanity,
      predator_type, resonance. Bane and compulsion are derived from the
      clan, not stored. db.vampire is canonical for clan, generation and
      predator type; the copies on traits.CharacterBio are deprecated.
    - db.pools: damage counters per track ("health", "willpower")
    - db.humanity_data: convictions, touchstones, stains
    - db.advantages: backgrounds (instanced ones as lists), merits, flaws
    - db.experience: total_earned, total_spent, log (unspent XP is derived)
    - db.active_effects: active powers and conditions

    Approval is not stored here: `is_approved` reads `CharacterBio.status`.
    Ownership and approval are enforced by CHARACTER_LOCKS, which every
    creation path installs.
    """

    # Evennia formats this class attribute in some code paths; keep it equal
    # to the default lockstring so none of them grants the stock owner-puppet lock.
    lockstring = CHARACTER_LOCKS

    @classmethod
    def get_default_lockstring(cls, account=None, caller=None, **kwargs):
        """The same gated locks for every creation path (see CHARACTER_LOCKS)."""
        return CHARACTER_LOCKS

    def basetype_setup(self):
        """Install the gated locks on every new Character, however it is created.

        replace() rather than add(), so the stock puppet/delete/edit locks are
        swapped out without "access type changed" warnings.
        """
        super().basetype_setup()
        self.locks.replace(gated_lockstring(str(self.locks)))

    def at_object_delete(self):
        """Close the character's application job (traits.utils) before it goes."""
        from traits.utils import close_job_for_deleted_character

        close_job_for_deleted_character(self)
        return super().at_object_delete()

    def at_object_creation(self):
        """Initialize every V5 store that is not already present."""
        super().at_object_creation()

        defaults = {
            "stats": _new_stats,
            "vampire": _new_vampire,
            "pools": _new_pools,
            "humanity_data": _new_humanity_data,
            "advantages": _new_advantages,
            "experience": _new_experience,
            "active_effects": list,
        }
        for key, factory in defaults.items():
            if not self.attributes.has(key):
                self.attributes.add(key, factory())

    # Stores a chargen application owns. reset_sheet() puts these back to a
    # new character's values; snapshot_sheet()/restore_sheet() let a caller
    # undo a failed rewrite.
    SHEET_STORES = {
        "stats": _new_stats,
        "vampire": _new_vampire,
        "pools": _new_pools,
        "humanity_data": _new_humanity_data,
        "advantages": _new_advantages,
        "experience": lambda: {"total_earned": 0, "total_spent": 0, "log": []},
    }

    def reset_sheet(self):
        """Reset every chargen-owned store to a new character's values.

        For an application being resubmitted before approval, so the new
        sheet replaces the old one instead of merging with it.
        """
        for key, factory in self.SHEET_STORES.items():
            self.attributes.add(key, factory())

    def snapshot_sheet(self):
        """Plain copies of the chargen-owned stores, for restore_sheet()."""
        return {key: deserialize(self.attributes.get(key)) for key in self.SHEET_STORES}

    def restore_sheet(self, snapshot):
        for key, value in snapshot.items():
            if value is None:
                self.attributes.remove(key)
            else:
                self.attributes.add(key, value)

    # ------------------------------------------------------------------
    # Store helpers: (re)create a store or sub-dict instead of crashing
    # on a missing or wrongly shaped one.
    # ------------------------------------------------------------------

    def _store(self, key, factory):
        if not isinstance(self.attributes.get(key), Mapping):
            self.attributes.add(key, factory())
        return self.attributes.get(key)

    def _stats_section(self, category, group=None):
        stats = self._store("stats", _new_stats)
        if not isinstance(stats.get(category), Mapping):
            stats[category] = {}
        section = stats[category]
        if group is not None:
            if not isinstance(section.get(group), Mapping):
                section[group] = {}
            section = section[group]
        return section

    def _advantage_section(self, kind):
        advantages = self._store("advantages", _new_advantages)
        if not isinstance(advantages.get(kind), Mapping):
            advantages[kind] = {}
        return advantages[kind]

    # ------------------------------------------------------------------
    # db.vampire scalars
    # ------------------------------------------------------------------

    def _vampire_get(self, key, default):
        vampire = self.db.vampire
        if not isinstance(vampire, Mapping):
            return default
        value = vampire.get(key, default)
        return default if value is None else value

    def _vampire_set(self, key, value):
        self._store("vampire", _new_vampire)[key] = value

    @property
    def hunger(self):
        """Current Hunger, 0-5."""
        return _clamp(self._vampire_get("hunger", 1), 0, 5)

    @hunger.setter
    def hunger(self, value):
        self._vampire_set("hunger", _clamp(_as_int(value, "Hunger"), 0, 5))

    @property
    def blood_potency(self):
        """Blood Potency, 0-10."""
        return _clamp(self._vampire_get("blood_potency", 1), 0, 10)

    @blood_potency.setter
    def blood_potency(self, value):
        self._vampire_set("blood_potency", _clamp(_as_int(value, "Blood Potency"), 0, 10))

    @property
    def humanity(self):
        """Humanity, 0-10."""
        return _clamp(self._vampire_get("humanity", 7), 0, 10)

    @humanity.setter
    def humanity(self, value):
        self._vampire_set("humanity", _clamp(_as_int(value, "Humanity"), 0, 10))

    @property
    def generation(self):
        return int(self._vampire_get("generation", 13))

    @generation.setter
    def generation(self, value):
        value = _as_int(value, "Generation")
        low, high = GENERATION_RANGE
        if not low <= value <= high:
            raise ValueError(f"Generation must be between {low} and {high}, got {value}")
        self._vampire_set("generation", value)

    @property
    def age_category(self):
        """Sea of Time age category at creation (a GENERATION_BY_AGE key), or None."""
        return self._vampire_get("age_category", None)

    @age_category.setter
    def age_category(self, value):
        self._vampire_set("age_category", _canonical_name(value, GENERATION_BY_AGE, "age category"))

    @property
    def clan(self):
        """Clan name (a key of v5_data.CLANS) or None."""
        return self._vampire_get("clan", None)

    @clan.setter
    def clan(self, value):
        self._vampire_set("clan", _canonical_name(value, CLANS, "clan"))

    @property
    def bane(self):
        """The clan's bane text from v5_data.CLANS (derived, not stored), or None."""
        return CLANS.get(self.clan, {}).get("bane") if self.clan else None

    @property
    def compulsion(self):
        """The clan's compulsion text from v5_data.CLANS (derived, not stored), or None."""
        return CLANS.get(self.clan, {}).get("compulsion") if self.clan else None

    @property
    def predator_type(self):
        """Predator type name (a key of v5_data.PREDATOR_TYPES) or None."""
        return self._vampire_get("predator_type", None)

    @predator_type.setter
    def predator_type(self, value):
        self._vampire_set("predator_type", _canonical_name(value, PREDATOR_TYPES, "predator type"))

    @property
    def splat(self):
        """What the character is: "vampire" (the default), "ghoul" or "mortal".

        Stored in the ``splat`` Attribute, which staff set on NPCs (e.g.
        ``@set <npc>/splat = mortal``); anything else reads as "vampire".
        """
        value = self.attributes.get("splat")
        value = str(value).strip().lower() if value else ""
        return value if value in SPLATS else "vampire"

    @splat.setter
    def splat(self, value):
        value = str(value or "").strip().lower()
        if value not in SPLATS:
            raise ValueError(f"Splat must be one of {', '.join(SPLATS)}, got {value!r}")
        self.attributes.add("splat", value)

    @property
    def is_kindred(self):
        """True for vampires (thin-bloods included)."""
        return self.splat == "vampire"

    @property
    def dice_hunger(self):
        """Hunger dice this character rolls: its Hunger if a vampire, else 0."""
        return self.hunger if self.is_kindred else 0

    @property
    def halves_superficial(self):
        """True if mundane Superficial damage is halved (rounded up) for this character.

        Vampires do; mortals and ghouls don't, nor do thin-bloods without the
        Vampiric Resilience merit (QR p.11).
        """
        if not self.is_kindred:
            return False
        if self.clan == "Thin-Blood":
            return "Vampiric Resilience" in self.advantages["merits"]
        return True

    @property
    def torpor(self):
        """{"reason", "time"} while the vampire is in torpor (set by the game, cleared by staff), else None."""
        value = self._vampire_get("torpor", None)
        return dict(value) if isinstance(value, Mapping) else None

    @torpor.setter
    def torpor(self, value):
        self._vampire_set("torpor", dict(value) if value else None)

    @property
    def last_hunt(self):
        """Time (time.time()) of the last +hunt, or None."""
        value = self._vampire_get("last_hunt", None)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @last_hunt.setter
    def last_hunt(self, value):
        self._vampire_set("last_hunt", None if value is None else float(value))

    @property
    def slake_carry(self):
        """Half a point of Hunger slaked but not yet counted (BP 2 animal/bagged blood): 0 or 0.5."""
        value = self._vampire_get("slake_carry", 0)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    @slake_carry.setter
    def slake_carry(self, value):
        self._vampire_set("slake_carry", max(0.0, min(0.5, float(value or 0))))

    @property
    def last_remorse(self):
        """Time (time.time()) of the last player-run Remorse test, or None."""
        value = self._humanity_data().get("last_remorse")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @last_remorse.setter
    def last_remorse(self, value):
        self._humanity_data()["last_remorse"] = None if value is None else float(value)

    @property
    def degenerating(self):
        """True while Stains fill the Humanity tracker (QR p.3: Impaired, -2 to all tests)."""
        return self.stains > 0 and self.humanity + self.stains >= 10

    def dice_penalty(self, physical=False):
        """Impairment dice for a test (QR p.3): -2 while the Humanity tracker is full of
        Stains (all tests), and -2 for a Physical test while the Health track is full."""
        penalty = -2 if self.degenerating else 0
        if physical:
            marks = self.damage["health"]
            if marks["superficial"] + marks["aggravated"] >= self.health_max:
                penalty -= 2
        return penalty

    @property
    def resonance(self):
        """Current resonance as {"type", "intensity", "expires"}, or None."""
        kind = self._vampire_get("current_resonance", None)
        intensity = self._vampire_get("resonance_intensity", 0)
        if not kind or intensity <= 0:
            return None
        return {
            "type": kind,
            "intensity": intensity,
            "expires": self._vampire_get("resonance_expires", None),
        }

    @resonance.setter
    def resonance(self, value):
        """Set from a {"type", "intensity", "expires"} mapping, or None to clear.

        The type must be a key of v5_data.RESONANCES (any case); intensity is
        clamped to 1-3.
        """
        if not value:
            self._vampire_set("current_resonance", None)
            self._vampire_set("resonance_intensity", 0)
            self._vampire_set("resonance_expires", None)
            return
        kind = _canonical_name(value["type"], RESONANCES, "resonance")
        if kind is None:
            raise UnknownTrait("Resonance type is required")
        intensity = _clamp(_as_int(value.get("intensity", 1), "Resonance intensity"), 1, 3)
        self._vampire_set("current_resonance", kind)
        self._vampire_set("resonance_intensity", intensity)
        self._vampire_set("resonance_expires", value.get("expires"))

    # ------------------------------------------------------------------
    # Humanity data
    # ------------------------------------------------------------------

    def _humanity_data(self):
        return self._store("humanity_data", _new_humanity_data)

    def _humanity_list(self, key):
        data = self._humanity_data()
        if not hasattr(data.get(key), "append"):
            data[key] = []
        return data[key]

    @property
    def stains(self):
        """Stains, 0-10."""
        return _clamp(self._humanity_data().get("stains", 0) or 0, 0, 10)

    @stains.setter
    def stains(self, value):
        self._humanity_data()["stains"] = _clamp(_as_int(value, "Stains"), 0, 10)

    @property
    def convictions(self):
        return list(deserialize(self._humanity_list("convictions")))

    @property
    def touchstones(self):
        return list(deserialize(self._humanity_list("touchstones")))

    def add_conviction(self, text):
        """Add a Conviction. Raises ValueError if empty or already at the maximum (3)."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("A Conviction needs some text")
        convictions = self._humanity_list("convictions")
        if len(convictions) >= MAX_CONVICTIONS:
            raise ValueError(f"You already have {MAX_CONVICTIONS} Convictions")
        convictions.append(text)
        return text

    def remove_conviction(self, index):
        """Remove and return the Conviction at `index`. Raises IndexError."""
        convictions = self._humanity_list("convictions")
        index = _as_int(index, "Conviction index")
        if not 0 <= index < len(convictions):
            raise IndexError(f"Invalid conviction index: {index}")
        return convictions.pop(index)

    def add_touchstone(self, name, description="", conviction_index=0):
        """Add a Touchstone ({"name", "description", "conviction_index"}).

        Each Touchstone belongs to one of the character's Convictions (core
        p.172-173), so ``conviction_index`` must name an existing Conviction
        (0-based). Raises ValueError for an empty name or a bad index.
        """
        name = str(name or "").strip()
        if not name:
            raise ValueError("A Touchstone needs a name")
        index = _as_int(conviction_index, "Conviction index")
        if not 0 <= index < len(self._humanity_list("convictions")):
            raise ValueError("A Touchstone must belong to one of your Convictions; add the Conviction first")
        touchstone = {
            "name": name,
            "description": str(description or ""),
            "conviction_index": index,
        }
        self._humanity_list("touchstones").append(touchstone)
        return dict(touchstone)

    def remove_touchstone(self, index):
        """Remove and return the Touchstone at `index`. Raises IndexError."""
        touchstones = self._humanity_list("touchstones")
        index = _as_int(index, "Touchstone index")
        if not 0 <= index < len(touchstones):
            raise IndexError(f"Invalid touchstone index: {index}")
        return deserialize(touchstones.pop(index))

    # ------------------------------------------------------------------
    # Traits
    # ------------------------------------------------------------------

    def get_trait(self, name, category=None):
        """Rating of an attribute, skill, discipline or background.

        Names resolve case-insensitively through v5_data.TRAIT_REGISTRY.
        Raises UnknownTrait for an unknown name and WrongCategory when
        `category` is given and doesn't match. An instanced background
        (Allies, Contacts, ...) rates as the total dots of its instances.
        """
        ref = resolve_trait(name, category)
        stats = self.db.stats if isinstance(self.db.stats, Mapping) else {}
        if ref.category in ("attributes", "skills"):
            section = stats.get(ref.category)
            group = section.get(ref.group) if isinstance(section, Mapping) else None
            default = TRAIT_RANGES[ref.category][0]
            return int(group.get(ref.key, default)) if isinstance(group, Mapping) else default
        if ref.category == "disciplines":
            disciplines = stats.get("disciplines")
            entry = disciplines.get(ref.key) if isinstance(disciplines, Mapping) else None
            return _discipline_level(entry)
        advantages = self.db.advantages if isinstance(self.db.advantages, Mapping) else {}
        backgrounds = advantages.get("backgrounds")
        entry = backgrounds.get(ref.key, 0) if isinstance(backgrounds, Mapping) else 0
        if isinstance(entry, (int, float)) and not isinstance(entry, bool):
            return int(entry)
        return sum(int(instance.get("dots", 0)) for instance in entry if isinstance(instance, Mapping))

    def set_trait(self, name, value, category=None):
        """Set an attribute, skill, discipline or background rating.

        Raises UnknownTrait/WrongCategory like get_trait, and ValueError if the
        value is not a whole number in the category's range (attributes 1-5,
        others 0-5). Instanced backgrounds are set per instance with
        set_background_instance().
        """
        ref = resolve_trait(name, category)
        low, high = TRAIT_RANGES[ref.category]
        value = _as_int(value, ref.name)
        if not low <= value <= high:
            raise ValueError(f"{ref.name} must be between {low} and {high}, got {value}")

        if ref.category in ("attributes", "skills"):
            self._stats_section(ref.category, ref.group)[ref.key] = value
        elif ref.category == "disciplines":
            disciplines = self._stats_section("disciplines")
            entry = _discipline_entry(disciplines.get(ref.key))
            entry["level"] = value
            disciplines[ref.key] = entry
        else:
            if _is_instanced(ref):
                raise ValueError(f"{ref.name} is taken per instance; use set_background_instance()")
            self._advantage_section("backgrounds")[ref.key] = value
        return value

    def background_instances(self, name):
        """Plain list of {"dots", "note"} for an instanced background."""
        ref = resolve_trait(name, "backgrounds")
        entry = deserialize(self._advantage_section("backgrounds").get(ref.key, []))
        return [dict(item) for item in entry if isinstance(item, Mapping)] if isinstance(entry, list) else []

    def set_background_instance(self, name, note, dots):
        """Set one instance of an instanced background (e.g. Allies "street gang").

        The note identifies the instance (case-insensitive); dots 0 removes it.
        Raises ValueError for a non-instanced background, an empty note, or
        dots outside 0-5.
        """
        ref = resolve_trait(name, "backgrounds")
        if not _is_instanced(ref):
            raise ValueError(f"{ref.name} is a single rating; use set_trait()")
        note = str(note or "").strip()
        if not note:
            raise ValueError(f"Each {ref.name} instance needs a note saying who or what it is")
        dots = _as_int(dots, ref.name)
        low, high = TRAIT_RANGES["backgrounds"]
        if not low <= dots <= high:
            raise ValueError(f"{ref.name} must be between {low} and {high}, got {dots}")

        instances = [
            item for item in self.background_instances(ref.key) if item.get("note", "").lower() != note.lower()
        ]
        if dots:
            instances.append({"dots": dots, "note": note})
        self._advantage_section("backgrounds")[ref.key] = instances
        return instances

    def set_advantage(self, kind, name, dots, note=None):
        """Set a merit or flaw rating; 0 removes it.

        `kind` is "merits" or "flaws". The name resolves case-insensitively to
        its v5_data.MERITS/FLAWS key, which is the storage key, and dots must
        be one of that entry's allowed ratings. `note` (e.g. the language a
        Linguistics dot buys, the clan of a Clan Curse) is kept in
        db.advantages["notes"][kind]; None leaves an existing note alone.
        Raises UnknownTrait or ValueError.
        """
        if kind not in ADVANTAGE_TABLES:
            raise ValueError(f"Unknown advantage kind: {kind}")
        table = ADVANTAGE_TABLES[kind]
        canonical = _canonical_name(name, table, kind[:-1])
        if canonical is None:
            raise UnknownTrait(f"A {kind[:-1]} name is required")
        dots = _as_int(dots, canonical)
        # Each store lookup can return its own copy of db.advantages, so write
        # the rating and then fetch the notes afresh (never hold both at once).
        if dots == 0:
            self._advantage_section(kind).pop(canonical, None)
            self._advantage_notes(kind).pop(canonical, None)
            return 0
        _check_advantage_dots(table, canonical, dots)
        self._advantage_section(kind)[canonical] = dots
        if note is not None:
            note = str(note).strip()
            if note:
                self._advantage_notes(kind)[canonical] = note
            else:
                self._advantage_notes(kind).pop(canonical, None)
        return dots

    def _advantage_notes(self, kind):
        advantages = self._store("advantages", _new_advantages)
        if not isinstance(advantages.get("notes"), Mapping):
            advantages["notes"] = {"merits": {}, "flaws": {}}
        if not isinstance(advantages["notes"].get(kind), Mapping):
            advantages["notes"][kind] = {}
        return advantages["notes"][kind]

    def advantage_note(self, kind, name):
        """The note on a merit or flaw ("" if none)."""
        if kind not in ADVANTAGE_TABLES:
            raise ValueError(f"Unknown advantage kind: {kind}")
        canonical = _canonical_name(name, ADVANTAGE_TABLES[kind], kind[:-1])
        return str(self._advantage_notes(kind).get(canonical, ""))

    # Blood Sorcery rituals and Thin-Blood Alchemy formulas (v5_data
    # DISCIPLINES[...]["rituals"/"formulas"]) have one store: the learned
    # lists on their discipline's entry, db.stats["disciplines"][<key>]
    # ["rituals"/"formulas"] (LEARNED_LISTS). rituals/formulas and
    # learn_ritual/learn_formula are the chargen-facing names for
    # known_rituals/known_formulas and learn_ritual_or_formula.

    @property
    def rituals(self):
        return self.known_rituals

    @property
    def formulas(self):
        return self.known_formulas

    def learn_ritual(self, name):
        """Record a Blood Sorcery ritual (canonical name). Raises UnknownTrait."""
        return self.learn_ritual_or_formula("ritual", name)

    def learn_formula(self, name):
        """Record a Thin-Blood Alchemy formula (canonical name). Raises UnknownTrait."""
        return self.learn_ritual_or_formula("formula", name)

    @property
    def discipline_levels(self):
        """{"Discipline Name": level} for every discipline rated above 0."""
        levels = {}
        for name in DISCIPLINES:
            level = self.get_trait(name)
            if level > 0:
                levels[name] = level
        return levels

    @property
    def known_powers(self):
        """Names of the discipline powers this character has learned."""
        stats = self.db.stats if isinstance(self.db.stats, Mapping) else {}
        disciplines = stats.get("disciplines")
        powers = []
        for entry in disciplines.values() if isinstance(disciplines, Mapping) else []:
            if isinstance(entry, Mapping):
                powers.extend(entry.get("powers", []))
        return powers

    def learn_power(self, power_name):
        """Record a power as learned under its discipline. Returns the power entry.

        Raises UnknownTrait if the power is not in v5_data.DISCIPLINE_POWERS.
        This does not check eligibility (discipline level, amalgams).
        """
        power = find_power(power_name)
        if power is None:
            raise UnknownTrait(f"Unknown discipline power: {power_name}")
        ref = resolve_trait(power["discipline"], "disciplines")
        disciplines = self._stats_section("disciplines")
        entry = _discipline_entry(disciplines.get(ref.key))
        if power["name"] not in entry["powers"]:
            entry["powers"].append(power["name"])
        disciplines[ref.key] = entry
        return power

    def _learned(self, kind):
        discipline, key = LEARNED_LISTS[kind]
        ref = resolve_trait(discipline, "disciplines")
        stats = self.db.stats if isinstance(self.db.stats, Mapping) else {}
        disciplines = stats.get("disciplines")
        entry = disciplines.get(ref.key) if isinstance(disciplines, Mapping) else None
        return list(entry.get(key, [])) if isinstance(entry, Mapping) else []

    @property
    def known_rituals(self):
        """Names of the Blood Sorcery rituals this character has learned."""
        return self._learned("ritual")

    @property
    def known_formulas(self):
        """Names of the Thin-Blood Alchemy formulas this character has learned."""
        return self._learned("formula")

    def learn_ritual_or_formula(self, kind, name):
        """Record a ritual ("ritual") or formula ("formula") as learned, without XP.

        Raises UnknownTrait for a name that isn't in v5_data. No eligibility
        check (for staff and chargen; +spend checks the discipline rating).
        """
        entry = find_ritual_or_formula(kind, name)
        if entry is None:
            raise UnknownTrait(f"Unknown {kind}: {name}")
        discipline, key = LEARNED_LISTS[kind]
        ref = resolve_trait(discipline, "disciplines")
        disciplines = self._stats_section("disciplines")
        current = _discipline_entry(disciplines.get(ref.key))
        if entry["name"] not in current.get(key, []):
            current.setdefault(key, []).append(entry["name"])
        disciplines[ref.key] = current
        return entry

    @property
    def advantages(self):
        """Plain copy of {"backgrounds", "merits", "flaws"}."""
        stored = deserialize(self.db.advantages) if isinstance(self.db.advantages, Mapping) else {}
        return {kind: dict(stored.get(kind) or {}) for kind in ("backgrounds", "merits", "flaws")}

    @property
    def specialties(self):
        """Plain copy of {"skill_key": ["Specialty", ...]}."""
        stats = self.db.stats if isinstance(self.db.stats, Mapping) else {}
        stored = deserialize(stats.get("specialties")) or {}
        return {skill: _specialty_list(names) for skill, names in stored.items() if _specialty_list(names)}

    def add_specialty(self, skill, name):
        """Add a specialty to a skill rated 1+. Returns False if it is already there.

        Raises UnknownTrait/WrongCategory for a non-skill and ValueError for an
        unrated skill or an empty name.
        """
        ref = resolve_trait(skill, "skills")
        name = str(name or "").strip()
        if not name:
            raise ValueError("A specialty needs a name")
        if self.get_trait(ref.key) < 1:
            raise ValueError(f"{ref.name} needs at least one dot before it can have a specialty")
        names = self.specialties.get(ref.key, [])
        if name.lower() in (existing.lower() for existing in names):
            return False
        self._stats_section("specialties")[ref.key] = names + [name]
        return True

    def remove_specialty(self, skill, name):
        """Remove a specialty (case-insensitive). Returns False if it wasn't there."""
        ref = resolve_trait(skill, "skills")
        names = self.specialties.get(ref.key, [])
        remaining = [existing for existing in names if existing.lower() != str(name).strip().lower()]
        if len(remaining) == len(names):
            return False
        section = self._stats_section("specialties")
        if remaining:
            section[ref.key] = remaining
        else:
            section.pop(ref.key, None)
        return True

    # ------------------------------------------------------------------
    # Derived pools and damage
    # ------------------------------------------------------------------

    @property
    def health_max(self):
        """Stamina + 3. Derived, never stored."""
        return self.get_trait("stamina") + 3

    @property
    def willpower_max(self):
        """Composure + Resolve. Derived, never stored."""
        return self.get_trait("composure") + self.get_trait("resolve")

    def _track_max(self, track):
        if track == "health":
            return self.health_max
        if track == "willpower":
            return self.willpower_max
        raise ValueError(f"Unknown damage track: {track}")

    @property
    def damage(self):
        """Plain copy of {"health"|"willpower": {"superficial": n, "aggravated": n}}.

        Clamped to the track's current maximum (aggravated first), so the
        marks never exceed the boxes even after the maximum drops.
        """
        pools = self.db.pools if isinstance(self.db.pools, Mapping) else {}
        result = {}
        for track in DAMAGE_TRACKS:
            marks = pools.get(track) if isinstance(pools.get(track), Mapping) else {}
            maximum = self._track_max(track)
            aggravated = _clamp(marks.get("aggravated", 0), 0, maximum)
            superficial = _clamp(marks.get("superficial", 0), 0, maximum - aggravated)
            result[track] = {"superficial": superficial, "aggravated": aggravated}
        return result

    def set_damage(self, track, superficial=None, aggravated=None):
        """Set the damage marked on a track; None leaves that kind unchanged.

        Aggravated is clamped to the track's maximum and superficial to the
        boxes left after aggravated. Overflow rules are the caller's job.
        """
        maximum = self._track_max(track)
        current = self.damage[track]
        aggravated = current["aggravated"] if aggravated is None else _as_int(aggravated, "Aggravated damage")
        superficial = current["superficial"] if superficial is None else _as_int(superficial, "Superficial damage")
        aggravated = _clamp(aggravated, 0, maximum)
        superficial = _clamp(superficial, 0, maximum - aggravated)
        self._store("pools", _new_pools)[track] = {"superficial": superficial, "aggravated": aggravated}
        return self.damage[track]

    @property
    def current_health(self):
        marks = self.damage["health"]
        return max(0, self.health_max - marks["superficial"] - marks["aggravated"])

    @property
    def current_willpower(self):
        marks = self.damage["willpower"]
        return max(0, self.willpower_max - marks["superficial"] - marks["aggravated"])

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------

    def _experience(self):
        return self.db.experience if isinstance(self.db.experience, Mapping) else {}

    @property
    def xp(self):
        """Unspent XP: total earned minus total spent (derived, not stored)."""
        return self.xp_earned - self.xp_spent

    @property
    def xp_earned(self):
        return int(self._experience().get("total_earned", 0))

    @property
    def xp_spent(self):
        return int(self._experience().get("total_spent", 0))

    def xp_spend_cost(self, name, category, note=None):
        """What +spend would cost, without spending: {"kind", "cost", "label", "new"}.

        Raises UnknownTrait, WrongCategory or ValueError (the reason) like spend_xp.
        """
        plan = self._plan_spend(name, category, note)
        return {key: plan[key] for key in ("kind", "cost", "label", "new")}

    def spend_xp(self, name, category, note=None, reason=""):
        """Buy one step of a trait with XP (V5 QR p.1; costs in v5_data.XP_COSTS).

        ``category`` is a key of SPEND_KINDS: attribute, skill, specialty
        (``name`` is the skill, ``note`` the specialty), discipline,
        advantage (a background or merit; ``note`` names the instance of an
        instanced background such as Allies), bp, ritual or formula. The
        name resolves through TRAIT_REGISTRY or v5_data, and the purchase is
        refused if it is unknown, of another category, past its cap or
        unaffordable.

        All checks run first. The trait, the XP total and the log entry are
        then written together, with one assignment per root Attribute, so a
        refusal changes nothing. Returns {"kind", "cost", "label", "new",
        "xp"}. Raises UnknownTrait, WrongCategory or ValueError.
        """
        plan = self._plan_spend(name, category, note)
        if plan["cost"] > self.xp:
            raise ValueError(f"Insufficient XP. Need {plan['cost']}, have {self.xp}")

        stores = {}
        for root, factory in plan["roots"].items():
            self._store(root, factory)
            stores[root] = deserialize(self.attributes.get(root))
        plan["apply"](stores)

        experience = deserialize(self._store("experience", _new_experience))
        experience["total_spent"] = int(experience.get("total_spent", 0)) + plan["cost"]
        balance = int(experience.get("total_earned", 0)) - experience["total_spent"]
        log = list(experience.get("log") or [])
        log.append({
            "type": "spend",
            "amount": -plan["cost"],
            "reason": plan["label"] + (f" - {reason}" if reason else ""),
            "date": datetime.now().isoformat(),
            "balance": balance,
        })
        experience["log"] = log

        for root, value in stores.items():
            self.attributes.add(root, value)
        self.attributes.add("experience", experience)
        return {"kind": plan["kind"], "cost": plan["cost"], "label": plan["label"], "new": plan["new"],
                "xp": balance}

    def _plan_spend(self, name, category, note=None):
        """Validate a purchase and return its cost and how to apply it to copied stores."""
        kind = SPEND_KINDS.get(str(category or "").strip().lower())
        if kind is None:
            raise ValueError(f"You can't spend XP on '{category}'")
        planner = getattr(self, f"_plan_{kind}")
        return planner(str(name or "").strip(), note)

    def _plan_attribute(self, name, note):
        return self._plan_rated(name, "attributes", "attribute")

    def _plan_skill(self, name, note):
        return self._plan_rated(name, "skills", "skill")

    def _plan_rated(self, name, category, kind):
        ref = resolve_trait(name, category)
        new = self.get_trait(ref.key) + 1
        if new > TRAIT_RANGES[category][1]:
            raise ValueError(f"{ref.name} is already at its maximum")

        def apply(stores):
            section = stores["stats"].setdefault(ref.category, {})
            section.setdefault(ref.group, {})[ref.key] = new

        return {"kind": kind, "cost": xp_cost(kind, new), "label": f"Raised {ref.name} to {new}", "new": new,
                "roots": {"stats": _new_stats}, "apply": apply}

    def _plan_specialty(self, name, note):
        ref = resolve_trait(name, "skills")
        specialty = str(note or "").strip()
        if not specialty:
            raise ValueError("Name the specialty")
        if self.get_trait(ref.key) < 1:
            raise ValueError(f"{ref.name} needs at least one dot before it can have a specialty")
        names = self.specialties.get(ref.key, [])
        if specialty.lower() in (existing.lower() for existing in names):
            raise ValueError(f"{ref.name} already has the specialty {specialty}")

        def apply(stores):
            stores["stats"].setdefault("specialties", {})[ref.key] = names + [specialty]

        return {"kind": "specialty", "cost": xp_cost("specialty", 1),
                "label": f"Added specialty: {ref.name} ({specialty})", "new": specialty,
                "roots": {"stats": _new_stats}, "apply": apply}

    def discipline_cost_kind(self, discipline):
        """XP_COSTS kind for a dot of ``discipline`` (a DISCIPLINES name) for this character.

        Caitiff pay the Caitiff rate for every discipline; a discipline of
        the character's clan is a clan discipline; anything else is "other".
        Thin-Blood Alchemy counts as a thin-blood's clan discipline (new
        level x 5; owner decision, the XP chart has no thin-blood row).
        """
        if self.clan == "Caitiff":
            return "caitiff_discipline"
        clan_disciplines = CLANS.get(self.clan, {}).get("disciplines", []) if self.clan else []
        if discipline in clan_disciplines or (self.clan == "Thin-Blood" and discipline == "Thin-Blood Alchemy"):
            return "clan_discipline"
        return "other_discipline"

    def _plan_discipline(self, name, note):
        ref = resolve_trait(name, "disciplines")
        if self.clan and self.clan not in CLANS:
            raise ValueError(f"Your clan ({self.clan}) is not available in this game, so discipline costs "
                             "can't be worked out. Ask staff to update your character.")
        if ref.name == "Thin-Blood Alchemy" and self.clan != "Thin-Blood":
            raise ValueError("Only thin-bloods can learn Thin-Blood Alchemy")
        if self.clan == "Thin-Blood" and ref.name != "Thin-Blood Alchemy":
            raise ValueError("Thin-bloods can't buy Disciplines with XP (the Discipline Affinity merit gives "
                             "one permanent dot); only Thin-Blood Alchemy")
        new = self.get_trait(ref.key) + 1
        if new > TRAIT_RANGES["disciplines"][1]:
            raise ValueError(f"{ref.name} is already at its maximum")
        kind = self.discipline_cost_kind(ref.name)

        # Each dot of Thin-Blood Alchemy comes with one formula (core p.282).
        formula = None
        if ref.name == "Thin-Blood Alchemy":
            formula = find_ritual_or_formula("formula", note) if note else None
            if formula is None:
                raise ValueError("Each Alchemy dot comes with a formula: +spend discipline Thin-Blood Alchemy = "
                                 "<formula> (see help alchemy)")
            if formula["level"] > new:
                raise ValueError(f"{formula['name']} is a level {formula['level']} formula; your new Alchemy "
                                 f"rating is {new}")
            if formula["name"] in self.known_formulas:
                raise ValueError(f"You already know {formula['name']}")

        def apply(stores):
            disciplines = stores["stats"].setdefault("disciplines", {})
            entry = _discipline_entry(disciplines.get(ref.key))
            entry["level"] = new
            if formula:
                entry.setdefault("formulas", []).append(formula["name"])
            disciplines[ref.key] = entry

        rate = {"clan_discipline": "in-clan", "caitiff_discipline": "Caitiff", "other_discipline": "out-of-clan"}
        label = f"Raised {ref.name} to {new} ({rate[kind]})" + (f" with {formula['name']}" if formula else "")
        return {"kind": kind, "cost": xp_cost(kind, new), "label": label,
                "new": new, "roots": {"stats": _new_stats}, "apply": apply}

    def _plan_blood_potency(self, name, note):
        new = self.blood_potency + 1
        limit = GENERATION_BLOOD_POTENCY.get(self.generation, {}).get("max", 0)
        if new > limit:
            raise ValueError(f"Blood Potency can't rise above {limit} at Generation {self.generation}")

        def apply(stores):
            stores["vampire"]["blood_potency"] = new

        return {"kind": "blood_potency", "cost": xp_cost("blood_potency", new),
                "label": f"Raised Blood Potency to {new}", "new": new,
                "roots": {"vampire": _new_vampire}, "apply": apply}

    def _plan_learned(self, name, kind):
        entry = find_ritual_or_formula(kind, name)
        if entry is None:
            raise UnknownTrait(f"Unknown {kind}: {name}")
        discipline, key = LEARNED_LISTS[kind]
        if self.get_trait(discipline) < entry["level"]:
            raise ValueError(f"{entry['name']} is a level {entry['level']} {kind}; it needs {discipline} "
                             f"{entry['level']}")
        if entry["name"] in self._learned(kind):
            raise ValueError(f"You already know {entry['name']}")
        ref = resolve_trait(discipline, "disciplines")

        def apply(stores):
            disciplines = stores["stats"].setdefault("disciplines", {})
            current = _discipline_entry(disciplines.get(ref.key))
            current.setdefault(key, []).append(entry["name"])
            disciplines[ref.key] = current

        return {"kind": kind, "cost": xp_cost(kind, entry["level"]), "label": f"Learned {entry['name']}",
                "new": entry["name"], "roots": {"stats": _new_stats}, "apply": apply}

    def _plan_ritual(self, name, note):
        return self._plan_learned(name, "ritual")

    def _plan_formula(self, name, note):
        return self._plan_learned(name, "formula")

    def _plan_advantage(self, name, note):
        merit = next((key for key in MERITS if key.lower() == name.lower()), None)
        if merit is None:
            if any(key.lower() == name.lower() for key in FLAWS):
                raise ValueError("Flaws aren't bought with XP")
            ref = resolve_trait(name, "backgrounds")
            return self._plan_background(ref, note)
        data = MERITS[merit]
        if data.get("thin_blood"):
            raise ValueError(f"{merit} is a thin-blood advantage taken at character creation")
        if self.clan in data.get("excluded_clans", []):
            raise ValueError(f"{self.clan} can't take {merit}")
        held = set(self.advantages["merits"]) | set(self.advantages["flaws"])
        clash = [other for other in data.get("excludes", []) if other in held]
        if clash:
            raise ValueError(f"{merit} can't be taken with {', '.join(clash)}")
        current = self.advantages["merits"].get(merit, 0)
        higher = [dots for dots in data["dots"] if dots > current]
        if not higher:
            raise ValueError(f"{merit} is already at its maximum")
        new = min(higher)
        _check_advantage_dots(MERITS, merit, new)

        def apply(stores):
            stores["advantages"].setdefault("merits", {})[merit] = new

        return {"kind": "advantage", "cost": xp_cost("advantage", new - current),
                "label": f"Raised {merit} to {new}", "new": new,
                "roots": {"advantages": _new_advantages}, "apply": apply}

    def _plan_background(self, ref, note):
        maximum = min(TRAIT_RANGES["backgrounds"][1], BACKGROUNDS[ref.name].get("max_dots", 5))
        if _is_instanced(ref):
            note = str(note or "").strip()
            if not note:
                raise ValueError(f"Say which {ref.name} you are raising: +spend advantage {ref.name} = <who>")
            instances = self.background_instances(ref.key)
            existing = next((item for item in instances if item.get("note", "").lower() == note.lower()), None)
            new = (existing["dots"] if existing else 0) + 1
            if new > maximum:
                raise ValueError(f"{ref.name} ({note}) is already at its maximum")
            label = f"Raised {ref.name} ({note}) to {new}"

            def apply(stores):
                kept = [item for item in instances if item.get("note", "").lower() != note.lower()]
                stores["advantages"].setdefault("backgrounds", {})[ref.key] = kept + [{"dots": new, "note": note}]
        else:
            new = self.get_trait(ref.key) + 1
            if new > maximum:
                raise ValueError(f"{ref.name} is already at its maximum")
            label = f"Raised {ref.name} to {new}"

            def apply(stores):
                stores["advantages"].setdefault("backgrounds", {})[ref.key] = new

        return {"kind": "advantage", "cost": xp_cost("advantage", 1), "label": label, "new": new,
                "roots": {"advantages": _new_advantages}, "apply": apply}

    # ------------------------------------------------------------------
    # Approval and bio (traits.CharacterBio)
    # ------------------------------------------------------------------

    @property
    def bio(self):
        """This character's CharacterBio, or None."""
        from traits.models import CharacterBio

        return CharacterBio.objects.filter(character_id=self.id).first()

    @property
    def is_approved(self):
        """True only if this character's CharacterBio is approved."""
        from traits.models import CharacterBio

        return CharacterBio.objects.filter(character_id=self.id, status="approved").exists()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def get_display_shortdesc(self, looker=None, **kwargs):
        if self.db.shortdesc:
            return self.db.shortdesc
        else:
            return "Use '+short <description>' to set a description."

    def format_idle_time(self, looker, **kwargs):
        # If the character is the looker, show 0s.
        if self == looker:
            return "|g0s|n"
        return format_idle_seconds(self.idle_time or self.connection_time)

    def get_display_name(self, looker, **kwargs):
        """
        Returns the name to display for this character.
        Can be customized to show clan, titles, etc.
        """
        name = super().get_display_name(looker, **kwargs)

        # Staff can see more info
        if looker.check_permstring("Builder") and self.clan:
            name = f"{name} ({self.clan}, H:{self.hunger})"

        return name


def format_idle_seconds(seconds):
    """Colour-coded idle time for the room display ("|g0s|n" when unknown or under 0.5s).

    Green under 10 minutes, bright green from 11, yellow from 15, red from 20.
    """
    if not seconds:
        return "|g0s|n"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    if days:
        return f"|x{days}d|n"
    if hours:
        return f"|x{hours}h|n"
    if minutes:
        if minutes >= 20:
            color = "|r"
        elif minutes >= 15:
            color = "|y"
        elif minutes > 10:
            color = "|G"
        else:
            color = "|g"
        return f"{color}{minutes}m|n"
    return f"|g{secs}s|n"


def _canonical_name(value, table, label):
    """Match `value` case-insensitively to a key of `table`; None clears."""
    if value is None or value == "":
        return None
    wanted = str(value).strip().lower()
    for key in table:
        if key.lower() == wanted:
            return key
    raise UnknownTrait(f"Unknown {label}: {value}")


def _discipline_level(entry):
    """Level of a stored discipline entry; a bare int (old web shape) is its level."""
    if isinstance(entry, Mapping):
        return int(entry.get("level", 0))
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return int(entry)
    return 0


def _discipline_entry(entry):
    """A {"level", "powers"} dict for a stored entry, plus "rituals" or
    "formulas" lists when any are learned.

    Keeps a bare int's level (old web shape) and the learned rituals or
    formulas.
    """
    if isinstance(entry, Mapping):
        result = {"level": int(entry.get("level", 0)), "powers": list(deserialize(entry.get("powers", [])))}
    else:
        result = {"level": _discipline_level(entry), "powers": []}
    for key in ("rituals", "formulas"):
        stored = entry.get(key) if isinstance(entry, Mapping) else None
        if stored:
            result[key] = list(deserialize(stored))
    return result


def find_ritual_or_formula(kind, name):
    """The v5_data entry (with "level") for a Blood Sorcery ritual or a
    Thin-Blood Alchemy formula, matched case-insensitively, or None."""
    wanted = str(name or "").strip().lower()
    if kind == "ritual":
        candidates = DISCIPLINES["Blood Sorcery"].get("rituals", [])
    elif kind == "formula":
        candidates = [
            dict(formula, level=level)
            for level, formulas in DISCIPLINES["Thin-Blood Alchemy"].get("formulas", {}).items()
            for formula in formulas
        ]
    else:
        raise ValueError(f"Unknown kind: {kind}")
    return next((dict(item) for item in candidates if item["name"].lower() == wanted), None)


def _check_advantage_dots(table, name, dots):
    """Raise ValueError unless ``dots`` is one of the entry's allowed ratings."""
    if dots not in table[name]["dots"]:
        allowed = ", ".join(str(d) for d in table[name]["dots"])
        raise ValueError(f"{name} can be taken at {allowed} dots, not {dots}")


def _specialty_list(names):
    """Stored specialties for one skill as a list of names (older shapes: str or dict)."""
    if isinstance(names, str):
        return [names] if names else []
    if isinstance(names, Mapping):
        return [str(name) for name in names]
    if isinstance(names, (list, tuple)):
        return [str(name) for name in names if name]
    return []
