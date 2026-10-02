"""
+daylight marks sunlight damage (V5 Quick Reference 2.0 p.13 for Day Drinker;
the per-turn amounts are a house convention, UNVERIFIED, see
commands/v5/utils/thin_blood_utils.SUNLIGHT_AGGRAVATED_PER_TURN).
"""

from evennia.utils.test_resources import EvenniaCommandTest

from commands.v5.thinblood import CmdDaylight
from commands.v5.utils.thin_blood_utils import SUNLIGHT_AGGRAVATED_PER_TURN


class DaylightTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char1.set_trait("stamina", 3)  # Health 6

    def _health(self):
        return self.char1.damage["health"]

    def test_vampire_takes_aggravated_each_turn(self):
        out = self.call(CmdDaylight(), "/expose 2 direct")
        per_turn = SUNLIGHT_AGGRAVATED_PER_TURN["direct"]
        self.assertEqual(self._health()["aggravated"], min(6, 2 * per_turn))
        self.assertEqual(self._health()["superficial"], 0)
        self.assertNotIn("bashing", out.lower())

    def test_obscured_sun_is_one_a_turn(self):
        self.call(CmdDaylight(), "/expose obscured")
        self.assertEqual(self._health()["aggravated"], SUNLIGHT_AGGRAVATED_PER_TURN["obscured"])

    def test_full_track_of_aggravated_is_torpor(self):
        out = self.call(CmdDaylight(), "/expose 3 direct")
        self.assertEqual(self._health()["aggravated"], 6)
        self.assertIn("torpor", out)

    def test_thin_blood_without_day_drinker_burns(self):
        self.char1.clan = "Thin-Blood"
        self.call(CmdDaylight(), "/expose obscured")
        self.assertEqual(self._health()["aggravated"], 1)

    def test_day_drinker_halves_health_once(self):
        """QR p.13: sunlight only halves your Health (rounded up); no other damage."""
        self.char1.clan = "Thin-Blood"
        self.char1.set_advantage("merits", "Day Drinker", 1)
        out = self.call(CmdDaylight(), "/expose 3 direct")
        self.assertEqual(self._health()["aggravated"], 0)
        self.assertEqual(self.char1.current_health, 3)  # ceil(6 / 2)
        self.assertIn("Day Drinker", out)
        # Already at half: nothing more.
        self.call(CmdDaylight(), "/expose")
        self.assertEqual(self.char1.current_health, 3)

    def test_mortal_is_unharmed(self):
        self.char1.splat = "mortal"
        out = self.call(CmdDaylight(), "/expose 3")
        self.assertEqual(self._health(), {"superficial": 0, "aggravated": 0})
        self.assertIn("doesn't harm", out)

    def test_view_marks_nothing(self):
        out = self.call(CmdDaylight(), "")
        self.assertIn("Aggravated", out)
        self.assertEqual(self._health()["aggravated"], 0)

    def test_bad_arguments_are_refused(self):
        out = self.call(CmdDaylight(), "/expose 99")
        self.assertIn("Usage", out)
        self.assertEqual(self._health()["aggravated"], 0)
