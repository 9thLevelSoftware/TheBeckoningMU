"""
seed_traits copies world/v5_data.py into the legacy traits tables.
(The web chargen validator's clan check is tested in tests/test_rules_chargen.py.)
"""

from io import StringIO

from django.core.management import call_command
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from traits.models import CharacterPower, DisciplinePower, Trait


def seed():
    call_command("seed_traits", stdout=StringIO())


class SeedTraitsTests(EvenniaTest):
    def test_rouse_count_is_shown(self):
        seed()
        self.assertEqual(DisciplinePower.objects.get(name="Bond Famulus").cost, "3 Rouse Checks")
        self.assertEqual(DisciplinePower.objects.get(name="Majesty").cost, "2 Rouse Checks")
        self.assertEqual(DisciplinePower.objects.get(name="Scry the Soul").cost, "One Rouse Check")
        self.assertEqual(DisciplinePower.objects.get(name="Awe").cost, "Free")

    def test_reseeding_updates_rows_and_prunes_stale_ones(self):
        seed()
        auspex = Trait.objects.get(name="Auspex", category__code="disciplines")
        # A row from older data that nothing uses, a stale row a character
        # uses, and a current row with an outdated value.
        DisciplinePower.objects.create(name="Imposter's Guise", discipline=auspex, level=5)
        used = DisciplinePower.objects.create(name="One with the Beast", discipline=auspex, level=4)
        char = create.create_object("typeclasses.characters.Character", key="Seedy")
        CharacterPower.objects.create(character=char, power=used)
        DisciplinePower.objects.filter(name="Bond Famulus").update(cost="One Rouse Check", level=3)
        Trait.objects.create(name="Oblivion", category=auspex.category)

        seed()

        self.assertFalse(DisciplinePower.objects.filter(name="Imposter's Guise").exists())
        used.refresh_from_db()
        self.assertFalse(used.is_active)
        bond = DisciplinePower.objects.get(name="Bond Famulus")
        self.assertEqual((bond.cost, bond.level), ("3 Rouse Checks", 1))
        self.assertFalse(Trait.objects.filter(name="Oblivion", category__code="disciplines").exists())

