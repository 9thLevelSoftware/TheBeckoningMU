import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("chronicle", "0001_initial"),
        ("objects", "0013_defaultobject_alter_objectdb_id_defaultcharacter_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="NarrativePersona",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("profile", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("character", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="narrative_persona", to="objects.objectdb")),
                ("registered_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="registered_narrative_personas", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="NarrativeConsent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opted_in", models.BooleanField(default=False)),
                ("opted_in_at", models.DateTimeField(blank=True, null=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="narrative_consents", to=settings.AUTH_USER_MODEL)),
                ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="narrative_consents", to="objects.objectdb")),
            ],
        ),
        migrations.CreateModel(
            name="MemoryFact",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("staff_entry", models.TextField(blank=True)),
                ("visibility", models.CharField(choices=[("public", "Public"), ("private", "Private to subject"), ("staff", "Staff only")], default="private", max_length=12)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved"), ("redacted", "Redacted")], default="draft", max_length=10)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("persona", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memories", to="narrative.narrativepersona")),
                ("source_event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="narrative_memories", to="chronicle.chronicleevent")),
                ("subject", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="narrative_private_memories", to="objects.objectdb")),
            ],
            options={"ordering": ("created_at", "id"), "indexes": [models.Index(fields=["persona", "status", "visibility", "subject", "expires_at"], name="narr_mem_scope_exp_idx")]},
        ),
        migrations.AddConstraint(
            model_name="memoryfact",
            constraint=models.CheckConstraint(condition=models.Q(source_event__isnull=False) | ~models.Q(staff_entry=""), name="narrative_memory_has_provenance"),
        ),
        migrations.AddConstraint(
            model_name="memoryfact",
            constraint=models.CheckConstraint(condition=~models.Q(visibility="private") | models.Q(subject__isnull=False), name="narrative_private_memory_requires_subject"),
        ),
        migrations.CreateModel(
            name="StorySession",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("location", models.CharField(default="street", max_length=32)),
                ("status", models.CharField(choices=[("active", "Active"), ("completed", "Completed"), ("closed", "Closed")], default="active", max_length=10)),
                ("resume_state", models.JSONField(blank=True, default=dict)),
                ("deterministic_outcome", models.JSONField(blank=True, default=dict)),
                ("current_action", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="narrative_sessions", to="objects.objectdb")),
                ("persona", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sessions", to="narrative.narrativepersona")),
            ],
        ),
        migrations.AddConstraint(
            model_name="storysession",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "active")), fields=("character",), name="narrative_one_active_session_per_character"),
        ),
        migrations.CreateModel(
            name="StoryGenerationRequest",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_text", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="pending", max_length=10)),
                ("response", models.TextField(blank=True)),
                ("citations", models.JSONField(blank=True, default=list)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="requests", to="narrative.storysession")),
            ],
        ),
        migrations.AddConstraint(
            model_name="narrativeconsent",
            constraint=models.UniqueConstraint(fields=("account", "character"), name="narrative_consent_account_character_uniq"),
        ),
    ]
