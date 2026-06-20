# Plan generation large tuning search spec

**Status:** current behavior

Implemented as an offline/non-schedulable research tuning search script and UI queue action.

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

## Search shape

Operator-facing name: **Plan Generation Large Tuning Search**. This name keeps it under the plan-generation tuning family while distinguishing it from the built-in standard/exploratory/wide tuning searches.

The tool performs two phases:

1. **Coarse search**: deterministic random sampling across exploration ranges for all plan-generation tuning parameters.
2. **Fine tune**: local random search around the best coarse candidates using a smaller radius.

Both phases score search and validation partitions. Ranking prefers:

1. minimum validation actionable sample count,
2. validation expected value,
3. validation win rate,
4. search expected value,
5. lower ambiguity.

## UI

The Plan Generation Tuning page exposes **Plan Generation Large Tuning Search** in the controls card. It queues a hidden non-schedulable `plan_generation_tuning` system job and writes progress/results to the run/debugger artifacts. It never applies promotion.

## Walk-forward validation memory safety

Large-search winners must be validated with walk-forward checks before any promotion. Walk-forward validation must avoid building a new list of records for every rolling slice. It should sort the eligible records once, use lightweight slice views for each rolling window, and release per-slice work promptly. Full unbounded validation may still be long-running, but it should not multiply memory by the number of walk-forward slices.

## Resume cache

Large tuning searches must be interrupt-safe. Each run writes a JSONL resume cache next to the final artifact unless a custom cache path is provided. The cache stores:

- metadata header: baseline config version, active config, evidence record counts, requested search settings, and cache schema version.
- one line per evaluated parameter permutation: phase, deterministic parameter fingerprint, full config, changed keys, and search/validation metrics.

On restart with compatible metadata, the search reloads cached permutations, reconstructs the current top candidates, and skips already evaluated fingerprints. If metadata is incompatible, the cache is ignored rather than reused. This avoids mixing evidence from different baselines/windows.

The cache is research evidence only. It must not mutate active config, broker settings, thresholds, or order execution.

## Command

```bash
.venv/bin/python scripts/large_plan_generation_parameter_search.py \
  --coarse-candidates 200000 \
  --fine-candidates 50000 \
  --top-k 100 \
  --artifact artifacts/large-parameter-search.json \
  --cache artifacts/large-parameter-search.cache.jsonl
```

Use smaller candidate counts for smoke tests. The UI defaults to 20,000 coarse and 5,000 fine candidates as a safer first pass; operators can explicitly increase counts for multi-hour searches. The script is intentionally long-running for large searches.
