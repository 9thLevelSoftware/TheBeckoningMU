import json
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView
from evennia.objects.models import ObjectDB

from narrative.curation import (
    CurationConflictError,
    approve_memory_fact,
    create_memory_fact,
    memory_source_available,
    redact_memory_fact,
    register_persona,
    revise_memory_fact,
    update_persona,
)
from narrative.forms import MemoryCurationForm, MemoryRevisionForm, PersonaProfileForm, PersonaRegistrationForm
from narrative.models import MemoryFact, NarrativePersona
from narrative.services import configured_provider

from .generation import MAX_SOURCES, request_draft
from .models import ChronicleEvent, ChronicleGenerationRequest
from .read_services import account_chronicle
from .services import (
    ModerationConflictError,
    begin_correction,
    correct_event,
    discard_correction,
    public_events,
    publish_event,
    record_event,
    redact_event,
    revise_correction,
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
        events = (
            staff_events(self.request.user).select_related("supersedes", "revision_of").prefetch_related("corrections")
        )
        context["draft_memory_facts"] = MemoryFact.objects.filter(status=MemoryFact.Status.DRAFT).select_related(
            "persona__character", "subject", "source_event"
        )[:100]
        context["recent_memory_facts"] = MemoryFact.objects.select_related(
            "persona__character", "subject", "source_event"
        ).order_by("-created_at")[:100]
        context["recent_events"] = [
            {
                "event": event,
                "payload_json": json.dumps(event.payload, ensure_ascii=False),
                "active_correction": next(
                    (draft for draft in event.corrections.all() if draft.status == ChronicleEvent.Status.DRAFT), None
                ),
            }
            for event in events[:100]
        ]
        context["draft_events"] = events.filter(status=ChronicleEvent.Status.DRAFT).prefetch_related("source_events")[
            :100
        ]
        context["withdrawn_events"] = events.filter(status=ChronicleEvent.Status.WITHDRAWN).select_related(
            "withdrawn_by"
        )[:100]
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
            if context["selected_source"]:
                context["selected_source_active_correction"] = (
                    context["selected_source"].corrections.filter(status=ChronicleEvent.Status.DRAFT).first()
                )
        draft_id = self.request.GET.get("draft", "")
        if draft_id.isascii() and draft_id.isdigit():
            selected = events.filter(pk=draft_id, supersedes__isnull=False).first()
            if selected:
                context["selected_correction"] = selected
                context["selected_correction_payload_json"] = json.dumps(selected.payload, ensure_ascii=False)
        selected = context.get("selected_correction")
        original = selected.supersedes if selected else context.get("selected_source")
        if original:
            context["correction_original"] = original
            context["correction_history"] = original.corrections.select_related(
                "revision_of", "discarded_by", "published_by"
            ).order_by("created_at", "pk")
            context["active_correction"] = original.corrections.filter(status=ChronicleEvent.Status.DRAFT).first()
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
                publish_event(event_id, request.user, expected_version=_posted_version(request, default=1))
            elif action == "redact":
                redact_event(event_id, request.user, expected_version=_posted_version(request))
            elif action == "begin-correction":
                draft = begin_correction(event_id, request.user)
                messages.success(request, f"Correction draft #{draft.pk} is ready to resume and review.")
                return _correction_review(draft)
            elif action == "correct":
                title = request.POST.get("title", "").strip()
                if not title:
                    raise ValueError("A title is required for a correction.")
                payload = json.loads(request.POST.get("payload", "{}"))
                if not isinstance(payload, dict):
                    raise ValueError("Correction payload must be a JSON object.")
                draft = correct_event(
                    event_id,
                    request.user,
                    title=title,
                    summary=request.POST.get("summary", "").strip(),
                    payload=payload,
                )
                messages.success(request, f"Correction draft #{draft.pk} is ready to resume and review.")
                return _correction_review(draft)
            else:
                raise Http404
        except ChronicleEvent.DoesNotExist as error:
            raise Http404 from error
        except ModerationConflictError as error:
            return HttpResponse(str(error), status=409, content_type="text/plain")
        except PermissionError as error:
            return HttpResponseForbidden(str(error))
        except ValueError as error:
            return HttpResponse(str(error), status=400, content_type="text/plain")
        else:
            messages.success(request, f"Chronicle event {action} action completed.")
        return HttpResponseRedirect(reverse("narrative_ops"))


def _posted_version(request, *, default=None, required=False):
    raw = request.POST.get("expected_version")
    if raw is None and not required:
        return default
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit() or not 1 <= len(raw) <= 10:
        raise ModerationConflictError()
    version = int(raw)
    if not 1 <= version <= 2147483647:
        raise ModerationConflictError()
    return version


def _correction_review(draft):
    return HttpResponseRedirect(f"{reverse('narrative_ops')}?draft={draft.pk}#correction-editor")


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class StaffCorrectionActionView(View):
    http_method_names = ["post"]

    def post(self, request, draft_id, action):
        try:
            version = _posted_version(request, required=True)
            if action == "revise":
                payload = json.loads(request.POST.get("payload", "{}"))
                if not isinstance(payload, dict):
                    raise ValueError("Correction payload must be a JSON object.")
                draft = revise_correction(
                    draft_id,
                    request.user,
                    version,
                    {
                        "title": request.POST.get("title", "").strip(),
                        "summary": request.POST.get("summary", "").strip(),
                        "payload": payload,
                    },
                )
                messages.success(
                    request,
                    f"Replacement correction draft #{draft.pk} needs fresh review. Prior text is retained in history.",
                )
                return _correction_review(draft)
            if action == "discard":
                draft = discard_correction(draft_id, request.user, version)
                messages.success(request, "Correction draft discarded; its prior text remains in staff history.")
                return HttpResponseRedirect(
                    f"{reverse('narrative_ops')}?source={draft.supersedes_id}#correction-history"
                )
            raise Http404
        except ChronicleEvent.DoesNotExist as error:
            raise Http404 from error
        except ModerationConflictError as error:
            return HttpResponse(str(error), status=409, content_type="text/plain")
        except PermissionError as error:
            return HttpResponseForbidden(str(error))
        except ValueError as error:
            return HttpResponse(str(error), status=400, content_type="text/plain")


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
            version = _posted_version(request, required=True)
            if action == "approve":
                approve_memory_fact(memory_id, request.user, version)
            elif action == "redact":
                redact_memory_fact(memory_id, request.user, version)
            else:
                raise Http404
        except MemoryFact.DoesNotExist as error:
            raise Http404 from error
        except (CurationConflictError, ModerationConflictError) as error:
            return HttpResponse(str(error), status=409, content_type="text/plain")
        except PermissionError as error:
            return HttpResponseForbidden(str(error))
        except ValueError as error:
            return HttpResponse(str(error), status=400, content_type="text/plain")
        else:
            messages.success(request, f"Memory fact {action} action completed.")
        return HttpResponseRedirect(reverse("narrative_ops_memory_edit", args=(memory_id,)))


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class PersonaCurationView(TemplateView):
    template_name = "chronicle/persona_curation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()[:100]
        personas = NarrativePersona.objects.select_related("character", "registered_by", "updated_by").order_by("-pk")
        candidates = ObjectDB.objects.filter(
            db_typeclass_path="typeclasses.characters.Character",
            db_account__isnull=True,
            vtm_bio__isnull=True,
            narrative_persona__isnull=True,
        ).order_by("db_key", "pk")
        if query:
            personas = personas.filter(
                Q(character__db_key__icontains=query)
                | Q(profile__icontains=query)
                | Q(pk=int(query) if query.isascii() and query.isdigit() else None)
            )
            candidates = candidates.filter(
                Q(db_key__icontains=query) | Q(pk=int(query) if query.isascii() and query.isdigit() else None)
            )
        context.update(
            {
                "query": query,
                "personas": Paginator(personas, 20).get_page(self.request.GET.get("page")),
                "candidates": Paginator(candidates.values("id", "db_key"), 20).get_page(
                    self.request.GET.get("npc_page")
                ),
            }
        )
        context.setdefault("form", PersonaRegistrationForm())
        return context

    def post(self, request):
        form = PersonaRegistrationForm(request.POST)
        if form.is_valid():
            try:
                character = ObjectDB.objects.filter(pk=form.cleaned_data["character_id"]).first()
                persona = register_persona(character, request.user, form.cleaned_data["profile"])
            except PermissionError as error:
                return HttpResponseForbidden(str(error))
            except CurationConflictError as error:
                return HttpResponse(str(error), status=409)
            except ValueError as error:
                form.add_error(None, str(error))
            else:
                messages.success(request, "NPC persona registered. Profile changes are versioned.")
                return HttpResponseRedirect(reverse("narrative_ops_persona_edit", args=(persona.pk,)))
        return self.render_to_response(self.get_context_data(form=form), status=400)


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class PersonaProfileView(TemplateView):
    template_name = "chronicle/persona_profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        persona = get_object_or_404(
            NarrativePersona.objects.select_related("character", "registered_by", "updated_by"),
            pk=self.kwargs["persona_id"],
        )
        context["persona"] = persona
        context.setdefault(
            "form", PersonaProfileForm(initial={"profile": persona.profile, "expected_version": persona.version})
        )
        return context

    def post(self, request, persona_id):
        form = PersonaProfileForm(request.POST)
        if form.is_valid():
            try:
                update_persona(persona_id, request.user, **form.cleaned_data)
            except PermissionError as error:
                return HttpResponseForbidden(str(error))
            except CurationConflictError as error:
                return HttpResponse(str(error), status=409)
            except ValueError as error:
                form.add_error(None, str(error))
            else:
                messages.success(request, "Persona profile updated.")
                return HttpResponseRedirect(reverse("narrative_ops_persona_edit", args=(persona_id,)))
        return self.render_to_response(self.get_context_data(form=form), status=400)


def _memory_review_row(fact, actor):
    note = ""
    effective = fact.status
    if fact.status in ("draft", "approved"):
        if fact.expires_at and fact.expires_at <= timezone.now():
            note, effective = "expired", "withdrawn"
        elif not memory_source_available(fact, actor):
            note, effective = "source unavailable", "withdrawn"
    return {"fact": fact, "effective_status": effective, "eligibility_note": note}


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class MemoryCurationView(TemplateView):
    template_name = "chronicle/memory_curation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()[:100]
        status = self.request.GET.get("status", "")
        persona_filter = self.request.GET.get("persona_id", "")
        if not persona_filter.isascii() or not persona_filter.isdigit():
            persona_filter = ""
        facts = MemoryFact.objects.select_related(
            "persona__character", "subject", "source_event", "approved_by"
        ).order_by("-pk")
        if persona_filter:
            facts = facts.filter(persona_id=int(persona_filter))
        if query:
            facts = facts.filter(
                Q(text__icontains=query)
                | Q(staff_entry__icontains=query)
                | Q(persona__character__db_key__icontains=query)
                | Q(subject__db_key__icontains=query)
                | Q(pk=int(query) if query.isascii() and query.isdigit() else None)
            )
        rows = [_memory_review_row(fact, self.request.user) for fact in facts]
        if status in MemoryFact.Status.values:
            rows = [row for row in rows if row["effective_status"] == status]
        context.update(
            {
                "query": query,
                "selected_status": status,
                "persona_filter": persona_filter,
                "memory_statuses": MemoryFact.Status.choices,
                "memory_rows": Paginator(rows, 20).get_page(self.request.GET.get("page")),
            }
        )
        context.setdefault("form", MemoryCurationForm(initial={"persona_id": persona_filter}))
        return context

    def post(self, request):
        form = MemoryCurationForm(request.POST)
        if form.is_valid():
            try:
                fact = create_memory_fact(request.user, **form.cleaned_data)
            except PermissionError as error:
                return HttpResponseForbidden(str(error))
            except CurationConflictError as error:
                return HttpResponse(str(error), status=409)
            except ValueError as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request, "Memory saved as a staff-authored review draft. Approval is a separate action."
                )
                return HttpResponseRedirect(reverse("narrative_ops_memory_edit", args=(fact.pk,)))
        return self.render_to_response(self.get_context_data(form=form), status=400)


@method_decorator(login_required, name="dispatch")
@method_decorator(user_passes_test(staff_authorized), name="dispatch")
class MemoryRevisionView(TemplateView):
    template_name = "chronicle/memory_review.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fact = get_object_or_404(
            MemoryFact.objects.select_related(
                "persona__character",
                "subject",
                "source_event",
                "approved_by",
                "created_by",
                "updated_by",
                "redacted_by",
                "withdrawn_by",
            ),
            pk=self.kwargs["memory_id"],
        )
        row = _memory_review_row(fact, self.request.user)
        root = fact.revision_root_id or fact.pk
        context.update(row)
        context["history"] = (
            MemoryFact.objects.filter(Q(pk=root) | Q(revision_root_id=root))
            .select_related("created_by", "approved_by", "redacted_by")
            .order_by("created_at", "pk")
        )
        context["active_revision"] = (
            MemoryFact.objects.filter(revision_root_id=root, status__in=("draft", "approved")).order_by("-pk").first()
        )
        values = {
            key: getattr(fact, key)
            for key in (
                "persona_id",
                "subject_id",
                "text",
                "source_event_id",
                "staff_entry",
                "visibility",
                "expires_at",
            )
        }
        values["expected_version"] = fact.version
        context.setdefault("form", MemoryRevisionForm(initial=values))
        return context

    def post(self, request, memory_id):
        form = MemoryRevisionForm(request.POST)
        if form.is_valid():
            values = dict(form.cleaned_data)
            version = values.pop("expected_version")
            try:
                draft = revise_memory_fact(memory_id, request.user, version, values)
            except MemoryFact.DoesNotExist as error:
                raise Http404 from error
            except PermissionError as error:
                return HttpResponseForbidden(str(error))
            except CurationConflictError as error:
                return HttpResponse(str(error), status=409)
            except ValueError as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    "Replacement memory draft saved. Previous text is withdrawn from generation and fresh approval is required.",
                )
                return HttpResponseRedirect(reverse("narrative_ops_memory_edit", args=(draft.pk,)))
        return self.render_to_response(self.get_context_data(form=form), status=400)
