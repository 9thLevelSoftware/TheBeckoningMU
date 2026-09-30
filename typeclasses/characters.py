"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

"""

from evennia.objects.objects import DefaultCharacter

from .objects import ObjectParent


class Character(ObjectParent, DefaultCharacter):
    """
    The Character extends DefaultCharacter to support V5 vampire mechanics.

    All V5-specific data is stored in character.db attributes:
    - char.db.stats: Attributes, skills, specialties, disciplines
    - char.db.vampire: Clan, generation, blood potency, hunger, humanity
    - char.db.pools: Health, willpower, and damage tracking
    - char.db.humanity_data: Convictions, touchstones, stains
    - char.db.advantages: Backgrounds, merits, flaws
    - char.db.experience: XP tracking
    - char.db.effects: Active discipline effects and conditions

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Object child classes like this.

    """

    def at_object_creation(self):
        """
        Called when character is first created.
        Initialize all V5 data structures.
        """
        super().at_object_creation()

        # Initialize stats structure (attributes, skills, disciplines, specialties)
        self.db.stats = {
            "attributes": {
                "physical": {
                    "strength": 1,
                    "dexterity": 1,
                    "stamina": 1
                },
                "social": {
                    "charisma": 1,
                    "manipulation": 1,
                    "composure": 1
                },
                "mental": {
                    "intelligence": 1,
                    "wits": 1,
                    "resolve": 1
                }
            },
            "skills": {
                "physical": {
                    "athletics": 0, "brawl": 0, "craft": 0,
                    "drive": 0, "firearms": 0, "melee": 0,
                    "larceny": 0, "stealth": 0, "survival": 0
                },
                "social": {
                    "animal_ken": 0, "etiquette": 0, "insight": 0,
                    "intimidation": 0, "leadership": 0, "performance": 0,
                    "persuasion": 0, "streetwise": 0, "subterfuge": 0
                },
                "mental": {
                    "academics": 0, "awareness": 0, "finance": 0,
                    "investigation": 0, "medicine": 0, "occult": 0,
                    "politics": 0, "science": 0, "technology": 0
                }
            },
            "specialties": {},  # Format: {"skill_name": "specialty_name"}
            "disciplines": {},  # Format: {"discipline_name": {"level": 0, "powers": []}}
            "approved": False  # For chargen approval workflow
        }

        # Initialize vampire vitals
        self.db.vampire = {
            "clan": None,  # Set during character creation
            "generation": 13,  # Default generation for new vampires
            "blood_potency": 0,  # Increases with age/XP
            "hunger": 1,  # 0-5 scale, starts at 1
            "humanity": 7,  # 0-10 scale
            "predator_type": None,  # Set during character creation
            "current_resonance": None,  # Tracks last feeding resonance
            "resonance_intensity": 0,  # 0=none, 1=fleeting, 2=intense, 3=dyscrasia
            "bane": None,  # Set based on clan
            "compulsion": None  # Set based on clan
        }

        # Legacy hunger tracking (Phase 5 compatibility)
        if not hasattr(self.db, 'hunger'):
            self.db.hunger = 1

        # Initialize health and willpower pools
        self.db.pools = {
            "health": 3,  # Base health (Stamina + 3)
            "willpower": 3,  # Base willpower (Composure + Resolve)
            "current_health": 3,
            "current_willpower": 3,
            "superficial_damage": 0,
            "aggravated_damage": 0
        }

        # Initialize humanity system
        self.db.humanity_data = {
            "convictions": [],  # List of strings
            "touchstones": [],  # List of dicts: {"name": "...", "conviction_index": 0}
            "stains": 0,  # 0-10, track Humanity degradation
            "chronicle_tenets": []  # Chronicle-specific moral guidelines
        }

        # Initialize advantages (backgrounds, merits, flaws)
        self.db.advantages = {
            "backgrounds": {},  # Format: {"background_name": dots}
            "merits": {},  # Format: {"merit_name": dots}
            "flaws": {}  # Format: {"flaw_name": dots}
        }

        # Initialize experience tracking
        self.db.experience = {
            "total_earned": 0,
            "total_spent": 0,
            "current": 0,
            "history": []  # List of dicts: {"type": "earned/spent", "amount": X, "reason": "..."}
        }

        # Initialize active effects (discipline powers, conditions)
        self.db.effects = []  # List of dicts: {"name": "...", "expires": timestamp, "data": {}}
        self.db.active_effects = []  # Discipline power effects with durations

        # Initialize character creation tracking
        self.db.chargen = {
            "completed": False,
            "current_step": None,  # Tracks which step of chargen they're on
            "approved": False,
            "approval_job_id": None
        }

    def migrate_vampire_data(self):
        """Migrate old character data to new vampire structure.

        Called to upgrade existing characters to Phase 6 structure.
        """
        # Initialize vampire dict if missing
        if not self.db.vampire:
            self.db.vampire = {
                "clan": None,
                "generation": 13,
                "blood_potency": 0,
                "hunger": getattr(self.db, 'hunger', 1),  # Migrate from old location
                "humanity": 7,
                "predator_type": None,
                "current_resonance": None,
                "resonance_intensity": 0,
                "bane": None,
                "compulsion": None,
            }

        # Sync old hunger location with new
        if hasattr(self.db, 'hunger'):
            self.db.vampire['hunger'] = self.db.hunger

    @property
    def hunger(self):
        """Property for easy hunger access.

        Prioritizes vampire dict but falls back to legacy location if vampire dict
        is missing. Syncs values if they differ.
        """
        if self.db.vampire:
            # Check if legacy hunger exists and differs from vampire dict
            legacy_hunger = getattr(self.db, 'hunger', None)
            vampire_hunger = self.db.vampire.get('hunger', 1)

            # If legacy hunger is set and differs, sync to vampire dict
            if legacy_hunger is not None and legacy_hunger != vampire_hunger:
                self.db.vampire['hunger'] = legacy_hunger
                return legacy_hunger

            return vampire_hunger
        return getattr(self.db, 'hunger', 1)

    @hunger.setter
    def hunger(self, value):
        """Set hunger level."""
        value = max(0, min(5, value))  # Clamp 0-5
        if self.db.vampire:
            self.db.vampire['hunger'] = value
        self.db.hunger = value  # Keep legacy location synced

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
        if looker.check_permstring("Builder"):
            if self.db.vampire and self.db.vampire.get("clan"):
                clan = self.db.vampire["clan"]
                hunger = self.db.vampire.get("hunger", 0)
                name = f"{name} ({clan}, H:{hunger})"

        return name

    def calculate_health(self):
        """Calculate total health based on Stamina."""
        stamina = self.db.stats["attributes"]["physical"]["stamina"]
        return stamina + 3

    def calculate_willpower(self):
        """Calculate total willpower based on Composure + Resolve."""
        composure = self.db.stats["attributes"]["social"]["composure"]
        resolve = self.db.stats["attributes"]["mental"]["resolve"]
        return composure + resolve

    def update_derived_stats(self):
        """
        Recalculate derived stats (health, willpower) after attribute changes.
        Call this whenever attributes are modified.
        """
        old_health = self.db.pools["health"]
        old_willpower = self.db.pools["willpower"]

        new_health = self.calculate_health()
        new_willpower = self.calculate_willpower()

        # Update maximums
        self.db.pools["health"] = new_health
        self.db.pools["willpower"] = new_willpower

        # Adjust current values proportionally
        if old_health > 0:
            health_ratio = self.db.pools["current_health"] / old_health
            self.db.pools["current_health"] = int(new_health * health_ratio)
        else:
            self.db.pools["current_health"] = new_health

        if old_willpower > 0:
            willpower_ratio = self.db.pools["current_willpower"] / old_willpower
            self.db.pools["current_willpower"] = int(new_willpower * willpower_ratio)
        else:
            self.db.pools["current_willpower"] = new_willpower
