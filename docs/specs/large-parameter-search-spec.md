# Plan generation large tuning search spec

**Status:** current and target behavior

Implemented as an offline/non-schedulable, research-only staged tuning search script and UI queue action. Broad discovery, date/fold stability screening, bounded selection walk-forward, and locked stored-plan holdout falsification are implemented. Geometry-changing finalists still require canonical candidate-specific replay through the tuning workflow before promotion review.

## Goal

Allow very large plan-generation parameter searches, including hundreds of thousands of sampled permutations, without exhausting memory on the local machine.

This is a research tuning tool only. It is intentionally not schedulable and must not promote settings automatically.

## Safety rules

- The search runs offline from corrected eligible plan/outcome evidence.
- It must stream candidate generation/evaluation and keep only a bounded top-K result set in memory.
- It must reuse the memory-safe eligible-record loader from `PlanGenerationTuningService`.
- It must write an artifact with the best coarse-search candidates and local fine-tune candidates.
- It must not mutate active plan-generation config, actionability thresholds, broker settings, or order execution.
- Any promising result still needs normal holdout, walk-forward stability, paper evidence, and operator approval before promotion.

## Current search shape and fixed limitation

Operator-facing name: **Plan Generation Large Tuning Search**. This name keeps it under the plan-generation tuning family while distinguishing it from the built-in standard/exploratory/wide tuning searches.

The previous implementation scored every coarse and fine candidate on one chronological split, called the repeatedly inspected tail `validation`, ranked primarily by expected value, and used its winners for refinement. That caused the winner's-curse bug addressed by this spec: one exceptional date could dominate candidate selection, and the repeatedly inspected partition was not a true holdout.

The current implementation instead runs coarse and fine discovery on a shared deterministic discovery panel, applies paired date/fold stability checks, bounds rolling walk-forward selection to survivors, and evaluates frozen finalists on a separate locked stored-plan holdout. Precision-first canonical ordering replaces EV-first ordering. Artifacts use schema v2 and retain `promotion_capable=false`.

## Target staged search contract

Large exploration must use a multi-fidelity funnel:

1. **Preflight** — normalize, deduplicate, and reject invalid/effectively equivalent configs.
2. **Broad discovery** — score all candidates on one deterministic, stratified panel of dispersed market dates shared by every candidate.
3. **Stability screen** — score only survivors over multiple disjoint date blocks and reject candidates dependent on one date or one block.
4. **Selection walk-forward** — run rolling comparison against the active baseline for a bounded shortlist.
5. **Locked holdout** — evaluate finalists once on an immutable, non-overlapping period. Holdout results must not generate refinements or reorder candidates for another holdout attempt.
6. **Replay/paper validation** — keep normal candidate-specific replay, promotion, and paper gates unchanged.

The baseline config must survive every stage. Each stage must persist its input-date/window hash, candidate count entering and leaving, rejection reasons, objective, code/config version, and metrics. Later stages may reject candidates but must never retroactively turn discovery metrics into promotion evidence.

Broad discovery may be large because it is cheap. Expensive evidence must be allocated through successive halving rather than by running every candidate over the largest window. Default budgets and fallback behavior are defined in `../robust-large-search-validation-improvement-plan.md`.

## Objective profiles and hard sample gates

Large search must persist an `objective_profile` and `min_actionable_mode` in every schema-v2 artifact.

Supported objective profiles:

- `research_precision` — maximize actionable win rate after sample floors; EV remains visible but can be secondary.
- `research_ev_per_trade` — maximize expected value per actionable trade after sample and WR floors.
- `promotion_candidate` — require positive EV per actionable, non-negative total EV delta versus baseline, sufficient actionables, fold stability, and normal replay/promotion gates.

Supported minimum-actionable modes:

- `rank_only` — legacy exploratory behavior; low-sample candidates may be ranked below adequate-sample candidates but are not rejected solely by the sample floor.
- `hard_gate` — staged large-search default; non-baseline candidates below the stage minimum are rejected before they can become stability-screen survivors, walk-forward finalists, or holdout finalists.

Hard-gate behavior:

- baseline/no-change config always survives and is labelled separately;
- non-baseline candidates below `min_validation_actionable` receive `selection_actionable_below_minimum` or equivalent stage-specific rejection;
- non-baseline candidates with insufficient qualified walk-forward slices or holdout folds are research-only and cannot be counted as improvement finalists;
- artifacts must report baseline inclusion separately from `improvement_finalist_count`.

A candidate selected from fewer actionables than the configured minimum must not appear as a non-baseline finalist in `hard_gate` mode.

## Campaign-scoped search

Large search must persist `search_campaign` and the allowed key set in schema-v2 artifacts. Supported campaigns are:

- `selectivity_only` — only `global.actionable_confidence_floor_percent`;
- `entry_risk_only` — entry band risk fraction and setup-family entry band multiplier;
- `stop_risk_only` — headwind/volatility stop controls and stop-distance family multipliers;
- `take_profit_family_only` — one reward/take-profit multiplier at a time;
- `combined_small_delta` — default; any registered key may move, but at most three keys may change;
- `high_risk_research` — explicit all-knobs research mode with no changed-key cap.

The default large-search campaign is `combined_small_delta`. A finalist that changes more than three keys is valid only when `search_campaign=high_risk_research`.

## Stability and ranking rules

Pooled expected value and win rate remain visible, but they are insufficient for ranking or promotion by themselves.

For every stability-screen survivor, compute paired candidate-versus-baseline metrics by market date and fold, including:

- median and worst qualified-fold win-rate and expected-value delta
- positive/negative/tied qualified-fold counts
- result after excluding the candidate's best contributing date
- best-date and top-three-date share of positive expected-value contribution
- actionable, ambiguous, distinct-date, ticker, setup-family, and direction coverage

Stability eligibility is applied before the canonical objective from `plan-generation-tuning-spec.md`. Among stability-eligible candidates, ranking must use the canonical objective and tie rules over selection evidence, not a discovery-only tail split. Exploration objective variants may be reported separately but may not silently replace the canonical promotion ordering.

Uncertainty resampling must use market dates or contiguous date blocks as the independent unit, never individual trades from the same date. Thin or unstable evidence produces `research_only`/rejection status; it must not be converted into a positive score.

The locked holdout is a final falsification check, not another optimization set. Any candidate or search bounds changed after inspecting it require a new future holdout period or an explicit `holdout_contaminated` status.

Operator-facing summaries must keep these metrics separate:

- actionable win rate;
- expected value per actionable;
- total traded expected value;
- actionable count.

Non-actionable records do not contribute EV. They may be reported as ambiguous/non-actionable coverage only.

## UI

The Plan Generation Tuning page exposes **Plan Generation Large Tuning Search** in the controls card. It queues a hidden non-schedulable `plan_generation_tuning` system job and writes progress/results to the run/debugger artifacts. It never applies promotion.

## Walk-forward validation memory safety

Large-search survivors must be validated with walk-forward checks before locked holdout or any promotion. Walk-forward validation must avoid building a new list of records for every rolling slice. It should sort the eligible records once, use lightweight slice views for each rolling window, cache baseline/date aggregates, and release per-slice work promptly. Full unbounded validation may still be long-running, but it should not multiply memory by the number of walk-forward slices or the original candidate count.

## Resume cache

Large tuning searches must be interrupt-safe. Each run writes a JSONL resume cache next to the final artifact unless a custom cache path is provided. The current cache schema stores:

- metadata header: baseline config version, active config, evidence record counts, requested search settings, and cache schema version.
- one line per evaluated parameter permutation: phase, deterministic parameter fingerprint, full config, changed keys, and search/validation metrics.

On restart with compatible metadata, the search reloads cached permutations, reconstructs the current top candidates, and skips already evaluated fingerprints. If metadata is incompatible, the cache is ignored rather than reused. This avoids mixing evidence from different baselines/windows.

Cache schema v2 binds the cache metadata to evidence partitions, date panels, baseline, objective, scoring version, and stage policy, and keys candidate results by funnel stage. A cache entry from one stage or evidence partition must never satisfy another. Schema-v1 cache files are historical evidence only and are not reused for staged decisions.

The cache is research evidence only. It must not mutate active config, broker settings, thresholds, or order execution.

## Command

```bash
.venv/bin/python scripts/large_plan_generation_parameter_search.py \
  --coarse-candidates 200000 \
  --fine-candidates 50000 \
  --stage1-survivors 2000 \
  --stage2-survivors 100 \
  --finalists 10 \
  --discovery-start 2026-01-02 --discovery-end 2026-03-31 \
  --selection-start 2026-04-01 --selection-end 2026-04-30 \
  --holdout-start 2026-05-01 --holdout-end 2026-05-29 \
  --require-explicit-partitions \
  --artifact artifacts/large-parameter-search.json \
  --cache artifacts/large-parameter-search.cache.jsonl
```

Use smaller candidate counts for smoke tests. The UI defaults to 20,000 coarse and 5,000 fine candidates as a safer first pass; operators can explicitly increase counts for multi-hour searches. The script is intentionally long-running for large searches.
