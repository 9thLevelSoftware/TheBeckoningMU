"""Populated baseline-to-current migration rehearsal on a new disposable DB.

Run only after the model graph is frozen. The retained directory contains fixture
data and a sanitized report, never a copy of the existing game database.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASELINE = {
    "narrative": "0001_initial",
    "chronicle": "0002_chronicle_generation_request",
    "builder": "0007_buildproject_built_object_ids",
}


def populate(old_apps):
    from datetime import timedelta

    import evennia
    from django.utils import timezone
    from evennia.utils.dbserialize import deserialize

    from tests.chargen_fixtures import legal_payload
    from tests.support.local_runtime import fixtures
    from traits.models import CharacterBio
    from world.rules_chargen import apply_chargen, parse_submission

    evennia._init()
    (account, _other), (character, legacy_character) = fixtures()
    character.reset_sheet()
    submission = parse_submission(legal_payload())
    apply_chargen(character, submission)
    CharacterBio.objects.filter(character=character).update(submission=submission.as_dict())
    character.set_trait("Potence", 3)
    character.db.experience = {
        "total_earned": 50,
        "total_spent": 15,
        "log": [
            {"type": "award", "amount": 50, "reason": "Staff award", "balance": 50},
            {"type": "spend", "amount": -15, "reason": "Raised Potence to 3 (in-clan)", "balance": 35},
        ],
    }
    stats = deserialize(legacy_character.db.stats)
    stats["disciplines"]["potence"] = 2
    legacy_character.db.stats = stats
    character.db.active_effects = [
        {"type": "alchemy", "name": "Haze", "duration": "scene", "custom": {"keep": [1]}},
        {"id": "opaque", "duration": ["old"], "custom": "retain"},
    ]
    consent = old_apps.get_model("narrative", "NarrativeConsent")
    consent.objects.create(account_id=account.pk, character_id=character.pk, opted_in=True)
    session = old_apps.get_model("narrative", "StorySession").objects.create(
        character_id=character.pk,
        current_action="Disposable private pending action",
        deterministic_outcome={"hunger_before": 5, "hunger_after": 3, "hunting_success": True},
    )
    requests = old_apps.get_model("narrative", "StoryGenerationRequest")
    pending = requests.objects.create(session_id=session.pk, action_text="Disposable private pending action")
    success = requests.objects.create(session_id=session.pk, status="succeeded", response="Retained fixture prose")
    events = old_apps.get_model("chronicle", "ChronicleEvent")

    def event(name, **changes):
        fields = {
            "idempotency_key": "migration-" + name,
            "source_app": "fixture",
            "source_type": "scene",
            "source_id": name,
            "kind": "scene.curated",
            "title": name,
            "summary": "Fixture text " + name,
            "visibility": "public",
            "status": "published",
        }
        fields.update(changes)
        return events.objects.create(**fields)

    source = event("valid-source")
    generated = event("known-generated", ai_generated=True, status="superseded")
    corrected = event("generated-correction", ai_generated=True, supersedes_id=generated.pk)
    redacted_source = event("redacted-source", status="redacted", summary="")
    unavailable = event("generated-unavailable-source", ai_generated=True)
    ambiguous = event("generated-unknown-source", ai_generated=True)
    manual = event("manual-unavailable-source")
    manual.source_events.add(redacted_source)
    manual_child = event("manual-unavailable-descendant", status="draft")
    manual_child.source_events.add(manual)

    npc = evennia.create_object("typeclasses.characters.Character", key="Legacy narrator", nohome=True)
    persona = old_apps.get_model("narrative", "NarrativePersona").objects.create(
        character_id=npc.pk, profile="Retained narrator profile", registered_by_id=account.pk
    )
    facts = old_apps.get_model("narrative", "MemoryFact")
    approved_at = timezone.now()
    expires_at = approved_at + timedelta(days=7)
    approved_fact = facts.objects.create(
        persona_id=persona.pk,
        text="Retained approved memory",
        source_event_id=source.pk,
        visibility="public",
        status="approved",
        approved_at=approved_at,
        expires_at=expires_at,
    )
    private_fact = facts.objects.create(
        persona_id=persona.pk,
        subject_id=character.pk,
        text="Retained private draft",
        staff_entry="Historical staff provenance",
        visibility="private",
        status="draft",
    )
    redacted_fact = facts.objects.create(
        persona_id=persona.pk,
        subject_id=character.pk,
        text="Legacy redacted text must be erased",
        staff_entry="Legacy sensitive provenance must be erased",
        visibility="private",
        status="redacted",
    )
    generations = old_apps.get_model("chronicle", "ChronicleGenerationRequest")
    for output, parent in ((generated, source), (unavailable, redacted_source)):
        generations.objects.create(
            mode="recap",
            requested_by_id=account.pk,
            status="succeeded",
            source_ids=[str(parent.pk)],
            citations=[str(parent.pk)],
            draft_event_id=output.pk,
        )
    pending_recap = generations.objects.create(
        mode="recap",
        requested_by_id=account.pk,
        source_ids=[str(source.pk)],
        dispatched_at=timezone.now(),
    )
    corrections = []
    for status in ("draft", "published", "redacted"):
        original = event("original-" + status, status="published" if status == "draft" else "superseded")
        correction = event(
            "correction-" + status,
            status=status,
            supersedes_id=original.pk,
            summary="" if status == "redacted" else "Retained correction " + status,
        )
        corrections.append(
            {"id": correction.pk, "original": original.pk, "status": status, "summary": correction.summary}
        )
    room = evennia.create_object("typeclasses.rooms.Room", key="Legacy published room")
    room.db.day_night = "restricted"  # No invented allowlist during migration.
    design = {"rooms": [{"id": "legacy", "name": room.key, "v5": {"day_night": "restricted"}}], "exits": []}
    project = old_apps.get_model("builder", "BuildProject").objects.create(
        user_id=account.pk,
        name="Legacy published project",
        status="live",
        map_data=design,
        approved_map_data={"map_data": design, "connection_room_id": None, "connection_direction": ""},
        built_object_ids=[room.pk],
        version=8,
    )
    return {
        "character": character.pk,
        "legacy_character": legacy_character.pk,
        "xp": deserialize(character.db.experience),
        "effects": deserialize(character.db.active_effects),
        "session": session.pk,
        "pending": pending.pk,
        "success": success.pk,
        "pending_recap": pending_recap.pk,
        "source": source.pk,
        "generated": generated.pk,
        "corrected_generated": corrected.pk,
        "unavailable": unavailable.pk,
        "ambiguous": ambiguous.pk,
        "manual_unavailable": manual.pk,
        "manual_descendant": manual_child.pk,
        "persona": persona.pk,
        "persona_character": npc.pk,
        "persona_registrar": account.pk,
        "approved_fact": approved_fact.pk,
        "private_fact": private_fact.pk,
        "redacted_fact": redacted_fact.pk,
        "memory_approved_at": approved_at,
        "memory_expires_at": expires_at,
        "corrections": corrections,
        "project": project.pk,
        "room": room.pk,
        "design": design,
    }


def verify(fixture):
    from evennia.objects.models import ObjectDB
    from evennia.utils.dbserialize import deserialize
    from evennia.utils.idmapper.models import flush_cache

    from chronicle.generation import recover_pending_drafts
    from chronicle.models import ChronicleEvent, ChronicleGenerationRequest
    from commands.v5.utils.discipline_effects import normalize_effects
    from narrative.models import MemoryFact, NarrativeConsent, NarrativePersona, StoryGenerationRequest, StorySession
    from traits.power_reconciliation import reconcile_discipline_powers
    from web.builder import operation_runtime
    from web.builder.models import BuilderOperationGuard, BuildProject
    from world.room_rules import room_access

    flush_cache()
    character = ObjectDB.objects.get(pk=fixture["character"])
    assert deserialize(character.db.experience) == fixture["xp"]
    assert ObjectDB.objects.get(pk=fixture["legacy_character"]).get_trait("Potence") == 2
    before = character.snapshot_sheet()
    dry = reconcile_discipline_powers(character)
    assert len(dry["proposed"]) == 1 and character.snapshot_sheet() == before
    first = reconcile_discipline_powers(character, apply=True)
    assert len(first["created"]) == 1
    assert reconcile_discipline_powers(character, apply=True)["created"] == []
    # Explicit reconciliation adds only entitlement metadata, never XP charges.
    expected_experience = {**fixture["xp"], "power_choices": first["created"]}
    assert deserialize(character.db.experience) == expected_experience
    normalize_effects(character)
    assert deserialize(character.db.active_effects) == fixture["effects"]
    normalized = normalize_effects(character, persist=True)
    assert normalized["records"][0]["id"] and normalized["records"][0]["custom"] == {"keep": [1]}
    assert normalized["records"][1]["duration"] == ["old"]
    assert normalize_effects(character, persist=True)["changes"] == []
    pending = StoryGenerationRequest.objects.get(pk=fixture["pending"])
    assert (pending.status, pending.error, pending.action_text) == ("failed", "legacy_dispatch_unknown", "")
    assert StoryGenerationRequest.objects.get(pk=fixture["success"]).response == "Retained fixture prose"
    session = StorySession.objects.get(pk=fixture["session"])
    assert session.current_action == "" and session.deterministic_outcome["hunger_after"] == 3
    assert NarrativeConsent.objects.get(character_id=character.pk).opted_in
    # Chronicle already persisted dispatch claims on the old schema. Its
    # interrupted attempt is settled by startup recovery, not a data migration.
    assert ChronicleGenerationRequest.objects.get(pk=fixture["pending_recap"]).status == "pending"
    scheduled = []
    assert recover_pending_drafts(provider=object(), scheduler=scheduled.append) == 0
    assert recover_pending_drafts(provider=object(), scheduler=scheduled.append) == 0
    assert scheduled == []
    recovered = ChronicleGenerationRequest.objects.get(pk=fixture["pending_recap"])
    assert (recovered.status, recovered.error) == ("failed", "interrupted")
    for correction in fixture["corrections"]:
        current = ChronicleEvent.objects.get(pk=correction["id"])
        assert current.supersedes_id == correction["original"]
        assert current.status == correction["status"] and current.summary == correction["summary"]
    for key in ("generated", "corrected_generated"):
        current = ChronicleEvent.objects.get(pk=fixture[key])
        assert current.source_events.filter(pk=fixture["source"]).exists()
    for key in ("unavailable", "ambiguous", "manual_unavailable", "manual_descendant"):
        current = ChronicleEvent.objects.get(pk=fixture[key])
        assert current.status == "withdrawn" and current.summary and current.withdrawal_reason
    persona = NarrativePersona.objects.get(pk=fixture["persona"])
    assert persona.character_id == fixture["persona_character"]
    assert persona.registered_by_id == fixture["persona_registrar"]
    assert persona.profile == "Retained narrator profile" and persona.version == 1
    approved = MemoryFact.objects.get(pk=fixture["approved_fact"])
    assert approved.text == "Retained approved memory" and approved.status == "approved"
    assert approved.source_event_id == fixture["source"] and approved.visibility == "public"
    assert approved.approved_at == fixture["memory_approved_at"] and approved.expires_at == fixture["memory_expires_at"]
    assert approved.approved_by_id is None and approved.revision_of_id is None and approved.version == 1
    private = MemoryFact.objects.get(pk=fixture["private_fact"])
    assert private.subject_id == character.pk and private.visibility == "private" and private.status == "draft"
    assert private.text == "Retained private draft" and private.staff_entry == "Historical staff provenance"
    redacted = MemoryFact.objects.get(pk=fixture["redacted_fact"])
    assert redacted.status == "redacted" and redacted.text == "" and redacted.staff_entry == ""
    assert redacted.subject_id == character.pk and redacted.persona_id == persona.pk
    project = BuildProject.objects.get(pk=fixture["project"])
    assert project.status == "live" and project.version == 8
    assert project.map_data == fixture["design"] and project.built_object_ids == [fixture["room"]]
    assert not project.live_manifest and not project.fixture_manifest
    assert project.builder_operation == {}
    assert not BuilderOperationGuard.objects.exists()
    # Legacy projects carry no operation claim. Fresh recovery must therefore
    # permit normal world access without inventing a guard or a journal.
    operation_runtime.recover_operation_fences()
    assert not operation_runtime.world_mutation_is_guarded()
    assert not operation_runtime.object_is_fenced(fixture["room"])
    assert project.builder_operation == {} and not BuilderOperationGuard.objects.exists()
    room = ObjectDB.objects.get(pk=fixture["room"])
    assert room.db.day_night == "restricted" and not room_access(character, room)[0]
    return {
        "xp_preserved": True,
        "power_entitlements_idempotent": True,
        "effect_normalization_idempotent": True,
        "legacy_requests_failed_without_dispatch": True,
        "correction_ids_preserved": True,
        "generated_ancestry_repaired_or_withdrawn": True,
        "manual_unavailable_ancestry_withdrawn": True,
        "memory_identity_scope_audit_preserved": True,
        "legacy_redacted_memory_erased": True,
        "legacy_project_identity_preserved": True,
        "legacy_builder_operation_default_empty": True,
        "empty_builder_guard_compatible": True,
    }


def main():
    from tests.support.local_runtime import bootstrap

    run = Path(tempfile.mkdtemp(prefix="beckoning-completeness-migration-"))
    (run / ".local-acceptance").touch()
    database = run / "acceptance.sqlite3"
    bootstrap(database)
    from django.core.management.sql import emit_post_migrate_signal
    from django.db import connection, connections
    from django.db.migrations.executor import MigrationExecutor

    try:
        executor = MigrationExecutor(connection)
        final = executor.loader.graph.leaf_nodes()
        assert ("builder", "0011_bounded_builder_operations") in final
        old = [node for node in final if node[0] not in BASELINE] + list(BASELINE.items())
        executor.migrate(old)
        old_apps = executor.loader.project_state(old).apps
        # MigrationExecutor does not run the management command's post-migrate
        # receivers. Evennia's normal factories require those content types.
        from web.builder import operation_runtime
        from web.builder.models import BuilderOperationGuard

        assert BuilderOperationGuard._meta.db_table not in connection.introspection.table_names()
        fence_fast_path = operation_runtime.world_mutation_is_guarded
        # The factories seed the OLD schema, which predates builder fences.
        # Suppress only the new fence hook's fast path during this disposable
        # setup. Never relax runtime behavior or carry this patch into migrate
        # or verification; production's missing-schema failure stays intact.
        with patch.object(operation_runtime, "world_mutation_is_guarded", return_value=False):
            emit_post_migrate_signal(verbosity=0, interactive=False, db="default", apps=old_apps)
            fixture = populate(old_apps)
        assert operation_runtime.world_mutation_is_guarded is fence_fast_path
        executor = MigrationExecutor(connection)
        executor.migrate(final)
        checks = verify(fixture)
        executor = MigrationExecutor(connection)
        assert executor.migration_plan(final) == []
        report = {
            "database": str(database),
            "baseline": BASELINE,
            "final_targets": final,
            "checks": checks,
            "old_schema_seed_fence_patch_restored": True,
            "second_migration_plan_empty": True,
            "passed": True,
        }
        path = run / "rehearsal-report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(path), "passed": True}))
    finally:
        connections.close_all()


if __name__ == "__main__":
    main()
