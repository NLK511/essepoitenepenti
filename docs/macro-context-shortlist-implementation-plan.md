# Macro context shortlist implementation plan

**Status:** planned

Implementation tracker for `specs/macro-context-shortlist-spec.md`. The spec is the behavior contract; this file keeps only build order, integration seams, and rollout checks.

## Objective

Add bounded macro-context participation to upstream shortlist selection without making macro context a standalone selector. Technical cheap-scan evidence remains primary.

Success means:
- usable, mapped macro context can modestly boost or penalize shortlist priority;
- missing/degraded/unmapped macro context is neutral and visible;
- weak technical candidates cannot be shortlisted solely by macro;
- shortlist decisions expose raw technical scores, macro adjustment, lane, source snapshot, and reasons;
- replay uses only point-in-time stored context snapshots.

## Build sequence

### Phase 0 — Contract/seam confirmation

Review and document PR notes for:
- `ShortlistSelectionService`
- `WatchlistExecutionService`
- `WatchlistOrchestrationService`
- `WatchlistSignalBuilder`
- `WatchlistDecisionSamplesService`
- `ContextSnapshotResolver`
- `TickerTaxonomyService`
- ticker exposure ontology support

Decide first-release scope:
- preferred: macro snapshot drives bias; taxonomy/ontology explains ticker exposure;
- industry context remains diagnostic until mapped exposure scoring is proven.

### Phase 1 — Tests first

Add tests for:
- neutral output when macro snapshot is missing, degraded, blocked, or unmapped;
- bounded positive adjustment for usable aligned exposure;
- bounded negative adjustment for usable adverse exposure;
- no boost below technical floors;
- macro lane cap and floors;
- shorts-disabled rejection taking precedence;
- replay/as-of path avoiding provider refresh;
- decision payload carrying macro fields and `selection_lane=macro_context`.

Suggested homes:
- focused scorer tests for the new macro shortlist scorer;
- `tests/test_watchlist_orchestration_policy.py` or a new shortlist-selection test module;
- decision-sample persistence tests for compact diagnostics.

### Phase 2 — Scorer and model

Add a compact support model, preferably outside the cheap-scan candidate model to avoid broad churn:

```python
@dataclass(frozen=True)
class MacroShortlistSupport:
    score: float = 50.0
    adjustment: float = 0.0
    bias: str = "unknown"
    quality_status: str = "unknown"
    reasons: tuple[str, ...] = ()
    reason_details: tuple[dict[str, str], ...] = ()
    snapshot_id: int | None = None
    context_tags: tuple[str, ...] = ()
```

Add `macro_shortlist_scoring.py` with:
- `ContextSnapshotResolver | None`
- `TickerTaxonomyService`
- ticker exposure ontology if needed
- config for enable flag, max boost, max penalty, and saliency/confidence floors

Initial scorer algorithm:
1. Resolve latest macro snapshot at or before `as_of`.
2. Return neutral with explicit reason when absent/degraded/blocked/unmapped.
3. Read canonical context scoring fields from the resolver.
4. Map active macro events/tags to ticker exposure.
5. Determine whether the candidate direction sees tailwind, headwind, mixed, or unknown context.
6. Apply bounded adjustment: default `+5` max boost and `-5` max penalty.
7. Return governed reason details.

No remote calls are allowed.

### Phase 3 — Shortlist integration

Prefer passing `macro_support_by_ticker` into `ShortlistSelectionService.evaluate(...)` instead of mutating cheap-scan candidate shape.

Config defaults:
- disabled or diagnostics-only until replay validation passes;
- `macro_shortlist_max_boost = 5.0`;
- `macro_shortlist_max_penalty = 5.0`;
- `macro_shortlist_lane_fraction = 0.15`;
- `macro_shortlist_lane_max = 3`.

Ranking option for first implementation:
- preserve error/shorts eligibility ordering;
- use `attention_score + macro_adjustment`, then confidence;
- store both raw and adjusted scores.

If rank churn is too high, keep raw ranking and use macro only as a lane admission rule.

### Phase 4 — Macro lane

Add after core technical/catalyst handling.

Eligibility:
- no cheap-scan error;
- shorts allowed if short;
- confidence >= `max(40, minimum_confidence - 8)`;
- attention >= `max(50, minimum_attention - 5)`;
- macro adjustment > `0`;
- bias `tailwind`;
- quality `usable`;
- not already shortlisted.

Reasons/lane labels to govern:
- `macro_tailwind_boost`
- `macro_headwind_penalty`
- `macro_context_missing`
- `macro_context_degraded`
- `macro_exposure_not_mapped`
- `below_macro_lane_floor`
- `macro_context` selection lane

### Phase 5 — Orchestration and persistence

Wire once per run:
1. Resolve macro context with the same `as_of` used for cheap scan/deep analysis.
2. Build support for every cheap-scan candidate before shortlist evaluation.
3. Pass support into shortlist selection.
4. Store run artifact summary: snapshot id, boosted/penalized/neutral/missing counts, macro-lane count, context warnings.
5. Persist compact diagnostics in shortlist decision payloads, signal snapshots, and decision samples.

Suggested compact payload:

```json
{
  "macro_shortlist": {
    "score": 72.0,
    "adjustment": 4.0,
    "bias": "tailwind",
    "quality_status": "usable",
    "snapshot_id": 123,
    "context_tags": ["rates_easing", "risk_on"],
    "reasons": ["macro_tailwind_boost"]
  },
  "context_adjusted_attention": 69.2
}
```

Do not duplicate richer downstream transmission payloads in plans.

### Phase 6 — UI, tuning, validation

UI/read models should expose:
- raw attention/confidence;
- context-adjusted attention;
- macro adjustment;
- macro bias/quality;
- lane label;
- macro reasons.

Signal-gating analysis slices:
- `selection_lane=macro_context`;
- `macro_shortlist_bias`;
- `macro_shortlist_quality_status`;
- `macro_shortlist_adjustment_bucket`.

Replay comparison:
- baseline technical shortlist;
- macro-aware shortlist with default bounds;
- macro lane disabled vs enabled.

Promotion evidence must show:
- reduced missed-win rate among non-shortlisted samples;
- no material degradation in actionable plan win rate;
- no excessive deep-analysis budget increase;
- sufficient samples by lane and bias.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Macro narratives add noise | Keep boost small, require usable mapped evidence, benchmark before widening |
| Missed technical winners due to penalty | Bound penalty and keep degraded/missing neutral |
| Replay leakage | Resolver-only scoring; tests fail provider calls |
| Taxonomy gaps | Neutral with `macro_exposure_not_mapped` |
| UI over-trust | Label as shortlist triage, not prediction proof |
| Complexity creep | One scorer, compact payload, no new vendor work |

## Done checklist

- [ ] Scorer tests.
- [ ] `MacroShortlistSupport` model.
- [ ] Macro shortlist scoring service.
- [ ] Shortlist config and payload fields.
- [ ] Macro-adjusted ranking and/or macro lane.
- [ ] Orchestration wiring with point-in-time snapshots.
- [ ] Signal/decision-sample diagnostics.
- [ ] Taxonomy labels for lane/reasons.
- [ ] Replay-safety tests.
- [ ] UI/read-model fields.
- [ ] Replay comparison before positive boost is enabled in production.
