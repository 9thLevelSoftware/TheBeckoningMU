"""Durable addition receipts preserve the original replacement before-state."""

import copy
import json
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from web.builder.models import BuildProject
from web.builder.test_sandbox import SandboxTestBase


class ReplacementReceiptTests(SandboxTestBase):
    def project(self):
        return BuildProject.objects.create(
            user=self.owner,
            name="Receipt test",
            status="replacing",
            replacement_journal={
                "saved_objects": [{"id": 11, "attributes": {"desc": "Untouched before-state"}}],
                "saved_scripts": [{"id": 12, "remaining": 29}],
                "created_object_ids": [],
                "created_objects": [],
                "created_script_ids": [],
            },
        )

    def test_compact_sql_append_keeps_before_state_and_both_object_lists_coherent(self):
        from web.builder.replacement_receipts import append_receipt

        project = self.project()
        before = copy.deepcopy(project.replacement_journal)
        receipt = {"object_id": 101, "typeclass": 'typeclasses.rooms.Room"quoted', "kind": "rooms"}
        with CaptureQueriesContext(connection) as captured:
            append_receipt(project, object_receipt=receipt)
        writes = [query["sql"] for query in captured if query["sql"].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(len(writes), 1)
        self.assertNotIn("Untouched before-state", writes[0])
        self.assertNotIn("saved_objects", writes[0])
        # Keep using the stale Python instance: each append must use current DB lists.
        append_receipt(
            project, object_receipt={"object_id": 102, "typeclass": "typeclasses.exits.Exit", "kind": "exits"}
        )
        append_receipt(project, script_id=201)
        project.refresh_from_db()
        journal = project.replacement_journal
        self.assertEqual(journal["saved_objects"], before["saved_objects"])
        self.assertEqual(journal["saved_scripts"], before["saved_scripts"])
        self.assertEqual(journal["created_object_ids"], [101, 102])
        self.assertEqual(journal["created_objects"][0], receipt)
        self.assertIsInstance(journal["created_objects"][0], dict)
        self.assertEqual(journal["created_script_ids"], [201])
        self.assertTrue(all(type(value) is int for value in journal["created_object_ids"]))

    def test_changed_status_or_version_refuses_without_mutating_journal(self):
        from web.builder.replacement_receipts import ReceiptError, append_receipt

        for change in ({"status": "approved"}, {"version": 77}):
            with self.subTest(change=change):
                project = self.project()
                before = copy.deepcopy(project.replacement_journal)
                BuildProject.objects.filter(pk=project.pk).update(**change)
                with self.assertRaisesRegex(ReceiptError, "changed|replacing"):
                    append_receipt(project, script_id=201)
                self.assertEqual(BuildProject.objects.get(pk=project.pk).replacement_journal, before)

    def test_failure_after_update_rolls_back_both_appended_lists(self):
        from web.builder.replacement_receipts import append_receipt

        project = self.project()
        before = copy.deepcopy(project.replacement_journal)
        intercepted = []

        def fail_after_update(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.lstrip().upper().startswith("UPDATE"):
                intercepted.append((sql, params))
                raise RuntimeError("Injected receipt persistence failure")
            return result

        with (
            connection.execute_wrapper(fail_after_update),
            self.assertRaisesRegex(RuntimeError, "Injected receipt"),
        ):
            append_receipt(project, object_receipt={"object_id": 101, "typeclass": "Room", "kind": "rooms"})
        self.assertEqual(len(intercepted), 1)
        self.assertEqual(BuildProject.objects.get(pk=project.pk).replacement_journal, before)

    def test_missing_or_wrong_list_shape_refuses_without_partial_append(self):
        from web.builder.replacement_receipts import ReceiptError, append_receipt

        for lists in ({}, {"created_object_ids": [], "created_objects": "wrong", "created_script_ids": []}):
            with self.subTest(lists=lists):
                project = self.project()
                BuildProject.objects.filter(pk=project.pk).update(replacement_journal=lists)
                with self.assertRaises(ReceiptError):
                    append_receipt(project, object_receipt={"object_id": 101, "typeclass": "Room", "kind": "rooms"})
                self.assertEqual(BuildProject.objects.get(pk=project.pk).replacement_journal, lists)

    def test_invalid_receipt_values_refuse_without_a_write(self):
        from web.builder.replacement_receipts import ReceiptError, append_receipt

        project = self.project()
        for kwargs in (
            {},
            {"script_id": True},
            {"script_id": -1},
            {"object_receipt": {"object_id": 101, "typeclass": "Room", "kind": "invalid"}},
            {"object_receipt": {"object_id": 101, "typeclass": "Room", "kind": []}},
            {"object_receipt": {"object_id": "101", "typeclass": "Room", "kind": "rooms"}},
        ):
            with self.subTest(kwargs=kwargs), CaptureQueriesContext(connection) as captured:
                with self.assertRaises(ReceiptError):
                    append_receipt(project, **kwargs)
                self.assertEqual(len(captured), 0)

    def test_portable_branch_preserves_current_lists_and_refuses_changed_record(self):
        from web.builder.replacement_receipts import ReceiptError, append_receipt

        project = self.project()
        before = copy.deepcopy(project.replacement_journal)
        with mock.patch.object(connection, "vendor", "portable-test"):
            append_receipt(project, object_receipt={"object_id": 101, "typeclass": "Room", "kind": "rooms"})
            append_receipt(project, script_id=201)
            BuildProject.objects.filter(pk=project.pk).update(status="live")
            with self.assertRaises(ReceiptError):
                append_receipt(project, script_id=202)
        journal = BuildProject.objects.get(pk=project.pk).replacement_journal
        self.assertEqual(journal["saved_objects"], before["saved_objects"])
        self.assertEqual(journal["created_object_ids"], [101])
        self.assertEqual(journal["created_objects"], [{"object_id": 101, "typeclass": "Room", "kind": "rooms"}])
        self.assertEqual(journal["created_script_ids"], [201])
        self.assertEqual(json.loads(json.dumps(journal)), journal)
