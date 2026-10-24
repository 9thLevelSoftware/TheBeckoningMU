# Gameplay Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete discipline advancement, effects, impairment, rituals and narrated-hunt feedback, including existing-character compatibility.

**Architecture:** Retain Character accessors and the single V5 rules catalog. Normalize effect boundaries before connecting consumers; keep XP and learned powers in one synchronous persistence unit. Narration consumes an immutable deterministic hunt snapshot and cannot reapply mechanics.

**Tech Stack:** Existing Python/Evennia/Django/Twisted stack and Evennia command test runner.

**Spec:** [Scope contract](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-spec.md), [coordinator plan](D:/TheBeckoningMU/docs/superpowers/plans/2026-10-23-completeness-plan.md).

## Global Constraints

All master constraints apply. Rules in this plan are behavior contracts, not a substitute for source verification. Keep non-core content parked. Preserve Alchemy's dot-plus-formula contract. No automatic XP refund, power choice, elapsed-duration reconstruction, or deletion of unknown effects. No commits or live data repair are authorized by this plan.

## Review Focus

- A partially failed XP write must restore both persisted state and Evennia caches: G1.
- Legacy bare-int disciplines, missing effect IDs and SaverDict/SaverList values remain usable: G1/G2.
- An effect must not apply twice, alter an ineligible pool or survive a failed reroll: G2/G3.
- Interrupted casting must neither create a free success nor silently charge again: G4.
- Failed narration and repeated commands must not hide or repeat the deterministic hunt: G5.

## R0 — Verify the rules and room-policy contract

**Files:** Create docs/rules/completeness-contract.md; inspect world/v5_data.py, commands/v5/utils/thin_blood_utils.py and current help. Update rules data only after an evidence-backed decision; tests/test_v5_data.py records accepted values.

**Interfaces:** A decision table keyed by rule/field contains source edition/page/errata, accepted value, automated or adjudicated behavior, affected tasks and owner approval where it is a house rule. W4 consumes its room-policy rows; G1/G3/G4 consume power/ritual rows.

- [ ] Inventory every player-facing UNVERIFIED and creation signoff marker; separate parked non-core entries from shipped content. Check Obfuscate, predator alternatives, background ratings/benefits, feeding fractions, dyscrasias, Alchemy methods, Day Drinker and creation distributions.
- [ ] Verify exact power eligibility/amalgams, Fleetness/Prowess/Fortitude behavior, stacking, impairment classification and ritual cost/time/difficulty/exceptions against available authoritative sources. Record unavailable sources rather than guessing.
- [ ] Resolve day/night clock/timezone/boundaries, day-only splat restrictions, restricted access policy, hunting modifier sign/stacking and supported Haven actions. Every advertised automatic field needs a named consumer and exact test expectation; every adjudicated field needs honest UI copy and a staff workflow.
- [ ] Obtain required owner decisions for house rules and creation distributions. Independent defects can proceed; only the dependent mechanics wait.
- [ ] Add accepted-value assertions in tests.test_v5_data and update affected help when each rule is implemented. Structural table consistency is not rules signoff.

## G1 — Purchase a power with its discipline dot; repair historical deficits

**Files:** Modify typeclasses/characters.py, commands/v5/xp.py, commands/v5/utils/xp_utils.py, world/rules_chargen.py only for shared eligibility, and world/help/v5/xp-guide.txt. Create world/power_eligibility.py, tests/v5/test_advancement_completion.py and a dry-run management command traits/management/commands/reconcile_discipline_powers.py. Keep any reusable compatibility service in traits/power_reconciliation.py.

**Interfaces:** Preserve Character.spend_xp(name, category, note=None) and its existing return contract; ordinary discipline purchases interpret note as the selected power. Proposed pure helper eligible_power_names(character, discipline_name, prospective_rating) -> tuple[str, ...] is shared by chargen/purchase/legacy claims. New Character.claim_discipline_power(entitlement_id, power_name) -> dict returns the consumed entitlement and learned power; store entitlements under accessor-managed experience.power_choices, not discarded extra discipline-entry fields.

Syntax: +spend discipline Potence = Prowess. Add +spend/claim <entitlement-id> = <power> and a listing switch for pending choices. Missing selection lists eligible choices and changes nothing.

- [ ] Add AdvancementCompletionTests for purchase-to-activation and missing/wrong/duplicate/over-level/amalgam choices. Representative assertion: starting at Potence 1 with Lethal Body and 20 XP, purchasing Prowess yields rating 2, both known powers and 10 XP; invalid selection leaves the complete snapshot identical.
- [ ] Preserve read-only XP cost quoting without a selected power. Add test_cost_quote_does_not_require_power_choice: quoting Potence 1 to 2 returns 10 XP and leaves state unchanged; only the committing purchase requires a complete validated choice. Do not break existing xp_spend_cost/get_xp_cost_* callers while strengthening spend_xp.
- [ ] Add failure injection after the first Attribute write; both the existing object and a fresh persisted read must retain the pre-purchase sheet/XP/log. Repeated claims must change XP by zero and grant a power exactly once.
- [ ] Validate against prospective rating before mutation. Execute the synchronous reactor-owned XP unit inside a short transaction and explicitly refresh invalidated Attribute/idmapper caches on rollback. Do not span call_in_main_thread or HTTP with that transaction; do not rely on SQLite select_for_update for cross-process serialization. Notifications follow successful persistence.
- [ ] Implement dry-run inventory of rating, valid distinct powers and XP/grant provenance. Only proven deficits receive deterministic, uniquely identified choice entitlements when explicitly applied; ambiguous records require staff review. Preserve spent/earned totals and historical logs; never automatically select a power. Reset/snapshot/restore must include entitlements with the correct rejected-versus-revoked behavior.
- [ ] Run the new test label plus affected XPCostTableTests, XPSpendTests, ThinBloodXPTests and chargen PowerTests once for the combined G1 change. Repair old tests that bought a dot without the now-required choice; do not weaken their cost assertions.
- [ ] Verify the player command grants a selected power that can immediately activate, and a legacy entitlement claim needs no further XP.

## G2 — One effect representation, including legacy records

**Files:** Modify commands/v5/utils/discipline_effects.py, discipline_utils.py, thin_blood_utils.py and commands/v5/effects.py. Create tests/v5/test_effect_lifecycle.py and traits/management/commands/normalize_active_effects.py. Coordinate consumer edits with G3.

**Interfaces:** make_effect(*, effect_id, source_kind, power, discipline, duration, parameters, applied, turns_remaining=None) -> dict produces schema_version=1 records using existing field meanings. normalize_effects(character, *, persist=False) -> report returns normalized records, changes and unresolved records. A persist=False report does not invent permanent IDs or write data; explicit persistence assigns missing IDs once. effect_parameters(effect: Mapping) -> Mapping is the consumer boundary.

- [ ] Add EffectLifecycleTests using real activation, Alchemy and Character Attributes. Haze must have a stable ID/name, appear correctly, and be removable without touching another effect. Assert instant formula use leaves no lasting record, normalization is idempotent, and turn expiry/reroll removal still work after reload.
- [ ] Normalize legacy Alchemy names and top-level bonus fields without dropping unknown metadata. Report unsupported records and skip unsafe mechanical interpretation; display/removal must remain non-crashing. Preserve known IDs. Do not infer elapsed turns/scenes or merge historical duplicates without activation provenance.
- [ ] Change producers to create one logical effect per activation with a shared activation ID. Populate canonical parameters; eliminate the current empty generic-plus-handler duplication for new activations. All readers accept Mapping/Sequence wrappers.
- [ ] Make selective removal tolerate malformed legacy entries and remove only the requested canonical ID. Explicit reconciliation may retire verified instant leftovers with a report; it must not silently delete unknown entries.
- [ ] Run tests.v5.test_effect_lifecycle, commands.v5.tests.test_discipline_utils.TurnDurationPowerTests and tests.v5.test_rules_dice.PowerWillpowerTests once at this task gate.

## G3 — Connect effects to combat and apply impairment consistently

**Files:** Modify commands/v5/utils/combat_utils.py, discipline_utils.py and dice/discipline_roller.py. Create dice/pool_modifiers.py and tests/v5/test_power_integration.py. Reuse the resolved-trait Physical classification currently used by hunting rather than copying a second trait list.

**Interfaces:** impairment_for_pool(character, resolved_traits) -> dict returns total penalty plus labelled components from Character.dice_penalty(). Combat reads G2 parameters. Preserve existing roll-result shapes and central dice_roller randomness; add labelled modifiers without changing downstream callers' required keys.

- [ ] Add PowerCombatIntegrationTests activating actual Fleetness/Prowess before attack. Assert verified eligible defense/damage bonuses, no bonus to ineligible pools, best defense selected after modifiers, and no duplicate stacking. Retain Fortitude's damage-type restrictions.
- [ ] Add DisciplineImpairmentTests: degenerating Composure 3 + Resolve 3 resistance rolls four dice; Health-impaired Dexterity 3 + Athletics 2 Blink rolls three. Cover Physical defense, combined applicable penalties, healthy/social controls, mortals/ghouls and displayed-versus-rolled equality.
- [ ] Implement only R0-verified power handlers/stacking. Do not simply expose unverified hard-coded Draught/Resilience values. Apply the same impairment calculation to caster and defender, preserving Hunger, Blood Potency, resonance, surge and pool-floor behavior.
- [ ] Run tests.v5.test_power_integration plus affected AttackTests, DegenerationPoolTests and PowerCommandTests once. Existing synthetic bonus fixtures remain only where they test a separate rule; real activation tests must prove the integration.

## G4 — Replace ritual placeholder with persistent casting

**Files:** Create commands/v5/rituals.py, commands/v5/utils/ritual_utils.py, world/rituals/__init__.py, world/rituals/casting.py and tests/v5/test_ritual_casting.py. Update world/v5_data.py, commands/default_cmdsets.py, the placeholder in discipline_effects.py and new world/help/v5/ritual-guide.txt.

**Interfaces:** prepare_cast(caster, ritual_name, *, target=None, context=None) -> validated plan performs no payment; begin_cast(caster, plan) -> cast_id persists the attempt; resolve_cast(caster, cast_id) -> structured result conditionally resolves it once. +ritual lists/starts casts; +ritual/status and +ritual/cancel expose the supported lifecycle. A durable world.rituals.casting.RitualCastingScript owns timing/restart recovery; it uses R0's exact payment/cancellation contract.

- [ ] Define execution metadata for every offered ritual: learned/rating/target requirements, verified cost, casting time, difficulty, duration and mechanical/adjudicated result. Do not infer behavior from names. Ingredients require explicit tracked inventory or clearly recorded Storyteller attestation; neither is assumed to exist.
- [ ] Add RitualCastingTests for unknown/unlearned/over-level/invalid-target refusal without payment; verified cost and failure consequences; restart while casting; duplicate completion; cancellation timing; target loss; and effect expiry/removal.
- [ ] Implement validation, payment and durable cast state using the central dice/Rouse paths and G2 effect records. On an indeterminate interrupted resolution, fail for staff review rather than charging/rolling again. Structured results distinguish mechanical changes from requested Storyteller adjudication; never claim unavailable blood/identity facts were discovered.
- [ ] Remove or delegate the disconnected generic placeholder so there is one execution path. Register commands and update help with the exact supported outcomes.
- [ ] Run tests.v5.test_ritual_casting and the affected ritual learning/chargen tests. Use an injected clock and process restart fixture, not wall-clock sleeps.

## G5 — Show deterministic hunt results before narration

**Files:** Modify commands/v5/hunt.py and commands/v5/utils/hunting_utils.py; create tests/v5/test_hunt_presentation.py. Coordinate narrative snapshot persistence with N2; extend narrative/test_http_command.py and tests/support/local_runtime.py only at the combined HTTP acceptance gate.

**Interfaces:** serialize_hunt_outcome(result) -> JSON dict has schema_version=1, pool/modifier breakdown, difficulty, dice/outcome flags, feeding/Hunger, resonance and complications. format_hunt_outcome(snapshot) -> str is shared by ordinary hunt and story start. +hunt/story status reads the authorized session's stored result even when the provider is disabled.

- [ ] Add HuntPresentationTests asserting concrete result/Hunger/resonance/complication output before provider completion and after synchronous error, HTTP error, malformed response and timeout. Assert repeated start/resume never rerolls, reapplies feeding or resets cooldown.
- [ ] Persist only JSON primitives, not RollResult instances. Legacy snapshots display available facts and label absent original dice unavailable; never reconstruct them or ask the model to supply them.
- [ ] Display deterministic output once per initial hunt before requesting prose. Subsequent success/failure messages describe narration only. Status reads do not dispatch or require configured AI.
- [ ] Run tests.v5.test_hunt_presentation. Extend the existing local HTTP fixture and execute narrative.test_http_command once after N1/N2 and G5 are integrated; its owner records the shared result so it is not repeated per package.

## Completion

R0 decisions, G1–G5 regressions, existing-data rehearsal and the master Q1/Q3 gates must all be recorded. A reconciliation tool being ready does not imply live characters have been repaired; report that operational gate separately.
