# Fundamental valuation integration spec

**Status:** current + target behavior

This spec defines how fundamental data should be transformed into valuation/mispricing signals and integrated into plan generation, evaluation, tuning, and operator review.

## Current implementation snapshot

Implemented:

- fundamental snapshots derive a versioned `valuation_context`
- sparse provider payloads are downgraded instead of being marked healthy `ok`
- canonical valuation, quality, growth, balance-sheet-risk, analyst-upside, event-regime, and mispricing buckets are produced
- plan analysis context exposes compact `fundamental_valuation_context`
- watchlist signal breakdowns persist compact valuation context alongside existing fundamental buckets
- validation slices include mispricing and directional-support cohorts
- reliability feature extraction includes compact point-in-time valuation fields for future tuning/search
- positive fundamental confidence contribution remains disabled by default

Still target behavior / not yet proven:

- sector-relative valuation percentiles
- UI panels dedicated to valuation reasons and confidence effects
- live confidence caps for valuation contradictions
- positive confidence boosts from valuation support
- walk-forward promotion of any valuation-aware rule


## Purpose

Fundamentals are most useful to the app as a **valuation sanity layer**: they help answer whether a ticker appears underpriced, fairly valued, or overpriced relative to its quality, growth, risk, sector context, and analyst expectations.

The system should use valuation context to improve trade selectivity and risk discipline, not to replace timing signals. Technicals, catalysts, liquidity, execution quality, and broker risk remain responsible for whether a trade is actionable now.

Canonical question:

> Technical/catalyst evidence says there may be a trade. Do fundamentals make this direction sensible, risky, or contradictory?

## Scope

This spec covers:

- normalized fundamental valuation features
- mispricing classification
- confidence/risk integration rules
- storage and point-in-time safety
- plan-generation and plan-evaluation integration
- validation requirements before positive boosts
- UI/reporting expectations

It extends, but does not replace, `docs/fundamental-analysis-snapshot-spec.md`.

## Non-goals

Do not implement in v1:

- a full institutional factor model
- DCF valuation
- multi-year financial statement reconstruction
- unvalidated autonomous confidence boosts
- fundamental-only trade generation
- future-data backfills that explain historical plans using snapshots created after the plan timestamp
- broad tuning knobs before enough resolved evidence exists

## Design principles

1. **Point-in-time only**
   - Plan generation must use the latest fundamental snapshot at or before plan creation time.
   - No future snapshot may influence historical plan evaluation or replay.

2. **Valuation is relative, not absolute**
   - A low P/E is not automatically cheap.
   - A high P/E is not automatically expensive.
   - Valuation must be interpreted relative to growth, profitability, balance sheet risk, sector/industry norms, and analyst target context.

3. **Fundamentals should initially constrain more than boost**
   - Use them first for warnings, confidence caps, and validation slices.
   - Only allow positive confidence contribution after walk-forward evidence supports it.

4. **Timing remains separate**
   - Undervaluation can persist for months.
   - Fundamentals may make a long thesis more attractive, but technical/catalyst/actionability rules must still justify entry timing.

5. **Sparse data must not look strong**
   - Missing or low-quality provider data must produce `unknown`, `degraded`, or `blocked` valuation states.
   - Sparse data must not be interpreted as cheap, strong, or safe.

## Required normalized valuation payload

Each fundamental snapshot payload should include a derived `valuation_context` object in addition to raw normalized sections.

Example:

```json
{
  "valuation_context": {
    "schema_version": "fundamental-valuation-v1",
    "coverage_status": "ok",
    "mispricing_signal": "undervalued",
    "mispricing_score": 0.64,
    "valuation_bucket": "cheap",
    "valuation_relative_to_quality": "attractive",
    "valuation_relative_to_growth": "attractive",
    "analyst_upside_bucket": "positive",
    "quality_bucket": "strong",
    "growth_bucket": "high",
    "balance_sheet_risk_bucket": "low",
    "event_regime": "none_known",
    "directional_support": {
      "long": "supportive",
      "short": "contradictory"
    },
    "confidence_contribution": {
      "positive_boost": 0.0,
      "risk_penalty": 0.0,
      "cap_multiplier": 1.0
    },
    "reasons": [
      "forward PE is low relative to growth bucket",
      "profitability quality supports valuation premium",
      "analyst target upside is positive"
    ],
    "warnings": []
  }
}
```

## Canonical buckets

### Mispricing signal

Allowed values:

- `undervalued`
- `fairly_valued`
- `overvalued`
- `extreme_overvalued`
- `unclear`
- `unknown`

Definitions:

- `undervalued`: valuation appears attractive relative to quality/growth/risk and no severe data-quality or event-risk contradiction is present.
- `fairly_valued`: valuation appears broadly consistent with quality/growth/risk.
- `overvalued`: valuation appears rich relative to quality/growth/risk.
- `extreme_overvalued`: valuation is very rich and not justified by growth/quality evidence.
- `unclear`: mixed evidence or conflicting metrics.
- `unknown`: insufficient data.

### Valuation bucket

Allowed values:

- `cheap`
- `medium`
- `expensive`
- `extreme_expensive`
- `unknown`

Primary inputs:

- forward PE
- trailing PE
- price-to-sales
- price-to-book
- EV/EBITDA or EV/sales when available
- market-cap context
- sector/industry-relative percentiles when available

### Quality bucket

Allowed values:

- `strong`
- `mixed`
- `weak`
- `unknown`

Primary inputs:

- gross margin
- operating margin
- net margin
- return on equity
- return on assets
- free cash flow availability/quality

### Growth bucket

Allowed values:

- `high`
- `moderate`
- `low`
- `negative`
- `unknown`

Primary inputs:

- revenue growth
- earnings growth
- EPS trend when available

### Balance-sheet risk bucket

Allowed values:

- `low`
- `medium`
- `high`
- `unknown`

Primary inputs:

- debt/equity
- current ratio
- total cash vs total debt
- free cash flow vs debt burden when available

### Analyst upside bucket

Allowed values:

- `strong_positive`
- `positive`
- `neutral`
- `negative`
- `strong_negative`
- `unknown`

Primary inputs:

- target mean price upside percent
- recommendation mean/key
- recent upgrades/downgrades when available

## Minimum data-quality rules

A valuation context must be marked `unknown` or `unclear` unless enough input exists to support a classification.

Minimum for `valuation_bucket != unknown`:

- at least one usable valuation multiple, and
- price or market-cap context is present

Minimum for `mispricing_signal in {undervalued, overvalued, extreme_overvalued}`:

- usable valuation bucket, and
- at least two of:
  - quality bucket known
  - growth bucket known
  - balance-sheet risk bucket known
  - analyst upside bucket known
  - sector/industry-relative benchmark known

Coverage downgrade rules:

- If most core fields are null, `coverage_status` must not be `ok`.
- If provider returns only ticker metadata and no usable valuation/growth/quality metrics, use `blocked` or `degraded`.
- Missing data must produce explicit warnings and missing-input lists.

## Directional interpretation

Fundamental valuation should be converted into direction-aware support.

### Long direction

Supportive long cases:

- `undervalued`
- `fairly_valued` with strong quality/growth
- analyst upside positive without major balance-sheet risk

Long caution cases:

- `overvalued`
- `extreme_overvalued`
- weak/negative growth with expensive valuation
- high balance-sheet risk
- earnings/event risk inside the intended holding window

### Short direction

Supportive short cases:

- `overvalued` or `extreme_overvalued`
- expensive valuation plus weak growth or weak quality
- negative analyst upside or deterioration

Short caution cases:

- `undervalued`
- strong quality/growth at fair valuation
- positive analyst upside
- known corporate event likely to create gap risk

## Plan-generation integration

Plan generation should attach compact valuation fields into `signal_breakdown_json` and analysis payloads.

Required compact fields:

```json
{
  "fundamental_snapshot_id": 123,
  "fundamental_snapshot_as_of": "2026-06-14T07:43:26Z",
  "fundamental_coverage_status": "ok",
  "fundamental_feature_buckets": {
    "valuation": "cheap",
    "growth": "high",
    "profitability_quality": "strong",
    "balance_sheet_risk": "low",
    "event_regime": "none_known"
  },
  "fundamental_valuation_context": {
    "schema_version": "fundamental-valuation-v1",
    "mispricing_signal": "undervalued",
    "mispricing_score": 0.64,
    "directional_support": {
      "long": "supportive",
      "short": "contradictory"
    },
    "reasons": ["valuation attractive relative to growth"]
  }
}
```

The full raw payload may remain available in deeper diagnostics, but plan-level compact fields should be stable and small enough for tuning/replay.

## Confidence and gating policy

### Initial conservative policy

Before validation, fundamentals may:

- lower confidence when they contradict the proposed direction
- cap confidence for severe overvaluation/undervaluation contradictions
- add warnings to plan evidence
- raise actionability thresholds for risky directions
- classify setup families and validation slices

Before validation, fundamentals must not:

- create actionable plans on their own
- materially increase confidence
- override technical/catalyst/actionability failures
- suppress broker/risk-management gates

### Suggested v1 confidence mechanics

Add a separate `fundamental_valuation_confidence` component, but default positive boost to zero.

For risk control only:

- severe contradiction: cap composed confidence to at most `55-60`
- mild contradiction: multiply composed confidence by `0.90-0.95`
- unknown/degraded: no directional penalty except data-quality cap
- supportive: record as evidence but do not boost until validated

Example rules:

| Plan direction | Mispricing signal | Initial effect |
|---|---:|---|
| long | undervalued | evidence only, no boost |
| long | fairly_valued | neutral |
| long | overvalued | warning, mild cap |
| long | extreme_overvalued | severe cap unless catalyst setup has validated exception |
| short | overvalued | evidence only, no boost |
| short | extreme_overvalued | evidence only, no boost |
| short | undervalued | warning, mild/severe cap |
| any | unknown | no valuation directional effect |

## Plan evaluation and tuning integration

`PlanReliabilityFeatures` or its successor should include compact fundamental valuation fields:

- `fundamental_snapshot_id`
- `fundamental_snapshot_as_of`
- `fundamental_coverage_status`
- `valuation_bucket`
- `mispricing_signal`
- `mispricing_score`
- `quality_bucket`
- `growth_bucket`
- `balance_sheet_risk_bucket`
- `analyst_upside_bucket`
- `event_regime`
- `fundamental_directional_support`

Tuning and walk-forward reports should be able to evaluate candidates by:

- overall performance
- performance excluding unknown fundamentals
- long/short directional support buckets
- setup family + valuation bucket
- setup family + mispricing signal
- expensive longs vs non-expensive longs
- undervalued shorts vs non-undervalued shorts
- event-window vs no-event valuation signals

Auto-promotion must not rely on fundamental uplift unless validation evidence is sufficient and point-in-time safe.

## Validation requirements

A fundamental valuation rule may become an active positive driver only after walk-forward validation.

Required validation slices:

- `mispricing_signal`
- `valuation_bucket`
- `valuation_relative_to_quality`
- `valuation_relative_to_growth`
- `quality_bucket`
- `growth_bucket`
- `balance_sheet_risk_bucket`
- `analyst_upside_bucket`
- `directional_support`
- `setup_family + mispricing_signal`
- `setup_family + valuation_bucket`
- `horizon + mispricing_signal`

Required metrics:

- broker-preferred effective win rate
- actionable win rate
- expected value
- average return/R multiple when available
- false-positive reduction
- drawdown/loss-streak behavior
- actionability rate impact
- precision vs baseline
- sample count and concentration by ticker/sector/time window

Minimum evidence before positive boost:

- enough resolved samples in the target slice; default target at least `50` resolved and `20` wins/losses per directional side before considering a direct boost
- positive out-of-sample/walk-forward EV versus baseline
- no material win-rate regression versus baseline
- no excessive concentration in one ticker, sector, or market regime
- stable effect across at least two validation windows

Risk-filter promotion can require less evidence than positive boosting, but still must show reduced losses or improved EV without unacceptable opportunity loss.

## UI and reporting requirements

Operator-facing views should show:

- latest fundamental snapshot timestamp
- coverage status
- valuation bucket
- mispricing signal
- quality/growth/risk buckets
- analyst upside bucket
- directional support for the current plan
- reasons and warnings
- whether the signal affected confidence, capped confidence, or was informational only

Research views should show validation slices and sparse-evidence warnings.

Plans should clearly distinguish:

- technical/catalyst timing thesis
- valuation sanity thesis
- unsupported or unknown fundamental context

## Observability requirements

Record counters for:

- monitored tickers with current fundamental snapshots
- stale fundamental snapshots
- degraded/blocked snapshots
- valuation contexts with unknown mispricing
- plans generated with valuation context
- plans whose confidence was capped by valuation contradiction
- validation slice sample counts

Dashboard/operator status should warn when fundamental coverage is too sparse to support valuation claims.

## Implementation phases

### Phase 1: Quality and normalized valuation context

- Tighten coverage scoring so sparse payloads are not marked `ok`.
- Add `valuation_context` to fundamental snapshot payloads.
- Add deterministic bucket logic and reason strings.
- Add tests for sparse, undervalued, overvalued, and unclear cases.

### Phase 2: Passive plan attachment

- Persist compact `fundamental_valuation_context` in plan signal breakdown.
- Ensure point-in-time lookup uses only snapshots at or before plan time.
- Add UI display and API fields.
- Do not change confidence except for existing data-quality warnings.

### Phase 3: Evaluation features and reports

- Add valuation fields to reliability/evaluation records.
- Extend fundamental validation slices.
- Produce walk-forward reports comparing baseline vs valuation-aware risk filters.

### Phase 4: Conservative risk filters

- Enable only negative/capping effects for severe contradictions.
- Keep positive boost disabled.
- Validate opportunity loss, win-rate impact, and EV impact.

### Phase 5: Optional positive contribution

- Enable small positive contribution only for validated slices.
- Positive contribution must be bounded, versioned, and revertible.
- Default maximum positive impact should be small relative to technical/catalyst evidence.

## Acceptance criteria

The integration is satisfactory when:

1. Fundamental snapshots have reliable coverage classification.
2. Every generated plan with available fundamentals stores compact point-in-time valuation fields.
3. Plan evaluation and tuning can segment resolved outcomes by valuation/mispricing buckets.
4. Sparse/unknown fundamentals cannot create false confidence.
5. Directional contradictions can be measured and, after validation, used as conservative risk controls.
6. Any positive confidence boost is backed by walk-forward evidence and remains bounded.
7. Operators can see exactly why a plan is considered undervalued, fairly valued, overvalued, or unknown.
