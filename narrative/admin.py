"""Audit-only admin. All managed writes go through Builder Story Operations."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.html import format_html

from chronicle.services import staff_authorized

from .models import MemoryFact, NarrativePersona


class _CurationReadOnlyAdmin(admin.ModelAdmin):
    actions = None
    list_per_page = 20
    curation_route = ""

    def has_module_permission(self, request):
        return staff_authorized(request.user)

    def has_view_permission(self, request, obj=None):
        return staff_authorized(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.concrete_fields) + ("curation_link",)

    def get_fields(self, request, obj=None):
        return self.get_readonly_fields(request, obj)

    @admin.display(description="Builder curation")
    def curation_link(self, obj):
        return format_html('<a href="{}">Review in Story Operations</a>', reverse(self.curation_route, args=(obj.pk,)))

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Managed narrative records are read-only in admin. Use Story Operations.")


@admin.register(NarrativePersona)
class NarrativePersonaAdmin(_CurationReadOnlyAdmin):
    curation_route = "narrative_ops_persona_edit"
    list_display = ("character", "version", "registered_by", "updated_by", "updated_at")
    search_fields = ("character__db_key", "profile")


@admin.register(MemoryFact)
class MemoryFactAdmin(_CurationReadOnlyAdmin):
    curation_route = "narrative_ops_memory_edit"
    list_display = ("persona", "visibility", "status", "subject", "version", "expires_at", "approved_by")
    list_filter = ("status", "visibility", "expires_at")
    search_fields = ("text", "staff_entry", "persona__character__db_key")
