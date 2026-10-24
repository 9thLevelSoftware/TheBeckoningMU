# Narrative and Chronicle Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound generation, prevent duplicate recovery dispatch, complete moderation/curation and enforce the chosen withdrawal policy.

**Architecture:** Preserve pending/succeeded/failed request statuses but make queued versus dispatched state durable. Use short conditional record transitions around external work, versioned moderation and one availability policy for reads and provenance. Complete Builder curation through services shared with admin.

**Tech Stack:** Existing Django/SQLite, Twisted Deferred transport, Evennia authority, Django templates and read-only MCP projections.

**Spec:** [Scope contract](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-spec.md), [coordinator plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-plan.md).

## Global Constraints

All master constraints apply. No live provider requests, production migration or publication is authorized. No network work inside a database transaction. Consent/ownership/context are rechecked at actual dispatch and completion. Error persistence contains fixed categories, never raw provider bodies, player prompts or credentials. Retain successful history and deterministic outcomes.

## Review Focus

- Never-arriving headers, stalled/chunked bodies and cancellation settle both durable and caller state: N1.
- Two workers, restart and late callbacks cannot redispatch or overwrite terminal requests: N2.
- Double correction submissions and stale publication do not crash or undo later moderation: N3.
- Chained sources, corrections, warmed readers and unknown legacy lineage cannot expose withdrawn content: N4.
- Approved facts and admin edits cannot bypass redaction, scope, review or current Builder authority: N5.

## N1 — Bounded and cancellable provider transport

**Files:** Modify narrative/services.py and server/conf/secret_settings.example.py. Create narrative/provider_transport.py and narrative/test_provider_limits.py to keep bounded HTTP reading separate from narrative policy; retain TwistedChatProvider at its existing public import path.

**Interfaces:** TwistedChatProvider.generate(messages) -> Deferred[str] remains stable. Proposed configuration defaults: request_timeout_seconds=30, connect_timeout_seconds=10, response_max_bytes=1048576, prose_max_chars=12000. Validate positive bounded values; proposed allowed maxima are 300 seconds, 8 MiB and 100000 prose characters. Apply one total deadline across connection, headers, streaming body and parsing. Clock/transport injection is test-only dependency injection, not a production provider bypass.

- [ ] Add ProviderResponseLimitTests for never-arriving headers, a body that stops mid-stream, oversized declared and chunked bodies, malformed JSON, oversized prose, cancellation and deadline-versus-response races. At the configured deadline assert Deferred settled once, transport aborted where available, and no sensitive error text persisted.
- [ ] Replace unbounded readBody with a streaming reader that rejects both declared and actual oversized responses. Apply the deadline at the shared adapter so Chronicle and hunt drafting receive the same protection. Cancellation aborts pending transport and ignores late chunks/callbacks.
- [ ] Retain the current response schema/citation checks and attribution. Fixed failure categories distinguish timeout, canceled, response_too_large, malformed_response and upstream_failure. Do not automatically retry HTTP requests.
- [ ] Run narrative.test_provider_limits with a controlled clock and fake transport. Add real loopback stalled/chunked response cases to the existing HTTP harness, but run that harness once jointly with N2/G5.

## N2 — Durable dispatch claims and safe recovery

**Files:** Modify narrative/models.py, narrative/services.py, chronicle/models.py, chronicle/generation.py and server/conf/at_server_startstop.py only where recovery integration changes. Generate named narrative/chronicle migrations. Create narrative/test_request_lifecycle.py.

**Interfaces:** claim_story_request(request_id) -> StoryDispatchContext | None conditionally claims an eligible row. StoryDispatchContext contains request/session IDs, immutable prompt/provenance snapshot and deadline; it is not a second mutable game state. Add dispatched_at and deadline_at to story requests; add deadline_at to Chronicle requests, which already record dispatch.

| Stored state | Meaning | Recovery |
| --- | --- | --- |
| pending, dispatched_at null | New queued request | Revalidate and claim once |
| pending, dispatched_at set | External outcome may already exist | Fail as interrupted; never redispatch automatically |
| succeeded/failed | Terminal | No dispatch and no later overwrite |

- [ ] Add StoryRequestLifecycleTests for duplicate conditional claims, crash before claim, crash after claim/before send, crash after send, consent withdrawal, closed session, ownership transfer, expired context, timeout and late completion. A failed claimed request can be retried only as an explicit new request; that retry must not rerun hunt mechanics.
- [ ] Commit the conditional pending/unclaimed claim and dispatch metadata before calling provider.generate. Recheck authority/provenance at claim and completion. Conditional status/version writes, not SQLite select_for_update alone, arbitrate races. Maintain existing per-session in-flight constraints.
- [ ] Centralize terminalization so every failure clears request action_text and the matching session.current_action without erasing a newer request's action. Preserve session state and deterministic outcome. Resolve the waiting Deferred exactly once even after revocation or shutdown.
- [ ] Add a migration marking every legacy pending story request failed with legacy_dispatch_unknown and clearing only its raw action fields. Preserve successful rows, consent, sessions and hunt results. Unknown old rows cannot safely be assumed unsent.
- [ ] Recover only newly created unclaimed requests. Fail claimed interrupted rows and respect persisted deadlines. Apply equivalent terminal/callback guarantees to Chronicle generation using N1 limits.
- [ ] Run narrative.test_request_lifecycle and affected chronicle.test_generation tests. Populate old-schema fixtures for migration tests. Execute narrative.test_http_command once after G5 integration with exact dice-count and player-feedback assertions.

## N3 — Correction draft creation, editing and discard

**Files:** Modify chronicle/models.py, services.py, views.py, urls.py and web/templates/chronicle/staff_ops.html. Generate a named Chronicle migration. Create chronicle/test_moderation.py.

**Interfaces:** begin_correction(event_id, actor) -> draft returns the existing active draft on duplicate submission. revise_correction(draft_id, actor, expected_version, changes) -> replacement_draft preserves the prior draft as discarded history. discard_correction(draft_id, actor, expected_version) and publish_event(event_id, actor, expected_version) reject stale state. Keep a compatibility wrapper for current correct_event callers during transition.

- [ ] Replace supersedes OneToOne with ForeignKey, add discarded state and version/revision linkage, and add a conditional unique constraint for one active draft per original. Preserve every existing relationship and update reverse-relation callers explicitly.
- [ ] Add CorrectionDraftLifecycleTests: double begin returns one draft; concurrent begin yields no unhandled IntegrityError; edit preserves prior history; discard permits a new draft; stale edit/publish returns a clear conflict; redacted/superseded original cannot be replaced from an old form.
- [ ] Implement transitions in short transactions with conditional versions. Publication supersedes only the expected still-published original. Concurrency errors return an existing draft or HTTP 409, never a generic success or database traceback.
- [ ] Add discoverable edit/discard/resume controls and display which draft/version is being reviewed. Changing content requires review again; stale page submissions cannot approve replacement text.
- [ ] Run chronicle.test_moderation.CorrectionDraftLifecycleTests plus affected chronicle.tests and permission tests. Migration rehearsal covers originals with published, draft and redacted corrections.

## N4 — Transitive withdrawal and shared source eligibility

**Files:** Modify chronicle/models.py, services.py, read_services.py, generation.py, api.py and relevant views/templates; update narrative provenance/memory selection and MCP callers only to consume the shared policy. Generate a named Chronicle migration for withdrawal metadata and necessary lineage repair. Extend chronicle/test_moderation.py, chronicle/test_permissions.py and mcp_server/tests.py.

**Interfaces:** withdraw_dependents(source_ids, actor, reason) -> withdrawal report traverses source_events with a visited set and updates affected published/draft descendants. event_available(event, audience, account=None) -> bool and the corresponding queryset/projection helpers centralize publication, ownership and ancestry eligibility. Corrected-original linkage is historical lineage, not itself a claim that the original is valid prompt context.

- [x] Owner approved withdrawing dependent published recaps after source redaction/correction until staff review on October 23, 2026. Do not request this decision again.
- [ ] Add withdrawn state with actor/time/reason and a staff review queue under the approved policy. Withdrawing hides public/participant content and blocks generation; it does not claim staff-retained prose has been erased. Keep the separate derivative-erasure/retention decision explicit.
- [ ] Add DependentWithdrawalTests for A→B→C chains, shared ancestors, generated-event corrections, cycles/malformed edges, in-flight output, source-backed memories and fresh/warmed website/REST/MCP reads. Redacting A must immediately hide B/C in every player projection; a subsequent callback cannot republish them.
- [ ] Perform source redaction or correction publication and descendant invalidation consistently within record transactions. Explicit redaction erases the target and copied revision history; a correction retains historical source text. Do not restore withdrawn descendants merely because another source later becomes available.
- [ ] Route character_chronicle_for_account and all other direct queries through the same availability rules. Recheck ancestry at dispatch, response acceptance, correction publication and memory retrieval. A late ownership or authority change must fail closed.
- [ ] Reconstruct known generated-source edges from durable generation requests, including their correction revisions. Withdraw ambiguous legacy generated entries for review; record the ambiguity rather than invent links. Use an idempotent rehearsal and preserve event IDs/history.
- [ ] Require a new valid revision/generation and explicit staff publication to restore a withdrawn recap. Acknowledging an alert alone does not restore stale prose.
- [ ] Run DependentWithdrawalTests, affected Chronicle permission/generation tests and the shared MCP withdrawal tests. Q2 owns the final warmed-reader integration pass.

## N5 — Complete Builder persona and memory curation

**Files:** Create narrative/forms.py, narrative/curation.py and narrative/test_curation.py. Modify narrative/models.py/admin.py, chronicle/views.py/urls.py, web/templates/chronicle/staff_ops.html and new focused curation templates. Generate named migrations for version/revision and audit metadata.

**Interfaces:** register_persona(character, actor, profile), update_persona(persona_id, actor, expected_version, profile), create_memory_fact(actor, *, persona_id, subject_id, text, source_event_id, staff_entry, visibility, expires_at), revise_memory_fact(fact_id, actor, expected_version, changes), approve_memory_fact(fact_id, actor, expected_version), redact_memory_fact(fact_id, actor, expected_version). All return the persisted record or a typed validation/conflict/permission error; use staff_authorized consistently.

- [ ] Add PersonaCurationTests and MemoryCurationTests for a complete Builder workflow with is_staff=False, rejection of Django-only staff, player-character registration refusal, private-subject/provenance validation, expiry, stale edits, and approved-fact redaction through the rendered UI.
- [ ] Provide searchable/paginated persona registration/profile editing and memory draft/approved/withdrawn views. Every actionable record remains discoverable beyond the latest-page cutoff. Display provenance, scope, expiry, review identity and available actions.
- [ ] Edit approved facts by creating review drafts and revoking previous generation eligibility. Redaction clears text and sensitive staff provenance across that fact's revision history while preserving nonsensitive audit metadata. N4 source eligibility applies immediately to in-flight and resumed context.
- [ ] Share these transitions with Django admin or make managed fields read-only there. A direct admin status edit must not bypass text erasure/review. Keep current persona restrictions: persistent, account-less Character objects only.
- [ ] Do not add generated-memory suggestions or broaden the provider schema. Complete the established staff-authored workflow and explicitly document that scope.
- [ ] Run narrative.test_curation and chronicle.test_permissions once. Q1 exercises the actual pages, not just direct POSTs.

## Compatibility and rollback

Keep successful requests and sessions. Once multiple correction revisions exist, older one-to-one code cannot safely run; prefer a forward fix or a tested compatibility reader. Before reverting request-handling code, stop scheduling and terminalize in-flight rows so old recovery cannot repeat them. Never drop dispatch metadata or restore redacted content as an automatic rollback. Q3 owns populated migration and cross-package acceptance.
