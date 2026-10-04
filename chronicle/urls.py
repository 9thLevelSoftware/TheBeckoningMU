from django.urls import path

from . import views

urlpatterns = [
    path("chronicle/", views.PublicChronicleView.as_view(), name="chronicle_public"),
    path("chronicle/mine/", views.MyChronicleView.as_view(), name="chronicle_mine"),
    path("staff/narrative-ops/", views.NarrativeOpsView.as_view(), name="narrative_ops"),
    path(
        "staff/narrative-ops/events/<int:event_id>/<str:action>/",
        views.StaffEventActionView.as_view(),
        name="narrative_ops_action",
    ),
    path(
        "staff/narrative-ops/memories/<int:memory_id>/<str:action>/",
        views.StaffMemoryFactActionView.as_view(),
        name="narrative_ops_memory_action",
    ),
]
