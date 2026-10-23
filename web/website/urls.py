"""
This reroutes from an URL to a python view-function/class.

The main web/urls.py includes these routes for all urls (the root of the url)
so it can reroute to all website pages.

"""

from django.urls import path
from evennia.web.website.urls import urlpatterns as evennia_website_urlpatterns

from .views import CharacterApprovalView, CharacterCreationView, ChargenRedirectView, HomepageView

# add patterns here
urlpatterns = [
    path("", HomepageView.as_view(), name="homepage"),
    path("staff/character-approval/", CharacterApprovalView.as_view(), name="character_approval"),
    path("character-creation/", CharacterCreationView.as_view(), name="character_creation"),
    # Evennia's stock character create/update views bypass the V5 rules, the
    # name rules and approval; these must come before evennia_website_urlpatterns.
    path("characters/create/", ChargenRedirectView.as_view(), name="character-create"),
    path("characters/update/<str:slug>/<int:pk>/", ChargenRedirectView.as_view(), name="character-update"),
]

# read by Django
urlpatterns = urlpatterns + evennia_website_urlpatterns
