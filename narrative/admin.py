from django import forms
from django.contrib import admin
from django.utils import timezone
from evennia.objects.models import ObjectDB

from .models import MemoryFact, NarrativePersona
from .services import validate_persona_character


class NarrativePersonaForm(forms.ModelForm):
    character = forms.ModelChoiceField(queryset=ObjectDB.objects.filter(db_account__isnull=True))
    profile = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="Player-facing profile sent only to opted-in story generation. Do not add secrets.",
    )

    class Meta:
        model = NarrativePersona
        fields = ("character", "profile")

    def clean_character(self):
        character = self.cleaned_data["character"]
        try:
            return validate_persona_character(character)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error


@admin.register(NarrativePersona)
class NarrativePersonaAdmin(admin.ModelAdmin):
    form = NarrativePersonaForm
    list_display = ("character", "registered_by", "updated_at")
    search_fields = ("character__db_key", "profile")
    readonly_fields = ("registered_by", "created_at", "updated_at")
    fields = ("character", "profile", "registered_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registered_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


class MemoryFactForm(forms.ModelForm):
    text = forms.CharField(
        widget=forms.Textarea,
        help_text="Only approved public facts or approved facts for the exact subject may be sent to story generation.",
    )
    staff_entry = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="Staff-only annotation; it is never sent to story generation.",
    )

    def clean_subject(self):
        subject = self.cleaned_data.get("subject")
        if subject is not None and not subject.is_typeclass("typeclasses.characters.Character", exact=False):
            raise forms.ValidationError("Private memory subjects must be Character objects.")
        return subject

    class Meta:
        model = MemoryFact
        fields = (
            "persona",
            "subject",
            "text",
            "source_event",
            "staff_entry",
            "visibility",
            "status",
            "expires_at",
        )


@admin.register(MemoryFact)
class MemoryFactAdmin(admin.ModelAdmin):
    form = MemoryFactForm
    list_display = ("persona", "visibility", "status", "subject", "expires_at", "created_at")
    list_filter = ("status", "visibility", "expires_at")
    search_fields = ("text", "staff_entry", "persona__character__db_key")
    readonly_fields = ("created_at", "approved_at")
    fields = (
        "persona",
        "subject",
        "text",
        "source_event",
        "staff_entry",
        "visibility",
        "status",
        "expires_at",
        "created_at",
        "approved_at",
    )

    def save_model(self, request, obj, form, change):
        if obj.status == MemoryFact.Status.APPROVED:
            obj.approved_at = obj.approved_at or timezone.now()
        else:
            obj.approved_at = None
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False
