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

CLANS = {
    "Brujah": {
        "disciplines": ["Celerity", "Potence", "Presence"],
        "bane": "Violent Temper: Difficulty +2 to resist fury frenzy",
        "compulsion": "Rebellion: Must defy authority or lose 1 die from Social pools"
    },
    "Gangrel": {
        "disciplines": ["Animalism", "Fortitude", "Protean"],
        "bane": "Bestial Features: Animal features emerge when Hunger 4+",
        "compulsion": "Feral Impulses: Must avoid civilization or lose 1 die from Mental/Social pools"
    },
    "Hecata": {
        "disciplines": ["Auspex", "Fortitude", "Oblivion"],
        "bane": "Painful Kiss: Feeding causes intense pain to mortal victims, making it impossible to feed discreetly",
        "compulsion": "Morbidity: Must witness or cause death, or engage with death-related activities, or lose 2 dice from pools"
    },
    "Malkavian": {
        "disciplines": ["Auspex", "Dominate", "Obfuscate"],
        "bane": "Fractured Perspective: Must have at least one mental derangement",
        "compulsion": "Delusion: Fixate on irrational belief or lose 1 die from pools"
    },
    "Nosferatu": {
        "disciplines": ["Animalism", "Obfuscate", "Potence"],
        "bane": "Repulsive: Appearance 0, automatic fail on all Persuasion/Performance vs mortals",
        "compulsion": "Cryptophilia: Hoard secrets or lose 2 dice from actions"
    },
    "Toreador": {
        "disciplines": ["Auspex", "Celerity", "Presence"],
        "bane": "Aesthetic Fixation: May become entranced by beauty (Composure + Wits vs Diff 3+)",
        "compulsion": "Obsession: Fixate on beauty or lose 2 dice from other actions"
    },
    "Tremere": {
        "disciplines": ["Auspex", "Blood Sorcery", "Dominate"],
        "bane": "Deficient Blood: Blood bonds form one step stronger when drinking from Tremere",
        "compulsion": "Perfectionism: Retry failed action or lose 3 dice from other pools"
    },
    "Ventrue": {
        "disciplines": ["Dominate", "Fortitude", "Presence"],
        "bane": "Rarefied Taste: Can only feed from specific type of mortal (player chosen)",
        "compulsion": "Arrogance: Must dominate situation or lose 2 dice from actions"
    },
    "Caitiff": {
        "disciplines": [],  # Choose any 2 disciplines at character creation
        "bane": "Suspect Blood: Ostracized by Camarilla, -1 die to Social with non-Caitiff",
        "compulsion": "None (varies by individual)"
    },
    "Thin-Blood": {
        "disciplines": ["Thin-Blood Alchemy"],  # Plus 1 discipline with weakness
        "bane": "Thin Blood: No Blood Potency, can't create blood bonds or ghouls",
        "compulsion": "None (varies by individual)"
    },
    # Additional clans (unlockable via admin approval)
    "Lasombra": {
        "disciplines": ["Dominate", "Oblivion", "Potence"],
        "bane": "No Reflection: No reflection in mirrors or recordings",
        "compulsion": "Ruthlessness: Must pursue goal regardless of cost or lose 2 dice"
    },
    "Tzimisce": {
        "disciplines": ["Animalism", "Dominate", "Protean"],
        "bane": "Grounded: Must sleep in homeland soil or lose 1 die cumulatively",
        "compulsion": "Covetousness: Must possess desired object/person or lose 2 dice"
    },
    "Ravnos": {
        "disciplines": ["Animalism", "Obfuscate", "Presence"],
        "bane": "Doomed Blood: Bane severity increases at Hunger 4+",
        "compulsion": "Tempting Fate: Must take unnecessary risk or lose 2 dice"
    },
    "Banu Haqim": {
        "disciplines": ["Blood Sorcery", "Celerity", "Obfuscate"],
        "bane": "Blood Addiction: Must make Hunger Frenzy test when smelling vampire blood",
        "compulsion": "Judgement: Must punish transgressor or lose 2 dice"
    },
    "Ministry": {
        "disciplines": ["Obfuscate", "Presence", "Protean"],
        "bane": "Light Sensitivity: +1 Aggravated damage from sunlight",
        "compulsion": "Transgression: Must corrupt someone or lose 2 dice"
    },
    "Salubri": {
        "disciplines": ["Auspex", "Dominate", "Fortitude"],
        "bane": "Third Eye: Visible third eye reveals vampire nature",
        "compulsion": "Affective Empathy: Must help person in distress or lose 3 dice",
    },
}

# ============================================================================
# DISCIPLINES (power levels 1-5)
# ============================================================================

DISCIPLINES = {
    "Animalism": {
        "type": "standard",
        "description": "Commune with and command animals and the Beast",
        "powers": {
            1: [
                {
                    "name": "Bond Famulus",
                    "description": "Create supernatural bond with one animal, mental communication",
                    "rouse": True,
                    "dice_pool": "Charisma + Animal Ken",
                    "duration": "permanent",
                    "amalgam": None
                },
                {
                    "name": "Sense the Beast",
                    "description": "Sense presence and emotional state of animals and vampires nearby",
                    "rouse": False,
                    "dice_pool": "Resolve + Animalism",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Feral Whispers",
                    "description": "Communicate with and command animals",
                    "rouse": True,
                    "dice_pool": "Manipulation/Charisma + Animalism",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Animal Succulence",
                    "description": "Slake 1 additional Hunger when feeding from animals",
                    "rouse": False,
                    "dice_pool": None,
                    "duration": "passive",
                    "amalgam": None
                },
                {
                    "name": "Quell the Beast",
                    "description": "Calm or rouse the Beast in others",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Animalism",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Living Hive",
                    "description": "Infest body with stinging insects for defense and concealment",
                    "rouse": True,
                    "dice_pool": "Composure + Animalism",
                    "duration": "scene",
                    "amalgam": "Obfuscate 2"
                }
            ],
            4: [
                {
                    "name": "Subsume the Spirit",
                    "description": "Project consciousness into animal, control it fully",
                    "rouse": True,
                    "dice_pool": "Manipulation + Animalism",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Animal Dominion",
                    "description": "Command multiple animals or swarms simultaneously",
                    "rouse": True,
                    "dice_pool": "Charisma + Animalism",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Draw Out the Beast",
                    "description": "Force another's Beast into frenzy or calm it entirely",
                    "rouse": True,
                    "dice_pool": "Charisma + Animalism",
                    "duration": "instant",
                    "amalgam": None
                }
            ]
        }
    },
    "Auspex": {
        "type": "standard",
        "description": "Supernatural senses and perception",
        "powers": {
            1: [
                {
                    "name": "Heightened Senses",
                    "description": "Dramatically enhance all five senses",
                    "rouse": False,
                    "dice_pool": "Wits/Resolve + Auspex",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Sense the Unseen",
                    "description": "Detect supernatural presences (Obfuscate, ghosts, magic)",
                    "rouse": False,
                    "dice_pool": "Wits/Resolve + Auspex",
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Premonition",
                    "description": "Get glimpses of danger or future events",
                    "rouse": False,
                    "dice_pool": "Resolve + Auspex",
                    "duration": "passive",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Scry the Soul",
                    "description": "Read aura, discern emotional state, vampiric nature, resonance",
                    "rouse": True,
                    "dice_pool": "Intelligence + Auspex",
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Share the Senses",
                    "description": "See/hear through another's senses remotely",
                    "rouse": True,
                    "dice_pool": "Resolve + Auspex",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Spirit's Touch",
                    "description": "Read psychic impressions from objects (psychometry)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Auspex",
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Clairvoyance",
                    "description": "Project senses to a distant familiar location",
                    "rouse": True,
                    "dice_pool": "Intelligence + Auspex",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Possession",
                    "description": "Fully possess another person's body",
                    "rouse": True,
                    "dice_pool": "Resolve + Auspex",
                    "duration": "scene",
                    "amalgam": "Dominate 3"
                },
                {
                    "name": "Telepathy",
                    "description": "Read surface thoughts, project thoughts, mental communication",
                    "rouse": True,
                    "dice_pool": "Resolve + Auspex",
                    "duration": "scene",
                    "amalgam": None
                }
            ]
        },
    },
    "Blood Sorcery": {
        "type": "ritual",
        "description": "Blood magic and rituals",
        "powers": {
            1: [
                {
                    "name": "Corrosive Vitae",
                    "description": "Spit vitae as acid weapon",
                    "rouse": True,
                    "dice_pool": "Strength + Blood Sorcery",
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Blood of Potency",
                    "description": "Temporarily raise Blood Potency (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Blood Sorcery",
                    "duration": "scene",
                    "amalgam": None,
                    "ritual": True
                }
            ],
            2: [
                {
                    "name": "Extinguish Vitae",
                    "description": "Paralyze a vampire's limb (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Blood Sorcery",
                    "duration": "scene",
                    "amalgam": None,
                    "ritual": True
                },
                {
                    "name": "Ward Against Ghouls",
                    "description": "Create protective ward against ghouls (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Blood Sorcery",
                    "duration": "permanent",
                    "amalgam": None,
                    "ritual": True
                }
            ],
            3: [
                {
                    "name": "Scorpion's Touch",
                    "description": "Vitae becomes paralyzing poison in melee",
                    "rouse": True,
                    "dice_pool": "Strength + Blood Sorcery",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Incorporeal Passage",
                    "description": "Walk through walls (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Blood Sorcery",
                    "duration": "scene",
                    "amalgam": None,
                    "ritual": True
                }
            ],
            4: [
                {
                    "name": "Theft of Vitae",
                    "description": "Drain vitae from target at a distance",
                    "rouse": True,
                    "dice_pool": "Wits + Blood Sorcery",
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Cauldron of Blood",
                    "description": "Boil victim's blood, causing massive damage",
                    "rouse": True,
                    "dice_pool": "Manipulation + Blood Sorcery",
                    "duration": "instant",
                    "amalgam": None
                }
            ]
        },
        "rituals": []
    },
    "Celerity": {
        "type": "standard",
        "description": "Supernatural speed and reflexes",
        "powers": {
            1: [
                {
                    "name": "Cat's Grace",
                    "description": "Gain automatic success on Dexterity + Athletics roll. Passive: Add Celerity rating to Defense",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Rapid Reflexes",
                    "description": "Add Celerity rating to initiative",
                    "rouse": False,
                    "dice_pool": None,
                    "duration": "passive",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Fleetness",
                    "description": "Double movement speed for scene",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Blink",
                    "description": "Move short distance instantly (appears to teleport)",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Traversal",
                    "description": "Scale walls, run across water, perform impossible movements",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Draught of Elegance",
                    "description": "Gain Celerity rating as bonus dice to Dexterity rolls for scene",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Unerring Aim",
                    "description": "Automatically hit target with ranged attack",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": "Auspex 2"
                }
            ],
            5: [
                {
                    "name": "Lightning Strike",
                    "description": "Make multiple attacks in single turn",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Split Second",
                    "description": "Act first in turn order, interrupt actions",
                    "rouse": True,
                    "dice_pool": "Wits + Awareness",
                    "duration": "instant",
                    "amalgam": None
                }
            ]
        },
    },
    "Dominate": {
        "type": "standard",
        "description": "Mind control and mental commands",
        "powers": {
            1: [
                {
                    "name": "Cloud Memory",
                    "description": "Remove or alter short-term memories",
                    "rouse": True,
                    "dice_pool": "Charisma + Dominate",
                    "duration": "permanent",
                    "amalgam": None
                },
                {
                    "name": "Compel",
                    "description": "Issue one-word command target must obey",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Dominate",
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Mesmerize",
                    "description": "Issue complex hypnotic commands",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Dominate",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Dementation",
                    "description": "Drive target temporarily insane with hallucinations",
                    "rouse": True,
                    "dice_pool": "Manipulation + Dominate",
                    "duration": "scene",
                    "amalgam": "Obfuscate 2"
                },
                {
                    "name": "Submerged Directive",
                    "description": "Plant delayed trigger command",
                    "rouse": True,
                    "dice_pool": "Manipulation + Dominate",
                    "duration": "permanent",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "The Forgetful Mind",
                    "description": "Rewrite or remove extensive memories",
                    "rouse": True,
                    "dice_pool": "Manipulation + Dominate",
                    "duration": "permanent",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Rationalize",
                    "description": "Make victim justify/accept anything",
                    "rouse": True,
                    "dice_pool": "Manipulation + Dominate",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Mass Manipulation",
                    "description": "Dominate multiple targets simultaneously",
                    "rouse": True,
                    "dice_pool": "Charisma + Dominate",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Terminal Decree",
                    "description": "Implant suicidal or self-destructive command",
                    "rouse": True,
                    "dice_pool": "Manipulation + Dominate",
                    "duration": "permanent",
                    "amalgam": None
                }
            ]
        },
    },
    "Fortitude": {
        "type": "standard",
        "description": "Supernatural resilience and toughness",
        "powers": {
            1: [
                {
                    "name": "Resilience",
                    "description": "Add Fortitude rating to Health for scene",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Unswayable Mind",
                    "description": "Add Fortitude rating to Resolve or Composure for resisting mental attacks",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Toughness",
                    "description": "Reduce Aggravated damage from fire/sunlight by 1 per Bane Severity",
                    "rouse": False,
                    "dice_pool": None,
                    "duration": "passive",
                    "amalgam": None
                },
                {
                    "name": "Enduring Beast",
                    "description": "Ignore physical damage penalties for scene",
                    "rouse": True,
                    "dice_pool": "Stamina + Survival",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Fortify the Inner Facade",
                    "description": "Superficial damage becomes bashing for mortals witnessing violence",
                    "rouse": True,
                    "dice_pool": "Stamina + Fortitude",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Draught of Endurance",
                    "description": "Add Fortitude rating as bonus dice to Stamina rolls for scene",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Flesh of Marble",
                    "description": "Become nearly invulnerable to physical harm",
                    "rouse": True,
                    "dice_pool": "Composure + Fortitude",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Prowess from Pain",
                    "description": "Convert Health damage into bonus dice",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ]
        },
    },
    "Obfuscate": {
        "type": "standard",
        "description": "Supernatural stealth and invisibility",
        "powers": {
            1: [
                {
                    "name": "Cloak of Shadows",
                    "description": "Become invisible while stationary",
                    "rouse": True,
                    "dice_pool": "Wits + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Silence of Death",
                    "description": "Suppress all sound you make",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Unseen Passage",
                    "description": "Remain invisible while moving",
                    "rouse": True,
                    "dice_pool": "Wits + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Ghost in the Machine",
                    "description": "Erase digital presence, disappear from cameras",
                    "rouse": True,
                    "dice_pool": "Manipulation + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Mask of a Thousand Faces",
                    "description": "Appear as a different person",
                    "rouse": True,
                    "dice_pool": "Manipulation + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Conceal",
                    "description": "Hide objects or other people",
                    "rouse": True,
                    "dice_pool": "Wits + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Vanish",
                    "description": "Disappear instantly, even while observed",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Imposter's Guise",
                    "description": "Perfectly mimic specific person (voice, mannerisms, etc.)",
                    "rouse": True,
                    "dice_pool": "Manipulation + Obfuscate",
                    "duration": "scene",
                    "amalgam": None
                }
            ]
        },
    },
    "Oblivion": {
        "type": "standard",
        "description": "Power over death and the Underworld",
        "powers": {
            1: [
                {
                    "name": "Shadow Cloak",
                    "description": "Obfuscate 1 equivalent using shadows",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Oblivion's Sight",
                    "description": "See into lands of the dead",
                    "rouse": False,
                    "dice_pool": "Resolve + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Binding the Fetters",
                    "description": "Strengthen ghost anchors (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Oblivion",
                    "duration": "permanent",
                    "amalgam": None,
                    "ritual": True
                }
            ],
            2: [
                {
                    "name": "Tenebrous Avatar",
                    "description": "Become shadow-form",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Where the Shroud Thins",
                    "description": "Find weak points in death barrier (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Oblivion",
                    "duration": "scene",
                    "amalgam": None,
                    "ritual": True
                }
            ],
            3: [
                {
                    "name": "Shadow Cast",
                    "description": "Control shadows to attack or manipulate",
                    "rouse": True,
                    "dice_pool": "Manipulation + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Summon Spirit",
                    "description": "Call ghost to appear",
                    "rouse": True,
                    "dice_pool": "Intelligence + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Shadow Perspective",
                    "description": "Scry through shadows",
                    "rouse": True,
                    "dice_pool": "Intelligence + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Compel Spirit",
                    "description": "Force ghost to obey",
                    "rouse": True,
                    "dice_pool": "Manipulation + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Shadowstep",
                    "description": "Teleport through shadows",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Shambling Hordes",
                    "description": "Animate corpses",
                    "rouse": True,
                    "dice_pool": "Intelligence + Oblivion",
                    "duration": "scene",
                    "amalgam": None
                }
            ]
        },
    },
    "Potence": {
        "type": "standard",
        "description": "Supernatural strength",
        "powers": {
            1: [
                {
                    "name": "Lethal Body",
                    "description": "Unarmed attacks deal +1 damage, can be Aggravated",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Soaring Leap",
                    "description": "Jump incredible distances",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Prowess",
                    "description": "Add Potence rating as bonus dice to Strength rolls for scene",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Brutal Feed",
                    "description": "Gain additional Resonance benefit when feeding violently",
                    "rouse": False,
                    "dice_pool": None,
                    "duration": "passive",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Spark of Rage",
                    "description": "Cause frenzy in nearby vampires",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": "Presence 3"
                }
            ],
            5: [
                {
                    "name": "Earthshock",
                    "description": "Shockwave knocks down all nearby",
                    "rouse": True,
                    "dice_pool": "Strength + Potence",
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Fist of Caine",
                    "description": "One devastating attack causing massive damage",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                }
            ]
        },
    },
    "Presence": {
        "type": "standard",
        "description": "Supernatural charisma and emotion manipulation",
        "powers": {
            1: [
                {
                    "name": "Awe",
                    "description": "Become magnetic center of attention",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Presence",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Daunt",
                    "description": "Inspire terror in onlookers",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Presence",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Lingering Kiss",
                    "description": "Your Kiss causes euphoria, not pain",
                    "rouse": False,
                    "dice_pool": None,
                    "duration": "passive",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Dread Gaze",
                    "description": "Paralyze target with terror",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Presence",
                    "duration": "instant",
                    "amalgam": None
                },
                {
                    "name": "Entrancement",
                    "description": "Create obsessive fascination/love in target",
                    "rouse": True,
                    "dice_pool": "Charisma/Manipulation + Presence",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "Irresistible Voice",
                    "description": "Commands carry supernatural compulsion",
                    "rouse": True,
                    "dice_pool": "Manipulation + Presence",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Summon",
                    "description": "Call target to your location (they must come)",
                    "rouse": True,
                    "dice_pool": "Manipulation + Presence",
                    "duration": "permanent",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Majesty",
                    "description": "Radiate such magnificence others cannot act against you",
                    "rouse": True,
                    "dice_pool": "Charisma + Presence",
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Star Magnetism",
                    "description": "Affect large crowds with Presence powers",
                    "rouse": True,
                    "dice_pool": "Charisma + Presence",
                    "duration": "scene",
                    "amalgam": None
                }
            ]
        },
    },
    "Protean": {
        "type": "standard",
        "description": "Shapeshifting and transformation",
        "powers": {
            1: [
                {
                    "name": "Eyes of the Beast",
                    "description": "See perfectly in darkness, eyes glow red",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Weight of the Feather",
                    "description": "Reduce falling damage, land gracefully",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "instant",
                    "amalgam": None
                }
            ],
            2: [
                {
                    "name": "Feral Weapons",
                    "description": "Grow claws dealing Aggravated damage",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Metamorphosis",
                    "description": "Transform into animal form (bat, wolf, rat)",
                    "rouse": True,
                    "dice_pool": "Stamina + Protean",
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            3: [
                {
                    "name": "Shapechange",
                    "description": "Transform into mist form",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Earth Meld",
                    "description": "Merge with earth/stone for day sleep",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                }
            ],
            4: [
                {
                    "name": "One with the Beast",
                    "description": "Remain conscious while in frenzy",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "Fleshcraft",
                    "description": "Sculpt flesh (self or others)",
                    "rouse": True,
                    "dice_pool": "Dexterity + Protean",
                    "duration": "permanent",
                    "amalgam": None
                }
            ],
            5: [
                {
                    "name": "Horrid Form",
                    "description": "Transform into massive combat monster",
                    "rouse": True,
                    "dice_pool": None,
                    "duration": "scene",
                    "amalgam": None
                },
                {
                    "name": "The Unfettered Heart",
                    "description": "Remove heart from body, hide it elsewhere (ritual)",
                    "rouse": False,
                    "dice_pool": "Intelligence + Protean",
                    "duration": "permanent",
                    "amalgam": None,
                    "ritual": True
                }
            ]
        }
    },
    "Thin-Blood Alchemy": {
        "type": "thin-blood",
        "description": "Alchemical formulae unique to thin-blooded vampires",
        "powers": {
            1: [
                {
                    "name": "Far Reach",
                    "description": "Telekinesis to pull or push objects within short range (5 meters)",
                    "rouse": False,
                    "dice_pool": "Resolve + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "quicksilver"],
                    "craft_difficulty": 2
                },
                {
                    "name": "Haze",
                    "description": "Cloud the minds of observers, making them forget your presence",
                    "rouse": False,
                    "dice_pool": "Manipulation + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "alcohol"],
                    "craft_difficulty": 2
                },
                {
                    "name": "Envelop",
                    "description": "Wrap yourself in shadows, becoming harder to see",
                    "rouse": False,
                    "dice_pool": "Wits + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "ash"],
                    "craft_difficulty": 2
                }
            ],
            2: [
                {
                    "name": "Counterfeit",
                    "description": "Create a temporary duplicate of a small object",
                    "rouse": False,
                    "dice_pool": "Intelligence + Thin-Blood Alchemy",
                    "duration": "night",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "clay", "piece of original object"],
                    "craft_difficulty": 3
                },
                {
                    "name": "Defractionate",
                    "description": "Split your consciousness, perceive multiple locations",
                    "rouse": False,
                    "dice_pool": "Wits + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "mirror shards"],
                    "craft_difficulty": 3
                }
            ],
            3: [
                {
                    "name": "Airborne Momentum",
                    "description": "Levitate and move through the air",
                    "rouse": False,
                    "dice_pool": "Dexterity + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "feather", "powdered bone"],
                    "craft_difficulty": 4
                }
            ],
            4: [
                {
                    "name": "Awaken the Sleeper",
                    "description": "Temporarily grant a mortal a vampiric discipline power",
                    "rouse": False,
                    "dice_pool": "Manipulation + Thin-Blood Alchemy",
                    "duration": "scene",
                    "amalgam": None,
                    "ingredients": ["vampire blood", "distilled adrenaline", "rare herb"],
                    "craft_difficulty": 5
                }
            ],
            5: [
                {
                    "name": "Discipline Distillation",
                    "description": "Distill another vampire's blood to create a temporary discipline power",
                    "rouse": False,
                    "dice_pool": "Intelligence + Thin-Blood Alchemy",
                    "duration": "night",
                    "amalgam": None,
                    "ingredients": ["vampire blood with discipline", "alchemical catalyst"],
                    "craft_difficulty": 6
                }
            ]
        },
    },
}

# ============================================================================
# PREDATOR TYPES
# ============================================================================

PREDATOR_TYPES = {
    "Alleycat": {
        "description": "Hunt the homeless and forgotten",
        "specialty": "Intimidation or Streetwise",
        "disciplines": ["Celerity", "Potence"],
        "merits": [],
        "flaws": []
    },
    "Bagger": {
        "description": "Feed from blood bags and hospitals",
        "specialty": "Medicine or Streetwise",
        "disciplines": ["Blood Sorcery", "Obfuscate"],
        "merits": [],
        "flaws": []
    },
    "Blood Leech": {
        "description": "Feed from other vampires",
        "specialty": "Brawl or Stealth",
        "disciplines": ["Celerity", "Protean"],
        "merits": [],
        "flaws": []
    },
    "Cleaver": {
        "description": "Feed from a mortal family or group",
        "specialty": "Persuasion or Subterfuge",
        "disciplines": ["Animalism", "Dominate"],
        "merits": [],
        "flaws": []
    },
    "Consensualist": {
        "description": "Feed with permission and consent",
        "specialty": "Medicine or Persuasion",
        "disciplines": ["Auspex", "Fortitude"],
        "merits": [],
        "flaws": []
    },
    "Farmer": {
        "description": "Feed from animals",
        "specialty": "Animal Ken or Survival",
        "disciplines": ["Animalism", "Protean"],
        "merits": [],
        "flaws": []
    },
    "Osiris": {
        "description": "Cult leader who feeds from worshippers",
        "specialty": "Occult or Performance",
        "disciplines": ["Blood Sorcery", "Presence"],
        "merits": [],
        "flaws": []
    },
    "Sandman": {
        "description": "Feed from sleeping victims",
        "specialty": "Medicine or Stealth",
        "disciplines": ["Auspex", "Obfuscate"],
        "merits": [],
        "flaws": []
    },
    "Scene Queen": {
        "description": "Feed from the party scene",
        "specialty": "Performance or Streetwise",
        "disciplines": ["Dominate", "Presence"],
        "merits": [],
        "flaws": []
    },
    "Siren": {
        "description": "Seduce and feed",
        "specialty": "Persuasion or Subterfuge",
        "disciplines": ["Fortitude", "Presence"],
        "merits": [],
        "flaws": []
    },
}

# ============================================================================
# BACKGROUNDS (Advantages with mechanical benefits)
# ============================================================================

BACKGROUNDS = {
    "Allies": {
        "instanced": True,
        "description": "Mortal or supernatural allies who can provide aid",
        "benefit": "Can call for help. +[dots] to Social rolls when relevant",
        "uses_per_session": "dots"
    },
    "Contacts": {
        "instanced": True,
        "description": "Information sources in various areas",
        "benefit": "+[dots] to Investigation when using contacts for information",
        "uses_per_session": "dots * 2"
    },
    "Fame": {
        "description": "Recognition in mortal society",
        "benefit": "+[dots] to Social rolls with those who recognize you",
        "uses_per_session": "unlimited"
    },
    "Haven": {
        "description": "Quality and security of your haven",
        "benefit": "Security rating: +[dots] to defend against intrusion",
        "uses_per_session": "passive"
    },
    "Herd": {
        "description": "Regular feeding sources",
        "benefit": "Reduce Hunger by [dots] per week without hunting. No risk",
        "uses_per_session": "1 per week"
    },
    "Influence": {
        "instanced": True,
        "description": "Sway over mortal institutions",
        "benefit": "+[dots] to Leadership/Politics in domain. Can requisition resources",
        "uses_per_session": "dots"
    },
    "Mask": {
        "description": "Strength of your mortal identity",
        "benefit": "+[dots] to maintain Masquerade and resist investigation",
        "uses_per_session": "passive"
    },
    "Resources": {
        "description": "Wealth and material assets",
        "benefit": "Can acquire items of [dots] rating or less. Income level",
        "uses_per_session": "dots"
    },
    "Retainers": {
        "instanced": True,
        "description": "Loyal servants (ghouls, etc.)",
        "benefit": "[dots] loyal servants who can perform tasks",
        "uses_per_session": "unlimited"
    },
    "Status": {
        "instanced": True,
        "description": "Standing in vampire society",
        "benefit": "+[dots] to Social rolls with Kindred. Access to Elysium",
        "uses_per_session": "unlimited"
    },
    "Mawla": {
        "instanced": True,
        "description": "A Kindred mentor or patron who advises and protects you",
        "benefit": "Advice, protection and introductions from an elder",
        "uses_per_session": "dots"
    }
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
# Core-book merits and flaws (V5 core rulebook, "Advantages" chapter), plus
# the flaws attached to Backgrounds. "dots" lists the ratings a character may
# take. OWNER SIGN-OFF PENDING: these names and dot ratings follow the core
# book but have not been checked line by line against the owner's copy.

MERITS = {
    "Linguistics": {"category": "Linguistics", "dots": (1, 2, 3, 4, 5),
                    "description": "One additional language per dot"},
    "Beautiful": {"category": "Looks", "dots": (2,),
                  "description": "+1 die to appropriate Social pools"},
    "Stunning": {"category": "Looks", "dots": (4,),
                 "description": "+2 dice to appropriate Social pools"},
    "Bloodhound": {"category": "Feeding", "dots": (1,),
                   "description": "Smell the Resonance of mortal blood"},
    "Iron Gullet": {"category": "Feeding", "dots": (3,),
                    "description": "Feed on rancid, cold or otherwise spoiled blood"},
    "Anarch Comrades": {"category": "Thin-blood", "dots": (1,),
                        "description": "An Anarch group treats you as a mascot (Mawla 1)"},
    "Camarilla Contact": {"category": "Thin-blood", "dots": (1,),
                          "description": "A Camarilla Kindred contact (Mawla 1)"},
    "Catenating Blood": {"category": "Thin-blood", "dots": (1,),
                         "description": "Your blood can create blood bonds and ghouls"},
    "Day Drinker": {"category": "Thin-blood", "dots": (1,),
                    "description": "Sunlight only causes Superficial damage, halved"},
    "Discipline Affinity": {"category": "Thin-blood", "dots": (1,),
                            "description": "Learn one Discipline as in-clan"},
    "Lifelike": {"category": "Thin-blood", "dots": (1,),
                 "description": "Your body works like a mortal's"},
    "Thin-Blood Alchemist": {"category": "Thin-blood", "dots": (1,),
                             "description": "One dot of Thin-Blood Alchemy and a formula"},
    "Vampiric Resilience": {"category": "Thin-blood", "dots": (1,),
                            "description": "Suffer Superficial damage as a full vampire"},
}

FLAWS = {
    "Illiterate": {"category": "Linguistics", "dots": (2,),
                   "description": "You cannot read or write"},
    "Ugly": {"category": "Looks", "dots": (1,),
             "description": "-1 die to appropriate Social pools"},
    "Repulsive": {"category": "Looks", "dots": (2,),
                  "description": "-2 dice to appropriate Social pools"},
    "Addiction": {"category": "Substance Use", "dots": (1,),
                  "description": "-1 die unless you fed on the drug this scene"},
    "Hopeless Addiction": {"category": "Substance Use", "dots": (2,),
                           "description": "-2 dice unless you fed on the drug this scene"},
    "Prey Exclusion": {"category": "Feeding", "dots": (1,),
                       "description": "You refuse to feed from one kind of prey"},
    "Methuselah's Thirst": {"category": "Feeding", "dots": (1,),
                            "description": "Only supernatural blood fully slakes your Hunger"},
    "Farmer": {"category": "Feeding", "dots": (2,),
               "description": "You feed only from animals"},
    "Organovore": {"category": "Feeding", "dots": (2,),
                   "description": "You must eat flesh and organs to slake Hunger"},
    "Baby Teeth": {"category": "Thin-blood", "dots": (1,),
                   "description": "Your fangs never grew in"},
    "Bestial Temper": {"category": "Thin-blood", "dots": (1,),
                       "description": "You frenzy like a full vampire"},
    "Branded by the Camarilla": {"category": "Thin-blood", "dots": (1,),
                                 "description": "The Camarilla has marked you"},
    "Clan Curse": {"category": "Thin-blood", "dots": (1,),
                   "description": "You carry a clan's Bane at severity 1"},
    "Dead Flesh": {"category": "Thin-blood", "dots": (1,),
                   "description": "Your flesh is visibly dead"},
    "Mortal Frailty": {"category": "Thin-blood", "dots": (1,),
                       "description": "You cannot Rouse to mend damage"},
    "Shunned by the Anarchs": {"category": "Thin-blood", "dots": (1,),
                               "description": "The Anarchs want nothing to do with you"},
    "Vitae Dependency": {"category": "Thin-blood", "dots": (1,),
                         "description": "You must drink vampire vitae weekly or lose Disciplines"},
    "Enemy": {"category": "Allies", "dots": (1, 2, 3, 4, 5),
              "description": "Mortals who want to harm you"},
    "Infamy": {"category": "Fame", "dots": (1, 2, 3, 4, 5),
               "description": "You are known for something terrible"},
    "Dark Secret": {"category": "Fame", "dots": (1, 2),
                    "description": "A secret that would ruin you if revealed"},
    "No Haven": {"category": "Haven", "dots": (1,),
                 "description": "You have no fixed haven"},
    "Compromised Haven": {"category": "Haven", "dots": (2,),
                          "description": "Your haven has been raided or exposed"},
    "Disliked": {"category": "Influence", "dots": (1,),
                 "description": "-1 die to Social tests with mortal groups"},
    "Despised": {"category": "Influence", "dots": (2,),
                 "description": "A group works against you"},
    "Known Corpse": {"category": "Mask", "dots": (1,),
                     "description": "Others know you are dead"},
    "Known Blankbody": {"category": "Mask", "dots": (2,),
                        "description": "Your identity is flagged in government databases"},
    "Adversary": {"category": "Mawla", "dots": (1, 2, 3, 4, 5),
                  "description": "A Kindred who wants to harm you"},
    "Destitute": {"category": "Resources", "dots": (1,),
                  "description": "You have no money and no home"},
    "Stalkers": {"category": "Retainers", "dots": (1,),
                 "description": "Someone keeps attaching themselves to you"},
    "Suspect": {"category": "Status", "dots": (1,),
                "description": "You have broken the rules and are watched"},
    "Shunned": {"category": "Status", "dots": (2,),
                "description": "A sect despises you"},
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
