from django.http import JsonResponse
from django.views import View

from .read_services import (
    account_chronicle,
    character_chronicle_for_account,
    character_summary_for_account,
    public_chronicle,
)
from .services import event_projection


class PlayerReadOnlyAPIView(View):
    http_method_names = ["get", "head", "options"]

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication_required"}, status=401)
        return super().dispatch(request, *args, **kwargs)


def serialize_event(event, audience="public", account=None, *, character_id=None):
    return event_projection(event, audience, account, character_id=character_id)


def _project(events, audience="public", account=None, *, character_id=None):
    return [
        record
        for event in events
        if (record := serialize_event(event, audience, account, character_id=character_id)) is not None
    ]


class PublicChronicleAPIView(PlayerReadOnlyAPIView):
    def get(self, request):
        return JsonResponse({"events": _project(public_chronicle())})


class MyChronicleAPIView(PlayerReadOnlyAPIView):
    def get(self, request):
        return JsonResponse({"events": _project(account_chronicle(request.user), "account", request.user)})


class CharacterSummaryAPIView(PlayerReadOnlyAPIView):
    def get(self, request, character_id):
        summary = character_summary_for_account(request.user, character_id)
        if summary is None:
            return JsonResponse({"error": "character_not_found"}, status=404)
        return JsonResponse({"character": summary})


class CharacterChronicleAPIView(PlayerReadOnlyAPIView):
    def get(self, request, character_id):
        events = character_chronicle_for_account(request.user, character_id)
        if events is None:
            return JsonResponse({"error": "character_not_found"}, status=404)
        return JsonResponse({"events": _project(events, "participants", request.user, character_id=character_id)})
