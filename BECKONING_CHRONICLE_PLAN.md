# Beckoning Chronicle, Grounded Narrative, and Safe Agent Integration

## Resumption note - 2026-10-23

**Local work completed:** see the [completion report](docs/local-completion-2026-10-23.md) for the 399-test passing suite, completed feature/permission/integration checks, preserved WIP, and the separate unexecuted deployment gates. No commit, push, or deployment has been performed.

This is the original implementation plan. Most features were subsequently committed in `7045176` (Add Chronicle and MCP narrative services). The checkout and baseline described in stage 1 are historical. See [the resumption assessment](docs/resumption-2026-10-23.md) for current implementation gaps and verification evidence. Evennia test commands below were corrected to `--settings settings.py`; this launcher prepends `server.conf.` itself. The player API tests live in `chronicle.tests`, and narrative/MCP tests have their own modules.

## Goal and current-state findings

Integrate the research recommendations as one staged product: a source-linked, staff-governed Chronicle; durable and privacy-scoped NPC memory; optional, canon-grounded narrative assistance; useful player/staff read tools; and a hosted MCP interface. Close the disconnected character-creation path and verify the in-progress dice optimization before adding features.

The implementation must fit the existing Evennia 6.x / Django 6 application, its relational and `ObjectDB`/Attribute state, synchronous command dispatch, and game-loop ownership of Evennia world mutations. The live Django chargen at `/character-creation/` is the persisted creation/review route; the separately hosted VampSite currently has a disconnected client-side form that stores to localStorage and reports fake success. Boons, status, jobs, BBS, and builder each own distinct state and permission rules. The current `commands/v5/utils/ai_storyteller.py` is rule-based and process-local, not a live model-backed command. Hunting prey is generated as description/data rather than a persistent NPC. There is no installed LLM, vector database, task queue, or project-wide OAuth/token service.

Use an incremental transition ledger and read projections; do not migrate all game state to event sourcing. For safety, never allow model output or agent tools to roll/adjudicate dice, change Hunger or character state, approve content, invoke arbitrary commands, or mutate Evennia objects. Keep the ordinary deterministic hunt/feeding path fully functional without an AI provider.

## Settled product and deployment decisions

- **AI provider:** provider-neutral adapter; first wire protocol is OpenAI-compatible Chat Completions at a configured endpoint, not a vendor SDK. Server validates strict JSON responses itself. Provider is disabled until configured. Store credentials only in deployment environment/`server/conf/secret_settings.py`; never persist or log secrets/prompts. Player-facing AI use is opt-in and clearly attributed.
- **Chronicle publication:** public items are published by staff only. Private and staff-only facts remain scoped to their authorized participants/staff and are never promoted by a model.
- **Player agent:** hosted MCP over HTTPS, implemented as a companion ASGI process using the official MCP Python SDK. Bind it to localhost behind the public TLS reverse proxy. Use OAuth 2.1 authorization-code flow with PKCE, resource-bound tokens, scopes, and account/character ownership checks.
- **Static chargen destination:** read the canonical public game origin from deployment configuration at release; never invent or hardcode an unknown domain. A missing value must fail closed and block publication of a redirect.
- **Stable NPC identity:** memory belongs to an authored, persistent Evennia object identity (`ObjectDB` id/dbref), not generated prey, a prototype name, room, or faction. Register eligible persistent account-less `Character` objects as narrative personas; do not create an incompatible second NPC identity system.

## Ordered implementation plan

### 1. Preserve and verify the active dice work first

The checkout was observed on `e5e4e25`, parent/pre-optimization baseline `0885bfc`, with local modifications in `autoresearch.sh` and `dice/roll_result.py`. Preserve both; do not reset, stash, or overwrite them. Before integration work, compare the focused behavior tests on the parent source and current source using the same installed environment. Extract the baseline to a temporary directory (no branch checkout), set `PYTHONPATH` to that directory while running its test, then run the same target from the working tree. Run `dice.tests.RollResultTestCase` and `dice.tests.DiceRollerTestCase` with `--settings settings.py`. Record the same baseline/current failures and investigate any changed behavior; do not treat the repository's known unrelated test failures as new regressions. Check that `RollResult` semantics, including reroll and Hunger/critical classification, are unchanged; add only behavior-focused tests for any uncovered regression found. Keep the experiment harness line endings stable on Windows if that is the cause of its observed dirty change.
PowerShell baseline/current comparison (from the repository root; preserve the existing checkout):

```powershell
$repo = (Resolve-Path .).Path
$baseline = Join-Path $env:TEMP "beckoning-0885bfc-$PID"
New-Item -ItemType Directory -Path $baseline | Out-Null
git -C $repo archive 0885bfc | tar -xf - -C $baseline
$env:PYTHONPATH = $baseline
Push-Location $baseline
& "$repo\.venv\Scripts\evennia" test --settings settings.py dice.tests.RollResultTestCase
$baselineResult = $LASTEXITCODE
& "$repo\.venv\Scripts\evennia" test --settings settings.py dice.tests.DiceRollerTestCase
$baselineReroll = $LASTEXITCODE
Pop-Location
$env:PYTHONPATH = $repo
& "$repo\.venv\Scripts\evennia" test --settings settings.py dice.tests.RollResultTestCase
$currentResult = $LASTEXITCODE
& "$repo\.venv\Scripts\evennia" test --settings settings.py dice.tests.DiceRollerTestCase
$currentReroll = $LASTEXITCODE
Remove-Item Env:PYTHONPATH
```

Compare all four exit codes and test failure sets; a baseline failure is not a regression unless the current failure set changes. The temporary archive is isolated from the working tree; no checkout, reset, or commit is involved.

 
 

### 2. Make the persisted Django chargen the sole submission path

Keep the authenticated Django flow and approval APIs as the canonical implementation; do not clone or port chargen rules into the static JavaScript. Remove the static page's localStorage/fake-success submission behavior. Change both the current static CTA and legacy creation URL to reach `/character-creation/` on the canonical site. Generate/read that destination from one deployment value (`PUBLIC_GAME_BASE_URL`) and expose the corresponding value to the static site through its deployment config. If it is absent, render a clear unavailable state and do not claim submission succeeded; release acceptance requires it to be configured and a redirect tested from the real static host. Update the static README and player news/help that currently point to the obsolete route or wrong port. Add the staff approval link to the existing staff navigation and verify the rejected-edit/resubmit and approval path still uses the existing API.

### 3. Add a Chronicle app and append events at committed domain transitions

Create a `chronicle` Django app and migrations; add it through the existing `INSTALLED_APPS` convention. Implement an append-oriented `ChronicleEvent` with: source app/type/id, event kind, actor, occurred/created timestamps, participant `ObjectDB` relations, visibility (`public`, `participants`, `staff`), allow-listed structured payload, publication state (`draft`, `published`, `redacted`), publisher/time, and correction/supersession linkage. Never copy arbitrary private comments, staff notes, or raw BBS content into the payload. Keep correction history; redaction removes displayable sensitive payload while preserving minimal audit metadata. Public projection must require both public visibility and staff-published state; participant projection requires owner access to a linked character; staff projection requires staff permission.

Emit events only after the authoritative transition succeeds, using domain service boundaries rather than templates or command output: `boons/utils.py`, `status/utils.py`, `jobs/commands.py`/the job transition service, and `web/builder/promotion.py`. Include only relevant state transitions, not every read/comment. For BBS, add only explicitly IC/public, allow-listed post metadata and still leave it unpublished until staff approval. Add a staff-authored event path for curated scenes. A failed builder promotion emits no success event; reconcile partial promotion failures through the existing review state rather than claiming it completed. Preserve each source app's current permission rules and use the source records as authority; Chronicle is a projection/audit feed, not a second mutable source of game state.

Add `ChronicleReadService` functions for public, participant, and staff projections. Add deterministic tests for publication gating, corrections/redactions, owner isolation, source visibility, and successful versus failed transitions. Verify a duplicate delivery cannot create a second event for the same transition by using a stable transition idempotency key at the event-emission boundary.

### 4. Deliver player Chronicle views and staff story operations

Add a public `/chronicle/` view showing only staff-published public events and an authenticated “my Chronicle” projection that adds only that account's participant-visible entries. Use the project's existing Django templates and Bootstrap layout. Expose read-only session-authenticated endpoints under `/api/player/` for public Chronicle, the authenticated character's own summary/status/boon overview, and its participant Chronicle. Every endpoint is GET-only, rejects anonymous access to personal data, resolves character ownership from the current account, and has no staff bypass to another user's data.

Add staff-only `/staff/narrative-ops/` views using the existing staff-review patterns (`web/templates/character_approval.html`, `web/templates/builder/review.html`, and their shared base). Staff can publish, correct, redact, and review source-linked drafts. Provide a deterministic inconsistency report by comparing a boon's stored ledger with the existing recalculation result; never auto-correct records. Any AI recap/rumor appears as a draft with source event IDs and explicit attribution, and only staff can publish it. Test public/player/staff permissions and the full draft→publish/correct/redact sequence.

### 5. Replace process-local storytelling with durable scoped state and grounded optional generation

Add `NarrativePersona`, tied one-to-one to a persistent `ObjectDB`, and a staff-only registration/profile editor restricted to persistent account-less `Character` objects. Add `MemoryFact` records with persona, optional subject character, text, provenance (`ChronicleEvent` or staff entry), visibility (`public`, `private-to-subject`, `staff`), status (`draft`, `approved`, `redacted`), and optional expiry. A private fact is retrievable only in a scene for that exact character; staff-only facts are not sent to player-facing generation. Generated hunting prey is never silently registered as a persona.

Add durable `StorySession` records for active narrative hunts and `StoryGenerationRequest` records for asynchronous work. A session saves only the state needed to resume, structured deterministic outcomes, and short-lived player action text; expire raw action text when the session completes, retaining approved facts/events only. Enforce one active session per character. Connect the live `CmdHunt` via an explicit `+hunt/story` switch; ordinary `+hunt` stays deterministic. Reuse the real resolution path in `commands/v5/utils/hunting_utils.py` and the existing dice/blood mechanics. Compute deterministic outcomes first; send only the minimum authorized context and untrusted player text to the provider. AI may draft prose or a sourced memory suggestion, never state changes; memory suggestions remain staff-review drafts.

Implement a small `NarrativeProvider` interface and an OpenAI-compatible HTTP implementation. Require strict response JSON, validate expected fields and that every cited source ID was in the authorized prompt, then reject invalid output. Do not add vector storage or a separate job system: retrieve a bounded set of approved/relevant source facts directly from indexed relational rows. Keep provider calls non-blocking: persist a request, marshal scheduling to the Evennia reactor with a non-blocking bridge helper, perform HTTP I/O asynchronously with Twisted `Agent`, and persist the validated result on the reactor/game thread. Never send live Evennia objects into a worker. On startup, resume pending durable requests; provider failure leaves a visible failed request and deterministic hunt remains available. No automatic retries or automatic publication.

Add tests for session resume and completion, deterministic outcome invariance, provider-disabled behavior, provider failure/invalid JSON/untrusted citations, opt-in, subject scoping, expiry, and proof that an unauthorized private fact never enters another character's prompt or result. Smoke the actual `+hunt/story` command with the provider disabled and configured against a local test endpoint.

### 6. Expose least-privilege read tools and hosted MCP

Keep all business/visibility checks in the shared read service; do not let the MCP process query unrestricted objects or invoke commands. Add precisely read-only tools: `get_my_character_summary`, `get_my_status_and_boons`, `get_public_chronicle`, `get_my_chronicle`, and `get_public_lore`. Do not accept account IDs; any optional character identifier must be resolved and ownership-checked against the OAuth subject. Return only approved public lore and authorized character projections.

Use Django OAuth Toolkit 3.4+ (the project-compatible release) for OAuth authorization and metadata; it documents MCP authorization support, PKCE-by-default and protected-resource metadata. Add scopes `character:self:read`, `chronicle:read:public`, `chronicle:read:self`, and `lore:read:public`; issue resource/audience-bound, expiring tokens and support revocation. Register supported MCP clients through controlled registration initially; do not issue static bearer keys. Add a separate ASGI entry point using the official MCP Python SDK Streamable HTTP transport, with the SDK's auth middleware/token-verifier bound to the Django token authority. Validate issuer, audience/resource, expiry, subject, and scopes for each tool. Validate `Origin` and return 403 for invalid origins; serve HTTPS only in production. Bind the service to `127.0.0.1:8001` and configure the public TLS reverse proxy to route the configured `/mcp` endpoint and OAuth/protected-resource metadata to their owning services. Use `MCP_PUBLIC_URL` for the external resource URL. Do not announce remote availability until the proxy, TLS, OAuth discovery, and origin checks work end-to-end.

Add the official `mcp` SDK, `uvicorn`, and `django-oauth-toolkit>=3.4,<4` to `pyproject.toml`, refresh `uv.lock` with `uv sync`, and verify package compatibility with the repository's Django 6.0 version. Do not add a provider-specific LLM SDK.

Add tests for valid and invalid OAuth tokens, wrong audience/expiry/revocation, missing scopes, account/character crossover, GET-only REST behavior, invalid Origin, and denial of all writes/arbitrary commands. Use an MCP SDK client against the deployed HTTPS endpoint to initialize, authorize, and call each read tool as two separate accounts; verify the other account's character and all private facts are absent.

### 7. Roll out, document, and verify end to end

Add app migrations and run them with the repo's actual settings. Update existing player-facing help/news and `web/website/VampSite/README.md` to point to canonical chargen, Chronicle, AI opt-in/provider limitations, and the read-only agent boundary; keep ports consistent with the actual deployment. Update the project's existing release/changelog convention if one exists; do not add duplicate help keys for commands.

Run focused checks after implementation:

```powershell
uv run evennia test --settings settings.py dice.tests.RollResultTestCase
uv run evennia test --settings settings.py dice.tests.DiceRollerTestCase
uv run evennia test --settings settings.py chronicle.tests
uv run evennia test --settings settings.py narrative.tests mcp_server.tests
uv run evennia test --settings settings.py .
uv run ruff check .
uv run ruff format --check .
```

Capture `uv run evennia test --settings settings.py .` before feature work as the full-suite baseline, then rerun it after; compare failure sets. Run `uv run evennia makemigrations chronicle` and `uv run evennia migrate` (plus named app migrations only if models there changed). Launch the game and companion service with `uv run uvicorn web.mcp_service:app --host 127.0.0.1 --port 8001` behind the configured TLS reverse proxy, then exercise `MCP_PUBLIC_URL`, OAuth discovery, and tool calls with an MCP SDK client. Verify from the real static-host URL that chargen reaches Django and creates a pending `CharacterBio`; staff can approve it; a source transition appears privately as a draft then publicly only after staff publication; another account cannot see participant details; corrected/redacted items disappear from player projections; `+hunt/story` resumes safely and never alters dice/Hunger through model output; and the remote client is denied every write.

## Research references

- MCP Streamable HTTP transport, current revision: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- MCP authorization and OAuth resource protection: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index
- Official MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Django OAuth Toolkit MCP support (3.4+): https://django-oauth-toolkit.readthedocs.io/en/latest/
- Ollama's OpenAI-compatible API subset (wire-compatibility example; do not assume identical provider capabilities): https://docs.ollama.com/api/openai-compatibility
- Evennia TickerHandler guidance: https://www.evennia.com/docs/latest/Components/TickerHandler.html
- Retrieval-Augmented Generation: https://arxiv.org/abs/2005.11401
- Generative Agents (memory/reflection/planning reference): https://arxiv.org/abs/2304.03442
- Market context reviewed: https://mudai.app/en and https://clawmud.ai/
