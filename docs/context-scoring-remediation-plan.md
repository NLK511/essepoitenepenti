# Context scoring remediation plan

**Status:** implemented through mapped-exposure rollout guardrails

Implementation tracker for macro/industry context scoring. The durable behavior contract is `specs/context-scoring-spec.md`; this file tracks completed work, remaining work, and rollout order.

## Current state

Implemented:
- shared `ContextEvidenceScorer` for macro and industry event-derived support scoring;
- shared `ContextSnapshotSchemaAdapter` for canonical and old score keys;
- macro resolver compatibility for old `context_score`/`context_label` rows;
- canonical `support_score`, `support_label`, `directional_confidence_percent`, `score_components`, `score_reasons`, and `score_version=event_v1` on new macro/industry snapshots;
- no duplicate legacy score keys on new rows;
- read-only `scripts/report_context_scoring_impact.py` impact report;
- tests for resolver compatibility and primary-news-derived macro/industry support.

Implemented in this remediation pass:
- ticker-specific `ContextExposureMapper` output backed by the ticker exposure ontology;
- clean separation between raw support (`macro_support_score`, `industry_support_score`, `raw_support_score`) and mapped exposure alignment (`macro_exposure_alignment_percent`, `industry_exposure_alignment_percent`, `alignment_percent`);
- mapped exposure routed into deep-analysis transmission summaries and ticker signal snapshots without widening positive confidence caps;
- read-model neutral reasons for missing, degraded, unmapped, mixed, and true-neutral context;
- impact report ablation modes for `normal`, `forced_neutral`, `quality_only`, `adverse_only`, and `mapped_exposure`.

Still pending before promotion:
- replay results proving mapped context improves or preserves performance;
- any wider positive context boost beyond the current conservative cap.

## Why this remediation exists

Original issues:
- refresh payload `score`/`label` came mostly from social sentiment;
- primary news extraction created events, quality, summaries, and saliency but did not consistently recompute directional support;
- macro and industry used different score keys, which caused macro resolver fallback to neutral in some rows;
- context semantics were scattered across sentiment, exposure, transmission, setup family, confidence adjustment, and quality gating;
- shortlisting had no explicit context path.

Goal: keep context score production shared, auditable, point-in-time safe, and measurable before increasing context influence.

## Design principles

1. **Evidence first** — score from extracted events/drivers, not social sentiment alone.
2. **Shared semantics** — macro and industry use the same scoring primitives unless a difference is explicit.
3. **Neutral is honest** — missing, stale, unmapped, degraded, contradictory, or generic evidence should stay neutral or cautionary.
4. **Direction is contextual** — global context may be positive for one exposure and negative for another.
5. **Bounded influence** — context cannot dominate technical setup, calibration, broker policy, or risk gates.
6. **Replay safe** — use only snapshots available at or before `as_of`.
7. **Measured promotion** — positive boosts stay conservative until ablation/replay proves lift.

## Shared components

### Implemented: `ContextEvidenceScorer`

Converts extracted events/drivers into a normalized context score.

Inputs:
- active events/drivers;
- primary news and supporting social counts;
- source priority counts;
- context quality assessment;
- contradiction count;
- scope: `macro` or `industry`;
- legacy score/label for diagnostics.

Outputs:
- signed `support_score` from `-1.0` to `+1.0`;
- `support_label`: `POSITIVE`, `NEGATIVE`, `MIXED`, or `NEUTRAL`;
- `directional_confidence_percent`;
- `saliency_score`;
- `evidence_state` and `coverage_state`;
- transparent `score_components` and `score_reasons`.

Scoring model:

```text
raw_direction = weighted average of event directional signs
saliency = prominence of matched salient events and breadth
source_quality = official/trade/major/social weighted factor
confidence = source_quality * coverage * quality * non_contradiction_factor
support_score = raw_direction * saliency * confidence
```

Rules:
- no active events => neutral;
- contradictory evidence => mixed or penalized;
- social-only evidence is capped;
- degraded/blocked evidence is capped;
- score components are persisted.

### Implemented: `ContextSnapshotSchemaAdapter`

Canonical reader for old and new snapshot rows.

Rules:
- read `support_score`, fallback to old `context_score`;
- read `support_label`, fallback to old `context_label`;
- new rows write canonical `support_*` fields only;
- downstream services consume canonical resolved payloads.

### Partially implemented: directional classification

Current scorer uses existing event extraction fields:
- `evidence_direction`;
- `market_interpretation`;
- `state_transition`;
- `saliency_weight`;
- `source_priority`.

Pending hardening:
- extract a dedicated `ContextDirectionalClassifier` only if rules outgrow the compact scorer helper;
- add category-specific tests for inflation, yields, oil, guidance, demand, and mixed contradictory events.

### Implemented: `ContextExposureMapper`

Implemented before widening context influence.

Inputs:
- context events/drivers with beneficiary/loser tags and channels;
- ticker taxonomy profile;
- ticker exposure ontology;
- sector/relationship graph;
- candidate direction and horizon.

Outputs:
- `exposure_bias`: `tailwind`, `headwind`, `mixed`, `neutral`, or `unknown`;
- `alignment_percent`;
- `context_strength_percent`;
- `context_event_relevance_percent`;
- raw support fields and percent-style mapped alignment fields;
- matched exposure paths and relationship edges;
- conflict flags;
- expected transmission window;
- neutral/missing/degraded reason.

This mapper feeds transmission analysis and ticker signal snapshots. Context-aware shortlist expansion remains gated by replay evidence.

## Canonical payload

New macro and industry snapshots expose:

```json
{
  "support_score": 0.42,
  "support_label": "POSITIVE",
  "directional_confidence_percent": 64.0,
  "evidence_state": "usable",
  "coverage_state": "news",
  "context_quality_status": "usable",
  "context_quality_score": 82.0,
  "score_components": {
    "event_direction": 0.7,
    "event_saliency": 0.58,
    "source_quality": 0.75,
    "coverage_factor": 0.9,
    "quality_factor": 0.82,
    "contradiction_penalty": 0.0
  },
  "score_reasons": ["event_directional_evidence"],
  "score_version": "event_v1"
}
```

Old `context_score`/`context_label` rows are read-only compatibility data.

## Pipeline application policy

### Shortlisting

Current behavior: no explicit context effect.

Target behavior:
- context can participate only as bounded triage after cheap scan;
- use mapped exposure, not raw global score;
- missing/degraded/unmapped context is neutral;
- positive boost requires usable mapped context aligned with candidate direction;
- weak technical candidates cannot be rescued by context alone.

See `specs/macro-context-shortlist-spec.md` and `macro-context-shortlist-implementation-plan.md`.

### Deep analysis and signal building

Current improvement: raw support fields and score components are available.

Pending cleanup:
- distinguish true neutral from missing/degraded neutral;
- carry signed raw support separately from percent-style exposure alignment;
- build `macro_exposure_score` and `industry_alignment_score` from mapped exposure once `ContextExposureMapper` exists.

Suggested future fields:
- `macro_support_score`, `industry_support_score`;
- `macro_exposure_alignment_percent`, `industry_exposure_alignment_percent`;
- `macro_evidence_state`, `industry_evidence_state`;
- `macro_neutral_reason`, `industry_neutral_reason`.

### Transmission and confidence

Current transmission already has quality gates and conservative positive boosts.

Policy:
- positive mapped context boost remains capped, currently max `+2`, until replay validation;
- adverse/contradictory context may penalize more strongly or block;
- missing/degraded context cannot positive-boost;
- avoid double-counting the same evidence as news sentiment, context support, and transmission boost.

Concept separation:
1. **context evidence quality** — can cap/degrade confidence;
2. **context directional support** — small directional contribution;
3. **context transmission fit** — setup family, risks, action blockers.

### Setup family and plan framing

- `macro_beneficiary_loser` requires explicit usable mapped macro exposure.
- Industry context may support catalyst families only with concrete industry events.
- Generic neutral context must not create context-family labels.
- Plan geometry should use context family/bias only when mapped context is usable.

## Implementation phases

### Phase 1 — Resolver compatibility — implemented

- Macro resolver reads canonical and old keys.
- Industry resolver uses the same adapter path.
- Resolved payloads expose score-source diagnostics.

### Phase 2 — Shared scoring utilities — implemented

- Added `context_scoring.py`.
- Moved shared evidence/coverage state behavior into `ContextEvidenceScorer`.
- Normalized macro/industry source breakdowns around canonical `support_*` fields.

### Phase 3 — Event-derived support — implemented, hardening pending

- Macro and industry now derive support from extracted event direction, source priority, saliency, coverage, quality, and contradictions.
- Additional edge tests for social-only, degraded, blocked, and contradictory cases are still useful.

### Phase 4 — Impact report — partially implemented

Implemented report:

```bash
.venv/bin/python scripts/report_context_scoring_impact.py --json
```

Report covers:
- snapshot coverage and score distributions;
- label, evidence, quality, and score-version distributions;
- neutral reasons;
- plan context neutrality;
- transmission adjustment and action-reason summaries.

Implemented ablation modes:
- normal context;
- context forced neutral;
- context quality-only;
- context adverse-only;
- full mapped exposure.

### Phase 5 — Exposure mapping — implemented

- Added `ContextExposureMapper` using ticker exposure ontology.
- Preserved raw support separately from mapped exposure alignment.
- Fed mapped context into ticker deep analysis, signal builder, and transmission summaries.
- Tested direct, inverse, unmapped, and mixed exposures.

### Phase 6 — Downstream cleanup — implemented for read models and signal payloads

Audit and normalize usage of:
- `macro_context_score`;
- `industry_context_score`;
- `macro_exposure_score`;
- `industry_alignment_score`;
- `context_strength_percent`;
- `transmission_confidence_adjustment`.

Diagnostics now show raw support, mapped exposure, evidence state, quality state, neutral reason, and final confidence adjustment.

### Phase 7 — Replay validation — pending

Run point-in-time replay on representative windows.

Promotion gates:
- no future snapshot leakage;
- improved or unchanged actionable win rate;
- reduced missed-win rate if context shortlist is enabled;
- no excessive actionability collapse from penalties;
- sufficient samples by context lane/bias.

Until gates pass:
- keep positive boosts small;
- keep context primarily diagnostic and defensive.

### Phase 8 — UI/read-model cleanup — implemented for read models

Operator surfaces should distinguish:
- no context available;
- true neutral/no salient directional event;
- mixed/contradictory context;
- usable supportive/adverse context;
- mapped ticker exposure exists/does not exist.

Avoid showing a plain neutral `50` without evidence/coverage reason.

## Tests to keep expanding

Already covered:
- macro legacy key adapter;
- event-derived non-neutral macro support from primary news;
- event-derived non-neutral industry support from primary news;
- downstream proposal/deep-analysis context quality compatibility.

Add next:
- social-only cap;
- degraded/blocked quality caps;
- contradiction handling;
- no-active-events neutral behavior;
- same evidence shape produces consistent macro/industry common scoring;
- mapped exposure direct/inverse/unmapped/mixed cases;
- replay uses stored snapshots only.

## Data migration/backfill policy

Do not rewrite old context rows by default.

Policy:
1. resolver adapter supports old rows;
2. new rows write canonical fields;
3. impact report separates `score_version=legacy` and `score_version=event_v1`;
4. optional offline reconstruction may backfill replay research rows only when clearly marked as reconstructed.

## Next recommended PR

1. Run replay validation using `scripts/report_context_scoring_impact.py --ablation-mode forced_neutral|quality_only|adverse_only|mapped_exposure` plus historical replay batches.
2. Decide whether context-aware shortlist participation has enough evidence to graduate from diagnostic mode.
3. If promoted, keep positive boosts capped and prefer adverse/quality guardrails first.
