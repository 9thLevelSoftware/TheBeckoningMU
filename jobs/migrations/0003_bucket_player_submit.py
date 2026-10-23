"""Add Bucket.player_submit, and open the existing Requests/Bugs buckets to players.

Before this, any account could job/submit to any bucket. Buckets named
Requests or Bugs (the default player buckets) keep that; every other
existing bucket becomes staff-only.
"""

from django.db import migrations, models

PLAYER_BUCKETS = ("requests", "bugs")


def open_player_buckets(apps, schema_editor):
    Bucket = apps.get_model("jobs", "Bucket")
    for bucket in Bucket.objects.all():
        if bucket.name.lower() in PLAYER_BUCKETS:
            bucket.player_submit = True
            bucket.save(update_fields=["player_submit"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_normalize_priority"),
    ]

    operations = [
        migrations.AddField(
            model_name="bucket",
            name="player_submit",
            field=models.BooleanField(
                default=False, help_text="Players may file jobs here with job/submit, and see it in 'buckets'"
            ),
        ),
        migrations.RunPython(open_player_buckets, migrations.RunPython.noop),
    ]
