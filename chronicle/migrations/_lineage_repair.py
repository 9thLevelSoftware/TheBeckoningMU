"""Frozen N4 historical-model repair; never rewrite a saved source fingerprint."""

import hashlib
import json

from django.utils import timezone


def repair_lineage(apps, schema_editor):
    event_model = apps.get_model("chronicle", "ChronicleEvent")
    request_model = apps.get_model("chronicle", "ChronicleGenerationRequest")
    alias = schema_editor.connection.alias
    rows = {row.pk: row for row in event_model.objects.using(alias).all()}
    links = {pk: set(row.source_events.using(alias).values_list("pk", flat=True)) for pk, row in rows.items()}
    bindings = {}
    unknown = set()
    for request in request_model.objects.using(alias).filter(status="succeeded", draft_event__isnull=False):
        pk = request.draft_event_id
        if pk not in rows:
            continue
        try:
            if (
                not isinstance(request.source_ids, list)
                or not request.source_ids
                or any(
                    type(value) not in (str, int)
                    or not str(value).isascii()
                    or not str(value).isdigit()
                    or int(value) <= 0
                    for value in request.source_ids
                )
            ):
                raise ValueError
            source_ids = {int(value) for value in request.source_ids}
            if not source_ids.issubset(rows) or pk in source_ids or (links[pk] and links[pk] != source_ids):
                raise ValueError
        except (TypeError, ValueError):
            unknown.add(pk)
            continue
        bindings[pk] = request
        rows[pk].source_events.add(*(source_ids - links[pk]))
        links[pk].update(source_ids)

    def history(pk):
        chain, seen = [], set()
        while pk is not None:
            if pk not in rows or pk in seen or len(seen) >= 128:
                raise ValueError
            seen.add(pk)
            chain.append(pk)
            pk = rows[pk].supersedes_id
        return chain

    # Corrections/revisions retain their own identities and historical edges.
    # Propagate only real upstream sources, not the superseded original's ID.
    for pk, row in rows.items():
        try:
            chain = history(pk)
            inherited = set().union(*(links[item] for item in chain)) - set(chain[1:])
            upstream = set(inherited)
            revision = row.revision_of_id
            seen = {pk}
            while revision:
                if revision not in rows or revision in seen or len(seen) >= 128:
                    raise ValueError
                seen.add(revision)
                upstream.update(links[revision] - set(chain))
                revision = rows[revision].revision_of_id
            row.source_events.add(*(upstream - links[pk]))
            links[pk].update(upstream)
            if any(rows[item].ai_generated for item in chain) and (
                not inherited or not any(item in bindings for item in chain)
            ):
                unknown.add(pk)
            if set(chain) & unknown:
                unknown.add(pk)
        except ValueError:
            unknown.add(pk)

    participants = {pk: set(row.participants.using(alias).values_list("pk", flat=True)) for pk, row in rows.items()}

    def visible(pk, visibility, subjects):
        return (
            rows[pk].visibility == "public"
            or visibility == "staff"
            or (
                visibility == "participants"
                and rows[pk].visibility == "participants"
                and bool(subjects)
                and subjects.issubset(participants[pk])
            )
        )

    def closure(pk, path=(), *, visibility="public", subjects=frozenset()):
        if pk in path or len(path) >= 128 or pk in unknown:
            raise ValueError
        row = rows[pk]
        if row.status != "published" or not visible(pk, visibility, subjects):
            raise ValueError
        chain = history(pk)
        if any(
            rows[item].status not in {"published", "superseded"} or not visible(item, visibility, subjects)
            for item in chain[1:]
        ):
            raise ValueError
        sources = set().union(*(links[item] for item in chain)) - set(chain[1:])
        result = {pk}
        for source_id in sources:
            result.update(closure(source_id, (*path, pk), visibility=visibility, subjects=subjects))
        return result

    def fingerprint(pk):
        row = rows[pk]
        snapshot = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
        snapshot["sources"] = sorted(str(item) for item in links[pk])
        snapshot["participants"] = sorted(row.participants.using(alias).values_list("pk", flat=True))
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    # Metadata added by this migration can invalidate old whole-record hashes.
    # Keep those proofs unchanged and withdraw unverified output for new review.
    invalid = set(unknown)
    reasons = dict.fromkeys(unknown, "legacy_lineage_ambiguous")
    for pk, row in rows.items():
        reason = "legacy_source_unavailable"
        try:
            chain = history(pk)
            if any(rows[item].status not in {"published", "superseded"} for item in chain[1:]):
                raise ValueError
            generated = any(rows[item].ai_generated for item in chain)
            sources = set().union(*(links[item] for item in chain)) - set(chain[1:])
            ancestry = set().union(
                *(
                    closure(
                        item, visibility="public" if generated else row.visibility, subjects=frozenset(participants[pk])
                    )
                    for item in sources
                )
            )
            if not generated:
                continue
            reason = "legacy_provenance_unverified"
            request = next((bindings[item] for item in chain if item in bindings), None)
            if request is None:
                raise ValueError
            if request.source_fingerprints != {str(item): fingerprint(item) for item in ancestry}:
                raise ValueError
        except (ValueError, KeyError):
            invalid.add(pk)
            reasons.setdefault(pk, reason)

    # Propagate invalidity to copied/derived outputs, including manually reviewed
    # recaps. Ordinary correction histories with no invalid sources stay intact.
    frontier = set(invalid)
    while frontier:
        found = {
            pk
            for pk, row in rows.items()
            if pk not in invalid
            and (links[pk] & frontier or row.supersedes_id in frontier or row.revision_of_id in frontier)
        }
        invalid.update(found)
        reasons.update(dict.fromkeys(found, "legacy_source_unavailable"))
        frontier = found
    for pk in unknown:
        event_model.objects.using(alias).filter(pk=pk, lineage_status="known").update(
            lineage_status="unknown", lineage_note="legacy_lineage_ambiguous"
        )
    for reason in set(reasons.values()):
        event_model.objects.using(alias).filter(
            pk__in=[pk for pk in invalid if reasons[pk] == reason], status__in=("published", "draft")
        ).update(status="withdrawn", withdrawn_at=timezone.now(), withdrawal_reason=reason)
