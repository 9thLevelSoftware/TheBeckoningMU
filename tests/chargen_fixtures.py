"""
Chargen payloads for tests.

`legal_payload()` is the JSON the website's form (web/static/chargen/
codex-chargen.js, buildPayload()) posts for a legal Balanced Brujah neonate
with the Alleycat predator type; it lives in fixtures/chargen_balanced_brujah.json.
The other builders change it into other legal or illegal characters.
"""

import copy
import json
from pathlib import Path

FIXTURE = Path(__file__).with_name("fixtures") / "chargen_balanced_brujah.json"
_PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))


def legal_payload(**changes):
    """A fresh copy of the legal fixture, with top-level keys replaced by `changes`."""
    payload = copy.deepcopy(_PAYLOAD)
    payload.update(copy.deepcopy(changes))
    return payload


def zero_skills():
    return dict.fromkeys(_PAYLOAD["skills"], 0)


def thin_blood_payload(**changes):
    """A legal thin-blood Childer: no predator type, no disciplines, one thin-blood pair."""
    payload = legal_payload(
        name="Pip Harlow",
        clan="Thin-Blood",
        age="Childer",
        generation=14,
        predator_type=None,
        disciplines={},
        discipline_powers=[],
        specialties=[{"skill": "brawl", "name": "Boxing"}],
        advantages=[
            {"name": "Resources", "dots": 2},
            {"name": "Lifelike", "dots": 1},
        ],
        flaws=[
            {"name": "Addiction", "dots": 1, "note": "caffeine"},
            {"name": "Known Corpse", "dots": 1},
            {"name": "Baby Teeth", "dots": 1},
        ],
    )
    payload.update(copy.deepcopy(changes))
    return payload


def ancilla_payload(**changes):
    """A legal Ancilla Brujah: generation 11, 9 advantage dots, 4 flaw dots."""
    payload = legal_payload(
        name="Old Ruth",
        age="Ancilla",
        generation=11,
        advantages=[
            {"name": "Resources", "dots": 3},
            {"name": "Haven", "dots": 2},
            {"name": "Allies", "dots": 3, "note": "dockworkers union"},
            {"name": "Linguistics", "dots": 1},
        ],
        flaws=[
            {"name": "Addiction", "dots": 1, "note": "nicotine"},
            {"name": "Known Corpse", "dots": 1},
            {"name": "Living in the Past", "dots": 1},
            {"name": "Creepy", "dots": 1},
        ],
    )
    payload.update(copy.deepcopy(changes))
    return payload
