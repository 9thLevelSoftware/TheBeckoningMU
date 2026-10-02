"""
traits 0003 on a database that already holds pre-PR-7 applications: owners
are found from every source Evennia leaves behind, a leftover 'draft' becomes
'submitted', every existing Character gets the gated locks, and the trait
tables go.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("traits", "0002_characterbio_status_background")]
AFTER = [("traits", "0003_chargen_ownership_drop_trait_tables")]
CHARACTER = "typeclasses.characters.Character"


class TraitsMigration0003Tests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        self.apps = executor.loader.project_state(BEFORE).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def make_account(self, name):
        AccountDB = self.apps.get_model("accounts", "AccountDB")
        return AccountDB.objects.create(username=name, db_key=name, password="x", db_lock_storage="")

    def make_character(self, key, account=None, locks="puppet:pid(1) or perm(Developer);get:false()"):
        ObjectDB = self.apps.get_model("objects", "ObjectDB")
        return ObjectDB.objects.create(
            db_key=key,
            db_typeclass_path=CHARACTER,
            db_lock_storage=locks,
            db_account_id=account.id if account else None,
        )

    def add_attribute(self, owner, key, value):
        Attribute = self.apps.get_model("typeclasses", "Attribute")
        attribute = Attribute.objects.create(db_key=key, db_value=value)
        owner.db_attributes.add(attribute)

    def make_bio(self, character, status="submitted"):
        CharacterBio = self.apps.get_model("traits", "CharacterBio")
        return CharacterBio.objects.create(character_id=character.id, clan="Brujah", splat="vampire", status=status)

    def test_backfill_relock_and_drop(self):
        puppeteer, creator, lister = (self.make_account(n) for n in ("Puppeteer", "Creator", "Lister"))
        played = self.make_character("Played", account=puppeteer)
        created = self.make_character("Created")
        self.add_attribute(created, "creator_id", creator.id)
        listed = self.make_character("Listed")
        self.add_attribute(
            lister, "_playable_characters", [("__packed_dbobj__", ("objects", "objectdb"), "x", listed.id)]
        )
        orphan = self.make_character("Orphan")
        npc = self.make_character("Npc", locks="puppet:perm(Builder)")
        for character, status in (
            (played, "approved"),
            (created, "draft"),
            (listed, "rejected"),
            (orphan, "submitted"),
        ):
            self.make_bio(character, status)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        CharacterBio = apps.get_model("traits", "CharacterBio")
        ObjectDB = apps.get_model("objects", "ObjectDB")

        owners = dict(CharacterBio.objects.values_list("character__db_key", "account_id"))
        self.assertEqual(owners, {"Played": puppeteer.id, "Created": creator.id, "Listed": lister.id, "Orphan": None})
        self.assertEqual(CharacterBio.objects.get(character_id=created.id).status, "submitted")

        for character in (played, created, npc):
            locks = ObjectDB.objects.get(id=character.id).db_lock_storage
            self.assertIn("puppet:(char_owner() and char_approved()) or perm(Admin)", locks)
            self.assertNotIn("pid(1)", locks)
        self.assertIn("get:false()", ObjectDB.objects.get(id=played.id).db_lock_storage)

        tables = set(connection.introspection.table_names())
        self.assertIn("traits_characterbio", tables)
        for gone in ("traits_trait", "traits_charactertrait", "traits_disciplinepower", "traits_traitcategory"):
            self.assertNotIn(gone, tables)
