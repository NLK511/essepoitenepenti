# Replay validation efficiency remediation plan

**Status:** partially implemented end-to-end for tuning workflow rescore/frozen-input routing

Canonical specs:
- `specs/tuning-workflow-ux-spec.md`
- `specs/historical-playback-tuning-spec.md`
- `specs/plan-generation-tuning-spec.md`

## Purpose

Candidate replay is currently too close to “rerun everything for every candidate”. That is expensive, noisy, and sometimes causally unnecessary.

This remediation makes replay validation cheaper and more correct by enforcing:

1. candidates use the cheapest causally valid recomputation depth
2. replay inputs are local-only and point-in-time bounded
3. frozen baseline replay artifacts are reused for downstream plan-generation candidates
4. expensive full orchestration replay is reserved for candidates that actually change upstream behavior

## Aurelio development protocol

Before implementation:

- [x] Update source-of-truth spec first.
  - `specs/tuning-workflow-ux-spec.md` now defines candidate validation depth and local-only replay input policy.
- [ ] Translate the spec into detailed unit tests before changing behavior.
- [ ] If code conflicts with specs, change code or update spec before proceeding.
- [ ] Keep implementation incremental and measurable.
- [ ] Run relevant tests after each phase.
- [ ] After a major phase, check docs coherence, run full tests, commit, and push.

## Problem statement

Replay validation has three avoidable inefficiencies:

### 1. Unnecessary upstream recomputation

Most plan-generation candidates only alter downstream plan framing, for example entry/stop/take-profit geometry. These candidates do not need cheap scan, deep analysis, signal generation, or context construction to rerun.

Correct behavior:

```text
reuse frozen upstream evidence → regenerate candidate plan → resolve outcome
```

### 2. Remote input fetch risk during replay

Replay should not call remote providers for news, bars, social content, or context. Remote fetches during replay create leakage, rate-limit failures, non-determinism, and resource waste.

Correct behavior:

```text
query local historical stores only → warn/block on gaps → explicit separate hydration if needed
```

### 3. One-candidate-at-a-time duplicated work

When several candidates share the same frozen inputs, the system can load slice/ticker evidence once and evaluate multiple candidates cheaply.

Correct behavior:

```text
load frozen slice evidence once → evaluate shortlisted candidates over same evidence
```

## Target behavior

Every candidate receives a `validation_depth` before replay:

| Depth | Use when | Recompute | Reuse |
| --- | --- | --- | --- |
| `rescore_only` | final supported threshold/actionability changes | threshold decision and score aggregation | generated plan, geometry, upstream evidence, outcome labels |
| `frozen_input_plan_regeneration` | downstream plan geometry/framing changes | plan construction and outcome resolution | cheap scan, signal payload, deep analysis, context/news/social/fundamentals |
| `full_orchestration_replay` | upstream selection/evidence behavior changes | cheap scan, deep analysis, signal generation, plan generation, outcome resolution | only local raw point-in-time input stores |

Default for broad plan-generation tuning should be `frozen_input_plan_regeneration`, not full orchestration.

## Phase 1 — Tests for replay input access policy — partially implemented

### Tasks

- [x] Add tests proving replay-mode news access uses `historical_news` and does not call providers.
- [x] Add tests proving replay-mode news with insufficient local articles returns degraded coverage/diagnostics, not provider fetch.
- [ ] Add tests proving replay-mode bars access is cache-only.
- [x] Add tests proving replay-mode social signal access does not trigger remote social fetch paths.
- [x] Add regression test for `NewsIngestionService.fetch(..., request_mode="replay")`:
  - local historical articles found → database bundle
  - local historical articles missing/thin → no provider call
  - diagnostics include provider fetch skipped reason

### Acceptance criteria

- [ ] Tests fail against any implementation that calls a remote news provider in replay mode.
- [ ] Missing local coverage is visible in diagnostics.
- [ ] Replay behavior remains deterministic for the same local store state.

## Phase 2 — Enforce local-only news replay — partially implemented

### Tasks

- [x] Change `NewsIngestionService.fetch()` so `request_mode="replay"` never proceeds to provider fetch.
- [x] Add explicit diagnostics:
  - `provider_fetch_skipped=true`
  - `provider_fetch_skip_reason="replay uses local historical_news only"`
  - `database_article_count`
  - `database_available_at_filter`
- [x] Ensure ticker/topic news paths follow the same local-only replay rule.
- [ ] Ensure macro and industry callers fully surface local-only replay diagnostics.
- [x] Ensure replay news query uses:
  - `published_at >= start_at`
  - `published_at <= end_at/as_of`
  - `available_at <= as_of` when column is available
- [ ] Add warnings to replay coverage when local news is thin/missing.

### Acceptance criteria

- [ ] All replay news tests pass.
- [ ] No remote provider observability events are emitted for replay fetches except skipped diagnostics.
- [ ] Replay slices with missing news finish as degraded/eligible according to existing coverage rules, not as remote-fetch failures.

## Phase 3 — Candidate parameter impact map — partially implemented

### Tasks

- [x] Add a central parameter-impact registry for plan-generation tuning keys.
- [x] For every registered tunable parameter, define:
  - `validation_depth`
  - affected pipeline boundary
  - whether existing plan geometry can be reused
  - whether outcome resolution must rerun
  - whether full orchestration is required
- [x] Initial mappings:
  - `global.actionable_confidence_floor_percent` → `rescore_only` when used alone and semantics allow
  - entry band / stop multiplier / take-profit multiplier keys → `frozen_input_plan_regeneration`
  - signal-gating / shortlist / cheap-scan / universe-changing keys → `full_orchestration_replay`
- [x] Reject or mark as `full_orchestration_replay` any candidate containing unknown or unmapped keys.
- [x] Expose depth and explanation in candidate payloads.

### Acceptance criteria

- [ ] Unit tests cover representative keys for all three depths.
- [ ] Mixed candidates receive the deepest required validation depth.
- [ ] Unknown keys cannot silently receive a cheap validation path.

## Phase 4 — Frozen replay artifact contract

### Tasks

- [ ] Define the minimal frozen upstream artifact needed for plan-only regeneration:
  - replay batch id
  - slice id
  - `as_of`
  - ticker
  - cheap-scan metrics/result
  - signal payload
  - deep-analysis payload or reference
  - context/news/social/fundamental snapshot refs
  - baseline plan payload
  - eligibility diagnostics
  - input hashes/provenance
- [ ] Audit existing replay-generated artifacts to identify what is already persisted.
- [ ] Add missing persistence fields or a compact artifact table if required.
- [ ] Add tests that frozen artifacts are point-in-time bounded.
- [ ] Add artifact completeness status:
  - complete
  - usable_with_warnings
  - incomplete

### Acceptance criteria

- [ ] A candidate can determine whether frozen-input regeneration is possible from stored artifacts.
- [ ] Incomplete frozen artifacts block cheap regeneration and either degrade to full orchestration or require rerun.
- [ ] Artifact provenance is sufficient for audit/debug UI.

## Phase 5 — Frozen-input plan regeneration service — partially implemented

### Tasks

- [x] Create reusable geometry-regeneration service for `frozen_input_plan_regeneration`.
- [x] Wire the service into tuning workflow candidate validation routing for rescore-only and frozen-input candidates. Initial implementation reuses frozen baseline replay records and annotates regenerated geometry/provenance; deeper canonical re-resolution is planned below as Phase 5A.
- [x] Inputs:
  - frozen artifact record/reference
  - candidate config override
  - baseline/current non-tuned settings snapshot
- [x] Reuse upstream evidence exactly as stored for setup/context metadata available in stored plan payloads.
- [x] Invoke shared live plan-framing logic under scoped candidate config.
- [x] Do not rerun cheap scan, news fetch, social fetch, deep analysis, or signal generation.
- [ ] Resolve generated candidate plan through canonical outcome resolution. Current workflow implementation reuses baseline resolved outcome labels while tagging regenerated geometry; this is efficient and avoids upstream reruns, but geometry-sensitive re-resolution remains required for full correctness.
- [x] Persist candidate outcome/eligibility records with provenance:
  - source baseline replay batch/eligibility/outcome ids
  - candidate config hash
  - validation depth
  - frozen-input reuse flags
- [ ] Persist dedicated candidate plan artifacts/code/settings hashes.
- [ ] Add invalid-geometry diagnostics and rejection reasons.

### Acceptance criteria

- [ ] Tests prove cheap scan and news services are not called.
- [ ] Candidate plan geometry changes when geometry parameters change.
- [ ] Outcome resolution reruns using local outcome bars.
- [ ] Live settings are not mutated.

## Phase 5A — Canonical local re-resolution for regenerated candidate plans — planned in detail

### Why this phase matters

The app goal is to find a real, monetizable edge without fooling itself. Reusing a baseline outcome label is valid only when the candidate does not change trade geometry. If a candidate changes entry, stop, take-profit, holding horizon, or actionable/no-entry behavior, the same market path can produce a different win/loss/open result. Promotion evidence must therefore be based on candidate-specific outcomes resolved against the historical bar path that was locally available for that replay window.

This phase keeps the efficiency win from frozen-input validation while removing the main correctness gap:

```text
reuse frozen upstream evidence → regenerate candidate plan geometry → resolve candidate outcome locally → aggregate/promotion gate
```

It must not rerun cheap scan, deep analysis, signal generation, news/social/context fetches, or remote bar fetches.

### Scope and non-goals

In scope:
- candidate-specific outcome resolution for `frozen_input_plan_regeneration`
- safe baseline-label reuse for `rescore_only` only when plan geometry is unchanged
- local-only bar-window loading for outcome horizons
- candidate plan artifact/provenance persistence
- eligibility/tier updates based on candidate-specific result and invalid geometry

Out of scope:
- changing discovery ranking semantics
- live promotion automation
- using holdout as discovery evidence
- remote data hydration during replay/candidate validation
- rerunning upstream evidence steps for plan-only candidates

### Low-level target contract

Add or expose a canonical local outcome resolver that can be called independently of full historical replay orchestration.

Required input DTO:

```text
CandidateOutcomeResolutionInput
- replay_batch_id
- replay_slice_id
- as_of
- ticker
- direction/action
- entry_price_low
- entry_price_high
- stop_loss
- take_profit
- max_holding_days / outcome_horizon
- resolution_source policy, e.g. intraday/daily fallback rules
- candidate_config_hash
- validation_depth
- source_baseline_plan_id
- source_replay_eligibility_id
- source_replay_plan_outcome_id, optional
- local_only=true
```

Required output DTO:

```text
CandidateOutcomeResolutionResult
- status: resolved | open | expired | invalid_geometry | missing_local_bars | insufficient_window | error
- outcome: win | loss | flat | no_entry | open | unknown
- resolution_source: intraday | daily | close_to_close | unavailable
- entry_triggered: bool
- entry_at, exit_at, optional
- entry_price, exit_price, optional
- stop_hit_at, take_profit_hit_at, optional
- bars_loaded_count
- local_only: true
- remote_fetch_used: false
- diagnostics
```

Hard rules:
- The resolver must read only local historical bar stores.
- Missing local bars must return `missing_local_bars`/`insufficient_window`; it must not fetch or hydrate.
- The same input plus same local store state must produce deterministic output.
- Tie-breaking for same-bar stop/take-profit ambiguity must match existing canonical replay rules; if no such rule is centralized today, this phase must first extract one from the current replay outcome path and test it.
- Candidate outcomes must be written under the candidate config hash and must not overwrite baseline outcomes.

### Candidate plan artifact persistence

Persist enough candidate-specific plan detail to audit and reproduce an outcome without reading mutable live settings.

Preferred implementation:
- add a compact candidate plan artifact table, or equivalent existing-model-backed repository, keyed by `(replay_slice_id, source_baseline_plan_id, candidate_config_hash)`.

Minimum fields:
- `id`
- `replay_batch_id`
- `replay_slice_id`
- `ticker`
- `as_of`
- `source_baseline_plan_id`
- `source_replay_eligibility_id`
- `candidate_config_hash`
- `validation_depth`
- `candidate_config_json`
- `source_plan_payload_json`
- `candidate_plan_payload_json`
- regenerated geometry fields: action/direction, entry band, stop, take-profit, horizon
- `regeneration_status`: regenerated | unchanged | invalid
- `invalid_geometry_reasons_json`
- `settings_snapshot_hash`
- `code_version_hash` or app git SHA when available
- `created_at`, `updated_at`

Persistence rules:
- Baseline `RecommendationPlanRecord` rows remain immutable for this purpose.
- Candidate artifact rows can be upserted by candidate hash for idempotent reruns.
- Outcome/eligibility rows link to the candidate artifact id in diagnostics at minimum; if schema changes are acceptable, add explicit nullable FK columns later.
- Store both human-readable diagnostics and machine-readable raw payloads.

### Resolution semantics by validation depth

`rescore_only`:
- Reuse baseline plan geometry and baseline canonical outcome label.
- Recompute only score/actionability/eligibility thresholds.
- Before reusing the label, assert candidate geometry hash equals baseline geometry hash.
- If geometry differs, fail closed and reclassify/block as `frozen_input_plan_regeneration` or `full_orchestration_replay`.

`frozen_input_plan_regeneration`:
- Load baseline frozen artifact and baseline plan.
- Regenerate candidate plan/levels from frozen evidence under candidate config.
- Validate geometry:
  - entry band present and positive
  - `entry_price_low <= entry_price_high`
  - stop/take-profit on correct side for action/direction
  - risk distance > minimum tick/epsilon
  - reward/risk inside configured safety bounds
  - horizon is supported by local bars
- If invalid, persist candidate artifact and eligibility as ineligible with explicit rejection reasons; do not reuse baseline outcome.
- If unchanged from baseline, the baseline outcome may be reused but must still be recorded under the candidate hash with `geometry_unchanged=true`.
- If changed, run canonical local outcome resolver against cached bars and persist the candidate-specific result.

`full_orchestration_replay`:
- Continue to use existing full replay path, already local/cache-only for replay inputs.
- Candidate artifacts may still be generated from resulting plans for consistent reporting, but this is not required for the first 5A implementation.

### Local bar-window loading

Add a repository/service helper for outcome windows:

```text
get_outcome_bars(ticker, as_of, horizon_days, resolution_source, local_only=True)
```

Behavior:
- Query local historical daily/intraday bar tables only.
- Bound the window to `as_of < bar_time <= as_of + horizon` or the equivalent existing replay convention.
- Return coverage diagnostics:
  - expected sessions/bars
  - loaded sessions/bars
  - first/last bar timestamp
  - missing date ranges
  - whether the window is sufficient for the selected resolver
- Cache loaded windows in process by `(ticker, as_of_date, horizon, resolution_source)` during one workflow action to avoid repeated DB reads across candidates.
- Never call Yahoo, Alpaca, or any provider path.

### Outcome write/update rules

For every candidate artifact:
- upsert a `ReplayPlanOutcomeRecord` using the same candidate hash
- set `resolution_source` to the resolver output source
- set `status` from the resolver output status
- set `outcome` from the resolver output outcome
- write `outcome_json` containing:
  - candidate artifact id/reference
  - source baseline outcome id/reference
  - resolver version
  - geometry hash before/after
  - local bar coverage diagnostics
  - `remote_fetch_used=false`
  - invalid/missing data status when applicable

For eligibility:
- upsert `ReplayEligibilityRecord` under candidate hash
- preserve source setup/context diagnostics from frozen baseline
- update tuning eligibility based on candidate-specific status:
  - valid resolved win/loss/flat and meets tier rules → eligible according to tier logic
  - invalid geometry → not eligible, tier downgrade/rejection reason
  - missing bars/insufficient window → not eligible for promotion evidence; visible as data coverage gap
  - no-entry/open → count according to existing replay aggregate conventions, but never as hidden wins

### Promotion and tuning implications

Promotion proposal must treat this evidence carefully:
- Discovery/search metrics remain non-promotion evidence.
- Main replay and holdout aggregates must use candidate-specific outcomes, not copied baseline labels, for geometry-changing candidates.
- `missing_local_bars`, `invalid_geometry`, and `insufficient_window` must lower confidence or block promotion according to existing minimum sample/data-quality gates.
- A candidate cannot be promoted if its only geometry-changing validation used copied baseline labels.
- UI comparison tables must show validation depth and whether outcome labels are canonical candidate outcomes or reused baseline labels.

This protects the app from selecting candidates that look better only because their changed stops/targets were never actually tested.

### Incremental implementation breakdown

1. **Extract/identify canonical outcome resolver**
   - Locate current full replay outcome-resolution logic.
   - Extract it behind a service callable with explicit local-only bar windows.
   - Preserve existing tie-break and horizon behavior.
   - Add unit tests around unchanged behavior.

2. **Add local outcome bar-window helper**
   - Implement repository/service function with no provider dependencies.
   - Add tests with complete, missing, and insufficient windows.
   - Add instrumentation/diagnostics proving `remote_fetch_used=false`.

3. **Persist candidate plan artifact**
   - Add migration/model/repository or equivalent existing-table-backed artifact storage.
   - Upsert by `(replay_slice_id, source_baseline_plan_id, candidate_config_hash)`.
   - Record candidate config/settings/code hashes and geometry hashes.

4. **Wire frozen-input validation to resolver**
   - In workflow lightweight candidate path, replace copied baseline outcome for geometry-changing candidates with resolver output.
   - Keep copied baseline label only for `rescore_only` or `geometry_unchanged=true`.
   - Persist invalid-geometry and missing-bar cases as explicit non-promotional evidence.

5. **Aggregate and UI correctness**
   - Ensure `ReplayValidationAggregateService` counts candidate-hash outcomes only.
   - Add detail fields to workflow comparison payload:
     - `canonical_candidate_outcomes_count`
     - `reused_baseline_outcomes_count`
     - `invalid_geometry_count`
     - `missing_local_bars_count`
   - Label non-canonical copied labels as insufficient for promotion.

6. **Promotion gate hardening**
   - Block promotion proposal when a geometry-changing candidate lacks canonical candidate outcomes.
   - Block or require manual remediation for excessive missing local bars.
   - Add clear operator message: hydrate historical bars separately, then rerun validation.

7. **Smoke experiment**
   - Run one small cache-only experiment with:
     - one `rescore_only` candidate
     - one geometry-changing frozen-input candidate
     - one intentionally invalid geometry candidate
   - Verify no provider calls, bounded memory, and candidate-specific outcome changes where expected.

### Detailed tests to add before code changes

- `rescore_only` candidate with unchanged geometry reuses baseline outcome and records threshold-only provenance.
- Geometry-changing candidate with tighter stop changes baseline win to candidate loss when local bars hit stop first.
- Geometry-changing candidate with wider take-profit changes resolved win to open/expired when target is not hit within horizon.
- Candidate with invalid long geometry, e.g. stop above entry or take-profit below entry, is ineligible and no outcome label is copied.
- Missing local outcome bars returns `missing_local_bars`, records diagnostics, and does not call remote providers.
- Candidate artifact upsert is idempotent for repeated workflow action calls.
- Baseline outcome and eligibility records are unchanged after candidate validation.
- Aggregates grouped by `candidate_config_hash` differ from baseline when candidate-specific resolution differs.
- Promotion proposal blocks a geometry-changing candidate whose outcomes are copied baseline labels rather than canonical candidate outcomes.
- Mixed candidate config receives deepest required depth and never slips into `rescore_only` if any geometry key is present.

### Acceptance criteria

- [ ] Geometry-changing candidates are resolved against regenerated candidate levels, not baseline labels.
- [ ] Candidate-specific outcomes use local bars only and expose coverage diagnostics.
- [ ] Invalid geometry is explicit, ineligible, and visible to the operator.
- [ ] Baseline records remain unchanged and auditable.
- [ ] Promotion cannot proceed on non-canonical copied labels for geometry-changing candidates.
- [ ] Runtime remains much cheaper than full orchestration because upstream evidence is not rerun.

## Phase 6 — Rescore-only path hardening

### Tasks

- [ ] Review existing actionability-floor calibration and replay-batch rescore behavior.
- [ ] Define explicit allowlist of parameters valid for `rescore_only`.
- [ ] Add tests showing geometry-changing candidates cannot use `rescore_only`.
- [ ] Persist rescore provenance:
  - source replay batch
  - source plan ids/outcome ids
  - threshold candidate
  - validation depth
- [ ] Ensure UI/API labels rescore-only as threshold-only evidence.

### Acceptance criteria

- [ ] Rescore-only never changes entry/stop/take levels.
- [ ] Rescore-only candidates are not confused with full replay candidates.
- [ ] Promotion gate knows when rescore-only evidence is sufficient or insufficient.

## Phase 7 — Multi-candidate shared slice execution

### Tasks

- [ ] Add an internal execution mode that loads frozen slice/ticker artifacts once and evaluates multiple candidates.
- [ ] Keep external audit model clear:
  - either one logical candidate batch per candidate
  - or one experiment batch with per-candidate results
- [ ] Add memory guardrails:
  - candidate chunk size
  - ticker chunk size
  - max slice artifacts in memory
- [ ] Keep default sequential on the small VPS.
- [ ] Add progress reporting by candidate and slice.

### Acceptance criteria

- [ ] Shared execution produces same results as independent candidate execution for a test fixture.
- [ ] Progress can still be displayed per candidate.
- [ ] Memory stays bounded by chunk settings.

## Phase 8 — Outcome bar-window reuse

### Tasks

- [ ] Add cache/repository helper for post-`as_of` outcome bar windows by ticker/date/horizon/resolution source.
- [ ] Reuse the same bar window for candidate plans with different stop/take levels.
- [ ] Persist resolution diagnostics per candidate outcome, not duplicated raw bar blobs unless necessary.
- [ ] Add tests proving no remote bar fetch during outcome resolution.

### Acceptance criteria

- [ ] Candidate outcome resolution uses local bars only.
- [ ] Multiple candidate outcomes for the same ticker/as_of reuse loaded bar windows in process.
- [ ] Missing bar windows produce coverage/eligibility diagnostics.

## Phase 9 — Candidate deduplication and preflight pruning — partially implemented

### Tasks

- [x] Deduplicate candidate configs by normalized config hash in the reusable `CandidateReplayPlanner` service.
- [ ] Wire planner deduplication into every replay queue path after existing candidate-order tests are migrated.
- [ ] Add effective-equivalence preflight over a small frozen artifact sample:
  - identical actionability decisions
  - near-identical generated levels
  - invalid geometry
  - extreme actionable-count drop
  - extreme concentration
- [ ] Mark duplicate/equivalent candidates as skipped with linked representative.
- [ ] Add preflight result to candidate shortlist UI/API.

### Acceptance criteria

- [ ] Duplicate candidates are not queued for replay.
- [ ] Preflight can only reject/skip candidates, not promote them.
- [ ] Candidate amount for replay pass counts only non-skipped candidates.

## Phase 10 — Early rejection / stop conditions — partially implemented

### Tasks

- [x] Add reusable configurable early-stop policy service for candidate validation aggregates.
- [ ] Wire early-stop policy into long-running replay execution after operator controls exist.
- [ ] Add configurable early-stop rules for candidate validation:
  - too few Tier A cases after minimum slice count
  - materially worse win rate/EV than baseline
  - invalid/no-entry explosion
  - excessive loss concentration
  - repeated infrastructure/data failures
- [ ] Ensure early stop only produces rejection/needs-review status, never promotion.
- [ ] Surface early-stop reason in workflow UI/API.

### Acceptance criteria

- [ ] Tests cover early rejection after minimum evidence threshold.
- [ ] Early-stopped candidate is not promotable.
- [ ] Operator can distinguish early statistical rejection from infrastructure failure.

## Phase 11 — Replay/candidate aggregates — partially implemented

### Tasks

- [x] Add reusable aggregate service over existing replay outcome/eligibility records.
- [x] Expose replay batch efficiency summary through the plan-generation tuning API.
- [ ] Add optional materialized aggregate table keyed by:
  - experiment id or replay batch id
  - candidate id/config hash
  - validation depth
  - tier
  - ticker
  - setup family
  - direction
  - date/window
  - outcome/horizon
- [ ] Update aggregates incrementally as candidate validation completes.
- [ ] Use aggregates for workflow comparison UI.
- [ ] Add rebuild command for aggregate repair.

### Acceptance criteria

- [ ] UI comparison does not require scanning every raw outcome repeatedly.
- [ ] Aggregate rebuild produces deterministic results.
- [ ] Aggregates include enough concentration metrics for promotion gates.

## Phase 12 — Workflow/API integration

### Tasks

- [ ] Add `validation_depth` to candidate DTOs.
- [ ] Add recomputation explanation to candidate cards.
- [ ] Add validation action routing:
  - `rescore_only` → rescore service
  - `frozen_input_plan_regeneration` → frozen-input service
  - `full_orchestration_replay` → existing full historical replay service
- [ ] Add blockers when requested depth is impossible due to missing frozen artifacts.
- [ ] Add operator copy:
  - “reused frozen cheap-scan/signal/context evidence”
  - “full orchestration required because candidate changes upstream selection”
  - “local historical news only; missing articles degrade coverage”

### Acceptance criteria

- [ ] Workflow page shows why a candidate is cheap/expensive to validate.
- [ ] Operators cannot accidentally run full orchestration for plan-only candidates without confirmation.
- [ ] Promotion proposal includes validation depth and evidence limitations.

## Phase 13 — Documentation and rollout

### Tasks

- [ ] Update `docs/tuning-workflow-ux-implementation-plan.md` to reference this remediation plan.
- [ ] Update `docs/historical-playback-tuning-plan.md` if replay operating discipline changes.
- [ ] Update operator docs once UI ships.
- [ ] Run full test suite.
- [ ] Run a small cache-only smoke experiment:
  - one baseline frozen artifact set
  - one rescore-only candidate
  - one frozen-input plan-regeneration candidate
  - one full-orchestration candidate if feasible
- [ ] Compare runtime/resource usage before and after.
- [ ] Commit and push coherent milestone.

### Acceptance criteria

- [ ] Docs clearly distinguish validation depths.
- [ ] Runtime improvement is measured and recorded.
- [ ] Existing full replay remains available for upstream-changing candidates.

## Recommended implementation order

1. Replay local-only news tests and enforcement.
2. Parameter impact map and candidate depth classifier.
3. Frozen artifact contract audit.
4. Frozen-input plan regeneration service.
5. Workflow/API labels and blockers.
6. Dedup/preflight pruning.
7. Shared slice execution and aggregates.
8. Early stop rules.

This order first removes leakage/provider risk, then prevents unnecessary full replay, then improves throughput.

## Risks and mitigations

### Risk: frozen artifacts are incomplete

Mitigation:
- add artifact completeness checks
- fall back to full orchestration only when causally required and local inputs are available
- otherwise block with a clear hydration/replay instruction

### Risk: cheap validation path becomes semantically wrong

Mitigation:
- central parameter impact map
- deepest-depth wins for mixed candidates
- tests for each parameter class
- unknown keys fail closed

### Risk: UI hides evidence limitations

Mitigation:
- computation labels are mandatory
- promotion proposal includes validation depth
- discovery/rescore/frozen/full evidence are not conflated

### Risk: optimization creates less auditable results

Mitigation:
- persist provenance links from candidate result to frozen artifact/source replay batch
- keep raw detail pages linked
- provide aggregate rebuild command

## Open questions

- Should frozen upstream artifacts be persisted in a new table or assembled from existing replay-generated signal/plan payloads?
- Is `global.actionable_confidence_floor_percent` always safe as `rescore_only`, or only when the stored intended action/plan geometry is already available?
- Should universe-filter candidates use full orchestration, or can a restricted “filtered frozen artifacts” mode be valid when the filter only removes tickers after baseline artifact generation?
- Which social/context/fundamental paths currently have remote refresh side effects that need explicit replay-mode guards?
