"""Ordinary Builder forms; managed review state is never a posted field."""

from django import forms

from .curation import MAX_CURATED_TEXT
from .models import MemoryFact


class PersonaRegistrationForm(forms.Form):
    character_id = forms.IntegerField(min_value=1, label="NPC Character ID")
    profile = forms.CharField(
        required=False,
        max_length=MAX_CURATED_TEXT,
        widget=forms.Textarea,
        help_text="Player-facing profile used only in opted-in stories. Keep secrets in staff-only memory provenance.",
    )


class PersonaProfileForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    profile = forms.CharField(required=False, max_length=MAX_CURATED_TEXT, widget=forms.Textarea)


class MemoryCurationForm(forms.Form):
    persona_id = forms.IntegerField(min_value=1, label="Registered persona ID")
    subject_id = forms.IntegerField(
        min_value=1,
        required=False,
        label="Subject Character ID",
        help_text="Required for a private fact; only this subject's opted-in stories may use it.",
    )
    text = forms.CharField(max_length=MAX_CURATED_TEXT, widget=forms.Textarea, label="Memory text")
    source_event_id = forms.IntegerField(min_value=1, required=False, label="Source Chronicle ID")
    staff_entry = forms.CharField(
        required=False,
        max_length=MAX_CURATED_TEXT,
        widget=forms.Textarea,
        label="Staff provenance",
        help_text="Provide a Chronicle source or a staff annotation. Staff provenance is never sent to the provider.",
    )
    visibility = forms.ChoiceField(
        choices=MemoryFact.Visibility.choices, initial=MemoryFact.Visibility.PRIVATE, label="Scope"
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        label="Expiry",
        help_text="Optional future date/time in the site's local time zone.",
    )


class MemoryRevisionForm(MemoryCurationForm):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
