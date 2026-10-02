"""
Web views for the website application.
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from django.views.generic import RedirectView, TemplateView

from web.permissions import has_perm


class HomepageView(TemplateView):
    """
    Public landing page for TheBeckoningMU.
    """

    template_name = "website/index.html"


@method_decorator(login_required, name="dispatch")
class CharacterApprovalView(TemplateView):
    """
    Staff interface for reviewing and approving/rejecting character applications.
    Needs the in-game Builder permission (Django's is_staff grants nothing).
    """

    template_name = "character_approval.html"

    def dispatch(self, request, *args, **kwargs):
        if not has_perm(request.user, "Builder"):
            raise PermissionDenied("Builder permission required")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Character Approval System"
        context["can_revoke"] = has_perm(self.request.user, "Admin")
        return context


@method_decorator(login_required, name="dispatch")
class CharacterCreationView(TemplateView):
    """
    Player interface for creating new character applications.
    """

    template_name = "character_creation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Character"
        edit_id = self.request.GET.get("edit")
        if edit_id and edit_id.isdigit():
            context["edit_character_id"] = int(edit_id)
        return context


class ChargenRedirectView(RedirectView):
    """
    Replaces Evennia's stock character create/update pages, which would make
    or rename a character without the V5 rules, the name rules or an
    application. Every method (GET and POST alike) just redirects to the
    website's character creation form.
    """

    pattern_name = "character_creation"
    permanent = False
    query_string = False

    def get_redirect_url(self, *args, **kwargs):
        return super().get_redirect_url()
