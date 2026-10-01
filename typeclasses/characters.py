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
    CLANS,
    DISCIPLINES,
    PREDATOR_TYPES,
    TRAIT_RANGES,
    UnknownTrait,
    WrongCategory,
    find_power,
    resolve_trait,
)

from .objects import ObjectParent

__all__ = ["Character", "UnknownTrait", "WrongCategory"]

DAMAGE_TRACKS = ("health", "willpower")


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
        "specialties": {},  # {"skill_key": "Specialty name"}
        "disciplines": {},  # {"discipline_key": {"level": n, "powers": ["Power Name", ...]}}
    }


def _new_vampire():
    return {
        "clan": None,  # a key of world.v5_data.CLANS
        "generation": 13,
        "blood_potency": 0,
        "hunger": 1,  # 0-5
        "humanity": 7,  # 0-10
        "predator_type": None,  # a key of world.v5_data.PREDATOR_TYPES
        "current_resonance": None,
        "resonance_intensity": 0,
        "resonance_expires": None,
        "bane": None,
        "compulsion": None,
    }


def _new_pools():
    """Damage counters only. Maximums and current values are derived."""
    return {track: {"superficial": 0, "aggravated": 0} for track in DAMAGE_TRACKS}


def _clamp(value, low, high):
    return max(low, min(high, int(value)))


class Character(ObjectParent, DefaultCharacter):
    """
    A V5 vampire character.

    All V5 state lives in Attributes and is read and written through the
    accessors below (never by poking `self.db.<key>` from other modules):

    - db.stats: attributes/skills (nested by physical/social/mental),
      specialties, disciplines ({"level": n, "powers": [...]})
    - db.vampire: clan, generation, blood_potency, hunger, humanity,
      predator_type, resonance, bane, compulsion
    - db.pools: damage counters per track ("health", "willpower")
    - db.humanity_data: convictions, touchstones, stains
    - db.advantages: backgrounds, merits, flaws
    - db.experience: current, total_earned, total_spent, log
    - db.effects / db.active_effects: active powers and conditions

    Approval is not stored here: `is_approved` reads `CharacterBio.status`.
    """

    def at_object_creation(self):
        """Initialize every V5 store that is not already present."""
        super().at_object_creation()

        defaults = {
            "stats": _new_stats,
            "vampire": _new_vampire,
            "pools": _new_pools,
            "humanity_data": lambda: {
                "convictions": [],
                "touchstones": [],  # [{"name": ..., "conviction_index": n}]
                "stains": 0,
                "chronicle_tenets": [],
            },
            "advantages": lambda: {"backgrounds": {}, "merits": {}, "flaws": {}},
            "experience": lambda: {
                "current": 0,
                "total_earned": 0,
                "total_spent": 0,
                "log": [],
            },
            "effects": list,
            "active_effects": list,
        }
        for key, factory in defaults.items():
            if not self.attributes.has(key):
                self.attributes.add(key, factory())

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
        if not isinstance(self.db.vampire, Mapping):
            self.db.vampire = _new_vampire()
        self.db.vampire[key] = value

    @property
    def hunger(self):
        """Current Hunger, 0-5."""
        return _clamp(self._vampire_get("hunger", 1), 0, 5)

    @hunger.setter
    def hunger(self, value):
        self._vampire_set("hunger", _clamp(value, 0, 5))

    @property
    def blood_potency(self):
        """Blood Potency, 0-10."""
        return _clamp(self._vampire_get("blood_potency", 0), 0, 10)

    @blood_potency.setter
    def blood_potency(self, value):
        self._vampire_set("blood_potency", _clamp(value, 0, 10))

    @property
    def humanity(self):
        """Humanity, 0-10."""
        return _clamp(self._vampire_get("humanity", 7), 0, 10)

    @humanity.setter
    def humanity(self, value):
        self._vampire_set("humanity", _clamp(value, 0, 10))

    @property
    def generation(self):
        return int(self._vampire_get("generation", 13))

    @generation.setter
    def generation(self, value):
        self._vampire_set("generation", int(value))

    @property
    def clan(self):
        """Clan name (a key of v5_data.CLANS) or None."""
        return self._vampire_get("clan", None)

    @clan.setter
    def clan(self, value):
        self._vampire_set("clan", _canonical_name(value, CLANS, "clan"))

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
        """Set from a {"type", "intensity", "expires"} mapping, or None to clear."""
        if not value:
            self._vampire_set("current_resonance", None)
            self._vampire_set("resonance_intensity", 0)
            self._vampire_set("resonance_expires", None)
            return
        self._vampire_set("current_resonance", value["type"])
        self._vampire_set("resonance_intensity", _clamp(value.get("intensity", 1), 1, 3))
        self._vampire_set("resonance_expires", value.get("expires"))

    # ------------------------------------------------------------------
    # Humanity data
    # ------------------------------------------------------------------

    def _humanity_data(self):
        if not isinstance(self.db.humanity_data, Mapping):
            self.db.humanity_data = {"convictions": [], "touchstones": [], "stains": 0, "chronicle_tenets": []}
        return self.db.humanity_data

    @property
    def stains(self):
        """Stains, 0-10."""
        return _clamp(self._humanity_data().get("stains", 0) or 0, 0, 10)

    @stains.setter
    def stains(self, value):
        self._humanity_data()["stains"] = _clamp(value, 0, 10)

    @property
    def convictions(self):
        return list(deserialize(self._humanity_data().get("convictions", [])))

    @property
    def touchstones(self):
        return list(deserialize(self._humanity_data().get("touchstones", [])))

    # ------------------------------------------------------------------
    # Traits
    # ------------------------------------------------------------------

    def get_trait(self, name, category=None):
        """Rating of an attribute, skill, discipline or background.

        Names resolve case-insensitively through v5_data.TRAIT_REGISTRY.
        Raises UnknownTrait for an unknown name and WrongCategory when
        `category` is given and doesn't match.
        """
        ref = resolve_trait(name, category)
        if ref.category in ("attributes", "skills"):
            group = (self.db.stats or {}).get(ref.category, {}).get(ref.group, {})
            default = TRAIT_RANGES[ref.category][0]
            return int(group.get(ref.key, default))
        if ref.category == "disciplines":
            entry = (self.db.stats or {}).get("disciplines", {}).get(ref.key)
            return int(entry.get("level", 0)) if isinstance(entry, Mapping) else 0
        return int((self.db.advantages or {}).get("backgrounds", {}).get(ref.key, 0))

    def set_trait(self, name, value, category=None):
        """Set an attribute, skill, discipline or background rating.

        Raises UnknownTrait/WrongCategory like get_trait, and ValueError if the
        value is outside the category's range (attributes 1-5, others 0-5).
        """
        ref = resolve_trait(name, category)
        low, high = TRAIT_RANGES[ref.category]
        value = int(value)
        if not low <= value <= high:
            raise ValueError(f"{ref.name} must be between {low} and {high}, got {value}")

        if ref.category in ("attributes", "skills"):
            if not isinstance(self.db.stats, Mapping):
                self.db.stats = _new_stats()
            self.db.stats[ref.category][ref.group][ref.key] = value
        elif ref.category == "disciplines":
            if not isinstance(self.db.stats, Mapping):
                self.db.stats = _new_stats()
            disciplines = self.db.stats["disciplines"]
            if isinstance(disciplines.get(ref.key), Mapping):
                disciplines[ref.key]["level"] = value
            else:
                disciplines[ref.key] = {"level": value, "powers": []}
        else:
            if not isinstance(self.db.advantages, Mapping):
                self.db.advantages = {"backgrounds": {}, "merits": {}, "flaws": {}}
            self.db.advantages["backgrounds"][ref.key] = value
        return value

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
        powers = []
        for entry in (self.db.stats or {}).get("disciplines", {}).values():
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
        if not isinstance(self.db.stats, Mapping):
            self.db.stats = _new_stats()
        disciplines = self.db.stats["disciplines"]
        if not isinstance(disciplines.get(ref.key), Mapping):
            disciplines[ref.key] = {"level": 0, "powers": []}
        if power["name"] not in disciplines[ref.key]["powers"]:
            disciplines[ref.key]["powers"].append(power["name"])
        return power

    @property
    def advantages(self):
        """Plain copy of {"backgrounds", "merits", "flaws"}."""
        stored = deserialize(self.db.advantages) or {}
        return {kind: dict(stored.get(kind, {})) for kind in ("backgrounds", "merits", "flaws")}

    @property
    def specialties(self):
        """Plain copy of {"skill_key": "Specialty"}."""
        return dict(deserialize((self.db.stats or {}).get("specialties", {})))

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
        """Plain copy of {"health"|"willpower": {"superficial": n, "aggravated": n}}."""
        pools = self.db.pools if isinstance(self.db.pools, Mapping) else {}
        result = {}
        for track in DAMAGE_TRACKS:
            marks = pools.get(track) if isinstance(pools.get(track), Mapping) else {}
            result[track] = {
                "superficial": int(marks.get("superficial", 0)),
                "aggravated": int(marks.get("aggravated", 0)),
            }
        return result

    def set_damage(self, track, superficial=None, aggravated=None):
        """Set the damage marked on a track; None leaves that kind unchanged.

        Aggravated is clamped to the track's maximum and superficial to the
        boxes left after aggravated. Overflow rules are the caller's job.
        """
        maximum = self._track_max(track)
        current = self.damage[track]
        aggravated = current["aggravated"] if aggravated is None else aggravated
        superficial = current["superficial"] if superficial is None else superficial
        aggravated = _clamp(aggravated, 0, maximum)
        superficial = _clamp(superficial, 0, maximum - aggravated)
        if not isinstance(self.db.pools, Mapping):
            self.db.pools = _new_pools()
        self.db.pools[track] = {"superficial": superficial, "aggravated": aggravated}
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
        """Unspent XP."""
        return int(self._experience().get("current", 0))

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
