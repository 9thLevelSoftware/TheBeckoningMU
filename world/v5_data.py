"""
V5 Vampire: The Masquerade rules data.

This module is the only source of V5 rules data in the game (attributes,
skills, clans, disciplines and their powers, predator types, backgrounds,
merits and flaws, the Blood Potency and XP tables). Game code imports from
here; nothing reads rules data from the database. The `traits` app's
legacy reference tables are seeded from these constants by `seed_traits`
for the web chargen API.

WARNING - CONTENT NOT YET VERIFIED. The structure here is authoritative, but
several content tables are known to disagree with the V5 core book and are
being corrected in a follow-up: the Blood Potency table, discipline powers
(levels, Rouse costs, rituals mixed in with powers), clan banes and
compulsions, predator types, merits and flaws, frenzy triggers and the
resonance names and dyscrasias. Don't treat their values as rules until that
correction lands.

It also builds the trait registry (`TRAIT_REGISTRY`, `resolve_trait`) that
`typeclasses.characters.Character.get_trait`/`set_trait` use to map a trait
name to where it is stored on the character.
"""

import re
from typing import NamedTuple

# ============================================================================
# ATTRIBUTES (Physical, Social, Mental)
# ============================================================================

ATTRIBUTES = {
    "Physical": ["Strength", "Dexterity", "Stamina"],
    "Social": ["Charisma", "Manipulation", "Composure"],
    "Mental": ["Intelligence", "Wits", "Resolve"]
}

# Helper function to create attribute dict with default value
def _create_attribute_dict(default_value=1):
    """Create a dict of all attributes with default value."""
    attrs = {}
    for category_attrs in ATTRIBUTES.values():
        for attr in category_attrs:
            attrs[attr.lower()] = default_value
    return attrs

# ============================================================================
# SKILLS (organized by category)
# ============================================================================

SKILLS = {
    "Physical": [
        "Athletics", "Brawl", "Craft", "Drive", "Firearms",
        "Melee", "Larceny", "Stealth", "Survival"
    ],
    "Social": [
        "Animal Ken", "Etiquette", "Insight", "Intimidation",
        "Leadership", "Performance", "Persuasion", "Streetwise", "Subterfuge"
    ],
    "Mental": [
        "Academics", "Awareness", "Finance", "Investigation",
        "Medicine", "Occult", "Politics", "Science", "Technology"
    ]
}

# Helper function to create skills dict with default value
def _create_skills_dict(default_value=0):
    """Create a dict of all skills with default value."""
    skills = {}
    for category_skills in SKILLS.values():
        for skill in category_skills:
            skills[skill.lower()] = default_value
    return skills

# ============================================================================
# CLANS (with in-clan disciplines, banes, compulsions)
# ============================================================================
# Source: V5 core book, clan chapter: Brujah p.65, Gangrel p.69, Malkavian
# p.75, Nosferatu p.81, Toreador p.87, Tremere p.93, Ventrue p.99, Caitiff
# p.105, Thin-blood p.109 (page anchors from the V5 Quick Reference 2.0 p.5;
# bane/compulsion text cross-checked against vtm.paradoxwikis.com clan pages,
# which cite the core book, and the Progeny V5 character creator's clan data).
# In-clan disciplines also match QR p.5.
#
# Banes scale with Bane Severity, which comes from Blood Potency
# (BLOOD_POTENCY[bp]["bane_severity"]); "Bane Severity" in the text below
# means that number. Compulsions trigger on a bestial failure (QR p.3-4)
# and are not stored on the character either.
#
# Caitiff and thin-bloods have no clan bane, compulsion or in-clan
# disciplines (QR p.2, p.5). Caitiff take the Suspect flaw at creation and
# pay new level x 6 XP for any discipline; thin-bloods take 1-3 thin-blood
# merits and the same number of thin-blood flaws, and get Thin-Blood Alchemy
# only through the Thin-blood Alchemist merit.
#
# CORE BOOK ONLY. The owner chose "V5 core book exactly", so CLANS holds the
# core-book clans. Clans from later books are in NON_CORE_CLANS below; they
# are not offered to players, and the Character.clan setter rejects them.
# Re-enabling one is an owner decision (see the PR 11 sign-off table): move
# its entry into CLANS.

CLANS = {
    "Brujah": {
        "disciplines": ["Celerity", "Potence", "Presence"],
        "bane": "Violent Temper: subtract Bane Severity dice from rolls to resist fury frenzy",
        "compulsion": ("Rebellion: -2 dice to all pools until you defy an order or expectation, "
                       "or change someone's mind"),
    },
    "Gangrel": {
        "disciplines": ["Animalism", "Fortitude", "Protean"],
        "bane": ("Bestial Features: in frenzy you gain animal features equal to Bane Severity, "
                 "each -1 to one Attribute, lasting one more night (one feature if you ride the wave)"),
        "compulsion": ("Feral Impulses: for one scene, -3 dice to rolls using Manipulation or "
                       "Intelligence, and you can speak only in one-word sentences"),
    },
    "Malkavian": {
        "disciplines": ["Auspex", "Dominate", "Obfuscate"],
        "bane": ("Fractured Perspective: on a bestial failure or compulsion, a penalty equal to Bane "
                 "Severity to one category of pools (chosen at creation) for the scene"),
        "compulsion": ("Delusion: for one scene, -2 dice to rolls using Dexterity, Manipulation, "
                       "Composure or Wits, and to rolls to resist terror frenzy"),
    },
    "Nosferatu": {
        "disciplines": ["Animalism", "Obfuscate", "Potence"],
        "bane": ("Repulsiveness: you take the Repulsive flaw and can't buy Looks merits; any attempt "
                 "to pass as undeformed (even by Discipline) loses Bane Severity dice"),
        "compulsion": ("Cryptophilia: -2 dice to actions not aimed at learning a secret, until you "
                       "learn a useful one; you won't share secrets except for a greater one"),
    },
    "Toreador": {
        "disciplines": ["Auspex", "Celerity", "Presence"],
        "bane": ("Aesthetic Fixation: in surroundings you find less than beautiful, subtract Bane "
                 "Severity dice from Discipline pools"),
        "compulsion": ("Obsession: -2 dice to actions not related to the object of your fixation, "
                       "until you can no longer perceive it or the scene ends"),
    },
    "Tremere": {
        "disciplines": ["Auspex", "Blood Sorcery", "Dominate"],
        "bane": ("Deficient Blood: you can't Blood Bond Kindred; a mortal or ghoul needs Bane "
                 "Severity extra drinks of your blood to be bound"),
        "compulsion": ("Perfectionism: -2 dice to all pools until you score a critical win on a "
                       "Skill roll or the scene ends; repeating an action lowers the penalty"),
    },
    "Ventrue": {
        "disciplines": ["Dominate", "Fortitude", "Presence"],
        "bane": ("Rarefied Taste: choose a preferred prey at creation; feeding outside it costs "
                 "Willpower equal to Bane Severity, or you vomit the blood and slake nothing"),
        "compulsion": ("Arrogance: -2 dice to actions not related to leadership, until someone "
                       "obeys an order you gave without supernatural compulsion"),
    },
    "Caitiff": {
        "disciplines": [],
        "bane": None,
        "compulsion": None,
    },
    "Thin-Blood": {
        "disciplines": [],
        "bane": None,
        "compulsion": None,
    },
}

# Non-core clans. NOT offered to players (see CLANS above); kept, with their
# sources, so the owner can decide whether to enable any of them. Sources:
# vtm.paradoxwikis.com clan pages and the Progeny V5 character creator.
NON_CORE_CLANS = {
    "Banu Haqim": {
        "source": "V5 Camarilla p.157",
        "disciplines": ["Blood Sorcery", "Celerity", "Obfuscate"],
        "bane": ("Blood Addiction: slaking at least 1 Hunger from a vampire forces a hunger frenzy "
                 "test at Difficulty 2 + Bane Severity"),
        "compulsion": ("Judgment: -3 dice to all rolls until you slake 1 Hunger from someone who "
                       "broke one of your Convictions, or the scene ends"),
    },
    "Ministry": {
        "source": "V5 Anarch p.176",
        "disciplines": ["Obfuscate", "Presence", "Protean"],
        "bane": ("Abhors the Light: in direct bright light, -Bane Severity dice to all pools; "
                 "sunlight deals Bane Severity extra Aggravated damage"),
        "compulsion": ("Transgression: -2 dice to actions not aimed at tempting someone to break a "
                       "Chronicle Tenet or Conviction, until someone takes a Stain"),
    },
    "Lasombra": {
        "source": "V5 Chicago by Night (and Players Guide)",
        "disciplines": ["Dominate", "Oblivion", "Potence"],
        "bane": ("Distorted Image: reflections and recordings distort; using modern communication "
                 "tech is a Technology roll at Difficulty 2 + Bane Severity"),
        "compulsion": ("Ruthlessness: after your next failure, -2 dice to all rolls until a later "
                       "attempt at the same action succeeds"),
    },
    "Hecata": {
        "source": "V5 Cults of the Blood Gods (and Players Guide)",
        "disciplines": ["Auspex", "Fortitude", "Oblivion"],
        "bane": ("Painful Kiss: your bite only hurts; victims must pass Stamina + Resolve at "
                 "Difficulty 2 + Bane Severity or recoil"),
        "compulsion": ("Morbidity: -2 dice to actions that don't move something from life toward "
                       "death or back, until you do"),
    },
    "Tzimisce": {
        "source": "V5 Companion (and Players Guide)",
        "disciplines": ["Animalism", "Dominate", "Protean"],
        "bane": ("Grounded: you must sleep among your chosen charge (a place, group or thing) or "
                 "take Aggravated Willpower damage equal to Bane Severity"),
        "compulsion": ("Covetousness: -2 dice to actions not aimed at owning a chosen thing, until "
                       "you own it or it can't be had"),
    },
    "Ravnos": {
        "source": "V5 Companion (and Players Guide)",
        "disciplines": ["Animalism", "Obfuscate", "Presence"],
        "bane": ("Doomed: sleeping in the same place twice in seven nights means rolling Bane "
                 "Severity dice, each 10 dealing 1 Aggravated damage; can't take No Haven"),
        "compulsion": ("Tempting Fate: -2 dice unless you choose the most dangerous solution to your "
                       "next problem, until it is solved or impossible"),
    },
    "Salubri": {
        "source": "V5 Companion (and Players Guide)",
        "disciplines": ["Auspex", "Dominate", "Fortitude"],
        "bane": ("Hunted: vampires who taste your blood must test for hunger frenzy at Difficulty "
                 "2 + Bane Severity; your third eye weeps blood when you use Disciplines"),
        "compulsion": ("Affective Empathy: -2 dice to actions that don't ease someone's personal "
                       "problem, until it is eased or the scene ends"),
    },
}

# ============================================================================
# DISCIPLINES (power levels 1-5)
# ============================================================================
# Source: V5 core book Disciplines chapter (p.244-288); each discipline's
# "source" gives its pages (anchors from the V5 Quick Reference 2.0 p.7).
# Power names, levels, Rouse costs, pools and amalgams were cross-checked
# against at least two community transcriptions of the core book:
# vtm.paradoxwikis.com (cites book and page), whitewolf.fandom.com
# ("Standard Powers (V5)"), and the VicarData, Progeny and vtm-platform V5
# character-creator datasets on GitHub. Powers from later books
# (Camarilla, Anarch, Chicago by Night, Cults of the Blood Gods, Players
# Guide, Companion, ...) are left out.
#
# Each power:
#   name, level (the key it sits under), description (a short paraphrase)
#   rouse      - number of Rouse checks to activate (0 = free)
#   dice_pool  - the user's pool, "Attribute + Trait"; "A / B + C" means
#                A or B plus C. None = no roll.
#   opposed_by - the target's resistance pool, if the roll is contested
#   duration   - short text
#   amalgam    - "Discipline N" the character must also have, or None
#   note       - optional rules detail the fields above can't express
#
# Blood Sorcery rituals and Thin-Blood Alchemy formulas are not powers:
# they live under "rituals" and "formulas" and are bought separately
# (XP: level x 3, QR p.1).


def _power(name, rouse, dice_pool, duration, description, *, opposed_by=None, amalgam=None, note=None):
    power = {
        "name": name,
        "description": description,
        "rouse": rouse,
        "dice_pool": dice_pool,
        "duration": duration,
        "amalgam": amalgam,
    }
    if opposed_by:
        power["opposed_by"] = opposed_by
    if note:
        power["note"] = note
    return power


def _ritual(name, level, description, *, dice_pool="Intelligence + Blood Sorcery", opposed_by=None, rouse=1):
    ritual = {"name": name, "level": level, "description": description, "rouse": rouse, "dice_pool": dice_pool}
    if opposed_by:
        ritual["opposed_by"] = opposed_by
    return ritual


def _formula(name, rouse, dice_pool, duration, description, *, resonance=None, opposed_by=None, note=None):
    formula = _power(name, rouse, dice_pool, duration, description, opposed_by=opposed_by, note=note)
    formula["resonance"] = resonance
    return formula


DISCIPLINES = {
    "Animalism": {
        "type": "standard",
        "description": "Commune with and command animals and the Beast",
        "source": "V5 core p.244-247",
        "powers": {
            1: [
                _power("Bond Famulus", 3, "Charisma + Animal Ken", "permanent",
                       "Ghoul one animal as a bonded companion that obeys simple commands",
                       note="3 Rouse checks over three nights, done once; the pool is for giving commands"),
                _power("Sense the Beast", 0, "Resolve + Animalism", "passive",
                       "Sense hostility, Hunger and supernatural nature in others",
                       opposed_by="Composure + Subterfuge"),
            ],
            2: [
                _power("Feral Whispers", 1, "Manipulation / Charisma + Animalism", "one scene",
                       "Talk with animals and summon those nearby",
                       note="1 Rouse per animal type per scene"),
            ],
            3: [
                _power("Animal Succulence", 0, None, "passive",
                       "Feeding on animals slakes more Hunger"),
                _power("Quell the Beast", 1, "Charisma + Animalism", "one scene",
                       "Cow a mortal into apathy, or pull a vampire out of frenzy",
                       opposed_by="Stamina + Resolve"),
                _power("Unliving Hive", 0, None, "passive",
                       "Your body hosts insect swarms that your Animalism powers can command",
                       amalgam="Obfuscate 2"),
            ],
            4: [
                _power("Subsume the Spirit", 1, "Manipulation + Animalism", "one scene",
                       "Move your mind into an animal's body and control it"),
            ],
            5: [
                _power("Animal Dominion", 2, "Charisma + Animalism", "one scene",
                       "Command whole flocks or swarms of animals"),
                _power("Drawing Out the Beast", 1, "Wits + Animalism", "one scene",
                       "Push your own frenzy out onto a nearby victim",
                       opposed_by="Composure + Resolve"),
            ],
        },
    },
    "Auspex": {
        "type": "standard",
        "description": "Supernatural senses and perception",
        "source": "V5 core p.248-252",
        "powers": {
            1: [
                _power("Heightened Senses", 0, None, "until ended",
                       "Add Auspex to perception rolls; senses sharpen beyond human limits",
                       note="Wits + Resolve only to resist sensory overload"),
                _power("Sense the Unseen", 0, "Wits / Resolve + Auspex", "passive",
                       "Notice Obfuscated beings, ghosts and spying Auspex",
                       opposed_by="Wits + Obfuscate (hidden vampires)"),
            ],
            2: [
                _power("Premonition", 0, "Resolve + Auspex", "passive",
                       "Receive intuitive visions and warnings",
                       note="1 Rouse when invoked actively; the pool is for active use"),
            ],
            3: [
                _power("Scry the Soul", 1, "Intelligence + Auspex", "one turn",
                       "Read a subject's aura: emotions, nature, diablerie",
                       opposed_by="Composure + Subterfuge"),
                _power("Share the Senses", 1, "Resolve + Auspex", "one scene",
                       "See and hear through another person's senses"),
            ],
            4: [
                _power("Spirit's Touch", 1, "Intelligence + Auspex", "one turn",
                       "Read emotional traces left on objects and places"),
            ],
            5: [
                _power("Clairvoyance", 1, "Intelligence + Auspex", "up to one night",
                       "Gather information about the surrounding area"),
                _power("Possession", 2, "Resolve + Auspex", "until ended",
                       "Take over a mortal's body",
                       opposed_by="Resolve + Intelligence", amalgam="Dominate 3"),
                _power("Telepathy", 1, "Resolve + Auspex", "one scene",
                       "Read surface thoughts or send your own",
                       opposed_by="Wits + Subterfuge",
                       note="Also 1 Willpower against an unwilling vampire"),
            ],
        },
    },
    "Blood Sorcery": {
        "type": "ritual",
        "description": "Blood magic and rituals",
        "source": "V5 core p.271-282",
        "powers": {
            1: [
                _power("Corrosive Vitae", 1, None, "instant",
                       "Your blood eats through inanimate, non-living matter",
                       note="More Rouse checks for a bigger effect"),
                _power("A Taste for Blood", 0, "Resolve + Blood Sorcery", "instant",
                       "Tasting a drop of blood reveals basic facts about its owner"),
            ],
            2: [
                _power("Extinguish Vitae", 1, "Intelligence + Blood Sorcery", "instant",
                       "Spoil another vampire's blood, raising their Hunger",
                       opposed_by="Stamina + Composure"),
            ],
            3: [
                _power("Blood of Potency", 1, "Resolve + Blood Sorcery", "one scene or one night",
                       "Temporarily raise your own Blood Potency"),
                _power("Scorpion's Touch", 1, "Strength + Blood Sorcery", "one scene",
                       "Turn your blood into a paralysing poison",
                       opposed_by="Stamina + Occult / Fortitude",
                       note="More Rouse checks for a stronger poison"),
            ],
            4: [
                _power("Theft of Vitae", 1, "Wits + Blood Sorcery", "one feeding",
                       "Draw a mortal's blood through the air into your mouth",
                       opposed_by="Wits + Occult"),
            ],
            5: [
                _power("Baal's Caress", 1, "Strength + Blood Sorcery", "one scene",
                       "Turn your blood into a poison that deals Aggravated damage",
                       opposed_by="Stamina + Occult / Fortitude",
                       note="More Rouse checks for a stronger poison"),
                _power("Cauldron of Blood", 1, "Resolve + Blood Sorcery", "one turn",
                       "Boil a victim's blood inside their body",
                       opposed_by="Composure + Occult / Fortitude",
                       note="Also costs Stains"),
            ],
        },
        # Rituals are learned separately from powers (XP: ritual level x 3).
        # Each costs 1 Rouse check, takes 5 minutes per level and rolls
        # Intelligence + Blood Sorcery at Difficulty level + 1 unless noted.
        # Source: V5 core p.275-282.
        "rituals": [
            _ritual("Blood Walk", 1, "Learn a subject's name, generation and sire from their blood"),
            _ritual("Clinging of the Insect", 1, "Climb walls and ceilings like a spider"),
            _ritual("Craft Bloodstone", 1, "Make a stone you can always locate"),
            _ritual("Wake with Evening's Freshness", 1, "Wake during the day when danger comes"),
            _ritual("Ward against Ghouls", 1, "Ward an object so it harms ghouls who touch it"),
            _ritual("Communicate with Kindred Sire", 2, "Talk mind to mind with your sire"),
            _ritual("Eyes of Babel", 2, "Gain a language from an eye and tongue"),
            _ritual("Illuminate the Trail of Prey", 2, "Make a known target's path glow"),
            _ritual("Truth of Blood", 2, "Your blood shows whether a statement is true"),
            _ritual("Ward against Spirits", 2, "Ward an object against spirits"),
            _ritual("Warding Circle against Ghouls", 2, "Ward an area against ghouls"),
            _ritual("Dagon's Call", 3, "Drown a target from afar through their blood",
                    dice_pool="Resolve + Blood Sorcery", opposed_by="Stamina + Resolve"),
            _ritual("Deflection of Wooden Doom", 3, "The first stake to strike you fails"),
            _ritual("Essence of Air", 3, "Become able to fly"),
            _ritual("Firewalker", 3, "Resist fire"),
            _ritual("Ward against Lupines", 3, "Ward an object against werewolves"),
            _ritual("Warding Circle against Spirits", 3, "Ward an area against spirits"),
            _ritual("Defense of the Sacred Haven", 4, "Your haven's windows block sunlight"),
            _ritual("Eyes of the Nighthawk", 4, "See through a bird and use Disciplines through it"),
            _ritual("Incorporeal Passage", 4, "Become intangible"),
            _ritual("Ward against Cainites", 4, "Ward an object against vampires"),
            _ritual("Warding Circle against Lupines", 4, "Ward an area against werewolves"),
            _ritual("Escape to True Sanctuary", 5, "Step between two prepared circles"),
            _ritual("Heart of Stone", 5, "Your heart turns to stone: immune to staking and emotion"),
            _ritual("Shaft of Belated Dissolution", 5, "Make a rowan stake whose splinter seeks the heart",
                    rouse=2),
            _ritual("Warding Circle against Cainites", 5, "Ward an area against vampires"),
        ],
    },
    "Celerity": {
        "type": "standard",
        "description": "Supernatural speed and reflexes",
        "source": "V5 core p.252-254",
        "powers": {
            1: [
                _power("Cat's Grace", 0, None, "passive",
                       "Automatically keep your balance"),
                _power("Rapid Reflexes", 0, None, "passive",
                       "Dodge gunfire without cover at no penalty; minor actions are faster"),
            ],
            2: [
                _power("Fleetness", 1, None, "one scene",
                       "Add Celerity to non-combat Dexterity rolls and to Dexterity-based defense"),
            ],
            3: [
                _power("Blink", 1, "Dexterity + Athletics", "one turn",
                       "Dash a long distance almost instantly and still act",
                       note="Roll only if the terrain makes it uncertain"),
                _power("Traversal", 1, "Dexterity + Athletics", "one turn",
                       "Run up walls or across liquid"),
            ],
            4: [
                _power("Draught of Elegance", 1, None, "one night",
                       "Those who drink your blood gain Celerity"),
                _power("Unerring Aim", 1, None, "one attack",
                       "The target can't defend against your ranged attack",
                       amalgam="Auspex 2"),
            ],
            5: [
                _power("Lightning Strike", 1, None, "one attack",
                       "The target can't defend against your close-combat attack"),
                _power("Split Second", 1, None, "one action",
                       "Act in a sudden moment, rewriting what just happened"),
            ],
        },
    },
    "Dominate": {
        "type": "standard",
        "description": "Mind control and mental commands",
        "source": "V5 core p.254-257",
        "powers": {
            1: [
                _power("Cloud Memory", 0, "Charisma + Dominate", "permanent",
                       "Make the target forget the current moment",
                       opposed_by="Wits + Resolve"),
                _power("Compel", 0, "Charisma + Dominate", "up to one scene",
                       "A one-word or short command the target obeys at once",
                       opposed_by="Intelligence + Resolve"),
            ],
            2: [
                _power("Mesmerize", 1, "Manipulation + Dominate", "until done or scene ends",
                       "Implant a more complex command",
                       opposed_by="Intelligence + Resolve"),
                _power("Dementation", 1, "Manipulation + Dominate", "one scene",
                       "Push the target toward breakdown or madness",
                       opposed_by="Composure + Intelligence", amalgam="Obfuscate 2"),
            ],
            3: [
                _power("The Forgetful Mind", 1, "Manipulation + Dominate", "permanent",
                       "Rewrite the target's memories",
                       opposed_by="Intelligence + Resolve"),
                _power("Submerged Directive", 0, None, "passive",
                       "Mesmerize commands can wait for a trigger"),
            ],
            4: [
                _power("Rationalize", 0, None, "permanent",
                       "Victims explain away dominated acts as their own choice"),
            ],
            5: [
                _power("Mass Manipulation", 1, None, "as the amplified power",
                       "Use a Dominate power on a whole group at once",
                       note="1 Rouse on top of the amplified power's cost; uses its pool"),
                _power("Terminal Decree", 0, None, "passive",
                       "Your commands may now harm or kill the victim"),
            ],
        },
    },
    "Fortitude": {
        "type": "standard",
        "description": "Supernatural resilience and toughness",
        "source": "V5 core p.258-260",
        "powers": {
            1: [
                _power("Resilience", 0, None, "passive",
                       "Add Fortitude to your Health track"),
                _power("Unswayable Mind", 0, None, "passive",
                       "Add Fortitude to resist coercion and attempts to sway your mind"),
            ],
            2: [
                _power("Toughness", 1, None, "one scene",
                       "Subtract Fortitude from Superficial physical damage"),
                _power("Enduring Beasts", 1, "Stamina + Animalism", "one scene",
                       "Animals you influence gain extra Health equal to your Fortitude",
                       amalgam="Animalism 1", note="Free and no roll on your famulus"),
            ],
            3: [
                _power("Defy Bane", 1, None, "one scene",
                       "Turn Aggravated damage from your banes into Superficial",
                       note="Wits + Survival to activate it reflexively"),
                _power("Fortify the Inner Facade", 0, None, "one scene",
                       "Harder to read with Scry the Soul or Telepathy; add Fortitude to resist"),
            ],
            4: [
                _power("Draught of Endurance", 1, None, "one night",
                       "Those who drink your blood temporarily gain Fortitude"),
            ],
            5: [
                _power("Flesh of Marble", 2, None, "one scene",
                       "Ignore the first source of physical damage each turn (not sunlight)"),
                _power("Prowess from Pain", 1, None, "one scene",
                       "No wound penalties; your injuries boost physical Attributes"),
            ],
        },
    },
    "Obfuscate": {
        "type": "standard",
        "description": "Supernatural stealth and invisibility",
        "source": "V5 core p.260-263",
        # Seeing through Obfuscate is a contest; the core book's general rule
        # is the observer's Wits + Auspex against the user's Wits +
        # Obfuscate (UNVERIFIED: from one researcher's reading of p.260).
        "powers": {
            1: [
                _power("Cloak of Shadows", 0, None, "one scene",
                       "Become unseen while you keep still"),
                _power("Silence of Death", 0, None, "one scene",
                       "Silence every sound you make"),
            ],
            2: [
                # UNVERIFIED: whether it has an activation pool (sources give
                # none, Wits + Stealth, or Wits + Obfuscate / Stealth).
                _power("Unseen Passage", 1, None, "one scene",
                       "Stay hidden while you move"),
            ],
            3: [
                _power("Ghost in the Machine", 0, None, "as the power used",
                       "Your Obfuscate also fools cameras, recordings and electronics"),
                _power("Mask of a Thousand Faces", 1, None, "one scene",
                       "Appear as a forgettable stranger who fits the setting"),
            ],
            4: [
                _power("Conceal", 1, "Intelligence + Obfuscate", "one night",
                       "Hide an object up to the size of a small building",
                       amalgam="Auspex 3", note="One more night per point of margin"),
                _power("Vanish", 0, "Wits + Obfuscate", "as the power used",
                       "Use Cloak of Shadows or Unseen Passage while being watched",
                       opposed_by="Wits + Awareness",
                       note="Costs what the boosted power costs"),
            ],
            5: [
                _power("Cloak the Gathering", 1, None, "as the power used",
                       "Extend your Obfuscate to your companions",
                       note="1 Rouse on top of the extended power's cost"),
                _power("Impostor's Guise", 1, "Wits + Obfuscate", "one scene",
                       "Look like one specific person",
                       note="Manipulation + Performance to keep up the act"),
            ],
        },
    },
    "Potence": {
        "type": "standard",
        "description": "Supernatural strength",
        "source": "V5 core p.263-266",
        "powers": {
            1: [
                _power("Lethal Body", 0, None, "passive",
                       "Your unarmed blows deal Aggravated damage to mortals"),
                _power("Soaring Leap", 0, None, "passive",
                       "Jump much higher and farther"),
            ],
            2: [
                _power("Prowess", 1, None, "one scene",
                       "Add Potence to unarmed and melee damage and to Strength feats"),
            ],
            3: [
                _power("Brutal Feed", 0, None, "one feeding",
                       "Drain a mortal completely within seconds"),
                _power("Spark of Rage", 1, "Manipulation + Potence", "one scene",
                       "Stir onlookers to anger or frenzy",
                       amalgam="Presence 3"),
                _power("Uncanny Grip", 1, None, "one scene",
                       "Climb and hang from walls and ceilings"),
            ],
            4: [
                _power("Draught of Might", 1, None, "one night",
                       "Those who drink your blood temporarily gain Potence"),
            ],
            5: [
                _power("Earthshock", 2, None, "instant",
                       "Strike the ground to stagger or knock down those nearby",
                       note="Everyone within 5 m rolls Dexterity + Athletics at Difficulty 3; once per scene"),
                _power("Fist of Caine", 1, None, "one scene",
                       "Your unarmed attacks deal Aggravated damage to mortals and vampires"),
            ],
        },
    },
    "Presence": {
        "type": "standard",
        "description": "Supernatural charisma and emotion manipulation",
        "source": "V5 core p.266-269",
        "powers": {
            1: [
                _power("Awe", 0, "Manipulation + Presence", "one scene",
                       "Become captivating; add Presence to Persuasion, Performance and Charisma pools",
                       opposed_by="Composure + Intelligence"),
                _power("Daunt", 0, None, "one scene",
                       "Add Presence to Intimidation; can't be used with Awe",
                       note="Anyone attacking you rolls Resolve + Composure at Difficulty 2"),
            ],
            2: [
                _power("Lingering Kiss", 0, None, "passive",
                       "Those you feed on grow attached to you",
                       note="The effect on a victim lasts nights equal to your Presence"),
            ],
            3: [
                _power("Dread Gaze", 1, "Charisma + Presence", "one turn",
                       "Terrify a target into fleeing or cowering",
                       opposed_by="Composure + Resolve"),
                _power("Entrancement", 1, "Charisma + Presence", "one hour",
                       "The target becomes infatuated and eager to please",
                       opposed_by="Composure + Wits", note="One more hour per point of margin"),
            ],
            4: [
                _power("Irresistible Voice", 0, None, "passive",
                       "Use Dominate with your voice alone, without eye contact",
                       amalgam="Dominate 1"),
                _power("Summon", 1, "Manipulation + Presence", "one night",
                       "Call someone you have used Presence on, or who tasted your blood",
                       opposed_by="Composure + Intelligence"),
            ],
            5: [
                _power("Majesty", 2, "Charisma + Presence", "one scene",
                       "No one can act against you without first resisting",
                       opposed_by="Composure + Resolve"),
                _power("Star Magnetism", 1, None, "as the power used",
                       "Presence powers work through live video and audio",
                       note="1 Rouse on top of the power used"),
            ],
        },
    },
    "Protean": {
        "type": "standard",
        "description": "Shapeshifting and transformation",
        "source": "V5 core p.269-271",
        "powers": {
            1: [
                _power("Eyes of the Beast", 0, None, "as long as desired",
                       "Your eyes glow and see in total darkness"),
                _power("Weight of the Feather", 0, None, "as long as desired",
                       "Become nearly weightless; no damage from falls or impacts",
                       note="Wits + Survival to activate it reflexively"),
            ],
            2: [
                _power("Feral Weapons", 1, None, "one scene",
                       "Grow deadly claws or fangs"),
            ],
            3: [
                _power("Earth Meld", 1, None, "a day or more",
                       "Sink into the earth to rest"),
                _power("Shapechange", 1, None, "one scene",
                       "Turn into one human-sized animal"),
            ],
            4: [
                _power("Metamorphosis", 1, None, "one scene",
                       "Take an extra animal form of any size",
                       note="Requires Shapechange"),
            ],
            5: [
                _power("Mist Form", 1, None, "one scene",
                       "Turn into mist that only fire, sun or supernatural attacks can harm",
                       note="Up to 3 Rouse checks; each extra one makes the change faster"),
                _power("The Unfettered Heart", 0, None, "passive",
                       "Your heart moves within your chest, making you much harder to stake"),
            ],
        },
    },
    "Thin-Blood Alchemy": {
        "type": "thin-blood",
        "description": "Alchemical formulae unique to thin-blooded vampires",
        "source": "V5 core p.282-288",
        # Thin-Blood Alchemy has formulas, not powers; a thin-blood gets it
        # through the Thin-blood Alchemist merit (QR p.2, p.11). Formulas are
        # learned separately (XP: formula level x 3) and distilled before
        # use. Distilling costs 1 Rouse check (Athanor Corporis: Stamina +
        # Alchemy; Calcinatio: Manipulation + Alchemy; Fixatio: Intelligence
        # + Alchemy when used), then the formula's own activation cost
        # applies. "rouse" below is that activation cost.
        "powers": {},
        "formulas": {
            1: [
                _formula("Far Reach", 1, "Resolve + Thin-Blood Alchemy", "one scene",
                         "Telekinetically shove or hold an object or person",
                         resonance="Choleric", opposed_by="Strength + Athletics"),
                _formula("Haze", 1, None, "one scene",
                         "Surround yourself with a cloud of mist",
                         resonance="Phlegmatic", note="1 more Rouse to cover a group"),
            ],
            2: [
                _formula("Envelop", 1, "Wits + Thin-Blood Alchemy", "one scene",
                         "A mist smothers and blinds one target",
                         resonance="Melancholy and Phlegmatic", opposed_by="Stamina + Survival"),
                _formula("Counterfeit", 0, None, "as the copied power",
                         "Copy a Discipline power one level below your Alchemy rating",
                         note=("Formula at levels 2-5; from level 3 needs vitae of a vampire who has "
                               "the Discipline. Cost and pool are the copied power's.")),
            ],
            3: [
                # UNVERIFIED: activation cost (sources split between 0 and 1 Rouse).
                _formula("Defractionate", 0, None, "instant",
                         "Make bagged or treated blood drinkable and nourishing",
                         resonance="Melancholy and Sanguine"),
                _formula("Profane Hieros Gamos", 1, "Stamina + Resolve", "permanent",
                         "Permanently reshape your body or sex",
                         resonance="Melancholy and Phlegmatic",
                         note="Difficulty 8 minus the distillation successes"),
            ],
            4: [
                _formula("Airborne Momentum", 1, "Strength + Thin-Blood Alchemy", "one scene",
                         "Fly under your own power",
                         resonance="Choleric and Sanguine"),
            ],
            5: [
                # UNVERIFIED: activation cost (sources split between 0 and 1 Rouse).
                _formula("Awaken the Sleeper", 1, None, "instant",
                         "Wake a vampire from day-sleep or torpor",
                         resonance="Choleric or Sanguine"),
            ],
        },
    },
}

# Non-core disciplines. NOT offered to players: they belong to the non-core
# clans (NON_CORE_CLANS) and are not in the trait registry or the power
# index. Kept so the owner can decide; see the PR 11 sign-off table.
#
# Oblivion: Chicago by Night p.293-294, Cults of the Blood Gods p.204-208,
# Players Guide p.85-90 (names, levels and amalgams from
# vtm.paradoxwikis.com, which cites those pages).
# UNVERIFIED: every Rouse cost and pool below except Tenebrous Avatar (2
# Rouse); they default to 1 Rouse and no pool. Ceremonies are listed by
# name and level only.
NON_CORE_DISCIPLINES = {
    "Oblivion": {
        "type": "standard",
        "description": "Power over shadow and the restless dead",
        "source": "Chicago by Night; Cults of the Blood Gods; Players Guide",
        "powers": {
            1: [
                _power("Shadow Cloak", 1, None, "one scene", "Wrap yourself in concealing shadow"),
                _power("Oblivion's Sight", 1, None, "one scene", "See in darkness and perceive ghosts"),
                _power("Ashes to Ashes", 1, None, "instant", "Dissolve a corpse"),
                _power("The Binding Fetter", 1, None, "one scene", "Sense the objects that anchor ghosts"),
            ],
            2: [
                _power("Shadow Cast", 1, None, "one scene", "Conjure shadows that hinder others"),
                _power("Arms of Ahriman", 1, None, "one scene", "Shadow limbs that grapple and strike",
                       amalgam="Potence 2"),
                _power("Fatal Precognition", 1, None, "instant", "Foresee a target's death",
                       amalgam="Auspex 2"),
                _power("Where the Shroud Thins", 1, None, "instant", "Sense how thin the barrier to death is"),
            ],
            3: [
                _power("Aura of Decay", 1, None, "one scene", "Things around you rot and wither"),
                _power("Passion Feast", 1, None, "instant", "Feed on a ghost's passion to slake Hunger",
                       amalgam="Fortitude 2"),
                _power("Shadow Perspective", 1, None, "one scene", "See and hear through a shadow"),
                _power("Shadow Servant", 1, None, "one scene", "Send a shadow to spy or act for you"),
                _power("Touch of Oblivion", 1, None, "instant", "Wither a victim's body by touch"),
            ],
            4: [
                _power("Necrotic Plague", 1, None, "instant", "Inflict a wasting sickness"),
                _power("Stygian Shroud", 1, None, "one scene", "Fill an area with smothering darkness"),
            ],
            5: [
                _power("Shadow Step", 1, None, "instant", "Step through one shadow and out of another"),
                _power("Skuld Fulfilled", 1, None, "instant", "Bring back an illness or injury a victim survived"),
                _power("Tenebrous Avatar", 2, None, "one scene", "Become a creature of living shadow"),
                _power("Withering Spirit", 1, None, "instant", "Erode a victim's will to live"),
            ],
        },
        "ceremonies": [
            {"name": "Gift of False Life", "level": 1},
            {"name": "Summon Spirit", "level": 1},
            {"name": "Awaken the Homuncular Servant", "level": 2},
            {"name": "Compel Spirit", "level": 2},
            {"name": "Host Spirit", "level": 3},
            {"name": "Shambling Hordes", "level": 3},
            {"name": "Bind the Spirit", "level": 4},
            {"name": "Split the Shroud", "level": 4},
            {"name": "Lazarene Blessing", "level": 5},
        ],
    },
}

# Every discipline name the data mentions, core or not (used to check that
# amalgams and clan lists point at something real).
ALL_DISCIPLINES = {**DISCIPLINES, **NON_CORE_DISCIPLINES}


# ============================================================================
# PREDATOR TYPES
# ============================================================================
# Source: V5 core p.175-178 (predator types) and p.307-308 (hunting pools),
# cross-checked against vtm.paradoxwikis.com/Predator_type (cites those
# pages) and the Progeny and VicarData V5 character-creator data. QR p.2:
# the bonus specialty, discipline and advantages/flaws cost no XP;
# thin-bloods and fledglings take no predator type.
#
#   hunting_pool       - the type's hunting roll (None: the book says not
#                        to reduce Blood Leech hunting to one roll)
#   alt_hunting_pool   - a second pool the book offers, if any
#   specialties        - (skill, specialty) pairs; pick one
#   disciplines        - pick one and take a dot in it
#   discipline_clans   - disciplines only some clans may pick, and which
#   humanity, blood_potency - changes to the starting value
#   merits, flaws, backgrounds - fixed grants: {"name", "dots", "note"}
#   flaw_choices, advantage_choices - "spend N dots among these" grants

PREDATOR_TYPES = {
    "Alleycat": {
        "description": "Take blood by force or threat from people on the street",
        "hunting_pool": "Strength + Brawl",
        "alt_hunting_pool": "Wits + Streetwise",
        "specialties": [("Intimidation", "Stickups"), ("Brawl", "Grappling")],
        "disciplines": ["Celerity", "Potence"],
        "humanity": -1,
        "blood_potency": 0,
        "merits": [],
        "flaws": [],
        "backgrounds": [{"name": "Contacts", "dots": 3, "note": "criminals"}],
    },
    "Bagger": {
        "description": "Feed on blood bags, corpses and other preserved blood",
        "hunting_pool": "Intelligence + Streetwise",
        "specialties": [("Larceny", "Lock Picking"), ("Streetwise", "Black Market")],
        "disciplines": ["Blood Sorcery", "Obfuscate"],
        # Core: Tremere only. The Players Guide p.107 adds Banu Haqim.
        "discipline_clans": {"Blood Sorcery": ["Tremere", "Banu Haqim"]},
        "humanity": 0,
        "blood_potency": 0,
        "merits": [{"name": "Iron Gullet", "dots": 3}],
        "flaws": [{"name": "Enemy", "dots": 2, "note": "someone who thinks you owe them"}],
        "backgrounds": [],
        "note": "Ventrue can't take this predator type",
    },
    "Blood Leech": {
        "description": "Feed on other vampires",
        "hunting_pool": None,
        "specialties": [("Brawl", "Kindred"), ("Stealth", "Against Kindred")],
        "disciplines": ["Celerity", "Protean"],
        "humanity": -1,
        "blood_potency": 1,
        "merits": [],
        "flaws": [{"name": "Prey Exclusion", "dots": 2, "note": "mortals"}],
        "flaw_choices": [{"dots": 2, "from": ["Dark Secret", "Shunned"],
                          "note": "Dark Secret: Diablerist, or Shunned"}],
        "backgrounds": [],
    },
    "Cleaver": {
        "description": "Feed covertly on your own mortal family or friends",
        "hunting_pool": "Manipulation + Subterfuge",
        "specialties": [("Persuasion", "Gaslighting"), ("Subterfuge", "Coverups")],
        "disciplines": ["Animalism", "Dominate"],
        "humanity": 0,
        "blood_potency": 0,
        "merits": [],
        "flaws": [{"name": "Dark Secret", "dots": 1, "note": "Cleaver"}],
        "backgrounds": [{"name": "Herd", "dots": 2}],
    },
    "Consensualist": {
        "description": "Feed only with the vessel's consent",
        "hunting_pool": "Manipulation + Persuasion",
        "specialties": [("Medicine", "Phlebotomy"), ("Persuasion", "Vessels")],
        "disciplines": ["Auspex", "Fortitude"],
        "humanity": 1,
        "blood_potency": 0,
        "merits": [],
        "flaws": [
            {"name": "Dark Secret", "dots": 1, "note": "Masquerade breacher"},
            {"name": "Prey Exclusion", "dots": 1, "note": "non-consenting vessels"},
        ],
        "backgrounds": [],
    },
    "Farmer": {
        "description": "Feed on animals only",
        "hunting_pool": "Composure + Animal Ken",
        "specialties": [("Animal Ken", "Specific animal"), ("Survival", "Hunting")],
        "disciplines": ["Animalism", "Protean"],
        "humanity": 1,
        "blood_potency": 0,
        "merits": [],
        "flaws": [{"name": "Farmer", "dots": 2}],
        "backgrounds": [],
        "note": "Ventrue and characters of Blood Potency 3+ can't take this predator type",
    },
    "Osiris": {
        "description": "Feed on the followers of your cult, band or fandom",
        # UNVERIFIED: the alternative pool. The wiki writes "Intimidation +
        # Fame", which mixes a Skill and a Background.
        "hunting_pool": "Manipulation + Subterfuge",
        "alt_hunting_pool": "Intimidation + Fame",
        "specialties": [("Occult", "Specific tradition"), ("Performance", "Specific field")],
        "disciplines": ["Blood Sorcery", "Presence"],
        # Core: Tremere only. The Players Guide p.107 adds Banu Haqim.
        "discipline_clans": {"Blood Sorcery": ["Tremere", "Banu Haqim"]},
        "humanity": 0,
        "blood_potency": 0,
        "merits": [],
        "flaws": [],
        "advantage_choices": [{"dots": 3, "from": ["Fame", "Herd"]}],
        "flaw_choices": [{"dots": 2, "from": ["Enemy", "Mythic flaws"]}],
        "backgrounds": [],
    },
    "Sandman": {
        "description": "Feed on sleeping victims",
        "hunting_pool": "Dexterity + Stealth",
        "specialties": [("Medicine", "Anesthetics"), ("Stealth", "Break-in")],
        "disciplines": ["Auspex", "Obfuscate"],
        "humanity": 0,
        "blood_potency": 0,
        "merits": [],
        "flaws": [],
        "backgrounds": [{"name": "Resources", "dots": 1}],
    },
    "Scene Queen": {
        "description": "Feed within a subculture where you have status",
        "hunting_pool": "Manipulation + Persuasion",
        "specialties": [
            ("Etiquette", "Specific scene"),
            ("Leadership", "Specific scene"),
            ("Streetwise", "Specific scene"),
        ],
        "disciplines": ["Dominate", "Potence"],
        "humanity": 0,
        "blood_potency": 0,
        "merits": [],
        "flaws": [],
        "flaw_choices": [{"dots": 1, "from": ["Disliked", "Prey Exclusion"],
                          "note": "Disliked outside the subculture, or Prey Exclusion (a different subculture)"}],
        "backgrounds": [{"name": "Fame", "dots": 1}, {"name": "Contacts", "dots": 1}],
    },
    "Siren": {
        "description": "Feed under the guise of sex or seduction",
        "hunting_pool": "Charisma + Subterfuge",
        "specialties": [("Persuasion", "Seduction"), ("Subterfuge", "Seduction")],
        "disciplines": ["Fortitude", "Presence"],
        "humanity": 0,
        "blood_potency": 0,
        "merits": [{"name": "Beautiful", "dots": 2}],
        "flaws": [{"name": "Enemy", "dots": 1, "note": "a spurned lover or jealous partner"}],
        "backgrounds": [],
    },
}

# ============================================================================
# BACKGROUNDS (Advantages with mechanical benefits)
# ============================================================================
# Source: the core book's Backgrounds (V5 core p.184-194), as summarized in
# the V5 Quick Reference 2.0 pp.8-11, cross-checked against
# vtm.paradoxwikis.com/Advantages_and_Flaws (cites core pages). These are
# the core book's eleven backgrounds. "max_dots" is the highest rating the
# QR lists. Background flaws (Enemy, Adversary, ...) are in FLAWS.
#
# "benefit" and "uses_per_session" drive the in-game +background command.
# They are a game convention, not book rules (UNVERIFIED), except Herd:
# you may slake Hunger up to your Herd rating each week without a hunting
# roll (core p.189 per vtm.paradoxwikis.com).

BACKGROUNDS = {
    "Allies": {
        "instanced": True,
        "max_dots": 5,  # effectiveness 1-4 + reliability 1-3, capped at 5 like other backgrounds
        "description": "Mortal associates, usually family or friends",
        "benefit": "Can call for help. +[dots] to Social rolls when relevant",
        "uses_per_session": "dots",
    },
    "Contacts": {
        "instanced": True,
        "max_dots": 3,
        "description": "People who can get you information or items",
        "benefit": "+[dots] to Investigation when using contacts for information",
        "uses_per_session": "dots * 2",
    },
    "Fame": {
        "max_dots": 5,
        "description": "How well known you are among mortals, from a subculture (1) to worldwide (5)",
        "benefit": "+[dots] to Social rolls with those who recognize you",
        "uses_per_session": "unlimited",
    },
    "Haven": {
        "max_dots": 3,
        "description": "A place to sleep safely by day, from small and likely secure (1) to large and private (3)",
        "benefit": "Security rating: +[dots] to defend against intrusion",
        "uses_per_session": "passive",
    },
    "Herd": {
        "max_dots": 5,
        "description": "Mortals you can feed from freely and safely, from 1-3 (1) to 31-60 (5)",
        "benefit": "Slake up to [dots] Hunger per week from your herd without a hunting roll",
        "uses_per_session": "1 per week",
    },
    "Influence": {
        "instanced": True,
        "max_dots": 5,
        "description": "Political power in mortal society, from well-connected (1) to dominant (5)",
        "benefit": "+[dots] to Leadership/Politics in domain. Can requisition resources",
        "uses_per_session": "dots",
    },
    "Mask": {
        "max_dots": 2,
        "description": "A false identity: a fake ID (1) or one that passes an in-depth check (2)",
        "benefit": "+[dots] to maintain Masquerade and resist investigation",
        "uses_per_session": "passive",
    },
    "Mawla": {
        "instanced": True,
        "max_dots": 5,
        "description": "A Kindred mentor, patron or confederate, from a neonate (1) to a prince or baron (5)",
        "benefit": "Advice, protection and introductions from an elder",
        "uses_per_session": "dots",
    },
    "Resources": {
        "max_dots": 5,
        "description": "Wealth and income, from living paycheck to paycheck (1) to ultra rich (5)",
        "benefit": "Can acquire items of [dots] rating or less. Income level",
        "uses_per_session": "dots",
    },
    "Retainers": {
        "instanced": True,
        "max_dots": 3,
        "description": "Followers, guards and servants, from a weak mortal (1) to a gifted ghoul (3)",
        "benefit": "[dots] loyal servants who can perform tasks",
        "uses_per_session": "unlimited",
    },
    "Status": {
        "instanced": True,
        "max_dots": 5,
        "description": "Standing in a sect, from known (1) to a position of power such as primogen (5)",
        "benefit": "+[dots] to Social rolls with Kindred. Access to Elysium",
        "uses_per_session": "unlimited",
    },
}

# ============================================================================
# BLOOD POTENCY TABLE
# ============================================================================
# Source: Renegade Game Studios, "V5 Blood Potency Correction" (official
# errata sheet, https://renegadegamestudios.com/content/File%20Storage%20for%20site/VTM/BloodPotencyTable.pdf),
# which is the table in The Companion (2020) p.63, Players Guide p.248 and
# later core printings. The V5 Quick Reference 2.0 p.14 and the 2018 first
# printing show older Surge and Bane values; don't use them.
#   blood_surge     - dice added by a Blood Surge
#   mend_amount     - Superficial damage mended per Rouse check
#   power_bonus     - dice added to Discipline pools
#   rouse_reroll    - re-roll a failed Rouse check for powers of this level
#                     and below (0 = no re-roll)
#   bane_severity   - clan Bane Severity
#   feeding_penalty - restrictions on slaking Hunger
# Nothing else in the game may hardcode these values; read this table.

BLOOD_POTENCY = {
    0: {"blood_surge": 1, "mend_amount": 1, "power_bonus": 0, "rouse_reroll": 0, "bane_severity": 0,
        "feeding_penalty": "No effect"},
    1: {"blood_surge": 2, "mend_amount": 1, "power_bonus": 0, "rouse_reroll": 1, "bane_severity": 2,
        "feeding_penalty": "No effect"},
    2: {"blood_surge": 2, "mend_amount": 2, "power_bonus": 1, "rouse_reroll": 1, "bane_severity": 2,
        "feeding_penalty": "Animal and bagged blood slake half Hunger"},
    3: {"blood_surge": 3, "mend_amount": 2, "power_bonus": 1, "rouse_reroll": 2, "bane_severity": 3,
        "feeding_penalty": "Animal and bagged blood slake no Hunger"},
    4: {"blood_surge": 3, "mend_amount": 3, "power_bonus": 2, "rouse_reroll": 2, "bane_severity": 3,
        "feeding_penalty": "Animal and bagged blood slake no Hunger; slake 1 less Hunger per human"},
    5: {"blood_surge": 4, "mend_amount": 3, "power_bonus": 2, "rouse_reroll": 3, "bane_severity": 4,
        "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 1 less Hunger per human; "
                            "must drain and kill a human to reduce Hunger below 2")},
    6: {"blood_surge": 4, "mend_amount": 3, "power_bonus": 3, "rouse_reroll": 3, "bane_severity": 4,
        "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 2 less Hunger per human; "
                            "must drain and kill a human to reduce Hunger below 2")},
    7: {"blood_surge": 5, "mend_amount": 3, "power_bonus": 3, "rouse_reroll": 4, "bane_severity": 5,
        "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 2 less Hunger per human; "
                            "must drain and kill a human to reduce Hunger below 2")},
    8: {"blood_surge": 5, "mend_amount": 4, "power_bonus": 4, "rouse_reroll": 4, "bane_severity": 5,
        "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 2 less Hunger per human; "
                            "must drain and kill a human to reduce Hunger below 3")},
    9: {"blood_surge": 6, "mend_amount": 4, "power_bonus": 4, "rouse_reroll": 5, "bane_severity": 6,
        "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 2 less Hunger per human; "
                            "must drain and kill a human to reduce Hunger below 3")},
    10: {"blood_surge": 6, "mend_amount": 5, "power_bonus": 5, "rouse_reroll": 5, "bane_severity": 6,
         "feeding_penalty": ("Animal and bagged blood slake no Hunger; slake 3 less Hunger per human; "
                             "must drain and kill a human to reduce Hunger below 3")},
}

# ============================================================================
# MERITS & FLAWS
# ============================================================================
# Source: V5 Quick Reference 2.0 pp.8-11 (Advantages & Flaws, compiled from
# V5 core p.179-197), cross-checked against vtm.paradoxwikis.com/
# Advantages_and_Flaws. "category" is the QR heading. "dots" lists the
# ratings a character may take; the cost is the dots, except:
#
# Thin-blood merits and flaws (QR p.11) have no point value: "cost": 0. A
# thin-blood takes one to three of each, and must take one flaw for each
# merit and vice versa (QR p.2). They are stored with dots 1 because a
# rating of 0 means "not taken" on the character.
#
# Background flaws (Enemy, Adversary, Dark Secret, No Haven, ...) are here
# because the character stores them with the other flaws. Domain flaws
# (No Domain) belong to a coterie, not a character.

MERITS = {
    # Linguistics (QR p.9 "Language (•)"): one dot per extra language.
    "Linguistics": {"category": "Linguistics", "dots": (1, 2, 3, 4, 5),
                    "description": "Fluent and literate in one additional language per dot"},
    "Beautiful": {"category": "Looks", "dots": (2,),
                  "description": "+1 die to relevant Social pools"},
    "Stunning": {"category": "Looks", "dots": (4,),
                 "description": "+2 dice to relevant Social pools"},
    "Bloodhound": {"category": "Feeding", "dots": (1,),
                   "description": "Smell the Resonance of mortal blood"},
    "Iron Gullet": {"category": "Feeding", "dots": (3,),
                    "description": "Feed on cold, rancid or preserved blood (no Resonance); not for Ventrue"},
    "Bond Resistance": {"category": "Bonding", "dots": (1,),
                        "description": "+1 die to resist a Blood Bond"},
    "Short Bond": {"category": "Bonding", "dots": (2,),
                   "description": "Blood Bonds on you must be reinforced twice a month"},
    "Unbondable": {"category": "Bonding", "dots": (5,),
                   "description": "You can never be Blood Bound"},
    "High-functioning Addict": {"category": "Substance Use", "dots": (1,),
                                "description": "+1 die when your last feeding included your drug"},
    "Eat Food": {"category": "Mythical", "dots": (2,),
                 "description": "Eat food, though you must purge it before day-sleep"},
    # Thin-blood merits (QR p.11). No point cost; pair each with a flaw.
    "Anarch Comrades": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                        "description": "An Anarch coterie treats you as a mascot (Mawla 1)"},
    "Camarilla Contact": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                          "description": "A Camarilla recruiter keeps you around (Mawla 1)"},
    "Catenating Blood": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                         "description": "You can create Blood Bonds and Embrace"},
    "Day Drinker": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                    "description": ("Sunlight only halves your Health (rounded up) and stops your "
                                    "Disciplines; it does no other damage")},
    "Discipline Affinity": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                            "description": "A permanent dot in one Discipline, never more than one"},
    "Lifelike": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                 "description": "You have a heartbeat and can eat food"},
    "Thin-blood Alchemist": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                             "description": "One dot of Thin-Blood Alchemy and one formula"},
    "Vampiric Resilience": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                            "description": "You take damage like a full vampire"},
}

FLAWS = {
    "Illiterate": {"category": "Linguistics", "dots": (2,),
                   "description": ("You can't read or write; Academics and Science stay at 1 or "
                                   "below with no specialties")},
    "Ugly": {"category": "Looks", "dots": (1,),
             "description": "-1 die to relevant Social pools"},
    "Repulsive": {"category": "Looks", "dots": (2,),
                  "description": "-2 dice to relevant Social pools"},
    "Anachronism": {"category": "Archaic", "dots": (2,),
                    "description": "Your Technology rating is permanently 0"},
    "Living in the Past": {"category": "Archaic", "dots": (1,),
                           "description": "You hold one or more outdated Convictions"},
    "Bondslave": {"category": "Bonding", "dots": (2,),
                  "description": "You are Blood Bound at the first taste of another vampire's blood"},
    "Bond Junkie": {"category": "Bonding", "dots": (1,),
                    "description": "-1 die to act against a Blood Bond"},
    "Long Bond": {"category": "Bonding", "dots": (1,),
                  "description": "Blood Bonds on you need reinforcing only every three months"},
    "Addiction": {"category": "Substance Use", "dots": (1,),
                  "description": "-1 die unless your last feeding included your drug"},
    "Hopeless Addiction": {"category": "Substance Use", "dots": (2,),
                           "description": "-2 dice unless your last feeding included your drug"},
    # Prey Exclusion is (•) in the QR; the Blood Leech predator type grants a
    # 2-dot version (mortals).
    "Prey Exclusion": {"category": "Feeding", "dots": (1, 2),
                       "description": "You refuse to feed on one class of prey"},
    "Methuselah's Thirst": {"category": "Feeding", "dots": (1,),
                            "description": "Your Hunger can't drop below 1 except on supernatural blood"},
    # "Farmer" is the errata'd core name; the QR (and older printings) call
    # it "Vegan".
    "Farmer": {"category": "Feeding", "dots": (2,),
               "description": "You feed only on animals; feeding on humans costs 2 Willpower; not for Ventrue"},
    "Organovore": {"category": "Feeding", "dots": (2,),
                   "description": "You must eat your victim's organs when you feed"},
    "Stake Bait": {"category": "Mythical", "dots": (2,),
                   "description": "A stake through the heart brings Final Death"},
    "Folkloric Bane": {"category": "Mythical", "dots": (1,),
                       "description": "A traditional anti-vampire object deals you Aggravated damage on touch"},
    "Folkloric Block": {"category": "Mythical", "dots": (1,),
                        "description": "You must shrink from a traditional ward or spend Willpower"},
    "Stigmata": {"category": "Mythical", "dots": (1,),
                 "description": "At Hunger 4 you bleed from parts of your body"},
    # Thin-blood flaws (QR p.11). No point cost; pair each with a merit.
    "Baby Teeth": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                   "description": "You have no fangs, or useless ones"},
    "Bestial Temper": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                       "description": "You frenzy like a full vampire"},
    "Branded by the Camarilla": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                                 "description": "A magical brand marks you as a thin-blood"},
    "Clan Curse": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                   "description": ("A clan Bane at severity 1 (Brujah/Gangrel need Bestial Temper, "
                                   "Tremere need Catenating Blood)")},
    "Dead Flesh": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                   "description": "You are slowly decaying; can't take Lifelike"},
    "Mortal Frailty": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                       "description": "You can't Rouse the Blood to mend; can't take Vampiric Resilience"},
    "Shunned by the Anarchs": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                               "description": "The Anarchs treat you as an enemy; can't take Anarch Comrades"},
    "Vitae Dependency": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                         "description": "You must drink vampire blood to use any Discipline"},
    # Background flaws (QR pp.8-11).
    # Enemy (QR p.8): rated two less than the equivalent Allies, so an
    # effectiveness of 1-2 plus a reliability of 0-1.
    "Enemy": {"category": "Allies", "dots": (1, 2, 3),
              "description": "Mortals who want to harm you"},
    "Infamy": {"category": "Fame", "dots": (1, 2, 3, 4, 5),
               "description": "You are infamous, from within a subculture (1) to worldwide (5)"},
    "Dark Secret": {"category": "Fame", "dots": (1, 2),
                    "description": "A secret that would harm you if it came out"},
    "No Haven": {"category": "Haven", "dots": (1,),
                 "description": "You have no fixed haven"},
    "Compromised": {"category": "Haven", "dots": (2,),
                    "description": "Your haven has been raided before; invaders get +2 dice to get in"},
    "Creepy": {"category": "Haven", "dots": (1,),
               "description": "Your haven looks like a serial killer's home"},
    # UNVERIFIED: the upper rating. QR p.9 gives "[•+]" with no maximum.
    "Haunted": {"category": "Haven", "dots": (1, 2, 3),
                "description": "Something supernatural haunts your haven"},
    "Obvious Predator": {"category": "Herd", "dots": (2,),
                         "description": "Mortals fear you: no Herd, and -1 die to put mortals at ease"},
    "Disliked": {"category": "Influence", "dots": (1,),
                 "description": "-1 die to Social pools with everyone but your contacts, allies and coterie"},
    "Despised": {"category": "Influence", "dots": (2,),
                 "description": "A group or region works against you; -2 dice to Social pools with them"},
    "Known Corpse": {"category": "Mask", "dots": (1,),
                     "description": "You died recently and people will recognize you"},
    "Known Blankbody": {"category": "Mask", "dots": (2,),
                        "description": "Intelligence databases flag you as a potential terrorist"},
    "Adversary": {"category": "Mawla", "dots": (1, 2, 3, 4, 5),
                  "description": "A Kindred enemy, from a neonate (1) to a prince or baron (5)"},
    "Destitute": {"category": "Resources", "dots": (1,),
                  "description": "You have no money and no home"},
    "Stalkers": {"category": "Retainers", "dots": (1,),
                 "description": "People tend to become irrationally interested in you"},
    "Suspect": {"category": "Status", "dots": (1,),
                "description": "Not in good standing with a sect; -2 dice to Social tests with it (Caitiff)"},
    "Shunned": {"category": "Status", "dots": (2,),
                "description": "A sect considers you an enemy"},
}

# ============================================================================
# RESONANCES (for Blood Potency/Feeding)
# ============================================================================

RESONANCES = {
    "Choleric": {
        "emotion": "Anger, rage, violence",
        "disciplines": ["Celerity", "Potence"],
        "dyscrasia": "Hot-blooded: +1 die to Physical feats for one scene"
    },
    "Melancholic": {
        "emotion": "Sadness, depression, fear",
        "disciplines": ["Fortitude", "Obfuscate"],
        "dyscrasia": "Icy: +1 die to Composure and Wits for one scene"
    },
    "Phlegmatic": {
        "emotion": "Calm, apathy, laziness",
        "disciplines": ["Auspex", "Dominate"],
        "dyscrasia": "Apathetic: +1 die to resist Dominate/Presence for one scene"
    },
    "Sanguine": {
        "emotion": "Joy, lust, passion",
        "disciplines": ["Blood Sorcery", "Presence"],
        "dyscrasia": "Passionate: +1 die to Persuasion and Performance for one scene"
    },
    "Animal": {
        "emotion": "Bestial (from animals)",
        "disciplines": ["Animalism", "Protean"],
        "dyscrasia": "Feral: +1 die to Survival and Animalism for one scene"
    }
}

# ============================================================================
# STATS TEMPLATE (legacy flat shape)
# ============================================================================
# Legacy: only traits/utils.py (web chargen) still uses this; it goes when
# web chargen writes through the Character accessors. The character schema
# is the nested one in typeclasses/characters.py.

def _get_default_stats_template():
    """
    Returns the default character stats template structure.
    This is used to initialize character.db.stats in the legacy system.
    """
    return {
        # Attributes (default value 1)
        "attributes": _create_attribute_dict(1),
        
        # Skills (default value 0)
        "skills": _create_skills_dict(0),
        
        # Disciplines (populated based on clan)
        "disciplines": {},
        
        # Backgrounds/Advantages
        "backgrounds": {},
        
        # Specialties
        "specialties": {},
        
        # Core stats
        "humanity": 7,
        "willpower": 0,  # Calculated
        "health": 0,     # Calculated
        "hunger": 1,
        "blood_potency": 0,
        
        # Character info
        "splat": "mortal",
        "clan": None,
        "generation": 13,
        
        # Admin tracking
        "xp": 0,
        "approved": False,
        "approved_by": None,
        "notes": ""
    }

# STATS is the base template for character stats
STATS = _get_default_stats_template()

# ============================================================================
# TRAIT CATEGORY LOOKUP
# ============================================================================

def get_trait_category(trait_name):
    """
    Legacy lookup used only by traits/utils.py (web chargen). It treats every
    unknown name as a background; game code uses resolve_trait() instead.

    Get the category (attributes, skills, disciplines) for a given trait name.
    
    Args:
        trait_name: Name of the trait to look up
        
    Returns:
        String category name or None if not found
    """
    trait_lower = trait_name.lower()
    
    # Check attributes
    for attr in _create_attribute_dict().keys():
        if attr == trait_lower:
            return "attributes"
    
    # Check skills
    for skill in _create_skills_dict().keys():
        if skill == trait_lower:
            return "skills"
    
    # Check disciplines
    if trait_name in DISCIPLINES:
        return "disciplines"

    # Check if it's a background (anything else is assumed to be background/advantage)
    return "backgrounds"


# ============================================================================
# DISCIPLINE POWER INDEX
# ============================================================================


def _build_discipline_powers():
    """Flat index of every power in DISCIPLINES, keyed by power name.

    Each value is the power's own dict plus "discipline" and "level". It is a
    view of DISCIPLINES, not a second copy of the data.
    """
    index = {}
    for discipline, data in DISCIPLINES.items():
        for level, powers in data.get("powers", {}).items():
            for power in powers:
                if power["name"] in index:
                    raise ValueError(f"Duplicate discipline power name: {power['name']}")
                index[power["name"]] = dict(power, discipline=discipline, level=level)
    return index


DISCIPLINE_POWERS = _build_discipline_powers()
_POWERS_BY_LOWER_NAME = {name.lower(): name for name in DISCIPLINE_POWERS}


def find_power(power_name):
    """Return the DISCIPLINE_POWERS entry for a power name (any case), or None."""
    name = _POWERS_BY_LOWER_NAME.get(str(power_name).strip().lower())
    return DISCIPLINE_POWERS[name] if name else None


# ============================================================================
# TRAIT REGISTRY
# ============================================================================
# Maps every rated trait a character can have to where Character stores it:
#   attributes  -> db.stats["attributes"][group][key]
#   skills      -> db.stats["skills"][group][key]
#   disciplines -> db.stats["disciplines"][key]["level"]
#   backgrounds -> db.advantages["backgrounds"][key]
# Storage keys are lower_snake_case ("animal_ken", "blood_sorcery").


class UnknownTrait(LookupError):  # noqa: N818 - public API name used by callers
    """The name is not an attribute, skill, discipline or background."""


class WrongCategory(ValueError):  # noqa: N818 - public API name used by callers
    """The trait exists, but not in the category the caller asked for."""


class TraitRef(NamedTuple):
    category: str  # "attributes", "skills", "disciplines" or "backgrounds"
    group: object  # "physical"/"social"/"mental" for attributes and skills, else None
    key: str  # storage key
    name: str  # display name


# Allowed ratings per category.
TRAIT_RANGES = {
    "attributes": (1, 5),
    "skills": (0, 5),
    "disciplines": (0, 5),
    "backgrounds": (0, 5),
}

_CATEGORY_ALIASES = {
    "attribute": "attributes",
    "attributes": "attributes",
    "skill": "skills",
    "skills": "skills",
    "discipline": "disciplines",
    "disciplines": "disciplines",
    "background": "backgrounds",
    "backgrounds": "backgrounds",
}


def normalize_trait_name(name):
    """'Animal Ken' / 'animal-ken' / ' ANIMAL_KEN ' -> 'animal_ken'."""
    return re.sub(r"[\s\-]+", "_", str(name).strip().lower())


def normalize_category(category):
    """Map 'skill'/'Skills' etc. to a TRAIT_RANGES key; raise WrongCategory if unknown."""
    try:
        return _CATEGORY_ALIASES[str(category).strip().lower()]
    except KeyError:
        raise WrongCategory(f"Unknown trait category: {category}") from None


def _build_trait_registry():
    registry = {}

    def add(category, group, display):
        key = normalize_trait_name(display)
        if key in registry:
            raise ValueError(f"Trait name collision: {display!r} and {registry[key].name!r}")
        registry[key] = TraitRef(category, group, key, display)

    for group, names in ATTRIBUTES.items():
        for name in names:
            add("attributes", group.lower(), name)
    for group, names in SKILLS.items():
        for name in names:
            add("skills", group.lower(), name)
    for name in DISCIPLINES:
        add("disciplines", None, name)
    for name in BACKGROUNDS:
        add("backgrounds", None, name)
    return registry


TRAIT_REGISTRY = _build_trait_registry()


def resolve_trait(name, category=None):
    """Resolve a trait name (any case or spacing) to its TraitRef.

    Raises UnknownTrait if the name is not a known trait, and WrongCategory if
    `category` is given and the trait belongs to a different one.
    """
    ref = TRAIT_REGISTRY.get(normalize_trait_name(name))
    if ref is None:
        raise UnknownTrait(f"Unknown trait: {name}")
    if category is not None and normalize_category(category) != ref.category:
        raise WrongCategory(f"{ref.name} is not one of the {normalize_category(category)}")
    return ref


# ============================================================================
# FRENZY TRIGGERS
# ============================================================================

FRENZY_TRIGGERS = {
    "hunger": {"difficulty": 3, "compulsion": "Feed"},
    "humiliation": {"difficulty": 2, "compulsion": "Fight"},
    "rage": {"difficulty": 3, "compulsion": "Fight"},
    "fear": {"difficulty": 3, "compulsion": "Flight"},
    "fire": {"difficulty": 4, "compulsion": "Flight"},
    "sunlight": {"difficulty": 5, "compulsion": "Flight"},
}
