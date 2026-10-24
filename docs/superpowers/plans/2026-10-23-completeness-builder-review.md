# Builder and Character Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete trigger editing, staff character review, curated object placement, room settings and safe project revision workflows.

**Architecture:** Keep server validation authoritative and approved snapshots immutable. Extend the existing builder units with explicit typed manifests and reversible revision operations. UI tests must cross save/reload boundaries and actual browser acceptance must reach the game world.

**Tech Stack:** Existing Django/Evennia services, vanilla JavaScript templates and Node-based client tests; existing SQLite/Evennia compensation pattern.

**Spec:** [Scope contract](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-spec.md), [coordinator plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-plan.md).

## Global Constraints

All master constraints apply. Never weaken review, version, authority, markup, room/exit/trigger-count or main-thread rules to make a new feature pass. Builder data is untrusted even when submitted by staff. Tags alone cannot authorize cleanup/replacement. No live replacement or deletion is authorized by this planning request.

## Review Focus

- Editing only one trigger property must preserve every other typed parameter and condition: W1.
- Staff must review played state after revocation rather than stale submitted JSON: W2.
- An old review must not authorize a new revision, catalog definition or replacement target: W3/W5.
- New access rules must compose with existing locks and apply room hunting modifiers once: W4.
- Moved/mismatched objects, occupants and foreign exits must prevent destructive lifecycle actions: W3/W5.

## W1 — Complete the trigger editor contract

**Files:** Modify web/templates/builder/editor.html, web/builder/views.py, trigger_actions.py and trigger_engine.py. Create web/builder/test_editor_client.py and web/builder/fixtures/trigger_editor.cjs. Extend web/builder/test_triggers.py and test_validators.py.

**Interfaces:** TriggerActionsAPI returns action IDs, labels and a server-defined typed parameter schema. Supported action fields remain message for message actions; target, attr_name and primitive value for permitted attribute actions. validate_trigger remains the authoritative schema/permission check. No arbitrary property assignment or broader attr allowlist.

- [ ] Add BuilderTriggerEditorTests executing the actual editor save/edit/delete functions: create message, edit only condition, preserve boolean/number/null values, switch action with compatible fields retained and invalid fields removed deliberately, and delete exactly the selected trigger. A saved/reloaded trigger must retain parameters byte-for-value at the JSON level.
- [ ] Add server tests rejecting empty/whitespace-only messages, bad target/name/type, forged primitive objects, unknown parameters and stale project versions. Accepted message actions must execute and report success.
- [ ] Render action-specific inputs from the metadata, load existing parameters, preserve primitive types and show validation errors without resetting other form data. Reveal Delete only for existing triggers; preserve keyboard labels/focus and escape authored text.
- [ ] Preserve legitimate parameters unknown to an older client until the server rejects them with actionable feedback; do not silently replace an entire dictionary with defaults. Save Project and RoomTriggersAPI must enforce the same schema.
- [ ] Run web.builder.test_editor_client and affected TriggerValidationTests once. Q1 must create/edit/save/reload/build/enter/delete through the real modal and verify delivery in the room.

## W2 — Complete reviewer-visible character data

**Files:** Modify traits/api.py and web/templates/character_approval.html. Create tests/test_character_review_completeness.py; extend the existing client harness pattern in tests/test_chargen_client.py only as needed.

**Interfaces:** Extend export_character additively with convictions, linked touchstones/descriptions, known rituals/formulas, age category and structured merit/flaw notes derived from current Character accessors. _sheet_by_category must preserve note-bearing values or expose a dedicated review section; existing API consumers keep their current keys.

- [ ] Add CharacterReviewCompletenessTests for ordinary, Blood Sorcery and Thin-Blood Alchemist sheets. Assert every submitted choice survives persistence/export/rendering, and revoked review reads the current played sheet rather than CharacterBio.submission.
- [ ] Test owner/Builder/unrelated account access, Builder-only address information, malformed legacy linked data and applicant text containing HTML/script-like strings. The DOM must render text, not executable markup.
- [ ] Add explicit review sections for convictions/touchstones, learned items and notes. Show empty states deliberately so missing data cannot look like an omitted panel. Preserve existing approval/revoke permissions and request payloads.
- [ ] Run tests.test_character_review_completeness plus affected tests.test_chargen_web and client checks once. Q1 verifies human-visible completeness before approve/reject actions.

## W3 — Immutable revisions and reviewed live replacement

**Files:** Modify web/builder/models.py, views.py, urls.py and dashboard/editor/review templates. Create web/builder/revisions.py, live_replacement.py and test_revisions.py. Generate a named builder migration. Integrate lifecycle manifests with sandbox_builder.py/promotion.py; live replacement follows W5's fixture expansion.

**Interfaces:** POST project/<id>/revisions/ with version creates a new draft, returning id/revision_of_id/root_project_id. fork_revision(project_id, actor, expected_version) copies only approved design/connection data. prepare_replacement(project_id, actor) -> reviewed diff identifies exact live-source revision, object identities and changes. replace_live_unit(project_id, actor, expected_version) -> result executes only the approved replacement plan on the reactor.

- [ ] Add ProjectRevisionTests for approved, built and live sources. New drafts preserve source snapshots/objects but omit reviewer fields, built IDs, sandbox locations and lifecycle timestamps. Nonowner and stale forks fail. Approval of a new revision cannot silently modify the live source.
- [ ] Persist immutable lineage and a live manifest mapping stable map IDs to exact object IDs/types and the approved design revision. Historical projects without trustworthy manifests remain read-only for replacement until an explicit reviewed adoption inventory establishes identity; never infer ownership from tags.
- [ ] Make revision intent explicit: a copy with a new connection versus a replacement of a named live revision. A reviewed replacement includes field-level changes, additions, retirements and connection changes. Recheck the exact source identity/version immediately before execution; only one live revision per lineage may win.
- [ ] Preserve IDs for retained rooms/exits/fixtures. Modify only reviewed builder-owned design fields; preserve gameplay Attributes. Refuse affected occupants (including NPCs), unreviewed foreign connections/contents, moved fixtures and ambiguous ownership. Pause affected timers and record compensating state before mutation.
- [ ] Prepare additions first and record them immediately. Retire removed owned empty objects by disconnecting/restricting them and stopping their timers; retain IDs/state for rollback. Do not physically purge them during replacement. Restore fields, links, timers and metadata on failure and remove only newly created recorded additions. Report any compensation failure visibly; do not claim success or automatic rollback.
- [ ] Add LiveRevisionTests for stale-source rejection, preserved unrelated live state, occupied/foreign-connected refusal, stable retained IDs, staged additions, retirement, injected failure at each phase and retry without duplicate publication. A separate future purge requires explicit authorization and a verified manifest.
- [ ] Run web.builder.test_revisions after the fork portion; run the live-replacement class once after W5 integration. Q1/Q3 exercise replacement with a realistic populated disposable world.

## W4 — Give room settings explicit, verified consumers

**Files:** Create world/room_rules.py and tests/v5/test_room_rules.py. Modify typeclasses/exits.py, web/builder/validators.py, sandbox_builder.py and editor/review templates. The gameplay owner integrates commands/v5/utils/hunting_utils.py after G5. Add a staff room-inspection command in commands/v5/staff.py.

**Interfaces:** room_access(character, destination, at_time) -> allowed/reason composes with existing traverse locks. hunting_context(character, ground) -> dict returns the resolved ground and labelled room contribution. haven_context(room, actor, action) -> validated facts/modifiers returns only R0-approved actions, with explicit adjudicated outcomes where automation lacks authoritative facts.

- [ ] Finish R0's room-policy rows before implementation: clock/timezone/day boundaries; each access enum including restricted policy and mortal-specific wording; hunting modifier meaning/bounds/stacking; every Haven rating's supported action. A generic +N bonus invented from a label is unacceptable.
- [ ] Add RoomAccessTests at each boundary and for every supported splat/access mode; existing traverse locks must still deny access. Provide explicit, audited staff bypass behavior only if the accepted policy requires it.
- [ ] Add RoomHuntingTests proving the room contribution is applied once and displayed, cannot be bypassed by choosing an unrelated ground, and leaves rooms with no properties backward-compatible. Preserve all Hunger/Rouse/resonance/cooldown rules.
- [ ] Add HavenRulesTests for each R0-defined consumer and a complete staff inspection view. If a rating is intentionally adjudicated, both builder and player/staff displays must say so and expose the facts needed to adjudicate; do not advertise automatic intrusion, capacity or ward mechanics that do not exist.
- [ ] Preserve old saved properties. During compatibility inventory flag ambiguous legacy restricted access rather than inventing a principal or silently opening it. Require an explicit reviewed policy before promoting an ambiguous revision.
- [ ] Run tests.v5.test_room_rules and affected builder validator/sandbox tests once. Q1 verifies actual traversal and hunting from a constructed room.

## W5 — Curated prototypes through the full builder lifecycle

**Files:** Create web/builder/prototype_catalog.py and test_prototypes.py. Modify views.py, validators.py, models.py, sandbox_builder.py, sandbox_cleanup.py, promotion.py and editor/review templates. Coordinate recorded-object handling with W3; extend existing sandbox tests.

**Interfaces:** GET prototypes returns catalog_version and prototypes[{id, revision, label, description}]. map.objects[placement_id] stores prototype_id, prototype_revision, room_id and bounded optional name/description. Approved snapshots embed the resolved reviewed definition/hash. A dedicated fixture manifest records placement ID, object ID, exact type and approved catalog revision.

- [ ] Define a small server-curated initial catalog of inert, immovable scenery, such as a wooden chair and table. Server definitions own typeclass, locks, attributes and behavior. No caller-supplied code, inheritance, script, lock, dbref, Character or account field is accepted. Reuse existing text/markup limits; proposed placement limits are 100 per project and 20 per room, subject to measured builder-unit bounds.
- [ ] Add PrototypeCatalogTests for authenticated access, real non-501 catalog results and rejection of unknown IDs/revisions. Add PrototypePlacementTests for missing rooms, count/markup limits and malicious definition overrides.
- [ ] Add actual catalog selection/place/edit/delete controls. Save/reload and staff review show exact fixture identity/version and overrides. Re-resolve only at draft validation; later catalog edits cannot change an already approved build.
- [ ] Build only the reviewed definitions on the reactor. Record fixture IDs immediately for compensation. Expand cleanup/promotion to the dedicated exact type/ID/provenance manifest without broadening room/exit deletion predicates or trusting tags. Check no account/Character substitution, moved objects or foreign contents; immovable fixtures simplify ordinary cleanup but do not replace these guards.
- [ ] Add build-to-inspection, rollback, promotion, cleanup, stale catalog and substituted-Character tests. Promotion retains fixtures in their rooms; cleanup refuses unexpected placement/contents and deletes only verified created fixtures. Supply W3 with the same manifest contract.
- [ ] Run web.builder.test_prototypes plus affected sandbox/validator tests once. Measure the maximum accepted map with fixtures on file-backed disposable SQLite; reduce proposed caps if it violates the repository's accepted reactor responsiveness bound. Do not relax that bound to pass.

## Completion

Every visible feature must survive save/reload, review and real-world use. Source/API tests cannot substitute for Q1 browser acceptance. Existing live adoption and replacement remain separately authorized operational steps even after their implementation is tested locally.
