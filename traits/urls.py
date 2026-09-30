"""
URL configuration for traits API endpoints.
"""

from django.urls import path
from .api import (
    TraitCategoriesAPI,
    TraitsAPI,
    DisciplinePowersAPI,
    CharacterValidationAPI,
    CharacterImportAPI,
    CharacterExportAPI,
    CharacterAvailableTraitsAPI,
    CharacterCreateAPI,
    PendingCharactersAPI,
    CharacterDetailAPI,
    CharacterApprovalAPI,
    MyCharactersAPI,
    CharacterEditDataAPI,
    CharacterResubmitAPI,
)

app_name = 'traits'

urlpatterns = [
    # Trait data endpoints
    path('categories/', TraitCategoriesAPI.as_view(), name='categories'),
    path('', TraitsAPI.as_view(), name='list'),
    path('discipline-powers/', DisciplinePowersAPI.as_view(), name='discipline_powers'),

    # Character management endpoints
    path('character/validate/', CharacterValidationAPI.as_view(), name='character_validate'),
    path('character/create/', CharacterCreateAPI.as_view(), name='character_create'),
    path('character/import/', CharacterImportAPI.as_view(), name='character_import'),
    path('character/<int:character_id>/export/', CharacterExportAPI.as_view(), name='character_export'),
    path('character/<int:character_id>/available-traits/', CharacterAvailableTraitsAPI.as_view(), name='character_available_traits'),

    # Character approval endpoints
    path('pending-characters/', PendingCharactersAPI.as_view(), name='pending_characters'),
    path('character/<int:character_id>/detail/', CharacterDetailAPI.as_view(), name='character_detail'),
    path('character/<int:character_id>/approval/', CharacterApprovalAPI.as_view(), name='character_approval'),

    # Player character management endpoints
    path('my-characters/', MyCharactersAPI.as_view(), name='my_characters'),
    path('character/<int:character_id>/for-edit/', CharacterEditDataAPI.as_view(), name='character_for_edit'),
    path('character/<int:character_id>/resubmit/', CharacterResubmitAPI.as_view(), name='character_resubmit'),
]
