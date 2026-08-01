# Recommendation quality evidence-review checklist

**Status:** active evidence-review checklist

This is the remaining active checklist for deciding whether recommendation-quality changes deserve production influence. The broad quality platform is already shipped; this document is now about repeatable review, evidence artifacts, and explicit keep/change/reject decisions.

## Current stance

- Confidence is a ranking and selection signal unless calibrated evidence supports stronger interpretation.
- Live/autonomous confidence calibration uses execution-only outcomes by default.
- Phantom outcomes are research/operator context and must not silently affect live execution confidence.
- Cheap-scan confidence is an upstream recall/ranking score. Do not reuse recommendation-plan calibration for cheap scan.
- Context, ontology, macro shortlist, industry context, and fundamental valuation may remain bounded/passive unless walk-forward evidence proves value.
- Promotion must consider win rate, expected value, calibration, drawdown/loss streaks, selectivity, degraded-input behavior, and simple baselines.

## Evidence bundle for each review

Every quality review should produce an artifact directory or saved notes with:

- review date, git commit, database/source window, and reviewer;
- commands/API endpoints used;
- sample counts and thin-slice warnings;
- before/after settings or candidate policy;
- baseline comparison;
- decision: `keep_current`, `promote_candidate`, `defer_thin_evidence`, `reject_candidate`, or `disable_or_tighten`;
- follow-up issue/checklist item if evidence is inconclusive.

Minimum gates unless a stricter spec applies:

- no production promotion from pooled-only results;
- no promotion when key slices are too thin to interpret;
- no positive boost from degraded/missing evidence;
- no change that materially worsens drawdown/loss-streak behavior without an explicit experimental cap;
- no silent live recalculation fallback for calibration.

## Checklist 1 — Calibration behavior

Goal: verify execution-only calibration is honest and not hurting selection quality.

Run/review:

- `GET /api/calibration/confidence?mode=execution_only`
- `GET /api/calibration/confidence?mode=side_by_side`
- `GET /api/recommendation-outcomes/calibration-report`
- latest persisted weekly calibration snapshot/run detail

Record:

- execution-only sample count by confidence bucket and horizon;
- raw vs calibrated Brier score and expected calibration error;
- actionable win rate and EV before/after calibration;
- thin buckets and whether they remain visibly thin;
- whether phantom-only differs materially from execution-only.

Decision rule:

- **Keep current** if calibration is not materially worse and no hidden regression appears.
- **Promote/adjust** only through persisted scheduled calibration snapshots.
- **Disable/tighten** if calibration worsens Brier/ECE or selection quality on meaningful slices.
- **Defer** if execution-only samples remain too thin.

## Checklist 2 — Context, ontology, and transmission usefulness

Goal: decide whether mapped context, ontology, and transmission signals should remain bounded or gain/lose influence.

Run/review:

- fresh ontology-enabled watchlist/plan run or replay slice;
- `scripts/report_context_scoring_impact.py` for `normal`, `forced_neutral`, `quality_only`, `adverse_only`, and `mapped_exposure` modes;
- `scripts/report_industry_context_quality.py`;
- outcome slices by transmission bias, context regime, matched exposure, macro shortlist lane, and degraded/missing context.

Record:

- matched exposure rate and unmapped-context rate;
- tailwind/headwind/mixed/neutral outcomes;
- macro shortlist lane count and outcomes;
- industry decision-usable rate and top neutral/degraded reasons;
- curated vs template/implicit ontology profile performance where available;
- false positives reduced or introduced by context influence.

Decision rule:

- **Keep bounded** unless walk-forward evidence beats taxonomy/transmission baseline across meaningful slices.
- **Tighten** if degraded/missing context is associated with false positives that pass gates.
- **Do not widen** positive context/macro influence from pooled EV alone.
- **Archive/neutralize** any context path that adds complexity without measurable value.

## Checklist 3 — Fundamental valuation passive validation

Goal: determine whether fundamental valuation should remain passive, tighten risk, or later gain bounded influence.

Run/review:

- point-in-time fundamental snapshot coverage/backfill status;
- outcome slices for valuation, profitability/quality, growth, balance-sheet risk, cash flow, analyst context, and event-regime buckets;
- comparison against plans without usable fundamental snapshots.

Record:

- snapshot coverage, stale coverage, degraded/sparse provider rows;
- false-positive reduction by valuation/risk bucket;
- EV, win rate, drawdown/loss streak, and no-entry behavior;
- lost true-positive cost if any conservative cap is proposed.

Decision rule:

- **No positive fundamental confidence boost** until point-in-time walk-forward evidence beats baseline without worsening drawdown/loss streaks.
- **Tightening/caps** require explicit policy notes and false-positive-vs-lost-winner review.
- **Defer** if snapshots are sparse, stale, or not point-in-time reliable.

## Checklist 4 — Plan-generation tuning promotion discipline

Goal: ensure threshold/config changes are promoted only from robust walk-forward evidence.

Run/review:

- candidate tuning artifacts from `GET /api/plan-generation-tuning` or saved tuning run artifacts;
- walk-forward comparison against current production settings and simple baselines;
- actionability expansion vs precision/win-rate behavior;
- false positives, skipped wins, selectivity, and degraded-input pass-through.

Record:

- baseline vs candidate metrics by window;
- actionable count, no-action count, shortlist/deep-analysis conversion;
- EV and win rate with friction assumptions noted;
- loss streak/drawdown behavior;
- whether the candidate is precision promotion or EV-expansion only.

Decision rule:

- **Promote** only if walk-forward evidence is stable and baseline comparison is acceptable.
- **Reject** candidates that improve EV only by greatly expanding actionability or materially worsening win rate, unless explicitly capped as experimental.
- **Keep EV-expansion candidates separate** from precision/win-rate promotion.

## Checklist 5 — Degraded-input penalties

Goal: keep degraded evidence visible and prevent degraded rows from producing false confidence.

Run/review:

- degraded plans that passed gates;
- warning/degraded fields in plan details, signal snapshots, context snapshots, and dashboard/research surfaces;
- outcome slices for missing bars, stale prices, missing context, degraded context, sparse fundamentals, provider failures, and summary fallbacks.

Record:

- degraded rows that became actionable;
- false positives by degraded condition;
- lost true positives if a stronger penalty/cap is proposed;
- operator visibility gaps.

Decision rule:

- **Tighten** only when false-positive reduction exceeds lost true-positive cost or safety requires it.
- **Do not hide** degraded rows by blending them into neutral/healthy buckets.
- **Distinguish required vs optional missing evidence** before changing gates.

## Checklist 6 — Cheap-scan calibration readiness

Goal: decide whether cheap-scan calibration is ready for design work. It is not currently production-calibrated.

Required dataset before implementation:

- shortlisted and non-shortlisted decision samples;
- missed-opportunity benchmarks;
- clean rejects;
- cheap-scan-only rows without full plan rows;
- enough resolved future returns to avoid training only on plan-generated/actionable cases.

Decision rule:

- **Do not implement cheap-scan calibration** until the dataset above exists and is documented.
- **Do not apply recommendation-plan calibration** to cheap-scan scores.
- **Proceed to a separate spec** only after dataset coverage and label policy are clear.

## Completion criteria for this active checklist

This checklist can be archived only when:

- calibration review has enough execution-only samples and an explicit keep/change decision;
- context/ontology/macro/industry usefulness has a recorded bounded/expand/tighten decision;
- fundamental valuation has a passive/tighten/boost decision based on point-in-time evidence;
- the current tuning promotion candidate, if any, has a walk-forward promote/reject/defer decision;
- degraded-input penalties have been reviewed for actionable false positives;
- cheap-scan calibration is either explicitly deferred or moved to a separate dataset/spec plan.

## Primary data sources and APIs

Data:

- `RecommendationPlanOutcome`
- broker-preferred effective outcomes
- `RecommendationDecisionSample`
- `RecommendationPlan`
- ticker signal snapshots
- macro/industry context snapshots
- fundamental analysis snapshots
- calibration snapshots and reports
- plan-generation tuning runs and artifacts

APIs:

- `GET /api/recommendation-outcomes`
- `GET /api/recommendation-outcomes/summary`
- `GET /api/recommendation-outcomes/calibration-report`
- `GET /api/recommendation-outcomes/setup-family-review`
- `GET /api/recommendation-outcomes/evidence-concentration`
- `GET /api/recommendation-plans/baselines`
- `GET /api/recommendation-decision-samples`
- `GET /api/calibration/confidence`
- `GET /api/signal-gating-tuning`
- `GET /api/plan-generation-tuning`

Scripts:

- `scripts/report_context_scoring_impact.py`
- `scripts/report_industry_context_quality.py`
- `scripts/report_steering_dry_run_quality.py`
- replay/tuning scripts listed in `operational-scripts-reference.md`

## See also

- `recommendation-methodology.md`
- `decision-sample-tuning-guide.md`
- `specs/confidence-calibration-spec.md`
- `specs/edge-validation-standard.md`
- `specs/plan-generation-tuning-spec.md`
- `specs/large-parameter-search-spec.md`
- `specs/context-scoring-spec.md`
- `specs/macro-context-shortlist-spec.md`
- `specs/ticker-exposure-ontology-spec.md`
- `specs/fundamental-valuation-integration-spec.md`
