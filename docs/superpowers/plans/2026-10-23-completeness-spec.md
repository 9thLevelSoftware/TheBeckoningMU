# Completeness repair scope and acceptance contract

Baseline: `34bb52f3cbd374dd657fd82c4edfd1db837027fe` on `main`. This document makes the October 23 audit portable with the implementation plans. [Original audit and runtime evidence](C:/Users/dasbl/.codex/visualizations/2026/10/23/01a16979-7f97-78b2-a38c-f6dece70f49d/beckoning-e2e-audit/AUDIT.md).

The requested outcome is to fully address every identified defect, unfinished capability, compatibility concern, and missing acceptance gate. Existing working behavior, player data, review history, permission boundaries, and deterministic game mechanics must survive. Passing CI alone is not completion.

## Findings that must close

| ID | Current failure | Required result |
| --- | --- | --- |
| F01 | XP buys a discipline dot without a usable power. | Eligible power selection and the purchase succeed together; historical under-grants have an idempotent repair path without another XP charge. |
| F02 | Trigger form saves empty parameters and hides deletion. | Create/edit/save/reload/delete preserves typed action data; accepted triggers actually execute. |
| F03 | Actual power activation does not supply documented combat bonuses. | Verified power effects reach eligible defense/damage calculations exactly once. |
| F04 | Alchemy records break shared effect display/removal. | One compatible effect lifecycle handles new and legacy records without losing unrelated effects. |
| F05 | Some discipline pools omit impairment. | The same applicable impairment reaches caster/defender pools and their displayed breakdowns. |
| F06 | Review omits persisted character choices. | Staff sees all current reviewable choices, including linked touchstones, learned items and notes. |
| F07 | Provider requests/body reads can hang indefinitely. | Bounded, cancellable work ends in a durable terminal state, clears raw action text and settles the caller. |
| F08 | Recovery sends already-dispatched actions again. | Durable claim precedes dispatch; interrupted/unknown dispatches are never retried automatically. |
| F09 | A second correction draft raises a unique-constraint error. | Begin/edit/discard/publish are explicit, versioned, repeat-safe operations preserving history. |
| F10 | Approved memory loses its redaction control. | Authorized staff can find and redact approved facts through the normal UI. |
| F11 | Saved boon request/dispute/ruling details cannot be retrieved. | Authorized participants/adjudicators can retrieve a complete case record without truncation or privacy expansion. |
| F12 | Ten newer records hide older actionable debts. | Every authorized outstanding boon and history record is discoverable through stable pagination. |
| F13 | Narration failure hides the already-applied hunt result. | Deterministic outcome is shown and retained independently of provider success. |
| F14 | Published derivatives retain withdrawn source content. | Implement the explicit dependency-withdrawal policy below across all projections and generation paths. |

## Additional scope

| ID | Capability or gap | Required disposition |
| --- | --- | --- |
| A01 | Prototype endpoint returns 501. | Curated catalog, placement, review, build, cleanup and promotion form one supported workflow. |
| A02 | Day/night, hunting and Haven properties have no gameplay consumers. | Source-backed behavior contracts and actual consumers for every advertised automatic effect; explicitly labelled staff adjudication where authoritative automation is unavailable. |
| A03 | Approved/built projects lack a revision path. | Immutable revisions can be reviewed/tested; existing live areas can be updated only through an explicit reviewed replacement procedure. |
| A04 | Ritual execution helper is a disconnected placeholder. | Validated, persistent casting workflow with verified costs/rolls and honest mechanical versus adjudicated results. |
| A05 | Status display implies automatic dice bonuses. | Wording matches the existing Storyteller-approved manual modifier policy. |
| A06 | Persona/memory curation requires separate Django admin access. | Builder-authorized registration, editing, provenance, approval, redaction and discovery in Story Operations. |
| A07 | Rules data contains UNVERIFIED/signoff markers. | Itemized evidence/house-rule decisions for all player-facing entries; no invented rules or unsupported completion claims. |
| A08 | OAuth refresh/client and browser/game acceptance incomplete. | Real local lifecycle tests plus separately recorded external qualification gates. |

## Approved decisions and proposed defaults

On October 23, 2026, the owner explicitly selected completing the advertised features and withdrawing dependent published recaps until staff review. Those two scope decisions are approved and must not be requested again. Other policy details below remain proposed implementation defaults unless already established by the repository. These answers approve the plan's direction, not implementation or operational execution.

1. **Approved scope:** Complete the advertised capabilities, including builder prototypes, gameplay settings, ritual execution and staff curation. Preserve explicitly manual Storyteller behavior; do not invent new combat, social or inventory simulation merely to make a field appear automatic.
2. **Approved withdrawal policy:** When a Chronicle source is redacted or corrected, withdraw dependent published recaps until staff review. The planned implementation applies this transitively to dependent public/participant prose and excludes it from player reads, MCP, prompts and memory retrieval. Staff-only retention of withdrawn prose is distinct from erasure. The proposed erasure behavior clears the targeted event and its copied revision text; erasing all derivative prose remains a separate retention-policy decision. No automated restoration from backups.
3. Status remains manual. Attack damage marking, ordinary scene endings and Harpy permission grants retain their documented policies.
4. New boon detail/discovery features do not grant global private-case access to Harpies. Private case details are for its actual participant characters and Builders; Harpies receive full public-case details. Builder adjudication completes the private-case workflow. Any broader Harpy private-reading policy requires an explicit owner decision.
5. Initial prototypes are reviewed, immovable, inert objects. Arbitrary Python, typeclasses, locks, scripts, NPCs and account-bearing objects are not part of the catalog.
6. Generated-memory suggestions are not an established requirement. Complete manual curation first; do not change the provider response schema to add suggestions without a separate requirement.
7. Local implementation and verification were authorized by "proceed" on October 23, 2026. Production data repair, commit, push, merge and deployment remain outside the current authorization.

## Decisions to settle through the rules-contract task

R0 must produce exact accepted values and citations before dependent mechanics are changed: authoritative game clock and day/night boundaries; meaning of `day_only` and `restricted`; hunting modifier sign/stacking; each Haven rating's supported actions; per-power stacking and exceptions; ritual requirements, payment/cancellation timing and adjudication; creation distributions and other player-facing UNVERIFIED entries. Use the existing reference materials and authoritative edition/errata sources. The quick reference and character sheet PDFs are not assumed to prove every rule. Missing source access or required owner decisions remain visible blockers for the affected task, while independent repairs proceed.

## Invariants

- CharacterBio.account is player ownership authority. Evennia Builder/Admin permissions are web staff authority; Django is_staff alone is insufficient.
- Character accessors and world/v5_data.py remain canonical. Evennia Mapping/Sequence wrappers are supported. No second character sheet or duplicated rules table.
- Game-object mutations run in the reactor-owned unit. Never hold a web-thread database transaction across call_in_main_thread. Pure Django record transitions may use short database transactions.
- No HTTP call occurs inside a database transaction. SQLite row-lock assumptions cannot replace conditional claims/version checks.
- Builder review snapshots remain immutable. Cleanup/replacement authority comes from recorded identities and validated provenance, never tags alone.
- Model prose cannot alter dice, Hunger, XP, consent, authority, publication or ownership.
- Preserve WIP and existing data. Compatibility repairs are explicit and repeat-safe; no automatic power selection, unproven refund, deletion of unknown effects, or guessed historical dice.
- Run planned checks once at each defined gate; rerun only affected failures after supported fixes. Escalate after two different failed repair attempts. Do not turn expected failures into completion.

## Completion evidence

Every F/A item needs an implementation or explicit accepted scope disposition, regression coverage where behavior is consequential, legacy-data disposition, user-facing documentation, and a result in the final acceptance ledger. Local implementation complete, CI complete, owner/rules acceptance, and external/deployment acceptance are separate statuses. An unresolved required gate cannot be labelled fully complete.
