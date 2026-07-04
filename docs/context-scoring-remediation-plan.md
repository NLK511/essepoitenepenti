# Context scoring remediation plan

**Status:** partially implemented

Implemented so far:
- shared `ContextEvidenceScorer` for macro and industry event-derived support scoring;
- shared `ContextSnapshotSchemaAdapter` for canonical and legacy score keys;
- macro resolver compatibility for legacy `context_score`/`context_label` rows;
- canonical `support_score`, `support_label`, `directional_confidence_percent`, `score_components`, `score_reasons`, and `score_version=event_v1` on new macro/industry snapshots without writing duplicate legacy score keys;
- read-only `scripts/report_context_scoring_impact.py` impact report;
- unit/integration tests for resolver compatibility and primary-news-derived macro/industry support.

Still pending: exposure-mapped ticker-specific context scoring, shortlist context participation, UI updates, and replay ablation/promotion evidence.

This plan remediates macro and industry context scoring so Aurelio uses shared, point-in-time, evidence-derived behavior instead of mostly neutral social-derived labels. It covers context production, common components, downstream application, measurement, and rollout.

## Problem statement

Macro and industry context contain useful evidence fields, but historical snapshots and the previous scoring path made the downstream directional score weak or neutral most of the time.

Original issues found before remediation:
- macro and industry refresh payloads initialized `score`/`label` mostly from social sentiment;
- later primary news extraction created events, quality, summaries, and saliency but did not consistently recompute directional support from those events;
- industry wrote `support_score`/`support_label`, while macro wrote `context_score`/`context_label`; the macro resolver read `support_score`/`support_label`, creating likely neutral fallback;
- missing/degraded context correctly avoided false confidence, but the same path suppressed many potentially useful primary-news signals;
- context was applied in several places with mixed semantics: sentiment score, exposure score, transmission quality, context quality gate, setup family, and confidence adjustment;
- shortlisting did not explicitly use context.

Current remediation has fixed shared event-derived score production and resolver compatibility for new snapshots. Remaining work is to make ticker-specific exposure mapping, shortlist participation, and downstream confidence usage fully measured and clean.

Goal: keep macro and industry context score production shared, auditable, point-in-time safe, and outcome-measurable before increasing its influence.

## Guiding principles

1. **Evidence first** — scores must be derived from extracted events/drivers and source quality, not social sentiment alone.
2. **Shared semantics** — macro and industry use the same scoring primitives and quality gates unless intentionally different.
3. **Neutral is honest** — missing, stale, unmapped, degraded, contradictory, or generic evidence should stay neutral or cautionary.
4. **Direction is contextual** — context may be positive for one exposure and negative for another; global context direction alone is not enough.
5. **Bounded influence** — context cannot dominate technical setup, calibration, broker policy, or risk gates.
6. **Replay safe** — context scoring and consumption must use only snapshots available at or before `as_of`.
7. **Measured promotion** — positive boosts remain conservative until ablation/replay proves lift.

## Target architecture

Introduce common context components used by both macro and industry.

### 1. `ContextEvidenceScorer`

Shared service that converts extracted events/drivers into a normalized context score.

Inputs:
- active events/drivers;
- previous events for lifecycle state;
- primary news items and supporting social items;
- source priority counts;
- coverage quality;
- contradiction count;
- summary status;
- quality assessment;
- context scope: `macro` or `industry`;
- optional exposure target: industry/ticker/sector/tags.

Outputs:
- `support_score`: signed `-1.0` to `+1.0`;
- `support_label`: `POSITIVE`, `NEGATIVE`, `MIXED`, or `NEUTRAL`;
- `directional_confidence_percent`;
- `saliency_score`;
- `evidence_state`: `usable`, `degraded`, `thin`, `missing`;
- `coverage_state`: `news`, `social`, `news+social`, `missing`;
- `context_quality_status`: `usable`, `degraded`, `blocked`;
- `score_components` with transparent sub-scores;
- `score_reasons` and governed reason details.

Initial scoring model:

```text
raw_direction = weighted average of event directional signs
saliency = prominence of matched salient events and evidence volume
source_quality = trade/official/major/source-priority weighted factor
freshness = lifecycle and timestamp factor
confidence = source_quality * saliency * evidence_quality * non_contradiction_factor
support_score = raw_direction * saliency * confidence * quality_factor
```

Rules:
- no active events => neutral score;
- contradictory positive and negative events => `MIXED`, low or zero support score;
- social-only evidence can inform but cannot create high confidence;
- source quality and context quality cap the score;
- degraded evidence cannot create positive boost downstream, but can warn or reduce confidence if adverse and concrete;
- all score components must be persisted.

### 2. `ContextDirectionalClassifier`

Shared classifier that assigns direction to each event/driver.

Inputs:
- event definition metadata;
- event extraction direction hints;
- lifecycle state: new/escalating/easing/fading/persistent;
- market interpretation if available;
- category-specific polarity rules.

Outputs per event:
- `direction`: `positive`, `negative`, `mixed`, or `neutral`;
- `direction_confidence`;
- `direction_reasons`.

Important nuance:
- Some events are not globally positive/negative. Example: higher oil is positive for energy but negative for airlines/consumer. Such events should be classified as directional by exposure tags, not global market sentiment.

### 3. `ContextExposureMapper`

Shared mapper that converts global/industry context into ticker- or industry-specific impact.

Inputs:
- context events/drivers with beneficiary/loser tags and transmission channels;
- taxonomy industry profile;
- ticker exposure ontology;
- sector and relationship graph;
- candidate direction and horizon.

Outputs:
- `exposure_bias`: `tailwind`, `headwind`, `mixed`, `neutral`, `unknown`;
- `alignment_percent`;
- `context_strength_percent`;
- `context_event_relevance_percent`;
- matched exposure paths and relationship edges;
- conflict flags;
- expected transmission window.

This component should feed downstream transmission analysis and shortlist context scoring.

### 4. `ContextSnapshotSchemaAdapter`

Compatibility adapter for old and new snapshot keys.

Rules:
- read `support_score` or fallback to old `context_score`;
- read `support_label` or fallback to old `context_label`;
- new rows write canonical `support_*` fields only;
- expose a canonical resolved object to downstream services.

This fixes the macro resolver mismatch while preserving old rows without duplicating legacy keys in new snapshots.

## Target payload contract

Macro and industry snapshots should both expose:

```json
{
  "support_score": 0.42,
  "support_label": "POSITIVE",
  "directional_confidence_percent": 64.0,
  "saliency_score": 0.58,
  "evidence_state": "usable",
  "coverage_state": "news",
  "context_quality_status": "usable",
  "context_quality_score": 82.0,
  "score_components": {
    "event_direction": 0.7,
    "event_saliency": 0.58,
    "source_quality": 0.75,
    "freshness": 0.9,
    "contradiction_penalty": 0.0,
    "quality_factor": 0.82
  },
  "score_reasons": ["primary_news_event_direction", "major_source_support"]
}
```

Legacy `context_score`/`context_label` are read-only compatibility keys. New snapshots should write canonical `support_score`/`support_label` only.

## Pipeline application redesign

### Shortlisting

Current: no direct macro/industry effect.

Target:
- context can participate only as bounded triage after cheap scan;
- macro/industry support should use `ContextExposureMapper`, not raw global score;
- missing/degraded context is neutral;
- positive context boost requires usable context, mapped exposure, alignment with candidate direction, and no severe contradiction;
- weak technical candidates cannot be rescued by context alone.

This follows `specs/macro-context-shortlist-spec.md` and should later generalize to `context-shortlist-spec` if industry is added.

### Deep analysis and signal building

Current problem: `macro_exposure_score` and `industry_alignment_score` often map neutral `0.0` to `50.0`, obscuring whether context is genuinely neutral or unavailable.

Target:
- carry both `score_percent` and `evidence_state`;
- distinguish `neutral_because_no_effect` from `neutral_because_missing/degraded`;
- build `macro_exposure_score`/`industry_alignment_score` from exposure mapping, not raw support alone;
- preserve raw support score separately.

Suggested fields:
- `macro_support_score`, `industry_support_score` signed `-1..1`;
- `macro_exposure_alignment_percent`, `industry_exposure_alignment_percent`;
- `macro_evidence_state`, `industry_evidence_state`;
- `macro_neutral_reason`, `industry_neutral_reason`.

### Transmission

Current: transmission already has quality gates and conservative positive boosts. New snapshots now provide healthier event-derived support scores, but transmission still needs ticker-specific exposure mapping before context influence should be widened.

Target:
- make transmission consume `ContextExposureMapper` output;
- use context strength/relevance from mapped exposures;
- keep positive boost capped at `+2` until validation;
- keep negative/contradiction penalties stronger than positive boosts;
- severe direct conflicts can still block actionability;
- context quality conflicts should be explainable by scope: macro, industry, or both.

### Confidence

Current: context appears in multiple confidence paths and may be double-counted as sentiment + context + transmission.

Target:
- separate three concepts:
  1. **context evidence quality** — can cap or degrade confidence;
  2. **context directional support** — small directional contribution;
  3. **context transmission fit** — determines setup family, risks, and action blockers.
- avoid adding the same event through news sentiment, context support, and market intelligence as three independent boosts;
- positive context contribution should be small and gated;
- adverse/contradictory context may reduce confidence or block.

Recommended initial confidence policy:
- raw deep-analysis confidence remains mostly technical/ticker-specific;
- mapped usable context tailwind: max `+2` through transmission only;
- mapped usable headwind: up to `-6` and possible action block;
- degraded/missing context: no positive support, optional data-quality warning/cap;
- contradictory context: no positive support, penalty/block depending severity.

### Setup family

Target:
- `macro_beneficiary_loser` requires explicit mapped macro exposure and usable/non-stale context;
- industry context may support `catalyst_follow_through` only if concrete industry event exists;
- generic neutral context must not create a context-family label.

### Plan generation

Target:
- plan geometry may use context family/bias only when mapped context is usable;
- headwind stop/take-profit adjustments remain downstream plan-generation knobs;
- context should not change entry/stop/take-profit if evidence is missing/degraded except through caution warnings or no-action.

### Outcome/evaluation

Add slices:
- `macro_support_label`;
- `industry_support_label`;
- `macro_evidence_state`;
- `industry_evidence_state`;
- `macro_exposure_bias`;
- `industry_exposure_bias`;
- `context_neutral_reason`;
- `context_score_source_version`.

## Implementation phases

### Phase 1 — Fix resolver and add compatibility tests — implemented

Implemented:
1. Macro resolver tests cover canonical and legacy score keys.
2. `ContextSnapshotResolver` uses canonical adapter logic.
3. Industry resolver uses the same adapter path.
4. Resolved payloads expose score-source diagnostics.

Impact: macro numeric score is no longer accidentally neutralized when historical rows contain `context_score`/`context_label`.

### Phase 2 — Extract common schema adapter and quality/evidence helpers — implemented

Implemented:
1. Added `context_scoring.py`.
2. Moved shared evidence/coverage state helpers into `ContextEvidenceScorer`.
3. Normalized macro and industry source breakdowns around canonical `support_*` fields.
4. Added tests for usable primary-news evidence and resolver compatibility. Additional edge tests for social-only/degraded/contradictory cases remain useful hardening work.

### Phase 3 — Shared event directional scoring — partially implemented

Implemented:
1. `ContextEvidenceScorer` uses existing event extraction direction fields, market interpretation, lifecycle state, source priority, and saliency.
2. Macro and industry now share this event-derived support computation.

Pending hardening:
1. Split a dedicated `ContextDirectionalClassifier` only if the scoring rules grow beyond the current compact helper.
2. Add more category-specific tests for inflation, yields, oil, guidance, demand, and mixed contradictory events.

### Phase 4 — Shared support score computation — implemented

Implemented:
1. Added `ContextEvidenceScorer`.
2. `MacroContextService.create_from_refresh_payload` uses it.
3. `IndustryContextService.create_from_refresh_payload` uses it.
4. Both persist `support_score`, `support_label`, `directional_confidence_percent`, `score_components`, `score_reasons`, and `score_version=event_v1`.
5. New rows do not write duplicate legacy score keys; legacy compatibility is in readers only.
6. Tests prove macro and industry can derive non-neutral support from primary news even when refresh payload/social labels are neutral.

### Phase 5 — Exposure mapping for downstream use

1. Add/extend `ContextExposureMapper` using ticker exposure ontology.
2. Map macro/industry events to ticker-specific tailwind/headwind/mixed.
3. Feed mapper output into ticker deep analysis and signal builder.
4. Preserve raw context support separately from mapped exposure alignment.
5. Add tests for direct exposure, inverse exposure, unmapped exposure, and mixed exposure.

### Phase 6 — Downstream application cleanup

1. Audit all uses of:
   - `macro_context_score`;
   - `industry_context_score`;
   - `macro_exposure_score`;
   - `industry_alignment_score`;
   - `context_strength_percent`;
   - `transmission_confidence_adjustment`.
2. Ensure each use consumes the intended semantic field.
3. Prevent double counting in confidence calculation.
4. Add plan payload diagnostics showing:
   - raw support;
   - mapped exposure;
   - quality/evidence state;
   - final confidence adjustment.

### Phase 7 — Measurement and ablation reports — partially implemented

Implemented: `scripts/report_context_scoring_impact.py` provides read-only coverage, score-distribution, neutral-reason, and plan-impact summaries.

Report sections:
- macro/industry snapshot coverage and score distribution;
- neutral reason breakdown;
- score source version distribution;
- plan impact summary;
- action-block summary;
- outcomes by context slice;
- examples where context changed confidence/action;
- suspicious cases: strong events but neutral score, usable quality but zero support, support without mapped exposure.

Pending ablation modes:
- normal context;
- context forced neutral;
- context quality-only;
- context adverse-only;
- context full mapped exposure.

Compare:
- shortlist recall;
- deep-analysis budget;
- actionable count;
- no-action reasons;
- confidence distribution;
- win rate / EV / benchmark follow-through.

### Phase 8 — Replay validation before stronger influence

Run point-in-time replay on representative windows.

Promotion gates:
- no future snapshot leakage;
- improved or unchanged actionable win rate;
- reduced missed-win rate among non-shortlisted samples if context shortlist is enabled;
- no excessive actionability collapse from context penalties;
- context-lane or context-supported plans show positive follow-through on sufficient sample.

Until gates pass:
- keep positive boosts small;
- keep context primarily diagnostic and defensive.

### Phase 9 — UI/read-model updates

Operator surfaces should distinguish:
- no context available;
- context neutral because no salient directional event;
- context mixed/contradictory;
- context usable and directionally supportive/adverse;
- mapped ticker exposure exists/does not exist.

Avoid showing a plain neutral `50` without explaining whether it is true neutral or missing/degraded fallback.

## Test matrix

Required unit tests:
- macro legacy key adapter;
- industry canonical key adapter;
- shared evidence states;
- event directional classifier;
- support score bounds;
- contradiction handling;
- quality caps;
- social-only cap;
- no active events => neutral;
- usable directional news => non-zero score;
- same evidence produces same common score behavior for macro and industry.

Required integration tests:
- macro context snapshot persists canonical support fields;
- industry context snapshot persists canonical support fields;
- resolver returns canonical fields for old and new rows;
- ticker analysis receives raw support and mapped exposure fields;
- transmission uses mapped context, not raw neutral fallback;
- plan signal breakdown exposes context score components;
- replay uses stored snapshots only.

Required regression tests:
- missing/degraded context cannot positive-boost confidence;
- context cannot make weak technical setup actionable by itself;
- severe context contradiction can still block;
- disabled/neutral context preserves existing behavior.

## Data migration/backfill policy

Do not rewrite old context rows initially.

Instead:
1. resolver adapter supports old rows;
2. new rows write canonical fields;
3. impact report separates `score_version=legacy` vs `score_version=event_v1`;
4. optional offline reconstruction can backfill only for replay research, clearly marked as reconstructed.

## Rollout policy

1. Ship resolver bug fix first.
2. Ship common scorer behind `context_scoring_version=event_v1`.
3. Run side-by-side scoring in diagnostics without changing confidence/action for at least one replay batch.
4. Compare legacy vs event-v1 reports.
5. Enable defensive penalties first if evidence supports them.
6. Enable small positive mapped boosts only after replay lift.
7. Consider shortlist context participation only after scoring is proven healthy.

## Open decisions

- Should macro global support have any direct market-wide bullish/bearish meaning, or only exposure-mapped meaning?
- Which event categories are globally directional versus exposure-specific?
- How much should source quality cap social-only context?
- What sample size is required before widening context boost caps?
- Should industry context be refreshed only for watchlist industries instead of all taxonomy industries to improve evidence quality and reduce noise?

## Next recommended code PR

Next safe PR:
1. add ticker-specific `ContextExposureMapper` output using the ticker exposure ontology;
2. preserve raw support score separately from mapped exposure alignment;
3. route mapped exposure into transmission summaries without widening positive confidence caps;
4. add replay-safe ablation/report support for forced-neutral versus mapped-context behavior;
5. update UI/read models so neutral `50` is not shown without its evidence/coverage reason.
