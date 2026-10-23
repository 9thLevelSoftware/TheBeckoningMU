from django.urls import path

from . import api

urlpatterns = [
    path("player/chronicle/", api.PublicChronicleAPIView.as_view(), name="player_public_chronicle"),
    path("player/chronicle/mine/", api.MyChronicleAPIView.as_view(), name="player_my_chronicle"),
    path(
        "player/characters/<int:character_id>/summary/",
        api.CharacterSummaryAPIView.as_view(),
        name="player_character_summary",
    ),
    path(
        "player/characters/<int:character_id>/chronicle/",
        api.CharacterChronicleAPIView.as_view(),
        name="player_character_chronicle",
    ),
]
