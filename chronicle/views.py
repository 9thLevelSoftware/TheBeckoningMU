import json
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from narrative.models import MemoryFact
from narrative.services import configured_provider

from .generation import MAX_SOURCES, request_draft
from .models import ChronicleEvent, ChronicleGenerationRequest
from .read_services import account_chronicle
from .services import (
    correct_event,
    public_events,
    publish_event,
    record_event,
    redact_event,
    staff_authorized,
    staff_events,
)


class PublicChronicleView(TemplateView):
    template_name = "chronicle/public.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["events"] = public_events()[:100]
        context["can_manage_stories"] = staff_authorized(self.request.user)
        return context


@method_decorator(login_required, name="dispatch")
class MyChronicleView(TemplateView):
    template_name = "chronicle/mine.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["events"] = account_chronicle(self.request.user)
        context["can_manage_stories"] = staff_authorized(self.request.user)
        return context


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class NarrativeOpsView(TemplateView):
    template_name = "chronicle/staff_ops.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = staff_events(self.request.user)
        context["draft_memory_facts"] = MemoryFact.objects.filter(status=MemoryFact.Status.DRAFT).select_related(
            "persona__character", "subject", "source_event"
        )[:100]
        context["recent_memory_facts"] = MemoryFact.objects.select_related(
            "persona__character", "subject", "source_event"
        ).order_by("-created_at")[:100]
        context["recent_events"] = [
            {"event": event, "payload_json": json.dumps(event.payload, ensure_ascii=False)} for event in events[:100]
        ]
        context["draft_events"] = events.filter(status=ChronicleEvent.Status.DRAFT).prefetch_related("source_events")[
            :100
        ]
        context["generation_enabled"] = configured_provider() is not None
        context["generation_sources"] = public_events()[:100]
        context["generation_requests"] = ChronicleGenerationRequest.objects.select_related(
            "draft_event", "requested_by"
        ).order_by("-id")[:50]
        context["generation_request_key"] = str(uuid4())
        context["generation_max_sources"] = MAX_SOURCES
        source_id = self.request.GET.get("source", "")
        if source_id.isascii() and source_id.isdigit():
            context["selected_source"] = events.filter(pk=source_id).first()
        return context

    def post(self, request, *args, **kwargs):
        title = request.POST.get("title", "").strip()
        summary = request.POST.get("summary", "").strip()
        if not title:
            messages.error(request, "A title is required for a curated Chronicle entry.")
            return HttpResponseRedirect(reverse("narrative_ops"))
        event_id = uuid4()
        record_event(
            idempotency_key=f"staff:scene.curated:{event_id}",
            source_app="chronicle",
            source_type="StaffScene",
            source_id=str(event_id),
            kind="scene.curated",
            title=title,
            summary=summary,
            payload={},
            visibility=ChronicleEvent.Visibility.PUBLIC,
            actor=request.user,
        )
        messages.success(request, "Curated scene saved as an unpublished draft.")
        return HttpResponseRedirect(reverse("narrative_ops"))


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class StaffEventActionView(View):
    http_method_names = ["post"]

    def post(self, request, event_id, action):
        try:
            if action == "publish":
                publish_event(event_id, request.user)
            elif action == "redact":
                redact_event(event_id, request.user)
            elif action == "correct":
                title = request.POST.get("title", "").strip()
                if not title:
                    raise ValueError("A title is required for a correction.")
                payload = json.loads(request.POST.get("payload", "{}"))
                if not isinstance(payload, dict):
                    raise ValueError("Correction payload must be a JSON object.")
                correct_event(
                    event_id,
                    request.user,
                    title=title,
                    summary=request.POST.get("summary", "").strip(),
                    payload=payload,
                )
            else:
                raise Http404
        except ChronicleEvent.DoesNotExist as error:
            raise Http404 from error
        except (ValueError, PermissionError) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Chronicle event {action} action completed.")
        return HttpResponseRedirect(reverse("narrative_ops"))


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class StaffGenerationRequestView(View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            draft_request = request_draft(
                request.user,
                request.POST.getlist("source_ids"),
                request.POST.get("mode", ""),
                request_key=request.POST.get("request_key"),
            )
        except (ValueError, PermissionError, RuntimeError) as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                f"Chronicle drafting request #{draft_request.pk} is {draft_request.status}. Publication requires staff review.",
            )
        return HttpResponseRedirect(reverse("narrative_ops"))


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class StaffMemoryFactActionView(View):
    http_method_names = ["post"]

    def post(self, request, memory_id, action):
        try:
            fact = MemoryFact.objects.get(pk=memory_id)
            if action == "approve":
                if fact.status != MemoryFact.Status.DRAFT:
                    raise ValueError("Only draft memory facts can be approved.")
                fact.status = MemoryFact.Status.APPROVED
                fact.approved_at = timezone.now()
                fact.save(update_fields=("status", "approved_at"))
            elif action == "redact":
                if fact.status == MemoryFact.Status.REDACTED:
                    raise ValueError("This memory fact is already redacted.")
                fact.status = MemoryFact.Status.REDACTED
                fact.text = ""
                fact.staff_entry = "" if fact.source_event_id else "[redacted staff entry]"
                fact.save(update_fields=("status", "text", "staff_entry"))
            else:
                raise Http404
        except MemoryFact.DoesNotExist as error:
            raise Http404 from error
        except ValueError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Memory fact {action} action completed.")
        return HttpResponseRedirect(reverse("narrative_ops"))
