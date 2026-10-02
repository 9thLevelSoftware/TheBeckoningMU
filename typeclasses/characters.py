"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

"""

from collections.abc import Mapping

from evennia.objects.objects import DefaultCharacter
from evennia.utils.dbserialize import deserialize

from world.v5_data import (
    BACKGROUNDS,
    CLANS,
    DISCIPLINES,
    FLAWS,
    MERITS,
    PREDATOR_TYPES,
    RESONANCES,
    TRAIT_RANGES,
    UnknownTrait,
    WrongCategory,
    find_power,
    resolve_trait,
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
        "disciplines": {},  # {"discipline_key": {"level": n, "powers": ["Power Name", ...]}}
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
    return {"backgrounds": {}, "merits": {}, "flaws": {}}


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
        """Install the gated locks on every new Character, however it is created."""
        super().basetype_setup()
        self.locks.add(CHARACTER_LOCKS)

    def at_object_creation(self):
        """Initialize every V5 store that is not already present."""
        super().at_object_creation()

        defaults = {
            "stats": _new_stats,
            "vampire": _new_vampire,
            "pools": _new_pools,
            "humanity_data": _new_humanity_data,
            "advantages": _new_advantages,
            "experience": lambda: {"total_earned": 0, "total_spent": 0, "log": []},
            "active_effects": list,
        }
        for key, factory in defaults.items():
            if not self.attributes.has(key):
                self.attributes.add(key, factory())

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

        Structural checks only (non-empty name, whole-number index). How many
        Touchstones a character may have is a rules check for the caller.
        """
        name = str(name or "").strip()
        if not name:
            raise ValueError("A Touchstone needs a name")
        touchstone = {
            "name": name,
            "description": str(description or ""),
            "conviction_index": _as_int(conviction_index, "Conviction index"),
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

    def set_advantage(self, kind, name, dots):
        """Set a merit or flaw rating; 0 removes it.

        `kind` is "merits" or "flaws". The name resolves case-insensitively to
        its v5_data.MERITS/FLAWS key, which is the storage key, and dots must
        be one of that entry's allowed ratings. Raises UnknownTrait or
        ValueError.
        """
        if kind not in ADVANTAGE_TABLES:
            raise ValueError(f"Unknown advantage kind: {kind}")
        table = ADVANTAGE_TABLES[kind]
        canonical = _canonical_name(name, table, kind[:-1])
        if canonical is None:
            raise UnknownTrait(f"A {kind[:-1]} name is required")
        dots = _as_int(dots, canonical)
        section = self._advantage_section(kind)
        if dots == 0:
            section.pop(canonical, None)
            return 0
        if dots not in table[canonical]["dots"]:
            allowed = ", ".join(str(d) for d in table[canonical]["dots"])
            raise ValueError(f"{canonical} can be taken at {allowed} dots, not {dots}")
        section[canonical] = dots
        return dots

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
        time = self.idle_time or self.connection_time
        if time is None:
            return "|g0s|n"
        minutes, seconds = divmod(time, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        # round seconds
        seconds = int(round(seconds, 0))
        minutes = int(round(minutes, 0))
        hours = int(round(hours, 0))
        days = int(round(days, 0))

        if days > 0:
            time_str = f"|x{days}d|n"
        elif hours > 0:
            time_str = f"|x{hours}h|n"
        elif minutes > 0:
            if minutes > 10 and minutes < 15:
                time_str = f"|G{minutes}m|n"
            elif minutes > 15 and minutes < 20:
                time_str = f"|y{minutes}m|n"
            elif minutes > 20 and minutes < 30:
                time_str = f"|r{minutes}m|n"
            elif minutes >= 30:
                time_str = f"|r{minutes}m|n"
            else:
                time_str = f"|g{minutes}m|n"
        elif seconds > 0:
            time_str = f"|g{seconds}s|n"
        return time_str.strip()

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
    """A {"level", "powers"} dict for a stored entry, keeping a bare int's level."""
    if isinstance(entry, Mapping):
        return {"level": int(entry.get("level", 0)), "powers": list(deserialize(entry.get("powers", [])))}
    return {"level": _discipline_level(entry), "powers": []}


def _specialty_list(names):
    """Stored specialties for one skill as a list of names (older shapes: str or dict)."""
    if isinstance(names, str):
        return [names] if names else []
    if isinstance(names, Mapping):
        return [str(name) for name in names]
    if isinstance(names, (list, tuple)):
        return [str(name) for name in names if name]
    return []
