"""Current played-sheet review data and safe client rendering."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from tests.chargen_fixtures import legal_payload, thin_blood_payload
from tests.test_chargen_web import ChargenWebTestCase, url
from traits.models import CharacterBio


class CharacterReviewCompletenessTests(ChargenWebTestCase):
    def detail(self, character_id, account=None):
        return self.as_(account or self.builder_b).get(url(character_id, "detail"))

    def test_ordinary_persisted_choices_and_permissions(self):
        payload = legal_payload()
        payload["advantages"][-1]["note"] = "Spanish and French"
        response, cid = self.create_as(self.player_a, payload)
        self.assertEqual(response.status_code, 201, response.content)
        char = self.character(cid)
        char.refresh_from_db()
        data = self.detail(cid).json()
        sheet = data["sheet"]
        self.assertEqual(sheet["age_category"], payload["age"])
        self.assertEqual(sheet["convictions"], [payload["convictions"][0]["conviction"]])
        self.assertEqual(
            sheet["touchstones"][0],
            {"name": "Teo Marquez", "description": "Her old shop steward", "conviction_index": 0},
        )
        self.assertEqual(sheet["advantage_notes"]["merits"]["Linguistics"], "Spanish and French")
        self.assertEqual(sheet["advantage_notes"]["flaws"]["Addiction"], "nicotine")
        self.assertIn("applicant_ip", data["bio"])
        owner = self.detail(cid, self.player_a)
        self.assertEqual(owner.status_code, 200)
        self.assertNotIn("applicant_ip", owner.json()["bio"])
        self.assertEqual(self.detail(cid, self.player_c).status_code, 403)

    def test_learned_items_survive_submission(self):
        tremere = legal_payload(clan="Tremere", predator_type="Bagger", rituals=["Blood Walk"])
        tremere["disciplines"] = {"Auspex": 2, "Dominate": 1, "Blood Sorcery": 1}
        tremere["discipline_powers"] = ["Heightened Senses", "Premonition", "Cloud Memory", "A Taste for Blood"]
        tremere["specialties"][0] = {"skill": "larceny", "name": "Lock Picking"}
        alchemist = thin_blood_payload(disciplines={"Thin-Blood Alchemy": 1}, formulas=["Haze"])
        alchemist["advantages"].append({"name": "Thin-blood Alchemist", "dots": 1})
        alchemist["flaws"].append({"name": "Clan Curse", "dots": 1, "note": "toreador"})
        for payload in (tremere, alchemist):
            with self.subTest(clan=payload["clan"]):
                response, cid = self.create_as(self.player_a, payload)
                self.assertEqual(response.status_code, 201, response.content)
                sheet = self.detail(cid).json()["sheet"]
                self.assertEqual(sheet["rituals"], payload.get("rituals", []))
                self.assertEqual(sheet["formulas"], payload.get("formulas", []))

    def test_revoked_sheet_uses_played_state_and_handles_legacy_links(self):
        response, cid = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.review(self.builder_b, cid, "approve").status_code, 200)
        char = self.character(cid)
        char.add_conviction("Played conviction")
        char.add_touchstone("New friend", "Played description", 1)
        char.set_advantage("flaws", "Addiction", 1, note="played note")
        self.assertEqual(self.review(self.admin_d, cid, "revoke", "review again").status_code, 200)
        data = self.detail(cid).json()
        self.assertEqual(data["bio"]["status"], "revoked")
        self.assertIn("Played conviction", data["sheet"]["convictions"])
        self.assertEqual(data["sheet"]["advantage_notes"]["flaws"]["Addiction"], "played note")
        self.assertNotIn("Played conviction", str(CharacterBio.objects.get(character_id=cid).submission))
        char.db.humanity_data = {
            "convictions": ["Valid"],
            "touchstones": [None, "legacy", {"name": "Orphan", "conviction_index": "oops"}],
        }
        self.assertEqual(self.detail(cid).status_code, 200)

    @skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_review_dom_escapes_text_and_shows_empty_states(self):
        response, cid = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 201)
        data = self.detail(cid).json()
        attack = '<img src=x onerror="throw 1"><script>throw 2</script>'
        data["sheet"]["convictions"] = [attack]
        data["sheet"]["touchstones"] = [
            {"name": attack, "description": attack, "conviction_index": 0},
            {"name": "Orphan", "conviction_index": "bad"},
            None,
        ]
        data["sheet"]["advantage_notes"] = {"merits": {"Linguistics": attack}, "flaws": {}}
        page = (Path(__file__).parents[1] / "web/templates/character_approval.html").read_text(encoding="utf-8")
        script = (
            re.search(r"<script>(.*?)</script>", page, re.S)[1]
            .replace("{{ csrf_token }}", "x")
            .replace('{{ can_revoke|yesno:"true,false" }}', "true")
        )
        harness = r"""
const vm = require('vm'), input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const target = {innerHTML: ''};
const document = {addEventListener() {}, getElementById(id) {return id === 'character-detail' ? target : null;}, createElement() {return {set textContent(v) {this.innerHTML = String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}};}};
const ctx = {document, console}; vm.createContext(ctx); vm.runInContext(input.script, ctx);
ctx.displayCharacterDetail(input.data); const populated = target.innerHTML;
input.data.sheet.convictions=[]; input.data.sheet.touchstones=[]; input.data.sheet.advantage_notes={};
ctx.displayCharacterDetail(input.data); console.log(JSON.stringify({populated, empty: target.innerHTML}));
"""
        result = subprocess.run(
            ["node", "-e", harness],
            input=json.dumps({"script": script, "data": data}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=60,
            check=True,
        )
        output = json.loads(result.stdout)
        self.assertNotIn(attack, output["populated"])
        self.assertIn("&lt;script&gt;", output["populated"])
        for heading in ("Convictions and Touchstones", "Rituals", "Formulas", "Merit and Flaw Notes"):
            self.assertIn(heading, output["populated"])
        self.assertIn("Unlinked touchstone", output["populated"])
        for message in (
            "No convictions recorded",
            "No touchstones recorded",
            "No rituals recorded",
            "No formulas recorded",
            "No merit or flaw notes recorded",
        ):
            self.assertIn(message, output["empty"])
