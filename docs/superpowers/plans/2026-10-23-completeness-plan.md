# Game Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. User authorization and Agent Policy override skill defaults about commits or additional agents.

**Goal:** Close all fourteen audit findings and eight additional capability/acceptance gaps while preserving existing player data and working behavior.

**Architecture:** Repair the existing command, service and web boundaries without replacing the game's architecture. Use canonical Character accessors, versioned review records, bounded asynchronous requests and explicit compatibility operations. Split independent systems into four implementation packages, then qualify their combined browser/game/MCP journeys.

**Tech Stack:** Python 3.12+, Evennia 6.x, Django 6, Twisted, SQLite, vanilla browser JavaScript, django-oauth-toolkit and the MCP SDK; retain the repository lockfile and supported dependency ranges.

**Spec:** [Completeness scope and acceptance contract](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-spec.md). Baseline `34bb52f3cbd374dd657fd82c4edfd1db837027fe`; the exact-commit existing CI passed, but the audit reproduced uncovered failures.

## Global Constraints

- Owner-approved scope: complete the advertised features and withdraw dependent published recaps after source redaction/correction until staff review. Local implementation was authorized by "proceed" on October 23, 2026.
- Implement and verify locally. Do not commit, push, merge, deploy or modify production data without the corresponding instruction.
- "Preserve existing work in progress and do not overwrite unrelated changes."
- "Plan relevant verification before editing. Run each planned check once. Re-run only the affected failed check after a supported fix; do not repeat successful checks. After two different failed repair attempts, return the evidence and escalate."
- Apply every invariant and approved decision in the spec, and keep remaining proposed policies clearly distinguished. Do not silently replace a confirmed defect with a smaller documentation-only deliverable.
- Use Evennia's runner, not pytest. Require the runner's actual OK summary and expected test discovery; the launcher can exit zero after settings failure.
- Never run bare makemigrations. Name only changed applications. Never migrate the existing game database during automated acceptance.
- Local source checks use changed paths; do not reformat the whole repository. Dependency changes need a concrete requirement, not a speculative upgrade.

## Review Focus

- Legacy, partially malformed and Evennia-wrapped Attributes must not lose data or crash after repair: G1/G2 compatibility tests and Q3 rehearsal.
- Double submits, stale views and late asynchronous callbacks must not double-charge, redispatch, republish or overrule newer state: G1, W1/W3, N1–N3.
- Source withdrawal, ownership transfer and permission revocation must take effect in warmed readers and in-flight work: N2/N4 and Q2.
- Interrupted build/replacement/casting must preserve the prior world and distinguish indeterminate effects from safe-to-resume work: W3/W5, G4, Q3.
- Real controls and commands must expose the data tested by services, including keyboard access and escaping: W1/W2, N5, S1/S2 and Q1.

## Work packages and ownership

| Package | Tasks | Primary ownership | Plan |
| --- | --- | --- | --- |
| Gameplay and rules | R0, G1–G5 | Character/accessor rules, effects/combat/rolls, XP, rituals, hunt command | [Gameplay plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-gameplay.md) |
| Builder and character review | W1–W5 | Builder models/services/templates, room rules, review export/rendering | [Builder/review plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-builder-review.md) |
| Narrative and Chronicle | N1–N5 | Provider transport, durable requests, moderation, provenance, curation | [Narrative plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-narrative.md) |
| Social workflows | S1–S3 | Boon details/discovery/permissions, Status presentation | [Social plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-social.md) |
| Integration and acceptance | M0, Q1–Q4 | Coordinator, cross-package contracts, acceptance evidence | This file |

Use one or two workers normally. Routine UI/formatter tasks fit implementation_worker; economic state, async persistence, data compatibility and destructive-world lifecycle changes require sol_engineer. Use sol_reviewer for those consequential changes. Use luna_worker for inventories and evidence. The coordinator owns completion and resolves shared-file ownership before dispatch.

Explicit shared-file boundaries: gameplay owns world/v5_data.py and commands/v5/utils/hunting_utils.py. W4 supplies its room-context interface after G5, then makes the agreed hunting call-site change serially. Narrative owns narrative/models.py/services.py and Chronicle models. G5 owns commands/v5/hunt.py and consumes the agreed versioned outcome shape. One worker owns all builder lifecycle files at a time. Coordinator integrates command registration and combined help checks.

## Sequence and dependencies

1. M0 freezes the baseline and verification ledger. R0 inventories rules and settles only the decisions needed for each dependent task.
2. Start W1, W2, S1/S3 and N1 while gameplay develops G2/G1. No dependency on a new game rules decision is required to repair lost form data or missing review fields.
3. G3 follows G2 and the relevant R0 decisions; G4 follows G2 and ritual decisions. G5 coordinates its outcome contract with N1/N2. S2 follows S1's shared visibility helper.
4. N2 follows N1; N3 can proceed independently; N4 follows N3's lineage model; N5 uses N4's shared eligibility rules.
5. W3 implements immutable revision creation before W5 catalog placements. The live replacement portion of W3 follows W5 so its manifests include fixtures. W4 follows room-policy signoff and G5's hunting boundary.
6. Q1 and Q2 qualify the integrated journeys; Q3 performs frozen migration/full-suite/review acceptance; Q4 is external qualification after explicit operational authorization.

Each task ends with its focused evidence and a reviewable local diff. Do not commit as an automatic task step.

## Audit-to-task traceability

| Audit item | Owner task | Required closure evidence |
| --- | --- | --- |
| F01 | G1 | Purchase-to-activation plus zero-cost legacy entitlement repair |
| F02 | W1 | Actual editor create/edit/delete to engine journey |
| F03/F04/F05 | G2/G3 | Real power/Alchemy activation to effect consumers and impaired rolls |
| F06 | W2 | Current persisted choices visible in staff browser review |
| F07/F08 | N1/N2 | Bounded hanging transport and dispatch/restart races |
| F09/F10 | N3/N5 | Repeated correction lifecycle and approved-memory redaction through UI |
| F11/F12 | S1/S2 | Complete authorized case record and all-page debt discovery |
| F13 | G5 | Deterministic result visible despite every provider failure mode |
| F14 | N4 | Transitive withdrawal across website, REST, MCP, memory and in-flight work |
| A01/A02/A03 | W5/W4/W3 | Catalog placement lifecycle; accepted room semantics; immutable/live revisions |
| A04/A07 | G4/R0 | Persistent ritual execution and itemized rules acceptance |
| A05/A06 | S3/N5 | Honest Status wording and complete Builder curation |
| A08 | Q1/Q2/Q4 | Browser/game journeys, refresh lifecycle and external qualification |

## M0 — Baseline, reproduction and verification ledger

**Files:** Create docs/acceptance/completeness/ledger.md and compatibility-inventory.md during implementation. Read existing audit artifacts, CLAUDE.md, tests/support/README.md and the installed/locked runtime. Do not copy secrets or the live database into the repository.

**Interfaces:** The ledger records task/test label, source revision/diff, expected behavior, actual result, log location, data-repair status and remaining gate. A check has one owner; a focused check may later be included once in the integrated suite because that validates a new combined state.

- [ ] Confirm current HEAD, status, worktrees and any drift from the audited tree. Preserve WIP; select an isolated codex/ implementation branch/worktree if execution is requested.
- [ ] Record available runtime/dependencies and current CI evidence. Revalidate only findings whose source changed since the audit; do not repeat the entire old audit or full suite by default.
- [ ] Convert each audit reproduction into a correct-behavior regression in its owning task. Do not check in tests asserting that the bug should continue.
- [ ] Register exact planned check labels before edits. New assertions may fail once as the reproduction stage, then pass once after the supported repair; other successful checks are not repeatedly rerun.
- [ ] Inventory legacy shapes using fixtures first. Prepare read-only production inventory tools, but do not access live data until separately authorized.

## Q1 — Real local browser and game-session acceptance

**Files:** Extend tests/support/local_runtime.py only for reusable disposable fixtures; create tests/support/completeness_e2e.py and docs/acceptance/completeness/browser-game.md. Keep browser automation dependencies in a separate optional development harness if a new runner is necessary; prefer available browser tooling for the first recorded pass.

**Interfaces:** An explicit harness mode starts an isolated Evennia Server/Portal and local static host with unique loopback ports, disposable DB/logs, fake provider and known fixture accounts. A lease/manifest records only processes and paths created by that run. It never falls back to the normal game DB/ports and terminates only its own processes. Readiness probes and teardown have bounded deadlines.

- [ ] Create player A, player B, Builder without Django is_staff, Admin, Harpy and NPC fixtures. Confirm the isolated DB/ports before starting services.
- [ ] In an actual browser, follow the static CTA to chargen; submit normal/Blood Sorcery/Alchemy sheets; reject/edit/resubmit/approve, then revoke a played character and resubmit without resetting XP. Inspect all review details and verify unrelated-account denial.
- [ ] Exercise builder modal authoring, project save/reload, independent review, sandbox build, walk/look/timed actions, fixture placement, safe cleanup, revision review and permitted replacement. Verify stale versions, owner restrictions, escaping and keyboard access through the UI.
- [ ] Through actual game sessions, exercise purchase/select/activate/attack; Alchemy display/remove; impaired power rolls; ritual start/restart/finish; hunt result with provider success, failure and timeout; boon offer/accept/call-in/dispute/detail/pagination.
- [ ] Through Story Operations, register NPC persona, author/approve/edit/redact memory, generate/publish/correct a recap, redact its ancestor and verify disappearance from every authorized player surface.
- [ ] Capture outcome assertions and minimal screenshots/transcripts without credentials/private prompts. Re-run only a failed journey after its supported repair. API or simulated-DOM checks alone cannot satisfy this task.

## Q2 — OAuth refresh and MCP client qualification

**Files:** Extend mcp_server/test_oauth_flow.py, mcp_server/test_process_freshness.py and tests/support/local_runtime.py; create mcp_server/test_client_authorization.py for the loopback SDK flow. Preserve current controlled client registration.

**Interfaces:** Use actual DOT endpoints and the installed MCP SDK OAuth client provider with a manually registered disposable client. Token storage is fixture-local; no DCR/CIMD expansion. Inspect installed APIs before implementation rather than guessing version-specific calls.

- [ ] Add OAuthFlowTests cases for refresh rotation preserving resource/scope, widening rejection, configured expiry/reuse protection, wrong-client rejection, logout/revocation preventing reissuance and access with old tokens. Use fixture timestamps rather than waits; explicitly establish the intended policy in test settings.
- [ ] Test discovery, authorization state/PKCE, exact redirects and issuer/resource binding through a real loopback transport; run all read tools as two accounts. Reject foreign ownership, disallowed host/origin and any write capability.
- [ ] Verify ownership transfer and N4 withdrawal with warmed MCP readers. If existing checks already cover unchanged behavior, retain them for the combined suite rather than rerunning ad hoc.
- [ ] Run: .\.venv\Scripts\evennia.exe test --settings settings.py mcp_server.test_oauth_flow mcp_server.test_client_authorization mcp_server.test_process_freshness. Require actual discovered tests and OK. Local HTTP does not qualify public TLS/proxy routing.

## Q3 — Frozen integration, migration and independent review

**Files:** Changed application migrations, compatibility tools, docs/acceptance/completeness/ledger.md and release-runbook.md. Generate migrations using the repository tools; never manually invent migration numbers before inspecting the current graph.

- [ ] Freeze a reviewable local diff after focused task gates. Run ruff check and ruff format --check on changed Python paths only. Resolve new issues without repository-wide formatting.
- [ ] Run named-app makemigrations --check --dry-run for every changed model app; require no drift. Rehearse the generated migration chain on populated disposable old-schema fixtures, not only an empty DB.
- [ ] Verify legacy pending requests fail as indeterminate, correction links/history remain valid, ambiguous ancestry is withdrawn, old projects keep their identity, missing powers do not charge XP, and repeated compatibility operations are no-ops.
- [ ] Inject failures into XP commits, dispatch completion, sandbox build and live replacement. Verify fresh persisted reads and already-cached objects agree after rollback/compensation. Destructive steps must refuse unexpected objects, occupants or stale identity.
- [ ] Run the combined local HTTP acceptance, help integrity, client JavaScript and static-site checks as part of the appropriate final gate. Static command: node --test web/website/VampSite/tests/game-link.test.cjs.
- [ ] Run the full suite once on the frozen combined state using the command below. Capture the test count and actual OK/FAILED summary. A later source fix invalidates only affected evidence unless its impact requires another integration run.

```powershell
.\.venv\Scripts\evennia.exe test --settings settings.py .
```
- [ ] Obtain independent sol_reviewer review of economic state, authorization, request races, provenance, migrations, builder destruction/compensation and the acceptance ledger. Resolve material findings before marking local implementation complete.
- [ ] Reconcile every F/A row with evidence. Report local, rules, CI and external gates separately. Do not mark unresolved owner rules or live qualification complete.

## Q4 — Operational qualification and release handoff

**Files:** docs/acceptance/completeness/release-runbook.md, settings examples and static-site deployment instructions. Do not put actual secrets, client tokens or deployment origins in tracked fixtures.

- [ ] Prepare a reviewed compatibility dry-run and backup/rollback procedure. For SQLite, stop the writer before a consistent backup. Live data repair/replacement is an explicit operational action, not a test side effect.
- [ ] Document forward-fix boundaries: old code must not run recovery on new dispatched rows; old one-to-one correction code cannot handle multiple historical drafts; removed sensitive text must not be restored automatically. Preserve new columns/history during a code rollback.
- [ ] After separate operational authorization, qualify one approved provider, public HTTPS/proxy routing, exact issuer/resource/host/origin/callback values, static-host redirects, browser consent, refresh and revocation with an external SDK client.
- [ ] Bound provider requests and retain only sanitized results/request identifiers. Confirm failed-provider operation still leaves deterministic gameplay usable.
- [ ] Before any later commit/push/deployment, review the concrete diff and evidence within that authorization. CI on an earlier commit is not evidence for the final implementation.

## Definition of done

Local completion requires all task acceptance checks, legacy-data tooling/rehearsal, actual local browser/game acceptance, independent review and the frozen combined suite. Full operational completion additionally requires accepted rules decisions, executed authorized data remediation where necessary, exact-final-revision CI and external qualification. The final report must name any gate still open; no whole-game percentage is inferred from test counts.
