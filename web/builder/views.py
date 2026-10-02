import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView, View

from web.permissions import has_perm

from .models import BuildProject, RoomTemplate, StaleReviewError
from .promotion import promote_project_to_live
from .sandbox_bridge import create_sandbox_from_project
from .trigger_actions import ACTION_REGISTRY, list_actions
from .trigger_engine import validate_trigger
from .v5_conditions import list_condition_types
from .validators import live_rooms, validate_build_map, validate_connection, validate_project

# V5 Room Template Presets
V5_ROOM_TEMPLATES = {
    "elysium": {
        "name": "Elysium",
        "description": "Neutral ground where violence is forbidden. A place of peace among Kindred.",
        "v5": {
            "location_type": "elysium",
            "day_night": "always",
            "danger_level": "safe",
            "hunting_modifier": 0,
        },
    },
    "haven": {
        "name": "Haven",
        "description": "A vampire's personal sanctuary and refuge from the outside world.",
        "v5": {
            "location_type": "haven",
            "day_night": "restricted",
            "danger_level": "low",
            "hunting_modifier": 0,
            "haven_ratings": {
                "security": 3,
                "size": 2,
                "luxury": 2,
                "warding": 1,
                "location_hidden": False,
            },
        },
    },
    "rack": {
        "name": "Rack (Feeding Ground)",
        "description": "A hunting ground where Kindred feed on mortals. Often dangerous.",
        "v5": {
            "location_type": "rack",
            "day_night": "night_only",
            "danger_level": "moderate",
            "hunting_modifier": 2,
        },
    },
    "hostile_territory": {
        "name": "Hostile Territory",
        "description": "Dangerous area controlled by enemies or hostile forces.",
        "v5": {
            "location_type": "hostile",
            "day_night": "restricted",
            "danger_level": "high",
            "hunting_modifier": -2,
        },
    },
    "neutral_ground": {
        "name": "Neutral Ground",
        "description": "Public areas like streets and parks. Generally safe but exposed.",
        "v5": {
            "location_type": "neutral",
            "day_night": "always",
            "danger_level": "low",
            "hunting_modifier": 0,
        },
    },
    "mortal_establishment": {
        "name": "Mortal Establishment",
        "description": "Human businesses like bars, shops, or restaurants.",
        "v5": {
            "location_type": "mortal",
            "day_night": "always",
            "danger_level": "safe",
            "hunting_modifier": 1,
        },
    },
    "supernatural_site": {
        "name": "Supernatural Site",
        "description": "Places of mystical significance or supernatural importance.",
        "v5": {
            "location_type": "supernatural",
            "day_night": "restricted",
            "danger_level": "moderate",
            "hunting_modifier": 0,
        },
    },
    "clear": {
        "name": "Clear Template",
        "description": "Reset all V5 settings to defaults.",
        "v5": {
            "location_type": "",
            "day_night": "always",
            "danger_level": "safe",
            "hunting_modifier": 0,
        },
    },
}


class BuilderRequiredMixin(LoginRequiredMixin):
    """
    Require the in-game Builder permission (or higher).

    Django's is_staff flag grants nothing here: web authority uses the same
    Evennia permission strings as in-game commands.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_perm(request.user, "Builder"):
            return HttpResponseForbidden(
                "Builder access requires the in-game Builder permission on your account (perm *<account> = Builder)."
            )
        return super().dispatch(request, *args, **kwargs)


def can_manage(user, project):
    """Owner or Admin (and above) may build, clean up and promote a project."""
    return project.user == user or has_perm(user, "Admin")


def can_view(user, project):
    """Public projects, your own, and anything awaiting or past review."""
    return project.is_public or project.user == user or project.status != "draft"


class BuilderDashboardView(BuilderRequiredMixin, TemplateView):
    """Dashboard showing all builder projects."""

    template_name = "builder/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # User's own projects
        ctx["my_projects"] = BuildProject.objects.filter(user=self.request.user)
        # Public projects from others
        ctx["public_projects"] = BuildProject.objects.filter(is_public=True).exclude(
            user=self.request.user
        )[:20]
        return ctx


class BuilderEditorView(BuilderRequiredMixin, TemplateView):
    """Main editor interface."""

    template_name = "builder/editor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        project_id = self.kwargs.get("pk")

        if project_id:
            project = get_object_or_404(BuildProject, pk=project_id)
            if not can_view(self.request.user, project):
                raise PermissionDenied("This project is private.")
            # Only the owner edits, and only before review
            ctx["is_owner"] = project.user == self.request.user
            ctx["can_edit"] = ctx["is_owner"] and project.is_editable()
            ctx["project"] = project
            # Rendered with |json_script, which escapes </script> and friends
            ctx["project_data_obj"] = project.map_data
            ctx["project_version"] = project.version
            ctx["project_id"] = project.id
            ctx["project_name"] = project.name
            ctx["project_status"] = project.status
            ctx["rejection_notes"] = project.rejection_notes or ""
            ctx["rejection_count"] = project.rejection_count or 0
            ctx["sandbox_room_id"] = project.sandbox_room_id
        else:
            ctx["is_owner"] = True
            ctx["can_edit"] = True
            ctx["project"] = None
            ctx["project_data_obj"] = BuildProject().get_default_map_data()
            ctx["project_version"] = None
            ctx["project_id"] = None
            ctx["project_name"] = "New Project"
            ctx["project_status"] = "new"
            ctx["rejection_notes"] = ""
            ctx["rejection_count"] = 0
            ctx["sandbox_room_id"] = None

        return ctx


# API views
class SaveProjectView(BuilderRequiredMixin, View):
    """Save or create a project."""

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "error": "Invalid JSON"}, status=400
            )
        if not isinstance(data, dict):
            return JsonResponse(
                {"status": "error", "error": "Expected a JSON object"}, status=400
            )

        project_id = data.get("id")
        name = data.get("name", "Untitled Project")
        map_data = data.get("map_data", {})

        # Validate project data. A draft may be saved while invalid; the
        # build rules (validate_build_map) are enforced at submit.
        is_valid, errors, warnings = validate_project(map_data)
        for error in validate_build_map(map_data):
            if error not in errors:
                errors.append(error)
        is_valid = not errors

        if project_id:
            # Update existing
            project = get_object_or_404(BuildProject, pk=project_id)
            if project.user != request.user:
                return JsonResponse(
                    {"status": "error", "error": "Not authorized"}, status=403
                )

            # Optimistic concurrency: the client must say which version it
            # edited, and the write only lands if that is still current.
            client_version = data.get("version")
            if type(client_version) is not int:
                return JsonResponse(
                    {"status": "error", "error": "version is required"}, status=400
                )

            if not project.is_editable():
                return _locked_response(project)

            updated = BuildProject.objects.filter(
                pk=project.pk,
                user=request.user,
                status="draft",
                version=client_version,
            ).update(
                name=name,
                map_data=map_data,
                version=F("version") + 1,
                updated_at=timezone.now(),
            )
            project.refresh_from_db()
            if not updated:
                if not project.is_editable():
                    return _locked_response(project)
                return JsonResponse(
                    {
                        "status": "error",
                        "error": "Project was modified by another session. Reload and try again.",
                        "server_version": project.version,
                    },
                    status=409,
                )
        else:
            # Create new
            project = BuildProject.objects.create(
                user=request.user,
                name=name,
                map_data=map_data,
                version=1,
            )

        return JsonResponse(
            {
                "status": "success",
                "id": project.id,
                "version": project.version,
                "validation": {
                    "is_valid": is_valid,
                    "errors": errors,
                    "warnings": warnings,
                },
            }
        )


def _locked_response(project):
    """409 for a map edit attempted after the project left draft."""
    return JsonResponse(
        {
            "status": "error",
            "error": (
                f"Project is '{project.status}': the map is locked once it is "
                "submitted for review."
            ),
        },
        status=409,
    )


class GetProjectView(BuilderRequiredMixin, View):
    """Get project data."""

    def get(self, request, pk, *args, **kwargs):
        project = get_object_or_404(BuildProject, pk=pk)

        # Check visibility
        if not can_view(request.user, project):
            return JsonResponse(
                {"status": "error", "error": "Not authorized"}, status=403
            )

        return JsonResponse(
            {
                "status": "success",
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "map_data": project.map_data,
                    "is_public": project.is_public,
                    "sandbox_room_id": project.sandbox_room_id,
                    "can_edit": project.user == request.user
                    and project.is_editable(),
                    "version": project.version,
                    "status": project.status,
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.updated_at.isoformat(),
                },
            }
        )


class DeleteProjectView(BuilderRequiredMixin, View):
    """Delete a project."""

    def delete(self, request, pk, *args, **kwargs):
        project = get_object_or_404(BuildProject, pk=pk)
        is_admin = has_perm(request.user, "Admin")

        if project.user != request.user and not is_admin:
            return JsonResponse(
                {"status": "error", "error": "Not authorized"}, status=403
            )

        # Once submitted, the row carries the review record (reviewer,
        # snapshot, connection) and may own built rooms; only Admins remove it.
        if project.status != "draft" and not is_admin:
            return JsonResponse(
                {
                    "status": "error",
                    "error": (
                        f"Project is '{project.status}': only drafts can be "
                        "deleted. Ask an Admin."
                    ),
                },
                status=409,
            )

        project.delete()
        return JsonResponse({"status": "success"})

    def post(self, request, pk, *args, **kwargs):
        # Allow POST as fallback for clients that don't support DELETE
        return self.delete(request, pk, *args, **kwargs)


class PrototypesView(BuilderRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "not_implemented"}, status=501)


class TemplatesView(BuilderRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "success", "templates": V5_ROOM_TEMPLATES})


# Approval Workflow Views


class SubmitProjectView(BuilderRequiredMixin, View):
    """Submit a project for staff review."""

    def post(self, request, pk, *args, **kwargs):
        project = get_object_or_404(BuildProject, pk=pk)

        # Only owner can submit their own project
        if project.user != request.user:
            return JsonResponse(
                {"status": "error", "error": "Not authorized"}, status=403
            )

        # Validate project is in draft status
        if not project.can_transition_to("submitted"):
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"Cannot submit project in '{project.status}' status",
                },
                status=400,
            )

        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "error": "Invalid JSON"}, status=400
            )
        if not isinstance(data, dict):
            return JsonResponse(
                {"status": "error", "error": "Expected a JSON object"}, status=400
            )

        # Only a map the sandbox build accepts can go to review: once it is
        # submitted the map is locked, so a bad one would be stuck.
        map_errors = validate_build_map(project.map_data)
        if map_errors:
            return JsonResponse(
                {"status": "error", "error": "; ".join(map_errors[:5]), "errors": map_errors},
                status=400,
            )

        # The live attachment point is part of what gets reviewed.
        errors, room_id, direction = validate_connection(
            data.get("connection_room_id"), data.get("connection_direction")
        )
        if errors:
            return JsonResponse(
                {"status": "error", "error": "; ".join(errors), "errors": errors},
                status=400,
            )
        project.connection_room_id = room_id
        project.connection_direction = direction

        notes = data.get("notes", "")
        if isinstance(notes, str) and notes:
            project.submission_notes = notes

        # Submit the project
        try:
            project.submit()
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Project submitted for review",
                    "project": {
                        "id": project.id,
                        "name": project.name,
                        "status": project.status,
                    },
                }
            )
        except StaleReviewError as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=409)
        except ValueError as e:
            return JsonResponse({"status": "error", "error": str(e)}, status=400)


def _connection_info(project):
    """The reviewed attachment point: dbref plus the room's current name."""
    if project.connection_room_id is None:
        return None
    from evennia.objects.models import ObjectDB

    room = ObjectDB.objects.filter(pk=project.connection_room_id).first()
    return {
        "room_id": project.connection_room_id,
        "room_name": room.db_key if room else None,
        "direction": project.connection_direction,
    }


class BuildReviewView(BuilderRequiredMixin, View):
    """Staff review interface - list submitted and recently reviewed projects."""

    RECENT_LIMIT = 20

    def get(self, request, *args, **kwargs):
        # Get all projects with submitted status
        projects = BuildProject.objects.filter(status="submitted").select_related(
            "user"
        )

        project_list = []
        for project in projects:
            map_data = project.map_data or {}
            rooms = map_data.get("rooms", {})
            exits = map_data.get("exits", {})

            project_list.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "user": {
                        "id": project.user.id,
                        "username": project.user.username,
                    },
                    "submission_notes": project.submission_notes,
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.updated_at.isoformat(),
                    "room_count": len(rooms),
                    "exit_count": len(exits),
                    "connection": _connection_info(project),
                    "can_review": project.can_be_reviewed_by(request.user),
                    "version": project.version,
                }
            )

        # Every review records who made it; list the recent ones so that
        # self-approvals by Admins are visible.
        reviewed = (
            BuildProject.objects.filter(reviewed_by__isnull=False)
            .exclude(status="submitted")
            .select_related("user", "reviewed_by")
            .order_by("-reviewed_at")[: self.RECENT_LIMIT]
        )
        reviewed_list = [
            {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "user": {
                    "id": project.user.id,
                    "username": project.user.username,
                },
                "reviewed_by": project.reviewed_by.username,
                "reviewed_at": (
                    project.reviewed_at.isoformat() if project.reviewed_at else None
                ),
                "self_reviewed": project.reviewed_by_id == project.user_id,
                "outcome": "rejected" if project.status == "draft" else "approved",
                "connection": _connection_info(project),
            }
            for project in reviewed
        ]

        return JsonResponse(
            {"status": "success", "projects": project_list, "reviewed": reviewed_list}
        )


class ApproveRejectProjectView(BuilderRequiredMixin, View):
    """Approve or reject a submitted project."""

    def post(self, request, pk, *args, **kwargs):
        project = get_object_or_404(BuildProject, pk=pk)

        # Determine action from URL path
        path = request.path
        is_approve = "/approve/" in path
        is_reject = "/reject/" in path

        if not is_approve and not is_reject:
            return JsonResponse(
                {"status": "error", "error": "Invalid action"}, status=400
            )

        # Builders never review their own work; Admins and above may.
        if not project.can_be_reviewed_by(request.user):
            return JsonResponse(
                {
                    "status": "error",
                    "error": "You cannot review your own project. Ask another staff member.",
                },
                status=403,
            )

        # Check project is in submitted status
        if project.status != "submitted":
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"Project is not in submitted status (current: {project.status})",
                },
                status=400,
            )

        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "error": "Invalid JSON"}, status=400
            )
        if not isinstance(data, dict):
            return JsonResponse(
                {"status": "error", "error": "Expected a JSON object"}, status=400
            )

        # The version the reviewer looked at; the review only lands if the
        # project is still submitted at that version.
        version = data.get("version")
        if type(version) is not int:
            return JsonResponse(
                {"status": "error", "error": "version is required"}, status=400
            )

        if is_approve:
            # Approve the project
            try:
                project.approve(request.user, version)
                return JsonResponse(
                    {
                        "status": "success",
                        "message": "Project approved",
                        "project": {
                            "id": project.id,
                            "name": project.name,
                            "status": project.status,
                            "reviewed_by": request.user.username,
                            "reviewed_at": project.reviewed_at.isoformat(),
                        },
                    }
                )
            except PermissionError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=403)
            except StaleReviewError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=409)
            except ValueError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=400)

        else:  # is_reject
            notes = data.get("notes", "")
            notes = notes.strip() if isinstance(notes, str) else ""
            if not notes:
                return JsonResponse(
                    {"status": "error", "error": "Rejection notes are required"},
                    status=400,
                )

            # Reject the project
            try:
                project.reject(request.user, notes, version)
                return JsonResponse(
                    {
                        "status": "success",
                        "message": "Project rejected with feedback",
                        "project": {
                            "id": project.id,
                            "name": project.name,
                            "status": project.status,
                            "rejection_count": project.rejection_count,
                        },
                    }
                )
            except PermissionError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=403)
            except StaleReviewError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=409)
            except ValueError as e:
                return JsonResponse({"status": "error", "error": str(e)}, status=400)


class BuildReviewDashboardView(BuilderRequiredMixin, TemplateView):
    """Staff review page template view."""

    template_name = "builder/review.html"


class BuildSandboxView(BuilderRequiredMixin, View):
    """Build approved project to sandbox."""

    def post(self, request, pk, *args, **kwargs):
        project = get_object_or_404(BuildProject, pk=pk)

        if not can_manage(request.user, project):
            return JsonResponse(
                {"status": "error", "error": "Not authorized"}, status=403
            )

        # Check project is approved
        if project.status != "approved":
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"Project must be approved (current: {project.status})",
                },
                status=400,
            )

        # Check if already built
        if project.sandbox_room_id:
            return JsonResponse(
                {
                    "status": "error",
                    "error": "Sandbox already exists",
                    "sandbox_id": project.sandbox_room_id,
                },
                status=400,
            )

        # Trigger sandbox creation
        success, result = create_sandbox_from_project(pk)

        if success:
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Sandbox created successfully",
                    "sandbox_id": result["sandbox_room_id"],
                    "room_count": result["room_count"],
                    "exit_count": result["exit_count"],
                    "project": {
                        "id": project.id,
                        "name": project.name,
                        "status": project.status,
                    },
                }
            )
        else:
            return JsonResponse(
                {"status": "error", "error": result.get("error", "Unknown error")},
                status=500,
            )


class CleanupSandboxView(BuilderRequiredMixin, View):
    """
    Delete a project's sandbox (owner or Admin). Acts only on the object ids
    recorded at build time (sandbox_cleanup.cleanup_unit); the project
    record stays and returns to 'approved'.
    """

    def post(self, request, pk, *args, **kwargs):
        from .sandbox_cleanup import cleanup_sandbox_for_project

        project = get_object_or_404(BuildProject, pk=pk)

        if not can_manage(request.user, project):
            return JsonResponse({"status": "error", "error": "Not authorized"}, status=403)

        if project.status != "built" or not project.built_object_ids:
            return JsonResponse({"status": "error", "error": "No active sandbox"}, status=400)

        success, result = cleanup_sandbox_for_project(pk)

        if success:
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Sandbox cleaned up",
                    "deleted": {
                        "rooms": result["deleted_rooms"],
                        "exits": result["deleted_exits"],
                        "objects": result["deleted_objects"],
                    },
                }
            )
        return JsonResponse({"status": "error", "error": result.get("error", "Unknown")}, status=409)


class ListConnectionRoomsView(BuilderRequiredMixin, View):
    """List rooms available for connection during promotion."""

    def get(self, request, *args, **kwargs):
        """
        Return list of live world rooms (non-sandbox) that can be used as connection points.

        For now, returns all non-sandbox rooms. Future enhancement could filter by
        ownership or builder permissions.
        """
        # Same rule as validate_connection: Room family, not sandbox-tagged.
        # (search_object("") matches on an empty key and returns nothing.)
        connection_rooms = []
        for room in live_rooms():
            connection_rooms.append(
                {
                    "id": room.id,
                    "name": room.name,
                    "key": room.key,
                    "description": room.db.desc or "",
                }
            )

        # Sort by name for consistent ordering
        connection_rooms.sort(key=lambda r: r["name"].lower())

        return JsonResponse(
            {
                "status": "success",
                "rooms": connection_rooms,
            }
        )


class PromoteProjectView(BuilderRequiredMixin, View):
    """Promote a built project from sandbox to live world."""

    def post(self, request, pk, *args, **kwargs):
        """
        Promote a built project to live world.

        Request body (optional): {
            "connection_room_id": int,
            "connection_direction": string (n/s/e/w/ne/nw/se/sw/u/d)
        }
        The connection is the one reviewed at approval (approved_map_data).
        A body that names a different one is refused with 409.
        """
        project = get_object_or_404(BuildProject, pk=pk)

        # Only the owner or an Admin can promote
        if not can_manage(request.user, project):
            return JsonResponse(
                {"status": "error", "error": "Not authorized"}, status=403
            )

        # Check project is in built status
        if project.status != "built":
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"Project must be in 'built' status (current: {project.status})",
                },
                status=400,
            )

        # Parse request body
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse(
                {"status": "error", "error": "Invalid JSON"}, status=400
            )

        if not isinstance(data, dict):
            return JsonResponse({"status": "error", "error": "Expected a JSON object"}, status=400)

        # Promotion uses the reviewed connection; a request may restate it
        # (and is refused if it differs) but can't choose another.
        success, result = promote_project_to_live(
            project.id, data.get("connection_room_id"), data.get("connection_direction")
        )

        if success:
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Project promoted to live world successfully",
                    "promoted_rooms": result.get("promoted_rooms", 0),
                    "created_exits": result.get("created_exits", []),
                    "entry_room_id": result.get("entry_room_id"),
                    "project": {
                        "id": project.id,
                        "name": project.name,
                        "status": "live",
                    },
                }
            )
        return JsonResponse(
            {"status": "error", "error": result.get("error", "Unknown error")},
            status=result.get("status", 500),
        )


class RoomTriggersAPI(BuilderRequiredMixin, View):
    """
    API for managing room triggers within a project.

    GET /builder/api/projects/<project_id>/rooms/<room_id>/triggers/
    POST /builder/api/projects/<project_id>/rooms/<room_id>/triggers/
    DELETE /builder/api/projects/<project_id>/rooms/<room_id>/triggers/<trigger_id>/
    """

    def get(self, request, project_id, room_id):
        """Get all triggers for a room."""
        try:
            project = BuildProject.objects.get(id=project_id, user=request.user)
            map_data = project.map_data or {}
            rooms = map_data.get("rooms", {})

            if room_id not in rooms:
                return JsonResponse({"error": "Room not found"}, status=404)

            room_data = rooms[room_id]
            triggers = room_data.get("triggers", [])

            return JsonResponse({"triggers": triggers})
        except BuildProject.DoesNotExist:
            return JsonResponse({"error": "Project not found"}, status=404)

    @staticmethod
    def _save_map(project, map_data):
        """Write map_data only if the project is still a draft at the version
        we read; otherwise return a 409 response."""
        updated = BuildProject.objects.filter(
            pk=project.pk, status="draft", version=project.version
        ).update(
            map_data=map_data,
            version=F("version") + 1,
            updated_at=timezone.now(),
        )
        if updated:
            return None
        project.refresh_from_db()
        if not project.is_editable():
            return _locked_response(project)
        return JsonResponse(
            {"error": "Project was modified by another session. Reload and try again."},
            status=409,
        )

    def post(self, request, project_id, room_id):
        """Add or update a trigger for a room."""
        try:
            project = BuildProject.objects.get(id=project_id, user=request.user)
            if not project.is_editable():
                return _locked_response(project)
            map_data = project.map_data or {}
            rooms = map_data.get("rooms", {})

            if room_id not in rooms:
                return JsonResponse({"error": "Room not found"}, status=404)

            # Parse trigger data
            try:
                trigger_data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON"}, status=400)

            # Validate trigger
            is_valid, error = validate_trigger(trigger_data)
            if not is_valid:
                return JsonResponse({"error": error}, status=400)

            # Get existing triggers
            room_data = rooms[room_id]
            triggers = room_data.get("triggers", [])

            # Check for duplicate ID (update) or add new
            trigger_id = trigger_data.get("id")
            existing_idx = None
            for i, t in enumerate(triggers):
                if t.get("id") == trigger_id:
                    existing_idx = i
                    break

            if existing_idx is not None:
                triggers[existing_idx] = trigger_data
            else:
                triggers.append(trigger_data)

            # Save back to room
            room_data["triggers"] = triggers
            rooms[room_id] = room_data
            map_data["rooms"] = rooms
            conflict = self._save_map(project, map_data)
            if conflict:
                return conflict

            return JsonResponse({"success": True, "trigger": trigger_data})

        except BuildProject.DoesNotExist:
            return JsonResponse({"error": "Project not found"}, status=404)

    def delete(self, request, project_id, room_id, trigger_id=None):
        """Delete a trigger from a room."""
        if not trigger_id:
            return JsonResponse({"error": "trigger_id required"}, status=400)

        try:
            project = BuildProject.objects.get(id=project_id, user=request.user)
            if not project.is_editable():
                return _locked_response(project)
            map_data = project.map_data or {}
            rooms = map_data.get("rooms", {})

            if room_id not in rooms:
                return JsonResponse({"error": "Room not found"}, status=404)

            room_data = rooms[room_id]
            triggers = room_data.get("triggers", [])

            # Find and remove trigger
            new_triggers = [t for t in triggers if t.get("id") != trigger_id]

            if len(new_triggers) == len(triggers):
                return JsonResponse({"error": "Trigger not found"}, status=404)

            # Save back
            room_data["triggers"] = new_triggers
            rooms[room_id] = room_data
            map_data["rooms"] = rooms
            conflict = self._save_map(project, map_data)
            if conflict:
                return conflict

            return JsonResponse({"success": True})

        except BuildProject.DoesNotExist:
            return JsonResponse({"error": "Project not found"}, status=404)


class TriggerActionsAPI(BuilderRequiredMixin, View):
    """
    API to get available trigger actions and conditions.

    GET /builder/api/trigger-metadata/
    """

    def get(self, request):
        """Return available actions and condition types."""
        # Build action metadata for UI
        action_metadata = {}
        for key in list_actions():
            action_metadata[key] = {
                "name": key.replace("_", " ").title(),
                "description": self._get_action_description(key),
            }

        return JsonResponse(
            {"actions": action_metadata, "conditions": list_condition_types()}
        )

    def _get_action_description(self, action_name):
        """Get human-readable description for action."""
        descriptions = {
            "send_message": "Send a message to the triggering character",
            "emit_message": "Emit a message to everyone in the room",
            "set_attribute": "Set an attribute on the room or character",
        }
        return descriptions.get(action_name, action_name.replace("_", " ").title())
