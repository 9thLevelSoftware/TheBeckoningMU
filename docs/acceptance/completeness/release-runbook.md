# Completeness release and compatibility runbook

This is an operational handoff, not an executed release. Current authority is local implementation and disposable acceptance only. The existing game database has not been copied, inventoried, migrated, normalized or repaired. The refreshed populated disposable migration rehearsal passed through `builder.0011_bounded_builder_operations`, with 12 invariants, restored fixture-boundary patch and an empty second migration plan. Its artifacts and harness hash are recorded in `.git/completeness-execution/Q3-async-migration-*`; independent review accepted this refreshed rehearsal. The earlier 0010 rehearsal and its hashes are historical and superseded for current migration evidence. Incremental builder runtime, world fences and lifecycle have independent acceptance; any cross-object change from a normal hook that alters a later reviewed object across a yield fails closed for inspection, with no automatic replay. The Q3 actual browser/game builder journey is complete on lease `f10rvy0i`; its owner reaped the children with exit 0 and closed tab 8. The serialized maximum-size performance run is locally qualified and independently verified: all 4,823 callback spans passed the unchanged 1.1-second limit. All 87 source hashes matched current files at benchmark review time; subsequent changes were confined to tests/help/harness, with product source unchanged. Full five-case rollback restored exact old state, removed its 430 additions, and released claims. Operation elapsed times are distinct from callback maxima; existing cleanup/promotion checks were setup only and were not requalified. The initial 1,359-test run had 1,348 unaffected passes, 10 failed checks and one prototype cache error. Each issue then passed its affected rerun (10/10 and 2/2 respectively), with independent acceptance of the prototype closure. This is combined passing evidence across all discovered tests, not a single fresh all-green suite run. R0 catalog/creation values remain provisional chronicle rules pending primary-source qualification. Production DB work, provider/TLS/CI qualification, commit/push and deployment are not included. Earlier Q1 browser/game journeys passed; see the ledger and `browser-game.md`. N6 requester-deactivation lifecycle tests passed and independent ACCEPT closed P2. Q4 local handoff is complete; operational actions remain outside scope.

Publication follow-up (October 23, 2026): committing, pushing, opening a PR against `main`, and repairing CI are now authorized. The preceding paragraph records the completed local implementation stage. Deployment and production database changes remain unauthorized; use the PR checks for the current committed revision's CI status.

## Before a later release

1. Review the concrete final diff and the task ledger. The local implementation/verification package is complete; its combined test evidence includes the initial full-suite failure and focused pass rechecks rather than one single fresh all-green 1,359-test run. Review the retained suite evidence and provisional R0/source-qualification boundaries. The actual Q3 builder browser/game journey is complete and documented in `browser-game.md`. Earlier baseline CI does not qualify this diff.
2. Obtain the separately authorized maintenance/release window. Pin the exact reviewed code revision and dependency lock. Check that running game, web and MCP processes use the intended checkout and configuration.
3. Stop the normal Evennia Server/Portal and every writer/companion process before a SQLite maintenance backup. Follow the repository's `evennia stop` procedure and verify they stopped. Do not copy a changing database or launch a second writer alongside the game.
4. Make a private, timestamped backup of `server/evennia.db3` and the matching code/configuration identity. Verify the backup opens and its hash is recorded. Keep secrets and database contents outside this repository and acceptance artifacts.
5. Rehearse the reviewed migration chain against a disposable database under explicitly isolated settings. Compare row identities, relationships and dispositions against `compatibility-inventory.md`; do not assume an empty database test covers existing data. The refreshed populated rehearsal started from `narrative.0001_initial`, `chronicle.0002_chronicle_generation_request` and `builder.0007_buildproject_built_object_ids`, then targeted every migration leaf discovered by Django, including builder 0011. It passed on October 23, 2026; its result and log are `.git/completeness-execution/Q3-async-migration-result.json` and `Q3-async-migration-rehearsal1.log`, and the marked DB is `C:\Users\dasbl\AppData\Local\Temp\beckoning-completeness-migration-5vb9ptyq\acceptance.sqlite3`. It reports 12 passed invariants and an empty second migration plan. The previous 0010-only rehearsal at `p4tsahmx` is retained as history, not current evidence. Repeat the rehearsal for the exact reviewed release graph if model/migration files change after this evidence.

## Local migration and compatibility procedure

Use the repository's configured, reviewed settings module for the target environment. In this checkout, `settings.py` is not a root file and the Evennia launcher rewrites its `--settings` values; do not copy a settings argument from the test launcher into a maintenance command. Django's direct management entry point takes the settings module as written. A future operator should first run the migration plan read-only, then apply only in the approved maintenance window:

```powershell
.\.venv\Scripts\python.exe -m django showmigrations --plan --settings YOUR_APPROVED_SETTINGS_MODULE
.\.venv\Scripts\python.exe -m django migrate --settings YOUR_APPROVED_SETTINGS_MODULE
```

Replace the placeholder only with the environment's actual reviewed module. Local test and disposable rehearsal settings are not production settings. Do not execute either command against the production target as part of this local handoff.

## Compatibility inventory and deliberate remediation

The two maintenance commands default to read-only inventory. Run them only against the explicitly selected offline database/settings, using the installed repository environment:

```powershell
.\.venv\Scripts\evennia.exe reconcile_discipline_powers --character <id>
.\.venv\Scripts\evennia.exe normalize_active_effects --character <id>
```

Review each report before selecting any apply operation. A documented, authorized offline apply adds `--apply --offline`; instant formula retirement additionally requires `--retire-instant`. The `--offline` flag is an operator assertion, not proof that other writers have stopped. `--character` is optional and repeatable; omitting it inventories every Character. Both commands default to read-only. `--retire-instant` has an effect only when normalization is explicitly persisted.

- Power reconciliation issues choices only for proven dot-only purchases. It does not select a power, refund XP or infer missing provenance. Ambiguous deficits require staff adjudication.
- Effect normalization preserves unknown/malformed/duplicate records for review. Stable missing IDs are assigned only on explicit persistence. It does not reconstruct elapsed time. Compare a second dry-run to prove idempotence for the accepted changes.
- Legacy Story requests from before dispatch metadata existed are indeterminate and fail during migration without dispatch. Chronicle already stored dispatch claims: startup recovery fails interrupted claimed attempts without retry; unclaimed intent is reauthorized before scheduling. Successful history and deterministic hunt results survive. Explicit retries create new requests and never reroll the hunt.
- Correction history, source edges and withdrawn recaps keep their identities. Unknown generated ancestry stays unavailable until reviewed. Staff-retained withdrawn prose is distinct from explicit target/history erasure.
- Legacy live builds lacking exact trusted manifests remain readable and ineligible for automatic replacement. This code has no automatic adoption path; a matching tag never proves ownership. Restricted rooms lacking explicit reviewed principals remain closed and cannot be published as a new ambiguous revision.

Do not run these illustrative commands against the normal database during automated acceptance. The current populated rehearsal and migration leaves are recorded in the ledger and `compatibility-inventory.md`; that evidence concerns only its disposable database. The commands use Evennia's active game configuration; there is no root `settings.py` in this checkout, so the local test-launcher setting is not suitable operational configuration.

## Migration and rollback boundaries

Run the configured migration command only after the rehearsed chain and maintenance window are authorized. Start the reviewed code after migrations finish and confirm recovery has settled indeterminate requests without sending them. The checked-in app leaves exercised by the refreshed populated rehearsal are `narrative.0003_versioned_manual_curation`, `chronicle.0005_source_withdrawal_lineage`, and `builder.0011_bounded_builder_operations`; intermediate app migrations and Django/Evennia dependency leaves are listed in the sanitized result. The fixture included legacy approved, draft, private, and already-redacted memory facts plus empty legacy builder operation/guard state. The refreshed rehearsal and exact harness hash are in `.git/completeness-execution/Q3-async-migration-*`; independent review accepted this current result. Older 0010-only hashes do not identify the refreshed run. This local pass does not authorize any production migration and does not complete aggregate Q3 acceptance.

A code rollback is not automatically a schema or data rollback:

- Old recovery code must not dispatch rows whose outcome may already exist.
- Old one-to-one correction code cannot handle multiple retained drafts/revisions.
- Preserve dispatch metadata, revision links, exact object manifests and withdrawal evidence when choosing a forward fix.
- Do not restore erased sensitive prose from an older backup as a routine rollback. Any restoration needs an explicit privacy and incident decision, with access to backups controlled accordingly.
- `narrative.0003_versioned_manual_curation` clears `text` and `staff_entry` on legacy rows already marked redacted. Its reverse data operation is a no-op, so rollback cannot recreate that content. Preserve non-redacted legacy fact text, IDs, provenance, scope, status, expiry and approval time; do not fabricate missing historical reviewer identities or revision links.
- In an uncertain builder/casting interruption, stop the affected operation and inspect recorded identities/state. Do not replay payment, dice, deletion or replacement to discover what happened.
- A builder replacement candidate is eligible only after approval at its current version, sandbox cleanup, exact target/source version and manifest checks, and a current v2 live manifest. A legacy live project without that manifest stays readable and requires explicit reviewed adoption; tags do not establish ownership. If compensation fails, retain the replacement claim and staged records for staff inspection. Do not clear the claim, delete held objects, retry the replacement, or promote another candidate until the journal and retained world objects have been reconciled.
- Rituals retain a durable operation claim before payment, rolls, or adjudication. A restart that finds an in-progress claim moves it to review; staff must inspect the persisted payment/roll history and close it explicitly. Never replay the claim or refund recorded costs to test what happened. Fresh persisted Builder authority, cast revision, target and account binding are checked again at decision and settlement boundaries.

## External qualification after authorization

These checks remain external release gates; none has run in this local task. Local loopback HTTP does not qualify a public endpoint. Check the approved provider and hosted configuration separately:

1. Confirm HTTPS certificate and reverse-proxy routing; exact OAuth issuer, MCP resource, allowed hosts/origins, callback URI and controlled client registration.
2. Follow the deployed static site's game link through browser login/consent with an external installed SDK client. Verify state/PKCE, scope/resource binding, refresh rotation, token reuse rejection, revocation and website sign-out.
3. Read as two accounts; deny foreign characters and write tools. Transfer fixture ownership and withdraw a source while a reader is warm; every subsequent projection must reflect the new authority/availability.
4. Send only the approved bounded provider qualification requests. Retain sanitized categories/request identifiers, never credentials, raw provider bodies or private player prompts. Verify provider failure leaves deterministic gameplay usable.
5. Require passing CI for the exact final committed revision. Publication and CI repair are authorized in the follow-up; record those results separately from the historical local test evidence.

## Rules qualification

The owner accepted existing advertised catalog/creation values as provisional chronicle rules and approved the room policy. `docs/rules/completeness-contract.md` records remaining primary-source limitations. Ritual-specific ingredients, blood/identity findings and Haven outcomes remain explicit Storyteller adjudications where no automated rule is defined. Passing software tests does not convert these conventions into verified core-book rules.
