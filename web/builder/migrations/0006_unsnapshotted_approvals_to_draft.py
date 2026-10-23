"""
Send projects approved before approval snapshots existed back to draft.

The sandbox build now reads only `approved_map_data`. A project approved
before 0005 has no snapshot, can't be built, and `approved` has no path back
to review, so it would be stuck. Returning it to draft lets the owner
resubmit it and a second reviewer approve it under the current rules.
Built and live projects are left alone: their rooms already exist.
"""

from django.db import migrations

NOTE = "Approved before review snapshots existed; please resubmit for review."


def unsnapshotted_approvals_to_draft(apps, schema_editor):
    BuildProject = apps.get_model("builder", "BuildProject")
    BuildProject.objects.filter(status="approved", approved_map_data__isnull=True).update(
        status="draft", rejection_notes=NOTE
    )


class Migration(migrations.Migration):
    dependencies = [
        ("builder", "0005_buildproject_approved_map_data"),
    ]

    operations = [
        migrations.RunPython(unsnapshotted_approvals_to_draft, migrations.RunPython.noop),
    ]
