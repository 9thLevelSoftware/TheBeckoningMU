"""
URL configuration for traits API endpoints.
"""

from django.urls import path

from .api import (
    CharacterApprovalAPI,
    CharacterCreateAPI,
    CharacterDetailAPI,
    CharacterEditDataAPI,
    CharacterExportAPI,
    CharacterResubmitAPI,
    CharacterValidationAPI,
    ChargenRulesAPI,
    DisciplinePowersAPI,
    MyCharactersAPI,
    PendingCharactersAPI,
    TraitCategoriesAPI,
    TraitsAPI,
)

app_name = "traits"

urlpatterns = [
    # Trait data endpoints
    path("categories/", TraitCategoriesAPI.as_view(), name="categories"),
    path("", TraitsAPI.as_view(), name="list"),
    path("rules/", ChargenRulesAPI.as_view(), name="rules"),
    path("discipline-powers/", DisciplinePowersAPI.as_view(), name="discipline_powers"),
    # Character management endpoints
    path("character/validate/", CharacterValidationAPI.as_view(), name="character_validate"),
    path("character/create/", CharacterCreateAPI.as_view(), name="character_create"),
    path("character/<int:character_id>/export/", CharacterExportAPI.as_view(), name="character_export"),
    # Character approval endpoints
    path("pending-characters/", PendingCharactersAPI.as_view(), name="pending_characters"),
    path("character/<int:character_id>/detail/", CharacterDetailAPI.as_view(), name="character_detail"),
    path("character/<int:character_id>/approval/", CharacterApprovalAPI.as_view(), name="character_approval"),
    # Player character management endpoints
    path("my-characters/", MyCharactersAPI.as_view(), name="my_characters"),
    path("character/<int:character_id>/for-edit/", CharacterEditDataAPI.as_view(), name="character_for_edit"),
    path("character/<int:character_id>/resubmit/", CharacterResubmitAPI.as_view(), name="character_resubmit"),
]
