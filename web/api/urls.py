"""
API URL routing configuration.
Routes API calls to the traits app endpoints.
"""
from django.urls import path, include

urlpatterns = [
    path('traits/', include('traits.urls')),
    path('', include('chronicle.api_urls')),
]
