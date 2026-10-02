from django.contrib import admin

from .models import BuildProject, RoomTemplate


@admin.register(BuildProject)
class BuildProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_public", "sandbox_room_id", "updated_at"]
    list_filter = ["is_public", "created_at"]
    search_fields = ["name", "user__username"]
    # The review record and the approved snapshot only change through the
    # review flow, never by hand.
    readonly_fields = [
        "user",
        "status",
        "reviewed_by",
        "reviewed_at",
        "approved_map_data",
        "created_at",
        "updated_at",
    ]


@admin.register(RoomTemplate)
class RoomTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "is_shared", "created_at"]
    list_filter = ["is_shared"]
    search_fields = ["name", "created_by__username"]
