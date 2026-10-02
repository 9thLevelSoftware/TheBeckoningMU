"""
V5 Vampire: The Masquerade rules data.

This module is the only source of V5 rules data in the game (attributes,
skills, clans, disciplines with their powers, rituals and formulas,
predator types, backgrounds, merits and flaws, the Blood Potency table,
generation tables, resonances and frenzy provocations). Game code imports
from here; nothing reads rules data from the database, and no other module
may hardcode these values. The web API (/api/traits/) serves them as JSON.

The content follows the V5 core book (2018) with Renegade's official
errata. Each table's comment cites its source: a core-book page, the V5
Quick Reference 2.0 (web/website/VampSite/references/, whose Blood Potency
Surge/Bane columns are pre-errata and are not used) or a public reference
that cites the book. Values that could not be checked against a source are
marked "UNVERIFIED" where they appear. Content from books other than the
core book is kept apart (NON_CORE_CLANS, NON_CORE_DISCIPLINES) and is not
offered to players.

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
# "required_flaws" are flaws the clan must take at creation;
# "excluded_merit_categories" are MERITS categories it may not buy.
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
        "required_flaws": [{"name": "Repulsive", "dots": 2}],
        "excluded_merit_categories": ["Looks"],
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
    # Core p.107: "The character begins with the Flaw Suspect (•) and they may
    # not purchase positive status during Character Creation."
    "Caitiff": {
        "disciplines": [],
        "required_flaws": [{"name": "Suspect", "dots": 1}],
        "excluded_backgrounds": ["Status"],
        "bane": None,
        "compulsion": None,
    },
    # QR p.5 lists "(Thin-blood Alchemy)", but QR p.2 says thin-bloods have
    # no starting or in-clan disciplines; Alchemy comes only through the
    # Thin-blood Alchemist merit (QR p.11, core p.282).
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
#   duration   - a token the effect code understands: one of
#                DURATION_TYPES (instant, turn, scene, night, permanent,
#                passive)
#   duration_text - the book's duration in words, for display
#   amalgam    - "Discipline N" the character must also have, or None
#   note       - optional rules detail the fields above can't express
#
# Blood Sorcery rituals and Thin-Blood Alchemy formulas are not powers:
# they live under "rituals" and "formulas" and are bought separately
# (XP: level x 3, QR p.1).


DURATION_TYPES = ("instant", "turn", "scene", "night", "permanent", "passive")

# Book duration wording -> the token the effect code tracks. Powers that
# only modify another power ("as the power used") have no effect of their
# own, so they are "instant".
_DURATION_TOKENS = {
    "instant": "instant",
    "as the power used": "instant",
    "as the amplified power": "instant",
    "as the copied power": "instant",
    "one turn": "turn",
    "one attack": "turn",
    "one action": "turn",
    "one scene": "scene",
    "up to one scene": "scene",
    "until done or scene ends": "scene",
    "until ended": "scene",
    "as long as desired": "scene",
    "one feeding": "scene",
    "one hour": "scene",
    "one scene or one night": "scene",
    "one night": "night",
    "up to one night": "night",
    "a day or more": "night",
    "permanent": "permanent",
    "passive": "passive",
}


def _power(name, rouse, dice_pool, duration, description, *, opposed_by=None, amalgam=None, note=None):
    power = {
        "name": name,
        "description": description,
        "rouse": rouse,
        "dice_pool": dice_pool,
        "duration": _DURATION_TOKENS[duration],
        "duration_text": duration,
        "amalgam": amalgam,
    }
    if opposed_by:
        power["opposed_by"] = opposed_by
    if note:
        power["note"] = note
    return power


def _ritual(name, level, description, *, dice_pool="Intelligence + Blood Sorcery", opposed_by=None, rouse=1,
            note=None):
    ritual = {"name": name, "level": level, "description": description, "rouse": rouse, "dice_pool": dice_pool}
    if opposed_by:
        ritual["opposed_by"] = opposed_by
    if note:
        ritual["note"] = note
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
                       note="1 Rouse per animal type per scene; free on your famulus"),
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
                       "Move your mind into an animal's body and control it",
                       note="Free on your famulus"),
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
        # Each costs 1 Rouse check unless noted, takes 5 minutes per level and rolls
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
            _ritual("Truth of Blood", 2, "Your blood shows whether a statement is true",
                    dice_pool="Resolve + Blood Sorcery", opposed_by="Composure + Occult"),
            _ritual("Ward against Spirits", 2, "Ward an object against spirits"),
            _ritual("Warding Circle against Ghouls", 2, "Ward an area against ghouls", rouse=3),
            _ritual("Dagon's Call", 3, "Drown a target from afar through their blood",
                    dice_pool="Resolve + Blood Sorcery", opposed_by="Stamina + Resolve"),
            _ritual("Deflection of Wooden Doom", 3, "The first stake to strike you fails"),
            _ritual("Essence of Air", 3, "Become able to fly"),
            _ritual("Firewalker", 3, "Resist fire"),
            _ritual("Ward against Lupines", 3, "Ward an object against werewolves"),
            _ritual("Warding Circle against Spirits", 3, "Ward an area against spirits", rouse=3),
            _ritual("Defense of the Sacred Haven", 4, "Your haven's windows block sunlight"),
            _ritual("Eyes of the Nighthawk", 4, "See through a bird and use Disciplines through it"),
            _ritual("Incorporeal Passage", 4, "Become intangible"),
            _ritual("Ward against Cainites", 4, "Ward an object against vampires"),
            _ritual("Warding Circle against Lupines", 4, "Ward an area against werewolves", rouse=3),
            _ritual("Escape to True Sanctuary", 5, "Step between two prepared circles", rouse=12,
                    note="12 Rouse checks in total, spread over the preparation"),
            _ritual("Heart of Stone", 5, "Your heart turns to stone: immune to staking and emotion"),
            _ritual("Shaft of Belated Dissolution", 5, "Make a rowan stake whose splinter seeks the heart",
                    rouse=2),
            _ritual("Warding Circle against Cainites", 5, "Ward an area against vampires", rouse=3),
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
                       opposed_by="Composure + Intelligence", amalgam="Obfuscate 2",
                       note="1 Rouse per target per scene"),
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
                       opposed_by="Intelligence + Composure", amalgam="Presence 3",
                       note="Roll only against vampires; mortals get no resistance roll"),
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
                         note=("Formula at levels 2-5; from level 4 (copying a 3-dot power) needs vitae "
                               "of a vampire of a matching clan or who has the Discipline. Cost and pool "
                               "are the copied power's.")),
            ],
            3: [
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
                         resonance="Choleric and Sanguine", opposed_by="Strength + Athletics",
                         note="The opposing pool applies only if a target resists"),
            ],
            5: [
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
#   flaw_choices, advantage_choices - "spend N dots among these" grants:
#                        "from" names, "from_categories" MERITS/FLAWS categories
#   excluded_clans, max_blood_potency - who may not take the type

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
        # Core: Tremere only. (The Players Guide p.107 adds Banu Haqim; add it
        # here if that non-core clan is ever enabled.)
        "discipline_clans": {"Blood Sorcery": ["Tremere"]},
        "humanity": 0,
        "blood_potency": 0,
        "merits": [{"name": "Iron Gullet", "dots": 3}],
        "flaws": [{"name": "Enemy", "dots": 2, "note": "someone who thinks you owe them"}],
        "backgrounds": [],
        "excluded_clans": ["Ventrue"],
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
        "excluded_clans": ["Ventrue"],
        "max_blood_potency": 2,
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
        # Core: Tremere only. (The Players Guide p.107 adds Banu Haqim; add it
        # here if that non-core clan is ever enabled.)
        "discipline_clans": {"Blood Sorcery": ["Tremere"]},
        "humanity": 0,
        "blood_potency": 0,
        "merits": [],
        "flaws": [],
        "advantage_choices": [{"dots": 3, "from": ["Fame", "Herd"]}],
        "flaw_choices": [{"dots": 2, "from": ["Enemy"], "from_categories": ["Mythical"]}],
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
# roll (core p.189 per vtm.paradoxwikis.com; UNVERIFIED against the book).

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
# GENERATION, AGE AND BLOOD POTENCY
# ============================================================================
# Source: V5 Quick Reference 2.0 p.15 (Generation / minimum and maximum Blood
# Potency table). Thin-bloods (14th-16th) have Blood Potency 0.

GENERATION_BLOOD_POTENCY = {
    4: {"min": 5, "max": 10},
    5: {"min": 4, "max": 9},
    6: {"min": 3, "max": 8},
    7: {"min": 3, "max": 7},
    8: {"min": 2, "max": 6},
    9: {"min": 2, "max": 5},
    10: {"min": 1, "max": 4},
    11: {"min": 1, "max": 4},
    12: {"min": 1, "max": 3},
    13: {"min": 1, "max": 3},
    14: {"min": 0, "max": 0},
    15: {"min": 0, "max": 0},
    16: {"min": 0, "max": 0},
}

# Source: V5 Quick Reference 2.0 p.3 ("Sea of Time"; core book "Sea of
# Time" in the character creation chapter). Each age category lists the
# generations a starting character may have and the Blood Potency that goes
# with them, plus the XP to spend and the extra advantage/flaw dots and
# Humanity change on top of normal creation. The core book's Elder rows are
# not in the Quick Reference and are left out (elders aren't player
# characters at creation).

GENERATION_BY_AGE = {
    "Childer": {
        "embraced": "Within the last 15 years",
        "options": [
            {"generations": (14, 15, 16), "blood_potency": 0, "thin_blood": True},
            {"generations": (12, 13), "blood_potency": 1, "thin_blood": False},
        ],
        "xp": 0,
        "extra_advantage_dots": 0,
        "extra_flaw_dots": 0,
        "humanity_change": 0,
    },
    "Neonate": {
        "embraced": "Between 1940 and a decade ago",
        "options": [
            {"generations": (12, 13), "blood_potency": 1, "thin_blood": False},
        ],
        "xp": 15,
        "extra_advantage_dots": 0,
        "extra_flaw_dots": 0,
        "humanity_change": 0,
    },
    "Ancilla": {
        "embraced": "Between 1780 and 1940",
        "options": [
            {"generations": (10, 11), "blood_potency": 2, "thin_blood": False},
        ],
        "xp": 35,
        "extra_advantage_dots": 2,
        "extra_flaw_dots": 2,
        "humanity_change": -1,
    },
}

# ============================================================================
# CHARACTER CREATION DISTRIBUTIONS
# ============================================================================
# Source: V5 Quick Reference 2.0 p.2 (Character Creation), citing V5 core
# p.155 (Attributes), p.159 (Skills and specialties), p.244 (Disciplines),
# p.179 (Advantages and Flaws) and p.236 (Humanity 7); QR p.3 (Hunger 1).
# world/rules_chargen.py reads these; nothing else may hardcode them.
# OWNER SIGN-OFF PENDING: this creation-distribution table is the plan's
# merge gate for the web chargen rebuild.

# One Attribute at 4, three at 3, four at 2, one at 1.
CREATION_ATTRIBUTE_SPREAD = (4, 3, 3, 3, 2, 2, 2, 2, 1)

# Pick one distribution: {rating: how many Skills}; every other Skill is 0.
CREATION_SKILL_DISTRIBUTIONS = {
    "Jack-of-all-Trades": {3: 1, 2: 8, 1: 10},
    "Balanced": {3: 3, 2: 5, 1: 7},
    "Specialist": {4: 1, 3: 3, 2: 3, 1: 3},
}

# A free specialty in each of these Skills the character has dots in, plus
# this many more free specialties. Specialties need at least one dot in the
# Skill. (The predator type's specialty comes on top.)
CREATION_FREE_SPECIALTY_SKILLS = ("Academics", "Craft", "Performance", "Science")
CREATION_EXTRA_FREE_SPECIALTIES = 1

# Two dots in one in-clan Discipline and one in another (Caitiff: any two
# Disciplines). Thin-bloods start with none (QR p.2).
CREATION_DISCIPLINE_DOTS = (2, 1)

# Advantage dots to spend (unspent dots may go to the coterie, QR p.2) and
# flaw dots to take, before the age category's extra dots (GENERATION_BY_AGE)
# and the predator type's grants. Thin-blood merits and flaws cost nothing and
# are taken in 1-3 matched pairs instead (QR p.2, p.11).
CREATION_ADVANTAGE_DOTS = 7
CREATION_FLAW_DOTS = 2
CREATION_THIN_BLOOD_PAIRS = (1, 3)

CREATION_HUMANITY = 7
CREATION_HUNGER = 1

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
#
# Not modelled (owner decision, see the PR 11 sign-off table): Loresheets
# (core p.382-406, one per character, each with its own five advantages)
# and the coterie Domain advantages (Chasse, Lien, Portillon; QR p.8),
# which belong to a coterie.
#
# Creation restrictions, for the chargen validator to read (the
# descriptions say the same in words):
#   excluded_clans - clans that may not take it
#   excludes       - names that may not be taken together with it
#   requires       - [{"kind": "backgrounds"|"merits"|"flaws", "name", "dots"}]
#                    that the character must also have
#   requires_by_clan - {clan: [names]}: extra requirements by Clan Curse clan

MERITS = {
    # Linguistics (QR p.9 "Language (•)"): one dot per extra language.
    "Linguistics": {"category": "Linguistics", "dots": (1, 2, 3, 4, 5),
                    "description": "Fluent and literate in one additional language per dot"},
    "Beautiful": {"category": "Looks", "dots": (2,),
                  "excluded_clans": ["Nosferatu"],
                  "description": "+1 die to relevant Social pools"},
    "Stunning": {"category": "Looks", "dots": (4,),
                 "excluded_clans": ["Nosferatu"],
                 "description": "+2 dice to relevant Social pools"},
    "Bloodhound": {"category": "Feeding", "dots": (1,),
                   "description": "Smell the Resonance of mortal blood"},
    "Iron Gullet": {"category": "Feeding", "dots": (3,),
                    "excluded_clans": ["Ventrue"],
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
    # Mask merits (QR p.10; core p.190): need Mask 2.
    "Zeroed": {"category": "Mask", "dots": (1,),
               "requires": [{"kind": "backgrounds", "name": "Mask", "dots": 2}],
               "description": "Your real identity has been erased from every record"},
    "Cobbler": {"category": "Mask", "dots": (1,),
                "requires": [{"kind": "backgrounds", "name": "Mask", "dots": 2}],
                "description": "You can make or source Masks for others"},
    # Haven merits (core p.188 per vtm.paradoxwikis.com; QR p.9 points to
    # them). UNVERIFIED: their ratings; the sources give "•+" with no cap.
    "Hidden Armory": {"category": "Haven", "dots": (1, 2, 3),
                      "description": "Weapons and armor hidden in your haven"},
    "Cell": {"category": "Haven", "dots": (1, 2, 3),
             "description": "A cell in your haven that can hold a prisoner"},
    "Watchmen": {"category": "Haven", "dots": (1, 2, 3),
                 "description": "Mortal guards watch over your haven"},
    "Laboratory": {"category": "Haven", "dots": (1, 2, 3),
                   "description": "A laboratory in your haven for science or alchemy"},
    "Library": {"category": "Haven", "dots": (1, 2, 3),
                "description": "A library in your haven for research"},
    # Thin-blood merits (QR p.11). No point cost; pair each with a flaw.
    "Anarch Comrades": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                        "excludes": ["Shunned by the Anarchs"],
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
                 "excludes": ["Dead Flesh"],
                 "description": "You have a heartbeat and can eat food"},
    "Thin-blood Alchemist": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                             "description": "One dot of Thin-Blood Alchemy and one formula"},
    "Vampiric Resilience": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                            "excludes": ["Mortal Frailty"],
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
    # "Archaic" is the core name (core p.179-182 per paradoxwikis and
    # fandom); the QR calls it "Anachronism".
    "Archaic": {"category": "Archaic", "dots": (2,),
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
    # Ventrue ban: QR p.9 (PDF p.11), on "Vegan" (= Farmer): "(Ventrue may
    # not take this flaw.)"
    "Farmer": {"category": "Feeding", "dots": (2,),
               "excluded_clans": ["Ventrue"],
               "description": "You feed only on animals; feeding on humans costs 2 Willpower; not for Ventrue"},
    # No clan ban: QR p.9 puts "(Ventrue may not take this flaw)" on Vegan only,
    # and vtm.paradoxwikis.com (core p.181) gives Organovore none.
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
                   "requires_by_clan": {"Brujah": ["Bestial Temper"], "Gangrel": ["Bestial Temper"],
                                        "Tremere": ["Catenating Blood"]},
                   "description": ("A clan Bane at severity 1 (Brujah/Gangrel need Bestial Temper, "
                                   "Tremere need Catenating Blood)")},
    "Dead Flesh": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                   "excludes": ["Lifelike"],
                   "description": "You are slowly decaying; can't take Lifelike"},
    "Mortal Frailty": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                       "excludes": ["Vampiric Resilience"],
                       "description": "You can't Rouse the Blood to mend; can't take Vampiric Resilience"},
    "Shunned by the Anarchs": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                               "excludes": ["Anarch Comrades"],
                               "description": "The Anarchs treat you as an enemy; can't take Anarch Comrades"},
    "Vitae Dependency": {"category": "Thin-blood", "dots": (1,), "cost": 0, "thin_blood": True,
                         "description": "You must drink vampire blood to use any Discipline"},
    # Background flaws (QR pp.8-11).
    # Enemy (QR p.8): rated two less than the equivalent Allies, so an
    # effectiveness of 1-2 plus a reliability of 0-1 (UNVERIFIED: derived).
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
# Source: V5 core p.226-231 (Resonance); humours, emotions and disciplines
# as in the V5 Quick Reference 2.0 p.12, which spells the humour
# "Melancholy". Dyscrasias: the core book's sample dyscrasia table,
# as transcribed by chartopia.d12dev.com chart 12112 and the
# cftarbay/VTM-V5-Resonance-Generator data (the two agree); effects are
# paraphrased. UNVERIFIED: the dyscrasias are not in the QR and the printed
# table wasn't seen.
#
# Animal blood carries no humour but counts as resonant for Animalism and
# Protean; bagged blood has none (QR p.12). They are in BLOOD_WITHOUT_HUMOUR,
# not RESONANCES, because a character's resonance is always one of the four.

RESONANCES = {
    "Choleric": {
        "emotion": "Angry, violent, bullying, passionate, envious",
        "disciplines": ["Celerity", "Potence"],
        "dyscrasias": {
            "Bully": "+1 damage, social or physical, against weaker foes",
            "Cycle of Violence": "Next choleric feeding slakes 1 extra Hunger; other blood slakes 1 less",
            "Envy": "+1 damage, social or physical, against foes who are better off",
            "Principled": "Re-roll one roll against an ideological enemy (not Hunger dice)",
            "Vengeful": "+2 dice against the kind of target the vessel wanted revenge on",
            "Vicious": "Re-roll Intimidation rolls (not Hunger dice)",
            "Driving": "1 free XP toward Celerity or Potence; used up when spent",
        },
    },
    "Melancholy": {
        "emotion": "Sad, scared, intellectual, depressed, grounded",
        "disciplines": ["Fortitude", "Obfuscate"],
        "dyscrasias": {
            "In Mourning": "+1 die to Remorse tests",
            "Lost Love": "+1 die to resist seduction, including Presence",
            "Lost Relative": "Slake 1 extra Hunger from the vessel's remaining family",
            "Massive Failure": "Re-roll tests that echo the vessel's failure (not Hunger dice)",
            "Nostalgic": "+1 die to rolls tied to the vessel's nostalgic subject",
            "Recalling": "1 free XP toward Fortitude or Obfuscate; used up when spent",
        },
    },
    "Phlegmatic": {
        "emotion": "Lazy, apathetic, calm, controlling, sentimental",
        "disciplines": ["Auspex", "Dominate"],
        "dyscrasias": {
            "Chill": "+2 dice to resist frenzy",
            "Comfortably Numb": "Ignore physical and social pain penalties",
            "Eating Your Emotions": "Eat and digest food without nausea (slakes no Hunger)",
            "Given Up": "Next phlegmatic feeding slakes 1 extra Hunger; other blood slakes 1 less",
            "Lone Wolf": "+1 die acting alone, -1 die when helping others, for a scene",
            "Procrastinate": "Regain 1 Willpower by putting off something important; once a session",
            "Reflection": "1 free XP toward Auspex or Dominate; used up when spent",
        },
    },
    "Sanguine": {
        "emotion": "Horny, happy, addicted, active, flighty, enthusiastic",
        "disciplines": ["Blood Sorcery", "Presence"],
        "dyscrasias": {
            "Contagious Enthusiasm": "+3 dice to convince someone you are touching skin to skin",
            "Smell Game": "+3 dice to detect other sanguine vessels",
            "High on Life": "Blush of Life without a Rouse check",
            "Manic High": "+1 die on all tests until you fail one, then -2 dice",
            "True Love": "Slake 1 extra Hunger from the vessel's true love",
            "Stirring": "1 free XP toward Blood Sorcery or Presence; used up when spent",
        },
    },
}

# Source: QR p.12 ("N/A" humour rows).
BLOOD_WITHOUT_HUMOUR = {
    "Animal": {"disciplines": ["Animalism", "Protean"], "dyscrasia": False},
    "Bagged": {"disciplines": [], "dyscrasia": False},
}

# Resonance intensity. Source: V5 core p.226-231 (per whitewolf.fandom.com
# "Blood Resonance" and vtm.paradoxwikis.com/Resonance, which agree):
# Fleeting gives no dice but lets you spend XP on the matching disciplines;
# Intense adds 1 die to matching Discipline pools; Acute adds the same die
# and carries a dyscrasia. The bonus lasts until you feed again or reach
# Hunger 5. Intensity 0 ("balanced") means no resonance.
RESONANCE_INTENSITIES = {
    1: {"name": "Fleeting", "discipline_dice": 0, "dyscrasia": False},
    2: {"name": "Intense", "discipline_dice": 1, "dyscrasia": False},
    3: {"name": "Acute", "discipline_dice": 1, "dyscrasia": True},
}

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
# FRENZY PROVOCATIONS
# ============================================================================
# Source: V5 Quick Reference 2.0 p.13 (Fury, Hunger and Terror Provocation
# tables) and p.4 (frenzy test: Willpower + Humanity / 3; Hunger 4+ makes a
# vampire prone to hunger frenzy); core p.219-220 per whitewolf.fandom.com
# "Frenzy (VTM)". The difficulty is set by the provocation, so each frenzy
# type lists its provocations rather than one difficulty. "goal" is what
# the frenzying vampire does (QR p.4).

FRENZY_PROVOCATIONS = {
    "fury": {
        "goal": "Destroy the source of the provocation",
        "provocations": {
            "Friend killed": 2,
            "Lover or Touchstone hurt": 3,
            "Lover or Touchstone killed": 4,
            "Physical provocation or harassment": 2,
            "Insulted by inferior": 2,
            "Public humiliation": 2,
        },
    },
    "hunger": {
        "goal": "Feed on fresh human blood from the closest source",
        "provocations": {
            "Sight of open wound or overpowering smell of blood at Hunger 4+": 2,
            "Taste of blood at Hunger 4+": 3,
            "Fail a Rouse check at Hunger 5": 4,
        },
    },
    "terror": {
        "goal": "Flee the source of danger (Rotschreck)",
        "provocations": {
            "Bonfire": 2,
            "Being burned": 2,
            "Inside a burning building": 3,
            "Obscured sunlight (through a window, etc.)": 3,
            "Fully exposed to direct sunlight": 4,
        },
    },
}
