"""Fresh, shared Chronicle authorization and source provenance.

Objects and prefetch caches supplied by a caller are identifiers only. Every
decision reloads records and canonical ownership; caches live for one decision.
Correction originals are history, while their upstream sources remain required.
"""

import hashlib
import json

from django.contrib.auth import get_user_model

from .models import ChronicleEvent, ChronicleGenerationRequest

MAX_ANCESTRY = 128


class UnavailableSourceError(ValueError):
    def __init__(self):
        super().__init__("Every source and its dependencies must still be available for this audience.")


def event_fingerprint(event):
    snapshot = {field.attname: getattr(event, field.attname) for field in event._meta.concrete_fields}
    snapshot["sources"] = sorted(str(item.pk) for item in event.source_events.all())
    snapshot["participants"] = sorted(item.pk for item in event.participants.all())
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class _Policy:
    def __init__(self, audience, account, character_id):
        if audience not in {"public", "participants", "account", "staff"}:
            raise ValueError("Unknown Chronicle audience.")
        self.audience = audience
        self.account = account
        self.owned = set()
        if (
            getattr(account, "is_authenticated", False)
            and get_user_model().objects.filter(pk=account.pk, is_active=True).exists()
        ):
            from traits.models import CharacterBio

            self.owned = set(CharacterBio.objects.filter(account_id=account.pk).values_list("character_id", flat=True))
        if character_id is not None:
            self.owned.intersection_update({character_id})
        self.rows = {}
        self.memo = {}
        self.links = {}

    def row(self, event_id):
        event_id = int(event_id)
        if event_id not in self.rows:
            self.rows[event_id] = (
                ChronicleEvent.objects.filter(pk=event_id).prefetch_related("source_events", "participants").first()
            )
        event = self.rows[event_id]
        if event is None:
            raise UnavailableSourceError()
        return event

    def visible(self, event, *, root=False):
        if self.audience == "staff":
            from .services import staff_authorized

            return staff_authorized(self.account)
        if event.visibility == "public":
            return not (root and self.audience == "participants")
        return (
            event.visibility == "participants"
            and self.audience in {"participants", "account"}
            and bool(self.owned.intersection(item.pk for item in event.participants.all()))
        )

    def sources(self, event):
        if event.pk in self.links:
            return self.links[event.pk]
        history, links, chain = set(), set(), [event]
        current = event
        while current.supersedes_id:
            if current.supersedes_id in history or len(history) >= MAX_ANCESTRY:
                raise UnavailableSourceError()
            history.add(current.supersedes_id)
            current = self.row(current.supersedes_id)
            if (
                current.pk == event.pk
                or current.status not in {"published", "superseded"}
                or current.lineage_status != "known"
            ):
                raise UnavailableSourceError()
            if not self.visible(current):
                raise UnavailableSourceError()
            chain.append(current)
        for item in chain:
            links.update(source.pk for source in item.source_events.all())
        # Old corrections sometimes recorded their original as a source. That
        # edge is historical; retaining it must not require superseded prose.
        links.difference_update(history)
        self.links[event.pk] = (links, chain)
        return links, chain

    def visit(self, event_id, path=()):
        event_id = int(event_id)
        if event_id in path or len(path) >= MAX_ANCESTRY:
            raise UnavailableSourceError()
        if event_id in self.memo:
            return self.memo[event_id]
        event = self.row(event_id)
        if event.status != "published" or event.lineage_status != "known" or not self.visible(event):
            raise UnavailableSourceError()
        links, chain = self.sources(event)
        closure = {event_id}
        for source_id in links:
            closure.update(self.visit(source_id, (*path, event_id)))
        if any(item.ai_generated for item in chain):
            # A correction inherits the original durable request. Source_type is
            # descriptive legacy metadata, never an authority binding by itself.
            requests = list(
                ChronicleGenerationRequest.objects.filter(
                    draft_event_id__in=[item.pk for item in chain], status="succeeded"
                )
            )
            if len(requests) != 1:
                raise UnavailableSourceError()
            request = requests[0]
            try:
                if not isinstance(request.source_ids, list) or any(
                    type(item) not in (str, int) or not str(item).isascii() or not str(item).isdigit() or int(item) <= 0
                    for item in request.source_ids
                ):
                    raise ValueError
                expected = {int(item) for item in request.source_ids}
            except (TypeError, ValueError):
                raise UnavailableSourceError() from None
            if not expected or expected != links:
                raise UnavailableSourceError()
            ancestry = closure - {event_id}
            actual = {str(pk): event_fingerprint(self.row(pk)) for pk in ancestry}
            if request.source_fingerprints != actual:
                raise UnavailableSourceError()
        self.memo[event_id] = closure
        return closure

    def require(self, event_id):
        event = self.row(event_id)
        if not self.visible(event, root=True):
            raise UnavailableSourceError()
        self.visit(event.pk)
        return event


def event_available(event, audience="public", account=None, *, character_id=None):
    try:
        _Policy(audience, account, character_id).require(getattr(event, "pk", event))
        return True
    except (UnavailableSourceError, TypeError, ValueError):
        return False


def available_events(queryset=None, *, audience="public", account=None, character_id=None):
    queryset = ChronicleEvent.objects.all() if queryset is None else queryset
    policy = _Policy(audience, account, character_id)
    allowed = []
    for event_id in queryset.filter(status="published").values_list("pk", flat=True):
        try:
            policy.require(event_id)
            allowed.append(event_id)
        except UnavailableSourceError:
            continue
    return ChronicleEvent.objects.filter(pk__in=allowed)


def event_sources_available(event, audience="public", account=None, *, character_id=None):
    policy = _Policy(audience, account, character_id)
    try:
        event = policy.row(getattr(event, "pk", event))
        if event.lineage_status != "known":
            return False
        links, _chain = policy.sources(event)
        for source_id in links:
            policy.visit(source_id)
        return True
    except (UnavailableSourceError, TypeError, ValueError):
        return False


def source_context(source_ids, *, max_dependencies=32):
    policy = _Policy("public", None, None)
    closure = set()
    selected = []
    for source_id in source_ids:
        selected.append(policy.require(source_id))
        closure.update(policy.visit(source_id))
        if len(closure) > max_dependencies:
            raise ValueError("Selected sources have too many dependencies.")
    return selected, {str(pk): event_fingerprint(policy.row(pk)) for pk in closure}


def source_fingerprints(event, audience="public", account=None, *, character_id=None):
    policy = _Policy(audience, account, character_id)
    policy.require(getattr(event, "pk", event))
    return {str(pk): event_fingerprint(policy.row(pk)) for pk in policy.visit(getattr(event, "pk", event))}


def event_projection(event, audience="public", account=None, *, character_id=None):
    try:
        event = _Policy(audience, account, character_id).require(getattr(event, "pk", event))
    except (UnavailableSourceError, TypeError, ValueError):
        return None
    return {
        "id": event.pk,
        "kind": event.kind,
        "title": event.title,
        "summary": event.summary,
        "occurred_at": event.occurred_at.isoformat(),
        "ai_generated": event.ai_generated,
        "payload": event.payload,
    }
