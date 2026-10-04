from django.http import JsonResponse
from django.views import View

from .read_services import (
    account_chronicle,
    character_chronicle_for_account,
    character_summary_for_account,
    public_chronicle,
)


class PlayerReadOnlyAPIView(View):
    http_method_names = ["get", "head", "options"]

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication_required"}, status=401)
        return super().dispatch(request, *args, **kwargs)


def serialize_event(event):
    return {
        "id": event.pk,
        "kind": event.kind,
        "title": event.title,
        "summary": event.summary,
        "occurred_at": event.occurred_at.isoformat(),
        "ai_generated": event.ai_generated,
        "payload": event.payload,
    }


class PublicChronicleAPIView(PlayerReadOnlyAPIView):
    def get(self, request):
        return JsonResponse({"events": [serialize_event(event) for event in public_chronicle()]})


class MyChronicleAPIView(PlayerReadOnlyAPIView):
    def get(self, request):
        return JsonResponse({"events": [serialize_event(event) for event in account_chronicle(request.user)]})


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
        return JsonResponse({"events": [serialize_event(event) for event in events]})
