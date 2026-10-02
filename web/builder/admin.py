from django.contrib import admin

from .models import BuildProject, RoomTemplate


@admin.register(BuildProject)
class BuildProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_public", "sandbox_room_id", "updated_at"]
    list_filter = ["is_public", "created_at"]
    search_fields = ["name", "user__username"]
    # The review record, the approved snapshot and the build record only change through the
    # review and build flows, never by hand.
    readonly_fields = [
        "user",
        "status",
        "reviewed_by",
        "reviewed_at",
        "approved_map_data",
        # Cleanup and promotion act on these ids, so they are never hand-edited.
        "sandbox_room_id",
        "built_object_ids",
        "created_at",
        "updated_at",
    ]

    def has_delete_permission(self, request, obj=None):
        # A project with a built sandbox can't be deleted (that would orphan
        # the sandbox); clean it up first.
        if obj is not None and obj.has_sandbox():
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        # The changelist bulk action checks has_delete_permission(obj=None)
        # only, so filter again here.
        built = [project.pk for project in queryset if project.has_sandbox()]
        if built:
            from django.contrib import messages

            self.message_user(
                request,
                f"Not deleted (clean up their sandboxes first): {', '.join(map(str, built))}",
                level=messages.WARNING,
            )
        super().delete_queryset(request, queryset.exclude(pk__in=built))


@admin.register(RoomTemplate)
class RoomTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "is_shared", "created_at"]
    list_filter = ["is_shared"]
    search_fields = ["name", "created_by__username"]
