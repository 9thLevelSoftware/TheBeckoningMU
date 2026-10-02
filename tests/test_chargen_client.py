"""
The creation form's payload builder (web/static/chargen/codex-chargen.js)
produces exactly the server's submission schema, from the rules the server
serves at /api/traits/rules/. Runs the real JS under Node; skipped without it.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from django.test import Client
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from tests.chargen_fixtures import FIXTURE, legal_payload
from traits.api import chargen_rules
from world import v5_data
from world.rules_chargen import parse_submission, validate_v5_creation

SCRIPT = Path(__file__).resolve().parent.parent / "web" / "static" / "chargen" / "codex-chargen.js"

# Fills a fresh form state the way a player would on each tab, then builds the payload.
NODE_PROGRAM = r"""
const core = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const rules = input.rules, fixture = input.fixture;

// 1. A player filling in the form.
const s = core.newState(rules);
Object.assign(s, {name: fixture.name, concept: fixture.concept, clan: 'Brujah', age: 'Neonate',
                  generation: '13', predator_type: 'Alleycat', sire: fixture.sire,
                  ambition: fixture.ambition, desire: fixture.desire, background: fixture.background});
Object.assign(s.attributes, fixture.attributes);
Object.assign(s.skills, fixture.skills);
s.specialties = [{skill: 'intimidation', name: ' Stickups '}, {skill: 'brawl', name: 'Boxing'}, {skill: 'melee', name: ''}];
s.disciplines = {Potence: 2, Presence: 1, Celerity: 1, Auspex: 0};
s.powers = ['Lethal Body', 'Prowess', 'Awe', 'Rapid Reflexes'];
s.advantages = fixture.advantages.map(a => Object.assign({note: '', source: null}, a)).concat([{name: '', dots: 1}]);
s.flaws = fixture.flaws.map(f => Object.assign({note: '', source: null}, f));
const typed = core.buildPayload(s);

// 2. The edit form: a stored submission back into state and out again.
const roundTrip = core.buildPayload(core.stateFromSubmission(rules, fixture));

console.log(JSON.stringify({typed, roundTrip, tallies: core.tallies(rules, s)}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ChargenClientPayloadTests(EvenniaTest):
    def run_node(self, rules):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = subprocess.run(
            ["node", "-e", NODE_PROGRAM, str(SCRIPT)],
            input=json.dumps({"rules": rules, "fixture": fixture}),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(result.stdout)

    def test_form_payload_is_the_fixture_and_validates(self):
        rules = json.loads(json.dumps(chargen_rules()))
        out = self.run_node(rules)
        self.assertEqual(out["typed"], legal_payload())
        self.assertEqual(out["roundTrip"], legal_payload())
        self.assertEqual(validate_v5_creation(parse_submission(out["typed"])), [])
        self.assertTrue(all(t[3] for t in out["tallies"]), out["tallies"])

    def test_rules_endpoint_serves_the_tables(self):
        account = create.create_account("RulesReader", email="r@example.com", password="testpassword123")
        client = Client()
        client.force_login(account)
        rules = client.get("/api/traits/rules/").json()
        self.assertEqual(rules["attribute_spread"], list(v5_data.CREATION_ATTRIBUTE_SPREAD))
        self.assertEqual(set(rules["clans"]), set(v5_data.CLANS))
        self.assertNotIn("Lasombra", rules["clans"])
        self.assertEqual(rules["skill_distributions"]["Balanced"], {"3": 3, "2": 5, "1": 7})
        self.assertIn("Prowess", [p["name"] for p in rules["disciplines"]["Potence"]["powers"]])
        account.delete()


class ClientHasNoNonCoreClansTests(unittest.TestCase):
    def test_form_files_do_not_offer_non_core_clans(self):
        template = (SCRIPT.parent.parent.parent / "templates" / "character_creation.html").read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        for clan in v5_data.NON_CORE_CLANS:
            self.assertNotIn(clan, template, clan)
            self.assertNotIn(clan, script, clan)
