# Replay validation efficiency remediation plan

**Status:** planned

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
- [ ] Wire the service into candidate replay execution with canonical outcome resolution.
- [x] Inputs:
  - frozen artifact record/reference
  - candidate config override
  - baseline/current non-tuned settings snapshot
- [x] Reuse upstream evidence exactly as stored for setup/context metadata available in stored plan payloads.
- [x] Invoke shared live plan-framing logic under scoped candidate config.
- [x] Do not rerun cheap scan, news fetch, social fetch, deep analysis, or signal generation.
- [ ] Resolve generated candidate plan through canonical outcome resolution.
- [ ] Persist candidate plan/outcome/eligibility with provenance:
  - source frozen artifact id
  - candidate config hash
  - validation depth
  - code/settings hashes
- [ ] Add invalid-geometry diagnostics and rejection reasons.

### Acceptance criteria

- [ ] Tests prove cheap scan and news services are not called.
- [ ] Candidate plan geometry changes when geometry parameters change.
- [ ] Outcome resolution reruns using local outcome bars.
- [ ] Live settings are not mutated.

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
