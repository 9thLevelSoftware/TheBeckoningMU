from django.urls import path

from . import views

urlpatterns = [
    path("chronicle/", views.PublicChronicleView.as_view(), name="chronicle_public"),
    path("chronicle/mine/", views.MyChronicleView.as_view(), name="chronicle_mine"),
    path("staff/narrative-ops/", views.NarrativeOpsView.as_view(), name="narrative_ops"),
    path("staff/narrative-ops/personas/", views.PersonaCurationView.as_view(), name="narrative_ops_personas"),
    path(
        "staff/narrative-ops/personas/<int:persona_id>/",
        views.PersonaProfileView.as_view(),
        name="narrative_ops_persona_edit",
    ),
    path("staff/narrative-ops/memories/", views.MemoryCurationView.as_view(), name="narrative_ops_memories"),
    path(
        "staff/narrative-ops/memories/<int:memory_id>/",
        views.MemoryRevisionView.as_view(),
        name="narrative_ops_memory_edit",
    ),
    path("staff/narrative-ops/generate/", views.StaffGenerationRequestView.as_view(), name="narrative_ops_generate"),
    path(
        "staff/narrative-ops/events/<int:event_id>/<str:action>/",
        views.StaffEventActionView.as_view(),
        name="narrative_ops_action",
    ),
    path(
        "staff/narrative-ops/corrections/<int:draft_id>/<str:action>/",
        views.StaffCorrectionActionView.as_view(),
        name="narrative_ops_correction_action",
    ),
    path(
        "staff/narrative-ops/memories/<int:memory_id>/<str:action>/",
        views.StaffMemoryFactActionView.as_view(),
        name="narrative_ops_memory_action",
    ),
]
