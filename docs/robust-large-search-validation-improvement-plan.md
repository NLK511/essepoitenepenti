# Robust large-search validation improvement plan

**Status:** substantially implemented; shadow validation and production-default rollout remain

Canonical contracts:
- `specs/large-parameter-search-spec.md`
- `specs/plan-generation-tuning-spec.md`
- `specs/historical-playback-tuning-spec.md`
- `specs/tuning-workflow-ux-spec.md`
- `specs/edge-validation-standard.md`

## Purpose

Prevent Aurelio from selecting plan-generation candidates that look exceptional only because one or a few dates performed unusually well, while preserving the ability to explore very large candidate spaces cheaply.

The solution is a deterministic multi-fidelity funnel:

```text
large cheap discovery
  → date/fold stability screen
  → bounded rolling walk-forward selection
  → one-time locked holdout
  → candidate-specific replay and paper validation
```

The large search remains research-only. This work improves which candidates deserve expensive validation; it does not weaken existing replay, promotion, edge-validation, or operator-approval gates.

## Problem confirmed in the current implementation

Current large-search behavior in `scripts/large_plan_generation_parameter_search.py`:

1. loads eligible records;
2. creates one oldest/newest split through `PlanGenerationTuningService._split_records()`;
3. evaluates every coarse and fine candidate on both partitions;
4. ranks primarily by `validation_expected_value`;
5. uses top coarse candidates to generate fine candidates.

This means the partition named `validation` participates directly in candidate selection and refinement. It is therefore discovery evidence, not an untouched validation set. With tens or hundreds of thousands of candidates, a configuration that happens to fit one exceptional date has a high probability of appearing near the top.

There was also a documentation conflict:

- `large-parameter-search-spec.md` described EV-first ranking on one split;
- `plan-generation-tuning-spec.md` required rolling walk-forward exploration ranking and canonical win-rate-first promotion ordering.

The canonical specs have now been reconciled: a broad search may use cheap discovery panels, but survivor selection requires stability and rolling evidence, and a locked holdout may not feed refinement.

## Goals

1. Search hundreds of thousands of configs without evaluating all of them over large windows.
2. Compare every candidate against the same baseline on the same dates at each stage.
3. detect dependence on exceptional dates before expensive replay.
4. prevent repeated holdout inspection from becoming hidden training.
5. preserve deterministic, resumable, memory-bounded execution.
6. expose enough diagnostics for an operator to understand why a candidate survived or failed.
7. preserve current active configuration, broker settings, and execution safety.

## Non-goals

- Automatically promote a large-search winner.
- Replace canonical point-in-time replay outcome resolution.
- Treat stored-plan rescoring as equivalent to full replay.
- Build a new optimizer for upstream signal-gating parameters.
- Guarantee statistical significance from thin historical evidence.
- Add an opaque weighted score that hides win rate, EV, drawdown, or concentration trade-offs.

## Terminology

### Discovery evidence

Evidence repeatedly inspected while generating, ranking, or refining candidates. It may be useful for pruning but cannot be called holdout evidence.

### Selection evidence

Disjoint date blocks and rolling walk-forward slices used to choose a bounded finalist set. It is stronger than discovery evidence but has still influenced selection.

### Locked holdout

An immutable, non-overlapping period evaluated only after finalist configs and their ordering policy are frozen. Its result may accept/reject/defer a finalist, but must not create another refinement round.

### Evidence date

The independent grouping unit for concentration and resampling:

1. replay evidence: canonical replay slice `as_of` market-session date;
2. stored-plan evidence: exchange-session date derived from `plan.computed_at` when available;
3. fallback: UTC date with an explicit `utc_date_fallback` diagnostic.

Multiple plans or tickers on one evidence date are correlated and must not be treated as independent bootstrap samples.

### Qualified fold

A disjoint evidence-date block where both candidate and baseline satisfy the configured minimum actionable/resolved sample requirement.

## Non-negotiable safety invariants

1. The active baseline config enters and survives every funnel stage.
2. All candidates in one stage use exactly the same evidence dates and records.
3. Discovery, selection, and holdout partitions do not overlap.
4. Holdout records are never passed to coarse search, fine search, stage ranking, or candidate generation.
5. Fine/refinement candidates may be generated only from discovery/selection results available before holdout.
6. Removing an exceptional date is calculated from per-date aggregates; it must not change outcome semantics.
7. Missing/thin data can reject or defer a candidate, never improve its rank.
8. Resampling uses dates or contiguous date blocks, never individual trades.
9. Current promotion and edge-validation gates remain unchanged and fail closed.
10. Resume-cache compatibility includes all evidence partition and stage policy hashes.

## Target evidence partition contract

### Explicit experiment windows

The tuning workflow should remain authoritative when an experiment provides dates:

- `discovery_start`, `discovery_end`
- `selection_start`, `selection_end`
- `holdout_start`, `holdout_end`

Validation rules:

- windows are chronological and non-overlapping;
- each ends before the next begins;
- all outcome horizons are resolvable using local data;
- dates are persisted before execution;
- editing windows after execution invalidates prior stage/holdout hashes;
- inspecting holdout and then changing configs marks the prior holdout `contaminated`.

### Standalone-script fallback

The CLI should accept explicit date boundaries. If omitted, it may derive deterministic boundaries from distinct evidence dates:

- oldest 60%: discovery;
- next 20%: selection;
- newest 20%: locked holdout.

A derived split requires at least 60 distinct evidence dates and at least 20 dates in both selection and holdout. Otherwise the run remains `research_only`, reports `insufficient_dates_for_locked_holdout`, and must not label any partition as holdout.

The fallback percentages are operational defaults, not a claim that 20% is always statistically sufficient.

### Partition identity

Persist for every partition:

```text
partition_id
role: discovery | selection | locked_holdout
start_date / end_date
evidence_dates
record_count
actionable/resolved count
ticker/setup/direction coverage
source batch/run identifiers
input_record_hash
partition_date_hash
created_at
```

For the first implementation this may live in artifact JSON rather than a new table. Database persistence should be added only if workflow lifecycle requirements cannot be met through existing experiment artifacts.

## Target successive-halving funnel

Defaults below are conservative starting points. They must be configurable, recorded in artifacts, and calibrated in shadow runs before being treated as stable operational defaults.

### Stage 0 — Normalize, deduplicate, and preflight

Input:
- baseline plus all generated coarse configs.

Work:
- normalize numeric values;
- hash canonical configs;
- remove exact duplicates;
- reject unknown keys;
- classify validation depth;
- reject impossible bounds;
- optionally detect effective equivalence on a tiny frozen sample;
- retain baseline regardless of equivalence.

Output:
- unique candidates;
- duplicate/equivalence links;
- explicit preflight rejection reasons.

Cost:
- no full scoring.

### Stage 1 — Broad discovery panel

Default input:
- up to the requested large-search budget, e.g. 200,000 configs.

Evidence:
- one deterministic panel of up to 24 dispersed discovery dates;
- minimum 12 dates, otherwise report thin discovery;
- dates stratified across calendar segments and available generation-time volatility/regime labels;
- no holdout or selection dates.

Stratification priority:
1. spread dates across the discovery period;
2. include available high/normal/low volatility dates;
3. include positive/negative/flat broad-market dates when labels are point-in-time safe;
4. maximize ticker/setup/direction coverage;
5. use a deterministic seed to break ties.

Scoring:
- compute pooled candidate metrics;
- compute per-date candidate and paired baseline metrics;
- enforce minimum actionability/coverage;
- rank only for pruning using the selected discovery objective and stability tie-breaks.

Default survivor budget:
- baseline plus the better of `1%` of unique candidates or `100`, capped at `2,000`.

Stage 1 is allowed to false-reject potentially good candidates in exchange for cost control. It is not allowed to promote one.

### Stage 2 — Multi-block stability screen

Input:
- Stage 1 survivors only.

Evidence:
- all discovery dates when affordable, otherwise a deterministic expanded panel of up to 60 dates;
- at least 6 disjoint chronological folds;
- the same folds for all candidates.

Metrics:
- candidate and baseline actionable count, win rate, and normalized EV by fold;
- candidate-minus-baseline fold deltas;
- median, minimum, and positive-fold fraction;
- per-date net contribution;
- result with best date removed;
- best-date and top-three-date positive-contribution shares;
- ambiguity and no-action changes;
- ticker, setup-family, and direction concentration.

Provisional instability flags:

- fewer than 4 qualified folds;
- candidate advantage disappears beyond canonical tie tolerance after removing its best date;
- fewer than half of qualified folds are non-worse than baseline on the primary objective;
- one date contributes more than `max(35%, baseline best-date share + 10pp)` of positive contribution;
- top three dates contribute more than `max(65%, baseline top-three share + 10pp)`;
- severe fold regression under existing walk-forward definitions;
- actionable coverage collapse beyond existing promotion guardrails.

Concentration flags should be `needs_review` rather than hard rejection when fewer than 20 dates have positive contribution. Thinness must be explicit; it must not be interpreted as stability.

Default survivor budget:
- baseline plus top `100` stability-eligible candidates.

### Stage 3 — Rolling walk-forward selection

Input:
- no more than 100 Stage 2 survivors by default.

Evidence:
- selection partition only;
- rolling windows through `PlanGenerationWalkForwardService`;
- no locked holdout records.

Required changes:
- evaluate baseline once per slice and reuse its aggregates;
- use slice views, not copied record lists;
- support candidate batches and bounded memory;
- persist qualified/thin slice counts and severe regressions;
- apply stability eligibility before canonical ranking.

Ranking:

1. reject/defer candidates failing minimum qualified slices or severe-regression rules;
2. apply the canonical objective from `plan-generation-tuning-spec.md`;
3. use median/worst-fold and exceptional-date diagnostics as stability tie-breakers;
4. prefer closer-to-live and fewer changed keys when still tied.

Default finalist budget:
- baseline plus top `10` candidates.

No fine candidates may be generated after this stage unless selection is explicitly restarted and a fresh future holdout will be used.

### Stage 4 — Locked holdout falsification

Input:
- frozen baseline and at most 10 frozen finalists;
- frozen ranking/objective/stability policy;
- immutable holdout partition hash.

Execution:
- evaluate each finalist once;
- compare it with baseline on paired dates;
- calculate pooled, per-fold, exceptional-date, concentration, and uncertainty metrics;
- run candidate-specific canonical replay where required by validation depth;
- do not generate or tune any new config.

Outcomes:
- `passed_holdout`
- `failed_holdout`
- `defer_thin_holdout`
- `holdout_contaminated`
- `holdout_data_incomplete`

Passing holdout means only that the candidate may proceed to normal replay/paper/promotion review. It does not make a large-search artifact promotion-capable.

If the operator changes the config, bounds, objective, fold policy, or ranking policy after viewing holdout results, the candidate needs a new future holdout. Re-running to repair an infrastructure failure is allowed only when the config and input hash are unchanged and the first attempt produced no scoreable result.

### Stage 5 — Existing replay, paper, and promotion gates

Preserve:
- validation-depth routing;
- candidate-specific geometry regeneration and local outcome resolution;
- replay Tier A requirements;
- baseline comparison;
- drawdown/loss-streak and concentration gates;
- paper evidence;
- operator approval;
- edge-validation/autonomy gate.

Discovery and selection evidence must be labeled separately from locked-holdout, replay, and broker evidence in every promotion proposal.

## Metric contract

### Per-date aggregate

For each candidate and evidence date persist/derive:

```text
date
candidate_config_hash
baseline_config_hash
record_count
actionable_count
win_count
loss_count
ambiguous_count
expected_value_total
expected_value_per_actionable
win_rate
baseline equivalents
paired deltas
```

`expected_value_total` remains useful for economics but must not silently reward a candidate only for producing more actions. `expected_value_per_actionable`, actionability ratio, and win rate must accompany it.

### Exceptional-date diagnostics

Use daily aggregates to calculate without rerunning candidate resolution:

```text
best_date
best_date_contribution
best_date_positive_share
top_three_positive_share
total_without_best_date
delta_vs_baseline_without_best_date
primary_objective_without_best_date
leave_one_date_out_worst_delta
profitable_date_count
non_worse_than_baseline_date_count
```

Positive-contribution share denominator is the sum of positive daily contributions, not total net EV. If there are no positive dates, the share is undefined and the candidate cannot claim stable positive performance.

The primary robustness question is paired:

> Does the candidate still beat or tie the baseline, within canonical tolerances, after removing the candidate's best contributing date?

### Fold metrics

For every fold:

- date range and partition hash;
- candidate and baseline sample counts;
- candidate and baseline win rate;
- total and per-actionable EV;
- paired deltas;
- actionability ratio;
- ambiguity count;
- qualification/thin reason.

Report median and worst qualified-fold deltas. Do not average away an unreported severe regression.

### Uncertainty

Add deterministic date-block bootstrap only after the deterministic funnel is working:

- resample evidence dates or contiguous blocks;
- fixed seed stored in artifact;
- report confidence interval for paired candidate-baseline win-rate and EV deltas;
- do not bootstrap individual plans independently;
- use lower confidence bounds only as rejection/defer evidence in the first release.

More advanced multiple-testing statistics, such as deflated Sharpe or probability of backtest overfitting, may be added later as diagnostics. They should not delay the core date-concentration fix.

## Candidate-generation policy

### Coarse generation

Keep current deterministic random generation for the first implementation so the validation change can be measured independently.

### Fine generation

Move fine generation after Stage 1 discovery and before Stage 2 stability screening. Fine seeds must come only from discovery evidence. Fine candidates join Stage 2 and must not bypass stability checks.

### Later efficiency experiment

After the funnel is stable, compare deterministic random search with Sobol/quasi-random or bounded evolutionary/TPE sampling. Adopt a smarter generator only if it:

- finds equal or better stable candidates with fewer evaluations;
- remains deterministic/reproducible;
- does not widen parameter bounds silently;
- records every proposed candidate and seed;
- does not inspect locked holdout evidence.

## Artifact and resume-cache schema v2

Top-level artifact additions:

```text
schema_version: 2
run_role: research_only
baseline_config_hash
objective
scoring_version
candidate_generation_policy
partitions
stage_policy
stages
finalists
locked_holdout_status
holdout_contamination_status
promotion_capable: false
```

Each stage records:

```text
stage_name
status
started_at / completed_at
input_candidate_count
evaluated_candidate_count
survivor_count
partition_id / partition_hash
date_panel_hash
baseline_hash
policy_hash
rejection_reason_counts
runtime and memory diagnostics
survivor summaries
```

Each candidate summary records:

- config and config hash;
- changed keys and validation depth;
- stage reached;
- pooled metrics;
- date/fold stability metrics;
- concentration metrics;
- uncertainty metrics when available;
- rejection/defer reasons;
- whether holdout was viewed;
- promotion capability fixed to false for the large-search artifact.

Resume cache v2 key:

```text
(config_hash, stage_name, partition_hash, panel_hash, baseline_hash, policy_hash, scoring_version)
```

Schema-v1 cache remains readable for historical artifacts but cannot be reused in a v2 staged run.

## Backend implementation design

### New focused modules

Prefer extracting reusable logic from the script:

- `src/trade_proposer_app/services/tuning_evidence_partitions.py`
  - evidence-date resolution;
  - explicit/derived partition validation;
  - deterministic partition and panel hashes.

- `src/trade_proposer_app/services/tuning_stability.py`
  - per-date/fold aggregates;
  - exceptional-date diagnostics;
  - stability flags;
  - candidate-versus-baseline comparison.

- `src/trade_proposer_app/services/large_search_funnel.py`
  - stage policies;
  - successive-halving orchestration;
  - survivor selection;
  - progress events;
  - no database/provider dependencies.

Keep CLI parsing and artifact writing in:
- `scripts/large_plan_generation_parameter_search.py`

Reuse:
- `PlanGenerationTuningService._candidate_resolution()` initially;
- `PlanGenerationWalkForwardService` for Stage 3;
- candidate validation-depth classifier;
- existing memory guards;
- frozen-input/local-only replay services for Stage 4.

After parity tests, expose public scoring interfaces rather than permanently depending on private `_score_records()` and `_candidate_resolution()` methods.

### Performance design

1. Sort eligible records once by evidence date.
2. Build index ranges/views per date and fold; avoid copied record lists.
3. Score baseline once per stage/date/fold.
4. Evaluate candidate batches with bounded top/survivor heaps.
5. Persist cache lines incrementally.
6. Release candidate per-date details after aggregate/cache write unless it survives.
7. Reuse frozen slice artifacts and outcome-bar windows where validation depth permits.
8. Keep execution sequential by default on the small VPS; parallelism is a later measured option.

### API/job integration

Update existing large-search request/job payloads to accept:

- explicit discovery/selection/holdout dates;
- stage candidate budgets;
- panel date limits;
- minimum qualified folds/dates;
- concentration thresholds;
- objective and deterministic seed;
- `allow_derived_partitions` flag.

Job progress should report:

```text
stage
input candidates
evaluated candidates
survivors
current partition/date panel
elapsed time
estimated next stage work
thin/failed reason
```

No new schedulable or auto-promotion job type is required.

## UI/workflow changes

### Experiment setup

- Require distinct discovery, selection, and holdout windows for robust large search.
- Show overlap/resolvability errors before queueing.
- Display candidate budgets per funnel stage rather than one misleading candidate count.
- Explain that larger discovery is cheap but does not increase promotion evidence.

### Candidate table

Add compact columns:

- stage reached;
- stability status;
- qualified/positive folds;
- median and worst-fold delta;
- result excluding best date;
- best-date contribution share;
- selection walk-forward status;
- locked-holdout status;
- validation depth.

### Candidate detail

Show:

- daily contribution chart against baseline;
- fold comparison table;
- highlighted best day/top three days;
- pooled result with and without best day;
- concentration by ticker/setup/direction;
- exact evidence partition and config hashes;
- rejection/defer reasons in plain language.

### Operator warnings

Required copy:

- “Discovery evidence was repeatedly used to select candidates; it is not holdout evidence.”
- “This candidate loses its advantage when its best date is removed.”
- “Locked holdout has been viewed. Refining this candidate requires a new future holdout.”
- “Evidence is too thin to determine stability.”
- “Large-search candidates remain research-only until replay and paper gates pass.”

## Detailed test-first plan

Tests must be added or updated from the revised specs before implementation behavior changes.

### Phase 1 tests — partition integrity

Create `tests/test_tuning_evidence_partitions.py`:

- explicit windows reject overlap and reverse chronology;
- discovery, selection, and holdout record IDs are disjoint;
- derived partitioning is deterministic;
- fewer than 60 distinct dates cannot claim locked holdout;
- partition hashes change when dates, records, baseline, or policy change;
- UTC fallback is visible;
- holdout records cannot be requested by a discovery-stage view;
- editing an experiment window invalidates prior hash/status.

### Phase 2 tests — stability metrics

Create `tests/test_tuning_stability.py`:

- one exceptional winning date plus many weak dates is flagged;
- a candidate with the same pooled EV spread across dates ranks as more stable;
- removing best date is paired correctly against baseline;
- best-date share uses sum of positive contributions;
- no positive dates produces undefined concentration and no stability claim;
- multiple same-date trades are grouped together;
- median and worst folds ignore thin folds but report thin reasons;
- baseline concentration allowance is applied correctly;
- candidate actionable-count collapse is visible;
- order of input records does not change outputs.

### Phase 3 tests — funnel and ranking

Expand `tests/test_large_plan_generation_parameter_search.py` and add `tests/test_large_search_funnel.py`:

- every candidate in a stage receives the same panel hash;
- baseline survives every stage;
- exact/effective duplicates are not re-evaluated;
- Stage 1 retains only the configured bounded survivor count;
- fine seeds come only from pre-holdout discovery survivors;
- unstable high-EV candidate loses to stable baseline-improving candidate;
- canonical ranking applies only after stability eligibility;
- Stage 3 receives no more than configured survivors;
- holdout is called only after finalist configs are frozen;
- holdout results cannot trigger fine generation;
- repeated scoreable holdout request is blocked/marked contaminated;
- infrastructure retry is idempotent when hashes match and no score exists;
- deterministic seed yields identical candidates, panels, and ranks.

Replace the current test asserting “best validation EV wins” with spec-backed tests for stage-specific discovery pruning and stable selection. This is a valid test change because the canonical specs have changed and the old behavior is the identified bug.

### Phase 4 tests — resume and interruption

- v1 cache cannot satisfy v2 stage evaluation;
- changing a partition/panel/policy hash invalidates only incompatible entries;
- restart resumes within a partially completed stage;
- completed earlier stages are reused exactly;
- interrupted holdout does not become `viewed/scored` unless a score was persisted;
- cache remains bounded to line streaming and top survivors.

### Phase 5 tests — walk-forward and replay integration

- baseline slice scores are computed once and reused;
- slice views do not copy full record lists;
- geometry-changing finalist uses candidate-specific canonical outcomes;
- rescore-only finalist reuses baseline geometry only when hashes match;
- missing local bars defer/reject rather than fetch remotely;
- locked holdout aggregation uses candidate outcomes, not copied labels;
- large-search artifact remains non-promotable after holdout pass.

### Phase 6 tests — API/UI

- request validation rejects overlapping windows and unsafe stage budgets;
- job payload round-trips stage policy;
- progress payload identifies current stage;
- workflow candidate import includes stability and partition provenance;
- UI displays best-date dependency and holdout contamination warnings;
- UI never labels discovery partition as validation/holdout;
- existing large-search artifact v1 remains readable with a legacy warning.

## Incremental implementation phases

### Phase 0 — Specification reconciliation — completed

- [x] Document current single-split winner's-curse limitation.
- [x] Reconcile large-search ranking with canonical tuning semantics.
- [x] Define discovery/selection/locked-holdout boundaries.
- [x] State that holdout cannot feed refinement.
- [x] Add this active implementation plan to the docs index.

### Phase 1 — Evidence-date and partition foundation — implemented

- [x] Add partition DTOs and hash functions.
- [x] Add explicit date CLI arguments and request fields.
- [x] Implement safe derived fallback.
- [x] Emit partition diagnostics in artifact v2.
- [x] Keep schema-v1 artifacts readable by existing generic artifact/UI paths, but do not reuse schema-v1 caches for staged decisions. The unsafe single-split execution mode was removed rather than retained.

Acceptance:
- partition integrity tests pass;
- no Stage 1 code can access holdout records;
- old artifacts remain readable.

### Phase 2 — Daily/fold stability engine — implemented

- [x] Reuse the canonical compact candidate scoring path for per-date evaluation.
- [x] Add per-date baseline/candidate aggregates.
- [x] Add best-date removal and contribution concentration.
- [x] Add fold metrics and instability reasons.
- [x] Validate calculations against hand-built fixtures.

Acceptance:
- exceptional-day fixture is rejected/flagged;
- stable fixture survives despite equal or slightly lower pooled EV;
- results are deterministic.

### Phase 3 — Stage 0/1/2 successive halving — implemented

- [x] Implement streaming normalization/deduplication and panel selection.
- [x] Evaluate coarse candidates only on Stage 1 panel.
- [x] Generate fine candidates from Stage 1 survivors.
- [x] Run Stage 2 expanded stability screen.
- [x] Stream cache/artifact progress and keep memory bounded.

Acceptance:
- a 200k logical-candidate run sends at most the configured 2,000 survivors to Stage 2 and 100 to Stage 3;
- baseline always survives;
- no selection/holdout leakage occurs.

### Phase 4 — Stage 3 walk-forward selection — implemented

- [x] Extend walk-forward service with reusable baseline slice aggregates.
- [x] Evaluate the bounded survivor set over selection evidence.
- [x] Apply stability eligibility then canonical precision-first ranking.
- [x] Freeze finalist configs and policy hashes in artifact v2.

Acceptance:
- no more than configured finalists proceed;
- candidate ordering is explained by visible metrics/tie rules;
- memory does not scale as candidates × copied slices.

### Phase 5 — Stage 4 locked holdout — partially implemented

- [x] Keep holdout records isolated from discovery, refinement, and selection code paths.
- [x] Classify finalists by validation depth.
- [x] Persist stored-plan holdout outcomes and paired diagnostics.
- [x] Never generate refinement candidates after holdout evaluation inside a run.
- [ ] Add durable cross-run/experiment holdout-view contamination tracking. Current artifacts prove that one staged run did not refine on holdout, but cannot detect a separate new run intentionally reusing the same historical holdout.
- [x] Mark geometry-changing finalists `requires_canonical_candidate_replay`; the existing tuning workflow remains the canonical local-only replay path.

Acceptance:
- holdout cannot influence candidate generation;
- changed config/policy requires new holdout;
- passing result remains research-only pending normal gates.

### Phase 6 — Workflow and UI — implemented for advanced tuning and workflow import

- [x] Add stage budgets/window controls to the advanced tuning page and workflow job payload.
- [x] Add selected-finalist stability, best-date, and holdout diagnostics.
- [x] Add plain-language research-only and canonical-replay warnings.
- [x] Preserve generic legacy artifact display.
- [x] Import stability/holdout status into tuning-workflow candidate metadata.
- [ ] Add a dedicated daily contribution chart; current UI exposes the compact metrics and raw artifact details.

Acceptance:
- operator can identify one-day-dependent candidates without opening raw JSON;
- discovery, selection, and holdout labels are unambiguous;
- next safe action is visible.

### Phase 7 — Shadow validation and threshold calibration

Run the new funnel without promotion influence on existing large-search evidence and at least one fresh cache-only campaign.

Compare:

- old top candidates vs new finalists;
- pooled EV/win rate;
- best-day/top-three dependency;
- walk-forward qualified and winning slices;
- locked-holdout result where a genuinely untouched period exists;
- candidate evaluations per stage;
- wall time, peak RSS, and cache size;
- false rejection concerns from candidates pruned early.

Do not tune thresholds against the locked holdout. Adjust Stage 1/2 budgets and concentration thresholds using discovery/selection shadow evidence only. Record every threshold change and reserve a new future holdout for final confirmation.

Acceptance:
- materially lower exceptional-date concentration among finalists;
- large-window work is bounded to survivors;
- no runtime/memory regression that defeats the funnel;
- explicit keep/change/reject decision artifact exists.

### Phase 8 — Rollout

- [ ] Make staged funnel the default large-search mode.
- [ ] Keep legacy mode advanced/research-only for one release, then remove if no audit need remains.
- [ ] Update operational docs and UI field guide.
- [ ] Run focused and full test suites.
- [ ] Check docs coherence.
- [ ] Commit and push the completed milestone.

## Performance acceptance targets

Measured on the same evidence and candidate-generation seed:

1. Stage 1 evaluates all configs only on its bounded panel.
2. No more than 1%/2,000 candidates reach Stage 2 by default.
3. No more than 100 candidates reach full selection walk-forward.
4. No more than 10 candidates reach locked holdout.
5. Peak memory remains bounded by eligible records plus one candidate batch and survivor summaries, not all candidate/date details.
6. Restart resumes without repeating compatible completed candidate-stage evaluations.
7. Baseline scoring work is reused per date/fold wherever semantics are identical.

Wall-time targets should be recorded after the first shadow run rather than guessed in advance.

## Rollback and compatibility

- No database migration is required for the first artifact-backed release.
- Keep artifact schema-v1 parsing and display a legacy single-split warning.
- Do not reuse v1 cache entries for v2 staged decisions.
- The staged mode can be disabled without affecting active configs or broker behavior.
- If Stage 3/4 fails, retain earlier research artifacts but mark the run incomplete and non-promotable.
- Never fall back silently from locked holdout to the old repeatedly inspected validation split.

## Risks and mitigations

### Risk: representative panel misses a narrow real edge

Mitigation:
- deterministic stratification;
- baseline retention;
- configurable survivor budget;
- shadow analysis of false rejections;
- panel rotation between campaigns, never within a campaign.

### Risk: concentration rules punish legitimately event-driven strategies

Mitigation:
- compare concentration with baseline;
- flag rather than hard-reject thin positive-date samples;
- allow explicitly approved narrow-policy research, while keeping normal promotion blocked.

### Risk: holdout becomes contaminated operationally

Mitigation:
- immutable partition/config/policy hashes;
- persisted viewed/scored status;
- UI warning and automatic `holdout_contaminated` state after refinement.

### Risk: overlapping plans make uncertainty look stronger than it is

Mitigation:
- group by evidence date;
- use date/block resampling;
- report distinct dates and concentration alongside trade counts.

### Risk: implementation duplicates outcome semantics

Mitigation:
- reuse `_candidate_resolution()` only as an interim stored-rescore path;
- use canonical candidate-specific replay resolver for geometry-changing holdout evidence;
- add parity tests before exposing public scoring APIs.

### Risk: a robust score becomes opaque or gameable

Mitigation:
- use explicit stability eligibility and canonical lexicographic ranking;
- show every component and rejection reason;
- avoid one blended scalar score in v1.

## Definition of done

This plan is complete when:

- large discovery no longer ranks all candidates on a partition described as validation;
- discovery, selection, and locked holdout are disjoint and auditable;
- large candidate sets are pruned through deterministic successive halving;
- per-date/fold and best-date-exclusion diagnostics are persisted and visible;
- selection walk-forward runs only on a bounded survivor set;
- holdout cannot feed refinement and contamination is explicit;
- geometry-changing finalists use canonical candidate outcomes;
- artifacts remain research-only until existing replay/paper/promotion gates pass;
- shadow evidence demonstrates lower lucky-day dependence at acceptable runtime;
- relevant focused tests and the full suite pass;
- docs are coherent and the completed plan is archived.
