# Migration to add status lifecycle, background, and rejection tracking fields
# to CharacterBio, replacing the boolean 'approved' field.

from django.db import migrations, models


def convert_approved_to_status(apps, schema_editor):
    """Convert boolean approved field to status string field."""
    CharacterBio = apps.get_model('traits', 'CharacterBio')
    CharacterBio.objects.filter(approved=True).update(status='approved')
    CharacterBio.objects.filter(approved=False).update(status='submitted')


def convert_status_to_approved(apps, schema_editor):
    """Reverse: convert status string field back to boolean approved field."""
    CharacterBio = apps.get_model('traits', 'CharacterBio')
    CharacterBio.objects.filter(status='approved').update(approved=True)
    CharacterBio.objects.exclude(status='approved').update(approved=False)


class Migration(migrations.Migration):

    dependencies = [
        ("traits", "0001_initial"),
    ]

    operations = [
        # Step 1: Add new fields
        migrations.AddField(
            model_name="characterbio",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("rejected", "Rejected"),
                    ("approved", "Approved"),
                ],
                default="submitted",
                help_text="Current approval status",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="characterbio",
            name="background",
            field=models.TextField(
                blank=True,
                help_text="Character's backstory/background narrative",
            ),
        ),
        migrations.AddField(
            model_name="characterbio",
            name="rejection_notes",
            field=models.TextField(
                blank=True,
                help_text="Staff feedback on why character was rejected",
            ),
        ),
        migrations.AddField(
            model_name="characterbio",
            name="rejection_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of times this character has been rejected",
            ),
        ),
        # Step 2: Data migration - convert existing boolean to status string
        migrations.RunPython(
            convert_approved_to_status,
            convert_status_to_approved,
        ),
        # Step 3: Remove the old boolean field
        migrations.RemoveField(
            model_name="characterbio",
            name="approved",
        ),
    ]
