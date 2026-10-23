# Chronicle work resumption - 2026-10-23

**Historical checkpoint:** the subsequent [local completion report](local-completion-2026-10-23.md) supersedes the implementation gaps and failing-suite status below. The original baseline/result files remain unchanged as evidence.

The branch was implementing the [Chronicle, narrative, and safe agent plan](../BECKONING_CHRONICLE_PLAN.md). Most of that work was already committed in `704517626bb40bf66633f4bbac8689b7fe21052f` (`Add Chronicle and MCP narrative services`, October 4). The uncommitted plan still described the earlier `e5e4e25` checkout. The other original changes were import/comment/spacing cleanup in `autoresearch.sh` and a blank line in `dice/roll_result.py`; neither changed dice behavior.

Estimated implementation completeness on arrival: **about 80%**. After this resumption, **about 85% of the local implementation** is present. These are engineering estimates against the seven-stage plan, not measured test coverage or a claim of production readiness. External rollout acceptance remains incomplete.

| Plan area | Current position | Remaining acceptance work |
| --- | --- | --- |
| Dice optimization | Complete for the targeted behavior comparison | No dice changes needed in this resumption |
| Canonical chargen | Django remains canonical; static pages fail closed | Configure the real origin and test static-host redirect, pending creation, rejection/resubmission, approval |
| Chronicle capture | Models, migrations, committed transition hooks, publication/corrections/redaction exist | More domain-transition tests for jobs, BBS exclusions, and builder success/partial failure |
| Chronicle views/staff tools | Public/personal projections, staff operations, safe read APIs exist | Source-linked AI recap/rumor drafting remains absent; broader view permission tests |
| Narrative | Durable sessions, opt-in, scoped memory, async provider, recovery, provenance checks | Actual command-to-local-provider smoke and approved deployment-provider qualification |
| Hosted MCP | Five read tools, OAuth/PKCE, resource/scopes, ownership, Host/Origin enforcement | Real two-process freshness and deployed HTTPS/proxy/discovery/client acceptance |
| Rollout/docs | Local checks and evidence captured; historical plan commands corrected | Production migrations/configuration and full real-host acceptance |

## Work resumed

- Narrative requests reload pending status, session state, and consent at actual dispatch. A queued opt-out prevents outbound provider calls. Context provenance covers all supplied facts, including uncited and inherited facts; changed/revoked/expired context is rejected before accepting a response. Legacy or unauthorized derived prose is omitted from subsequent prompts. No hunt mechanics are re-executed.
- Chronicle event creation and its initial relations are atomic. Duplicate transition deliveries cannot add participants or source links to an existing event.
- Staff-authored memory redaction clears sensitive text while retaining a fixed nonsensitive provenance marker, satisfying the existing database constraint.
- Character summaries read persisted scalar values rather than process-local Evennia caches, including character Attributes, status, position, and boon totals. Ownership checks use persisted state. Tests retain stale caches while simulating another process's writes.
- Added real local OAuth authorization-code/PKCE issuance tests that call all five SDK tools as two accounts, deny foreign characters and arbitrary commands, and verify revocation, incorrect verifier rejection, and resource escalation denial.

No models or migrations changed. No commit, push, provider credential configuration, live game launch, or production migration was performed. The original dice/harness edits were preserved byte-for-byte.

## Verification and limits

The machine-readable [baseline](verification/2026-10-23/baseline.json) records the initial head, original WIP hashes, and all initial failing test identities. The [final result](verification/2026-10-23/result.json) records the comparison, environment, feature-test counts, and source hashes.

Final frozen suite: **311 tests, 15 failures, 66 errors** in 289.838 seconds. The failing test identities and failure/error classifications exactly match the baseline: **no new failing tests**. All **75 Chronicle, narrative, and MCP tests passed**, including **27 newly added regression/integration tests**. Scoped Ruff lint/format checks and diff whitespace checks passed. The repository-wide suite is still not green.

- Pre-optimization `0885bfc` and working-tree dice suites: **23 tests passed on each**. Both benchmark runs retained checksum `144143`. Single timing samples were approximately 345k versus 374k rolls/second while other tests ran; this is not a rigorous performance result. The shell harness passed Bash syntax checking and already used LF line endings.
- Full pre-edit suite: **284 tests, 15 failures, 66 errors**. Initial failures are in legacy jobs, dice disciplines, character/blood behavior, and trait tests; none are in the Chronicle, narrative, or MCP modules.
- Initial global lint: **514 errors**; format check: **101 files** would change. Broad reformatting and unrelated legacy repairs are outside this resumption. Modified Python files receive scoped lint/format checks.
- Named Chronicle/narrative migration dry-run: no missing model migrations. No deployment database migration was applied.
- Local loopback HTTP provider smoke: real Twisted requests handled valid output, HTTP 503, and malformed JSON. This checks transport only, not the complete live hunt command or an external provider.
- Independent source review accepted the bounded repairs; local checks do not establish deployed TLS, proxy, browser-origin, or separate-process behavior.

Use `.venv/Scripts/evennia.exe test --settings settings.py ...`. The plan's old `--settings server.conf.settings` is expanded by this launcher to `server.conf.server.conf.settings` and exits **0 without running tests**. Verify `Ran ... tests` and `OK`/failure output, not just the process exit code. The direct read-only migration check used:

```powershell
.\.venv\Scripts\python.exe -m django makemigrations chronicle narrative --settings server.conf.settings --check --dry-run
```

The Evennia management-command launcher attempted interactive superuser bootstrap on the unconfigured local database, so it was not used for schema inspection. The local deployment has no `secret_settings.py`.

Installed Django OAuth Toolkit correctly rejects resource escalation with HTTP 400 and an `invalid_target` JSON body, but that exceptional response has an HTML Content-Type. The test verifies the rejection and lack of token issuance; error-response MIME interoperability remains a dependency-level follow-up.

## Files changed in this resumption

- `chronicle/services.py`, `chronicle/read_services.py`, `chronicle/views.py`, `chronicle/tests.py`
- `narrative/services.py`, `narrative/tests.py`
- `mcp_server/test_oauth_flow.py`
- `BECKONING_CHRONICLE_PLAN.md` (historical annotation and corrected test commands)
- This assessment and `docs/verification/2026-10-23/` evidence summaries

Original `autoresearch.sh` and `dice/roll_result.py` modifications remain uncommitted and untouched by this resumption.
