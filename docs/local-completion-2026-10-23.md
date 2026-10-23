# Local completion — 2026-10-23

This continues the [initial resumption assessment](resumption-2026-10-23.md) and implements the remaining local work in the [Chronicle plan](../BECKONING_CHRONICLE_PLAN.md). The earlier assessment and its baseline/result JSON remain historical evidence. The original `autoresearch.sh` and `dice/roll_result.py` changes are preserved byte-for-byte. Nothing has been committed, pushed, or deployed.

## Implementation

| Area | Completed local work |
| --- | --- |
| Canonical chargen | Full create → reject → edit → resubmit → approve lifecycle, actual trait/power persistence, structured instances/specialties, gameplay stat and derived-pool synchronization, atomic failed imports, playable roster/locks only on approval, fresh ownership and staff authority, and game-thread web writes. |
| Static entry points | `build_public_site_config` generates the static assignment from Django's `PUBLIC_GAME_BASE_URL`; empty configuration fails closed and invalid configuration preserves existing output. The checked-in origin remains blank. |
| Transition capture | Jobs, BBS exclusions, status, and builder success/failure coverage. Repaired per-bucket concurrent job numbering, status rollback caches, destructive promotion cleanup, tag-only discovery, and promotion dispatch/finalization timing. |
| Staff Chronicle operations | Durable, idempotent recap/rumor requests from bounded public/published sources, including provenance ancestry and freshness checks. Provider output creates attributed drafts; publication remains a separate staff action. Interrupted dispatched requests fail closed without automatic retry. |
| Permissions | Real Django-client role, ownership, publication, method, CSRF, and private-content leakage matrices across HTML and REST routes. |
| Narrative integration | Actual hunt command and dice/blood mechanics against a loopback Twisted HTTP provider, including delayed responses, heartbeat evidence, disabled provider, failures, output rejection, and no second mechanics resolution. |
| MCP integration | Real local OAuth/PKCE and SDK tools plus cached-reader freshness and ownership-transfer tests with a genuinely separate database writer process. MCP transport in that freshness test is in-process ASGI. |
| Legacy test failures | Repaired real blood/rouse/parser/job/trait defects and obsolete test fixtures rather than suppressing failures. |

The browser edit flow preserves predator bonuses, priority choices, instance/specialty text, saved skill specialties, and learned powers. Existing multiple-instance sheets that the single-instance form cannot represent are explicitly blocked with staff-help guidance instead of silently losing data. Backend validation remains authoritative when a changed trait no longer supports a retained power or specialty.

Web and status failure paths restore affected Evennia cached fields after SQL rollback, including retained Attribute identities and relation caches. They do not claim general rollback handling for arbitrary unrelated callers that roll back a transaction after a successful operation.

## Verification

Final combined Python suite: **399 tests passed, zero failures/errors, in 308.481 seconds**. All 81 failing cases from the initial 284-test baseline are resolved. See the [completion evidence](verification/2026-10-23/local-completion.json) and [full run log](verification/2026-10-23/full-local-completion.log).

Estimated completion is now **100% of the scoped local implementation and acceptance work**, up from approximately 80% on arrival. This is an engineering assessment against the plan, not measured test coverage or a claim of deployment readiness.

- Targeted tests passed for staff generation, domain transitions, concurrent numbering, status cache restoration, blood compatibility, import/export, chargen lifecycle and rollback, current ownership, and dispatch into a real Twisted reactor from a worker thread.
- JavaScript: **15 distinct Node VM tests passed** across the static entry-point tests and chargen edit/submission tests. These exercise the actual scripts and handlers with DOM fixtures; they are not a deployed-browser acceptance claim.
- Scoped Ruff lint and format checks passed for **44 changed Python files**, excluding the original untouched dice WIP and Django-generated migration. Source whitespace checks passed.
- Migration drift check for `chronicle narrative traits jobs status`: **no changes detected**. The new `chronicle/0002_chronicle_generation_request.py` migration is exercised by disposable test databases; it has not been applied to the existing game database.
- Independent source review accepted the final bounded changes after the builder timeout, stale ownership, and browser data-loss findings were repaired.
- The initial repository-wide lint/format debt was not treated as part of this feature completion. No claim is made that the entire repository passes global style checks.

The full-suite command is:

```powershell
.\.venv\Scripts\evennia.exe test --settings settings.py .
```

Use `--settings settings.py`, not `--settings server.conf.settings`: this Evennia launcher prepends `server.conf.`. Check the `Ran ... tests`/`OK` output as well as exit status.

## Remaining deployment gates

These were explicitly excluded from the authorized local work:

1. Configure the real public game origin, generate its static config, and verify both static entry URLs from the actual host.
2. Apply the reviewed migrations and configure the desired provider/credentials in the deployment environment. Qualify the approved external provider, without transferring loopback test evidence to it.
3. Qualify deployed HTTPS/proxy/Host/Origin, OAuth discovery and tokens, and the actual companion MCP deployment with two accounts.

No external provider request, production migration, public publication, commit, push, or deployment was performed.

## Changed-file inventory

The completion JSON records hashes of all changed source/assets. Main areas are `chronicle/`, `narrative/`, `mcp_server/`, `traits/`, `jobs/`, `status/`, blood/dice helpers and their tests, `typeclasses/characters.py`, `web/builder/promotion.py`, `web/static/chargen/codex-chargen.js`, the staff template, static configuration tooling, and disposable acceptance harnesses under `tests/support/`. The scope includes pre-existing resumption changes; the evidence distinguishes them from the original two preserved code edits.
