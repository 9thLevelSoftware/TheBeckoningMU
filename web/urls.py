"""
This is the starting point when a user enters a url in their web browser.

The urls is matched (by regex) and mapped to a 'view' - a Python function or
callable class that in turn (usually) makes use of a 'template' (a html file
with slots that can be replaced by dynamic content) in order to render a HTML
page to show the user.

This file includes the urls in website, webclient and admin. To override you
should modify urls.py in those sub directories.

Search the Django documentation for "URL dispatcher" for more help.

"""

from django.urls import include, path

# default evennia patterns
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns
from oauth2_provider.urls import metadata_urlpatterns

# add patterns
urlpatterns = [
    # Root RFC 8414/RFC 9728 discovery; OAuth endpoints are mounted under /o/.
    path("", include((metadata_urlpatterns, "oauth2_provider"), namespace="oauth2_metadata")),
    # Keep DOT application management staff-only; token and discovery endpoints remain available.
    path("o/applications/", include("web.oauth", namespace="staff_oauth_apps")),
    path("o/", include("oauth2_provider.urls")),
    # Chronicle public and staff pages
    path("", include("chronicle.urls")),
    # website
    path("", include("web.website.urls")),
    # webclient
    path("webclient/", include("web.webclient.urls")),
    # web admin
    path("admin/", include("web.admin.urls")),
    # API routing
    path("api/", include("web.api.urls")),
    # Web Builder
    path("builder/", include("web.builder.urls", namespace="builder")),
    # add any extra urls here:
    # path("mypath/", include("path.to.my.urls.file")),
]

# 'urlpatterns' must be named such for Django to find it.
urlpatterns = urlpatterns + evennia_default_urlpatterns
