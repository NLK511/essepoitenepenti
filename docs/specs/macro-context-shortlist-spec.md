# Macro context shortlist participation spec

**Status:** current and target behavior

Binding reference for how macro context may influence upstream shortlist selection before ticker deep analysis runs.

## Problem and goal

The current watchlist pipeline uses cheap-scan technical evidence to decide which tickers receive expensive deep analysis. Macro context is loaded later and can affect plan framing, transmission, confidence, and actionability, but it does not explicitly affect shortlist selection.

This creates two risks:
- names with strong technical scans but clear macro headwinds may consume deep-analysis budget before better-context names;
- names with adequate technical scans and a fresh macro tailwind may be missed or ranked too low for deep analysis.

Goal: let macro context influence shortlist prioritization in a bounded, auditable, replay-safe way without turning macro narratives into a standalone selection engine.

## Current behavior

Implemented current behavior:
- cheap scan uses price/volume-derived technical, volatility, breakout, momentum, trend, and liquidity signals;
- `ShortlistSelectionService` ranks candidates by cheap-scan attention and confidence, plus error/shorts eligibility;
- catalyst lane uses cheap-scan attention, breakout, and directional strength only;
- macro and industry context snapshots are used after shortlist during deep analysis/signal/plan framing;
- plan framing may block or degrade trades for context quality, headwind, or transmission contradiction;
- non-shortlisted tickers persist signal and decision-sample evidence, not full recommendation plans.

Therefore macro context currently has only indirect shortlist influence through price action already reflected in bars.

## Target behavior

Macro context should participate in upstream shortlist selection as a **bounded prioritization signal**, not as a hard requirement and not as a replacement for technical evidence.

Target behavior:
1. preserve the existing technical shortlist lane as the primary lane;
2. add a macro-aware shortlist adjustment to ranking and decision diagnostics;
3. optionally add a small macro-context lane for technically adequate names with strong, fresh macro support;
4. never allow macro context alone to shortlist a ticker with weak technical/attention evidence;
5. never give positive macro support when macro context is missing, stale, degraded, blocked, contradictory, or social-only weak evidence;
6. record every macro adjustment and rejection/support reason for operator review and signal-gating tuning.

## Scope

In scope:
- resolving reusable macro snapshots once per run using the run `as_of` timestamp;
- computing per-candidate macro shortlist support from point-in-time snapshots and ticker taxonomy exposure;
- bounded score adjustments to shortlist ranking/eligibility;
- macro lane diagnostics and decision-sample payload fields;
- replay-safe behavior and tests.

Out of scope:
- changing macro context refresh extraction logic;
- adding premium macro data vendors;
- letting macro evidence directly produce actionable plans;
- changing downstream plan-generation actionability thresholds;
- using future outcome data in shortlist scoring.

## Definitions

### Macro shortlist support

A compact per-candidate assessment of whether current macro context supports, conflicts with, or does not materially affect the candidate's cheap-scan direction.

Required fields:
- `macro_shortlist_score`: numeric support score on `0-100`; neutral is `50`;
- `macro_shortlist_adjustment`: bounded numeric points applied to shortlist ranking/triage;
- `macro_shortlist_bias`: `tailwind`, `headwind`, `mixed`, `neutral`, or `unknown`;
- `macro_shortlist_quality_status`: `usable`, `degraded`, `blocked`, `missing`, or `unknown`;
- `macro_shortlist_reasons`: machine-readable reason keys;
- `macro_shortlist_reason_details`: governed labels;
- `macro_shortlist_snapshot_id`: source macro snapshot id when available;
- `macro_shortlist_context_tags`: compact active tags/drivers that caused the score.

### Macro lane

A secondary shortlist lane that can admit technically adequate candidates with strong fresh macro support even when they narrowly miss the core technical threshold.

The macro lane must be capped and must be separately labeled from the technical and catalyst lanes.

## Scoring rules

### Hard safety rules

Macro context must not create a shortlist candidate when:
- cheap scan failed;
- shorts are disabled and candidate direction is short;
- candidate attention is below a minimum technical floor;
- candidate confidence is below a minimum technical floor;
- macro context is missing/degraded/blocked and only a positive macro boost would make the candidate eligible;
- no ticker exposure path or governed taxonomy relationship explains the macro read-through.

### Bounded adjustment

Default target bounds:
- positive boost: `0` to `+5` ranking/triage points;
- negative penalty: `0` to `-5` ranking/triage points;
- neutral/missing/degraded: `0` adjustment unless an explicit usable adverse exposure exists.

A positive adjustment requires all of:
- macro snapshot quality is `usable`;
- snapshot is fresh for the run horizon;
- active macro event/regime has sufficient saliency and confidence;
- ticker taxonomy has a direct or high-confidence exposure path;
- macro bias is aligned with candidate direction;
- no severe contradictory context flag is present.

A negative adjustment is allowed only when:
- macro snapshot is usable enough to trust the adverse read-through; and
- there is a direct/high-confidence adverse exposure to the candidate direction.

Missing or degraded macro context should generally be neutral plus diagnostic warning, not a silent penalty.

### Technical floor

Macro support can rescue only borderline technical candidates. It must not bypass minimum technical floors.

Initial target floors:
- macro lane confidence floor: `max(40, minimum_shortlist_confidence - 8)`;
- macro lane attention floor: `max(50, minimum_shortlist_attention - 5)`;
- no macro lane admission below both floors.

### Lane cap

Initial target cap:
- macro lane may add at most `min(3, ceil(watchlist_size * 0.15))` candidates;
- cap applies after the core technical lane;
- cap should be configurable only through signal-gating tuning after tests and replay evidence exist.

### Ranking integration

The ranking key should remain primarily technical. Macro may adjust ranking only through explicit bounded fields.

Recommended first implementation:
- compute `context_adjusted_attention = attention_score + macro_shortlist_adjustment`;
- rank by error/shorts eligibility, then `context_adjusted_attention`, then confidence;
- keep raw attention and macro adjustment in diagnostics.

If this proves too unstable, keep ranking raw and use macro only as a lane admission rule.

## Replay and leakage policy

Shortlist macro scoring must be point-in-time safe:
- use only snapshots created at or before run `as_of`;
- do not refresh macro context during replay shortlist evaluation;
- do not call remote providers from shortlist scoring;
- surface missing snapshot coverage rather than using later snapshots;
- persist enough diagnostics to reconstruct why a ticker was or was not shortlisted.

A replay candidate that changes macro-shortlist behavior requires full orchestration replay, not stored-plan rescore, because it changes which tickers reach deep analysis.

## Diagnostics and persistence

Shortlist decision payloads must include:
- raw `attention_score` and `confidence_percent`;
- `context_adjusted_attention` or equivalent adjusted ranking score;
- macro support fields listed above;
- `selection_lane` values including `technical`, `catalyst`, and `macro_context`;
- reasons such as `macro_tailwind_boost`, `macro_headwind_penalty`, `macro_context_missing`, `macro_context_degraded`, `macro_exposure_not_mapped`, `below_macro_lane_floor`.

Ticker signal snapshots and decision samples should carry compact versions of these fields so the operator can compare non-shortlisted near misses with later benchmark outcomes.

## UI and operator behavior

Operator-facing shortlist details should show:
- raw technical attention/confidence;
- macro adjustment and lane;
- macro snapshot freshness/quality;
- top macro drivers/tags;
- whether macro helped, hurt, or was neutral.

The UI must not imply that macro support is predictive proof. It is a triage reason to spend or avoid deep-analysis budget.

## Tuning and evaluation

Macro-shortlist knobs belong to signal-gating tuning, not plan-generation tuning.

Evaluation should compare:
- baseline technical shortlist vs macro-aware shortlist;
- missed-win rate among non-shortlisted candidates;
- good-reject rate;
- deep-analysis budget use;
- actionable plan precision after macro-lane admission;
- outcomes by `macro_shortlist_bias`, `macro_shortlist_quality_status`, and `selection_lane`.

Do not widen boost bounds or lane caps until replay/benchmark evidence shows improvement.

## Test requirements

Unit tests must prove:
- missing macro snapshot produces zero boost and explicit diagnostics;
- degraded/blocked macro context cannot positively boost;
- usable aligned macro context can add only bounded boost;
- usable adverse macro context can apply only bounded penalty;
- weak technical candidates cannot be shortlisted solely by macro;
- macro lane respects cap and floors;
- shorts-disabled logic still wins over macro support;
- replay/as-of resolver does not use future snapshots;
- decision payloads include raw and adjusted scores plus reason details;
- existing technical/catalyst behavior is unchanged when macro scoring is disabled or neutral.

Integration tests must prove:
- a watchlist run persists macro shortlist diagnostics in decision samples;
- non-shortlisted macro near misses can be benchmarked by the upstream decision benchmark flow;
- point-in-time replay reuses stored context snapshots and does not trigger remote context refresh.

## Decision rule

Macro context should improve shortlist prioritization only when it is fresh, usable, mapped to the ticker, and bounded. When evidence is weak, missing, stale, or contradictory, the correct behavior is neutral diagnostics or cautious deprioritization, not narrative-driven selection.
