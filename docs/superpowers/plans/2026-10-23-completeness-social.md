# Social Workflow Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make complete boon case records and every actionable debt discoverable while preserving privacy and the existing manual Status policy.

**Architecture:** Reuse existing Boon fields and transitions. Put visibility and case projection in shared helpers, then use those helpers for detail and keyset-paginated discovery. Keep adjudication authority separate from read access.

**Tech Stack:** Existing Evennia commands, Django models, CharacterBio ownership and command tests.

**Spec:** [Scope contract](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-spec.md), [coordinator plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-plan.md).

## Global Constraints

All master constraints apply. No new global Harpy private-case read authority. Participant-authored details and staff_notes are not equivalent to a public summary. Use persistent CharacterBio ownership for same-account guards; no change to the documented manual Harpy grant policy. No new audit-event table is required to expose existing records.

## Review Focus

- Long offline requests and accumulated dispute/ruling text must remain readable: S1.
- Alternate characters, private boons and staff notes must not leak through detail or cursors: S1/S2.
- New inserts and equal timestamps must not duplicate/skip older history pages: S2.
- Canonical ownership must block self-adjudication without requiring active puppet links: S1.
- Status output must not imply automatic changes to a submitted dice pool: S3.

## S1 — Full case detail with explicit visibility

**Files:** Modify boons/commands.py and utils.py; retain models.py's existing descriptive fields/transitions. Create boons/test_case_access.py. Update command docstrings, world/help/v5/boon_commands.txt and world/help/v5/boons-guide.txt.

**Interfaces:** Add +boon/view <id>. boon_view_level(actor, boon) -> none|summary|case|staff decides projection; project_boon(boon, view_level) -> dict and format_boon_detail(projected) -> str never accept arbitrary requested secret fields. canonical_owner_id(character) -> account ID or None resolves CharacterBio; identical-character identity is checked separately.

| Viewer | Public record | Private record |
| --- | --- | --- |
| Actual debtor/creditor Character | Full participant case | Full participant case |
| Another Character, even on the same account | Public summary | Denied |
| Harpy account permission | Full public case | Denied unless also an actual participant or Builder |
| Builder or higher | Full case and staff notes | Full case and staff notes |

- [ ] Add BoonCaseViewTests for complete original/request/confirmation/dispute/ruling text, timestamps and state. A distinctive suffix past character 200 must survive the persisted transition and later command output. Label legacy accumulated fulfillment_description as Case record; do not invent authors or timestamps missing from old text.
- [ ] Add the complete visibility matrix, unknown ID and denied-private-ID responses, private text/staff-note exclusion, Harpy public adjudication, and Builder private adjudication. Use one non-disclosing response for missing versus unauthorized private IDs.
- [ ] Add canonical ownership tests with no puppet/playable links. Prevent Harpy rulings involving either its active character or another character on the same owning account; preserve Builder override. Characters without a bio are not automatically considered co-owned. Update legacy tests to create actual ownership records instead of preserving an obsolete authority assumption.
- [ ] Implement the shared projection and command; use pager support for long records without truncation. Reading does not change boon state. Public summary contains original description/type/parties/status, while requests, confirmations and dispute/ruling narrative remain case details. staff_notes remain Builder-only.
- [ ] Keep read and ruling checks separate. Do not silently broaden private case discovery to match an existing ID-based ruling capability. A broader private Harpy workflow is an explicit policy change, not an incidental helper refactor.
- [ ] Run boons.test_case_access and affected boons.tests lifecycle/authority tests once. The ownership change is targeted contract hardening; the audit did not establish a normal-user exploit.

## S2 — Stable discovery and full history

**Files:** Modify boons/commands.py and utils.py; create boons/test_discovery.py. Reuse S1 visibility before pagination. No change to derived debt totals or transition semantics.

**Interfaces:** Add +boon/list [before=<id>] for the caller's outstanding accepted/called-in/disputed records; +boon/history [before=<id>] for all its records. Existing +boon <character> remains a short pair summary linking to history/detail. Extend +boonadmin/list [before=<id>] for the visible adjudication queue. list_visible_boons(actor, *, mode, before=None, counterpart_id=None, page_size=20) -> page returns projected rows and next_before; IDs are positive integers and page_size is server bounded.

- [ ] Add BoonDiscoveryTests reproducing an accepted debt hidden by ten newer terminal rows. Assert its ID remains discoverable and leads to full authorized detail. Outstanding mode includes called-in/disputed states; terminal records do not crowd them out.
- [ ] Add keyset tests with more than two pages, equal timestamps, a new insert between pages, malformed/negative cursor, sparse visible rows, last-page behavior and an ownership/permission change between requests. Filter visibility/status before taking the limit; never leak hidden counts or private IDs in cursor metadata.
- [ ] Order by descending primary key and query id < before, fetching one extra visible row to detect continuation. Display the next exact command using the final shown ID. Pages reflect current state rather than promising a frozen snapshot; new records appear when the user returns to the first page.
- [ ] Include the ID, counterparty, type/state and detail command in each row. Preserve +boon/pending's immediate-action prompts but link to the complete case instead of relying on its preview text.
- [ ] Run boons.test_discovery once after S1; Q1 exercises the actual commands with enough records to cross page boundaries.

## S3 — Honest Status wording

**Files:** Modify both Status formatter paths in status/utils.py, world/help/v5/status_commands.txt, world/help/v5/status-guide.txt and relevant command docstrings; create status/test_display.py.

**Interfaces:** Preserve existing get_status_bonus calculation and manual roll entry. Use copy such as: Suggested social modifier: +N dice, only when the Storyteller approves; add it to your entered pool.

- [ ] Add StatusDisplayTests.test_social_modifier_is_explicitly_manual for both formatter paths and zero/nonzero modifier states. Assert no dice function or character pool is mutated by displaying Status.
- [ ] Align active help and command output without introducing automatic social outcomes or a second Status rule.
- [ ] Run status.test_display once. The coordinator runs the final shared help-integrity gate after all packages finish their command documentation.

## Completion

Record full-text, privacy, ownership and pagination evidence separately. Existing scalar fields remain intact; no historical narrative rewrite or inferred case-event reconstruction is needed. Q1 validates practical adjudication/discovery and Q3 checks integration.
