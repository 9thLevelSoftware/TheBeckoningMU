"""
V5 location type constants for the Web Builder.
"""

LOCATION_TYPES = [
    ("haven", "Haven"),
    ("elysium", "Elysium"),
    ("rack", "Rack (Feeding Ground)"),
    ("hostile", "Hostile Territory"),
    ("neutral", "Neutral Ground"),
    ("mortal", "Mortal Establishment"),
    ("supernatural", "Supernatural Site"),
]

DAY_NIGHT_ACCESS = [
    ("always", "Always Accessible"),
    ("day_only", "Day Only (Mortals)"),
    ("night_only", "Night Only"),
    ("restricted", "Restricted Access"),
]

DANGER_LEVELS = [
    ("safe", "Safe"),
    ("low", "Low Risk"),
    ("moderate", "Moderate Risk"),
    ("high", "High Risk"),
    ("deadly", "Deadly"),
]

HAVEN_RATINGS = [
    ("security", "Security"),
    ("size", "Size"),
    ("luxury", "Luxury"),
    ("warding", "Warding"),
    ("location_hidden", "Hidden Location"),
]

# Trigger events for the builder
TRIGGER_EVENTS = [
    ("on_enter", "On Enter"),
    ("on_exit", "On Exit"),
    ("on_look", "On Look"),
    ("on_examine", "On Examine"),
    ("on_time", "On Time"),
]

# Trigger actions for the builder
TRIGGER_ACTIONS = [
    ("message", "Message to Character"),
    ("message_room", "Message to Room"),
    ("reveal_exit", "Reveal Exit"),
    ("hide_exit", "Hide Exit"),
    ("set_flag", "Set Flag"),
    ("check_flag", "Check Flag"),
]
