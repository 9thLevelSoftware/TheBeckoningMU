from django.urls import path

from . import views

app_name = "builder"

urlpatterns = [
    # Dashboard
    path("", views.BuilderDashboardView.as_view(), name="dashboard"),
    # Editor
    path("edit/", views.BuilderEditorView.as_view(), name="create_project"),
    path("edit/<int:pk>/", views.BuilderEditorView.as_view(), name="edit_project"),
    # API endpoints
    path("api/save/", views.SaveProjectView.as_view(), name="save_project"),
    path("api/project/<int:pk>/", views.GetProjectView.as_view(), name="get_project"),
    path(
        "api/project/<int:pk>/delete/",
        views.DeleteProjectView.as_view(),
        name="delete_project",
    ),
    path(
        "api/project/<int:pk>/submit/",
        views.SubmitProjectView.as_view(),
        name="submit_project",
    ),
    path(
        "api/build/<int:pk>/build-sandbox/",
        views.BuildSandboxView.as_view(),
        name="build_sandbox",
    ),
    # Cleanup deletes only the object ids recorded at build time.
    path(
        "api/build/<int:pk>/cleanup/",
        views.CleanupSandboxView.as_view(),
        name="cleanup_sandbox",
    ),
    path("api/prototypes/", views.PrototypesView.as_view(), name="prototypes"),
    path("api/templates/", views.TemplatesView.as_view(), name="templates"),
    # Review endpoints (staff only)
    path("review/", views.BuildReviewDashboardView.as_view(), name="build_review"),
    path("api/review/projects/", views.BuildReviewView.as_view(), name="review_projects"),
    path(
        "api/review/<int:pk>/approve/",
        views.ApproveRejectProjectView.as_view(),
        name="approve_project",
    ),
    path(
        "api/review/<int:pk>/reject/",
        views.ApproveRejectProjectView.as_view(),
        name="reject_project",
    ),
    # Promotion endpoints
    path(
        "api/connection-rooms/",
        views.ListConnectionRoomsView.as_view(),
        name="connection_rooms",
    ),
    path(
        "api/build/<int:pk>/promote/",
        views.PromoteProjectView.as_view(),
        name="promote_project",
    ),
    # Trigger endpoints
    path(
        "api/trigger-metadata/",
        views.TriggerActionsAPI.as_view(),
        name="trigger_metadata",
    ),
    path(
        "api/projects/<int:project_id>/rooms/<str:room_id>/triggers/",
        views.RoomTriggersAPI.as_view(),
        name="room_triggers",
    ),
    path(
        "api/projects/<int:project_id>/rooms/<str:room_id>/triggers/<str:trigger_id>/",
        views.RoomTriggersAPI.as_view(),
        name="room_trigger_detail",
    ),
]
