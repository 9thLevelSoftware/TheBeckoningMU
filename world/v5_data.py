"""
V5 Vampire: The Masquerade Game Data Configuration

This module contains all V5 game mechanics data in a database-ready format.
Unlike the reference repository, this data is NOT hardcoded - it will be loaded
into the database during initialization and can be modified without code changes.

See: V5_REFERENCE_DATABASE.md for complete mechanics reference
See: V5_IMPLEMENTATION_ROADMAP.md Phase 4+ for when this data gets used

ARCHITECTURAL PRINCIPLE:
- This file defines the DATA STRUCTURE only
- Actual data loading happens in beckonmu/server/conf/at_initial_setup.py
- Game logic uses database queries, NOT direct imports from this file
"""

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

# SKELETON ONLY - Full discipline powers defined in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {},  # Populated in Phase 5
        "rituals": []  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
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
        "powers": {}  # Populated in Phase 5
    },
    "Thin-Blood Alchemy": {
        "type": "thin-blood",
        "description": "Thin-blood formula crafting",
        "powers": {}  # Populated in Phase 9
    }
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
        "description": "Mortal or supernatural allies who can provide aid",
        "benefit": "Can call for help. +[dots] to Social rolls when relevant",
        "uses_per_session": "dots"
    },
    "Contacts": {
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
        "description": "Loyal servants (ghouls, etc.)",
        "benefit": "[dots] loyal servants who can perform tasks",
        "uses_per_session": "unlimited"
    },
    "Status": {
        "description": "Standing in vampire society",
        "benefit": "+[dots] to Social rolls with Kindred. Access to Elysium",
        "uses_per_session": "unlimited"
    }
}

# ============================================================================
# BLOOD POTENCY TABLE
# ============================================================================

BLOOD_POTENCY = {
    0: {
        "blood_surge": 0,
        "mend_amount": 1,
        "power_bonus": 0,
        "rouse_reroll": 0,
        "bane_severity": 0,
        "feeding_penalty": "No effect"
    },
    1: {
        "blood_surge": 1,
        "mend_amount": 1,
        "power_bonus": 0,
        "rouse_reroll": 0,
        "bane_severity": 1,
        "feeding_penalty": "No slaking from animals"
    },
    2: {
        "blood_surge": 2,
        "mend_amount": 2,
        "power_bonus": 1,
        "rouse_reroll": 1,
        "bane_severity": 1,
        "feeding_penalty": "No slaking from animals"
    },
    3: {
        "blood_surge": 2,
        "mend_amount": 2,
        "power_bonus": 1,
        "rouse_reroll": 1,
        "bane_severity": 2,
        "feeding_penalty": "No slaking from animals or bagged blood"
    },
    4: {
        "blood_surge": 3,
        "mend_amount": 3,
        "power_bonus": 2,
        "rouse_reroll": 2,
        "bane_severity": 2,
        "feeding_penalty": "No slaking from animals or bagged blood"
    },
    5: {
        "blood_surge": 3,
        "mend_amount": 3,
        "power_bonus": 2,
        "rouse_reroll": 2,
        "bane_severity": 3,
        "feeding_penalty": "Must drain and kill to slake at least 1 Hunger"
    },
    6: {
        "blood_surge": 4,
        "mend_amount": 3,
        "power_bonus": 3,
        "rouse_reroll": 3,
        "bane_severity": 3,
        "feeding_penalty": "Must drain and kill to slake at least 1 Hunger"
    },
    7: {
        "blood_surge": 4,
        "mend_amount": 4,
        "power_bonus": 3,
        "rouse_reroll": 3,
        "bane_severity": 4,
        "feeding_penalty": "Must drain and kill, only 1 Hunger per human"
    },
    8: {
        "blood_surge": 5,
        "mend_amount": 4,
        "power_bonus": 4,
        "rouse_reroll": 4,
        "bane_severity": 4,
        "feeding_penalty": "Must drain and kill, only 1 Hunger per human"
    },
    9: {
        "blood_surge": 5,
        "mend_amount": 5,
        "power_bonus": 4,
        "rouse_reroll": 4,
        "bane_severity": 5,
        "feeding_penalty": "Must drain and kill vampires (1 Hunger per vampire)"
    },
    10: {
        "blood_surge": 6,
        "mend_amount": 5,
        "power_bonus": 5,
        "rouse_reroll": 5,
        "bane_severity": 5,
        "feeding_penalty": "Must drain and kill vampires (1 Hunger per vampire)"
    }
}

# ============================================================================
# CHARACTER CREATION RULES
# ============================================================================

CHARGEN_RULES = {
    "attributes": {
        "starting_value": 1,  # All attributes start at 1
        "priority_pools": {
            "primary": 7,    # 7 dots to primary category
            "secondary": 5,  # 5 dots to secondary category
            "tertiary": 3    # 3 dots to tertiary category
        },
        "max_at_creation": 5  # Can't start higher than 5
    },
    "skills": {
        "starting_value": 0,  # Skills start at 0
        "priority_pools": {
            "primary": 13,   # 13 dots to primary category
            "secondary": 9,  # 9 dots to secondary category
            "tertiary": 5    # 5 dots to tertiary category
        },
        "max_at_creation": 5,  # Can't start higher than 5
        "specialties": 1  # 1 free specialty
    },
    "disciplines": {
        "in_clan_dots": 2,   # 2 dots in in-clan disciplines
        "out_clan_dots": 1,  # 1 dot in any discipline
        "max_at_creation": 3  # Can't start higher than 3
    },
    "backgrounds": {
        "dots": 3,  # 3 dots in backgrounds
        "max_per_background": 5
    },
    "starting_values": {
        "humanity": 7,
        "willpower": 0,  # Calculated: Composure + Resolve
        "health": 0,     # Calculated: Stamina + 3
        "hunger": 1,     # Start at Hunger 1
        "generation": 13,  # Standard fledgling
        "blood_potency": 0,  # Start at BP 0
        "experience": 0
    },
    "advantages": {
        "merits": 7,  # 7 dots in merits
        "flaws": 2    # Up to 2 dots in flaws for bonus points
    }
}

# ============================================================================
# EXPERIENCE COSTS
# ============================================================================

XP_COSTS = {
    "attribute": {
        "formula": "current * 5",
        "description": "Current rating × 5"
    },
    "skill": {
        "formula": "current * 3",
        "description": "Current rating × 3"
    },
    "specialty": {
        "cost": 3,
        "description": "Flat 3 XP"
    },
    "discipline": {
        "in_clan": {
            "formula": "current * 5",
            "description": "Current rating × 5 (in-clan)"
        },
        "out_clan": {
            "formula": "current * 7",
            "description": "Current rating × 7 (out of clan)"
        }
    },
    "ritual": {
        "cost": 3,
        "description": "Flat 3 XP per ritual level"
    },
    "thin_blood_formula": {
        "cost": 3,
        "description": "Flat 3 XP"
    },
    "background": {
        "formula": "current * 3",
        "description": "Current rating × 3"
    },
    "humanity": {
        "formula": "current * 10",
        "description": "Current rating × 10"
    },
    "willpower": {
        "cost": 8,
        "description": "Flat 8 XP per permanent dot"
    }
}

# ============================================================================
# MERITS & FLAWS (SKELETON)
# ============================================================================

# Full merit/flaw lists populated in Phase 8
MERITS = {}
FLAWS = {}

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
# STATS TEMPLATE (for character.db.stats compatibility)
# ============================================================================

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
# FRENZY TRIGGERS (Phase 11: Humanity/Touchstones)
# ============================================================================

FRENZY_TRIGGERS = {
    "hunger": {"difficulty": 3, "compulsion": "Feed"},
    "humiliation": {"difficulty": 2, "compulsion": "Fight"},
    "rage": {"difficulty": 3, "compulsion": "Fight"},
    "fear": {"difficulty": 3, "compulsion": "Flight"},
    "fire": {"difficulty": 4, "compulsion": "Flight"},
    "sunlight": {"difficulty": 5, "compulsion": "Flight"},
}
