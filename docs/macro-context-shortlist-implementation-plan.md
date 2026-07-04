# Macro context shortlist implementation plan

**Status:** planned

This plan implements `specs/macro-context-shortlist-spec.md`: macro context participates in upstream shortlist prioritization as bounded, auditable triage evidence while technical cheap-scan evidence remains primary.

## Success criteria

- Macro context can modestly boost or penalize shortlist priority only when point-in-time evidence is usable and mapped to the ticker.
- Missing/degraded macro context is neutral and visible, not silently punitive.
- Weak technical candidates cannot be shortlisted solely by macro context.
- Every shortlist decision exposes raw technical scores, macro adjustment, lane, source snapshot, and reason details.
- Historical replay uses only snapshots available at `as_of` and does not refresh remote context.
- Tests cover scorer behavior, shortlist lane/caps, diagnostics, and replay safety.

## Phase 0 — Confirm contracts and current seams

1. Review active services:
   - `ShortlistSelectionService`
   - `WatchlistExecutionService`
   - `WatchlistOrchestrationService`
   - `WatchlistSignalBuilder`
   - `WatchlistDecisionSamplesService`
   - `ContextSnapshotResolver`
   - `TickerTaxonomyService`
2. Confirm where `as_of` flows through watchlist execution and replay.
3. Confirm available macro snapshot fields and taxonomy exposure fields sufficient for first-pass mapping.
4. Decide whether first release uses macro-only or macro+industry context for exposure mapping. Preferred first release: macro snapshot drives the bias; taxonomy/ticker profile explains exposure; industry is diagnostics only unless already available without extra fetch.

Deliverable: short code notes in the PR description; no code behavior change.

## Phase 1 — Unit-test the target behavior first

Add tests before implementation.

### New scorer tests

Create tests for a new service, tentatively `WatchlistMacroShortlistScorer`:
- returns neutral support when no macro snapshot exists;
- returns neutral support when snapshot quality is degraded/blocked/missing;
- returns bounded positive adjustment for usable aligned macro exposure;
- returns bounded negative adjustment for usable adverse exposure;
- returns no positive support when ticker exposure cannot be mapped;
- preserves snapshot id, quality status, reason keys, and active tags;
- respects `as_of` by using resolver output only, not provider refresh.

### Shortlist service tests

Extend `tests/test_watchlist_orchestration_policy.py` or add focused shortlist tests:
- raw technical ranking remains unchanged when macro scoring is neutral/disabled;
- context-adjusted attention changes rank only within bounded adjustment;
- macro lane admits a borderline candidate above macro floors;
- macro lane rejects candidates below technical floors;
- macro lane cap is enforced;
- shorts-disabled rejection beats macro support;
- decision payload includes macro fields and `selection_lane=macro_context` when selected by that lane.

### Persistence/decision-sample tests

Add/extend tests to prove:
- signal diagnostics include macro shortlist fields;
- recommendation decision sample payload includes compact macro shortlist evidence;
- non-shortlisted macro near misses remain decision samples, not plan rows.

## Phase 2 — Add macro shortlist support model and scorer

### New dataclass

Add a compact immutable model, for example in `shortlist_selection.py` or a new file:

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

### New service

Add `src/trade_proposer_app/services/macro_shortlist_scoring.py` with:
- constructor dependencies:
  - `ContextSnapshotResolver | None`
  - `TickerTaxonomyService`
  - config for enable flag, max boost, max penalty, saliency/confidence floors
- method:
  - `score(ticker, direction, *, as_of, horizon) -> MacroShortlistSupport`

Initial algorithm:
1. Resolve latest macro snapshot at or before `as_of`.
2. If absent, return neutral with `macro_context_missing`.
3. Derive quality/freshness from snapshot fields.
4. If not usable, return neutral with `macro_context_degraded` or `macro_context_blocked`.
5. Extract active macro tags/drivers/events and saliency/confidence.
6. Map ticker exposure using taxonomy profile / exposure ontology.
7. Determine directional support for candidate direction.
8. Apply bounded adjustment:
   - aligned/direct/high-confidence: up to `+5`
   - adverse/direct/high-confidence: down to `-5`
   - mixed/weak/unmapped: `0`
9. Return support with governed reason details.

Keep first algorithm intentionally simple and deterministic. Do not add remote calls.

## Phase 3 — Extend shortlist candidate and ranking

### Candidate shape

Extend `CheapScanCandidate` or attach sidecar support in shortlist evaluation:
- `macro_shortlist_support: MacroShortlistSupport | None`
- derived property/function for `context_adjusted_attention`.

Prefer avoiding broad model churn: pass a `macro_support_by_ticker` dictionary into `ShortlistSelectionService.evaluate(...)` if that keeps cheap-scan candidate clean.

### Shortlist config

Extend `ShortlistSelectionConfig` with conservative defaults:
- `macro_shortlist_enabled: bool = False` initially, or true only after tests if product owner wants immediate target behavior;
- `macro_shortlist_max_boost: float = 5.0`;
- `macro_shortlist_max_penalty: float = 5.0`;
- `macro_shortlist_lane_fraction: float = 0.15`;
- `macro_shortlist_lane_max: int = 3`.

Use active signal-gating settings only after metadata is added to the signal-gating parameter registry. Until then, keep constants/defaults.

### Ranking

Implement first target ranking:
- preserve error/shorts eligibility ordering;
- rank by `attention_score + macro_adjustment`, then confidence;
- include raw and adjusted values in decision payload.

If tests reveal too much churn, switch to raw ranking plus macro lane only.

## Phase 4 — Add macro lane

Add lane after core technical lane and catalyst lane decision ordering is reviewed.

Recommended order:
1. core technical lane fills all eligible technical names as today;
2. catalyst lane preserves event/technical breakout candidates;
3. macro lane admits additional borderline macro-supported names only if below final limit/cap.

Because current shortlist limit effectively equals ticker count, enforce macro lane by lane-specific floors and diagnostics rather than pretending there is a scarce fixed limit. If future configs reintroduce strict limits, macro lane cap becomes binding.

Macro lane eligibility:
- no cheap-scan error;
- shorts allowed if short;
- confidence >= `max(40, minimum_confidence - 8)`;
- attention >= `max(50, minimum_attention - 5)`;
- macro adjustment > 0 and bias `tailwind`;
- quality `usable`;
- not already shortlisted.

Decision reasons:
- `macro_tailwind_boost`
- `macro_headwind_penalty`
- `macro_context_missing`
- `macro_context_degraded`
- `macro_exposure_not_mapped`
- `below_macro_lane_floor`

Add taxonomy definitions for new reason and lane labels if governed labels live in taxonomy config/code.

## Phase 5 — Wire orchestration and replay-safe context resolution

In watchlist execution/orchestration:
1. Resolve macro context once per run with the same `as_of` used for cheap scan/deep analysis.
2. Build macro support for every cheap-scan candidate before shortlist evaluation.
3. Pass support into shortlist evaluation.
4. Ensure replay mode uses local snapshot resolver only and never calls context refresh.
5. Add run artifact summary:
   - macro snapshot id;
   - number boosted/penalized/neutral/missing;
   - macro-lane count;
   - warnings if snapshot missing/degraded.

## Phase 6 — Persist diagnostics

Add compact fields to:
- shortlist decision payload;
- `TickerSignalSnapshot.diagnostics`;
- `TickerSignalSnapshot.source_breakdown` if useful for operator detail;
- `RecommendationDecisionSample.decision_context` / compact context payload.

Suggested payload:

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

Keep plan payload additions minimal because plans already include richer transmission summaries after deep analysis.

## Phase 7 — UI/read-model updates

Update API serializers/read models used by shortlist and decision-sample pages to expose:
- raw attention/confidence;
- context-adjusted attention;
- macro adjustment;
- macro bias/quality;
- lane label;
- macro reasons.

UI changes:
- add a small “Macro shortlist” row/badge in signal and decision sample details;
- show neutral/missing/degraded explicitly;
- avoid green positive styling when evidence is degraded or missing;
- add filters later only if operator review shows need.

## Phase 8 — Tuning and validation

Add signal-gating analysis slices:
- `selection_lane=macro_context`;
- `macro_shortlist_bias`;
- `macro_shortlist_quality_status`;
- `macro_shortlist_adjustment_bucket`.

Run historical replay comparing:
- baseline technical shortlist;
- macro-aware shortlist with default bounds;
- macro lane disabled vs enabled.

Promotion evidence must include:
- missed-win reduction for non-shortlisted samples;
- no material degradation in actionable plan win rate;
- no excessive deep-analysis budget increase;
- sample-size sufficiency by lane and bias.

## Phase 9 — Documentation and cleanup

After implementation:
- update `docs/recommendation-methodology.md` from target wording to implemented wording;
- update `docs/features-and-capabilities.md` if UI/operator capability changes;
- update `docs/raw-details-reference.md` with new payload fields;
- archive this implementation plan when complete.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Macro narratives add noise | Keep boost small, require usable evidence, benchmark before widening |
| Missed technical winners due to macro penalty | Bound penalty and keep degraded/missing neutral |
| Replay leakage | Use snapshot resolver only; tests fail if providers are called |
| Taxonomy exposure gaps | Neutral with `macro_exposure_not_mapped`, do not infer unsupported read-through |
| UI over-trust | Label as shortlist triage, not prediction proof |
| Complexity creep | One scorer, compact payload, no new vendor/source work |

## Initial implementation checklist

- [ ] Add spec tests for macro support scorer.
- [ ] Add `MacroShortlistSupport` dataclass.
- [ ] Add macro shortlist scoring service.
- [ ] Add shortlist config defaults and decision payload fields.
- [ ] Add macro-adjusted ranking and macro lane.
- [ ] Wire scorer into watchlist orchestration using point-in-time context snapshots.
- [ ] Persist diagnostics into signal snapshots and decision samples.
- [ ] Add taxonomy labels for new lane/reasons.
- [ ] Add replay-safety tests.
- [ ] Add UI/read-model fields.
- [ ] Run full targeted test suite.
- [ ] Run replay comparison before enabling positive boost by default in production.
