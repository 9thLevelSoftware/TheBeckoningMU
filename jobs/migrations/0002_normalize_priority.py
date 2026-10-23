"""Map the invalid 'NORMAL' priority (written by the old +hunt/staffed) to 'MEDIUM'.

Job.save() now validates priority, so a leftover 'NORMAL' row could not be
claimed, assigned, closed or reopened. A no-op on a fresh database.
"""

from django.db import migrations


def normalize_priority(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    Job.objects.filter(priority="NORMAL").update(priority="MEDIUM")


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_priority, migrations.RunPython.noop),
    ]
