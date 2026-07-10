# Context scoring spec

**Status:** current and target behavior

Binding contract for macro and industry context scoring and downstream use.

## Purpose

Macro and industry context must produce auditable, point-in-time, evidence-derived scores. Scores are used to describe context support, context quality, and mapped transmission. They are not standalone trade signals.

## Current implemented behavior

Macro and industry context now share common scoring primitives:
- `ContextEvidenceScorer` derives signed support from extracted events/drivers, source quality, coverage, context quality, saliency, and contradiction penalties.
- `ContextSnapshotSchemaAdapter` reads both canonical `support_score`/`support_label` and older `context_score`/`context_label` rows.
- New macro and industry snapshots persist canonical `support_score`, `support_label`, `directional_confidence_percent`, `score_components`, `score_reasons`, and `score_version=event_v1`.
- Macro resolver no longer loses score/label when old rows contain only `context_score`/`context_label`.
- Missing or eventless context remains neutral with explicit reasons.
- Degraded, blocked, contradictory, or social-only context is capped and cannot create strong positive support.
- `ContextExposureMapper` maps raw macro/industry support into ticker-specific exposure alignment using the ticker exposure ontology while preserving raw support separately from mapped alignment.
- Deep-analysis transmission and ticker signal diagnostics expose raw support, mapped alignment, matched exposure paths, neutral reasons, and quality/evidence states.

## Required score semantics

`support_score` is signed and bounded from `-1.0` to `+1.0`:
- positive means evidence directionally supports the context subject;
- negative means evidence directionally pressures the context subject;
- zero means neutral, missing, thin, mixed, degraded beyond usefulness, or unmapped.

`support_label` is one of:
- `POSITIVE`
- `NEGATIVE`
- `MIXED`
- `NEUTRAL`

`directional_confidence_percent` is an evidence-confidence score, not a win probability.

## Quality and coverage rules

Positive support requires active directional events and sufficient quality. Quality caps apply as follows:
- no active events => neutral;
- missing evidence => neutral/missing;
- social-only evidence => capped confidence;
- degraded context => capped confidence;
- blocked context => no positive decision support;
- contradictory evidence => mixed or penalized support.

## Canonical snapshot fields

Macro and industry source breakdowns must expose:
- `support_score`
- `support_label`
- `directional_confidence_percent`
- `score_components`
- `score_reasons`
- `score_version`
- `coverage_state`
- `evidence_state`
- `context_quality_score`
- `context_quality_status`
- `context_quality_flags`
- `context_quality_notes`

Older rows may still contain only `context_score`/`context_label`; readers must use `ContextSnapshotSchemaAdapter`. New rows must not write duplicate legacy score keys.

## Industry context role

Industry context is secondary corroborating context, not the primary ticker-exposure model. Current behavior:
- industry snapshots expose quality, evidence, coverage, score reasons, neutral reasons, active-driver counts, and source diagnostics;
- missing snapshots resolve as blocked/missing rather than meaningful neutral evidence;
- empty-driver snapshots must say no salient industry evidence was found;
- degraded, blocked, partial, failed, missing, or driverless industry context cannot provide positive mapped support;
- decision-usable industry context requires usable quality, usable evidence, and at least one active driver;
- Context Review and `scripts/report_industry_context_quality.py` surface usable/degraded/blocked counts, stale rows, zero-confidence rows, active-driver rate, and neutral reasons.

Any wider industry-positive role requires outcome evidence against ontology/transmission baselines.

## Downstream use

Context scores may influence downstream analysis only through bounded paths:
- plan context fields and evidence summaries;
- macro/industry exposure scores in ticker analysis;
- transmission alignment and quality diagnostics;
- conservative confidence adjustment after quality gates;
- action blocking for severe usable contradictions or blocked broad context.

Context scores must not:
- bypass technical setup requirements;
- create actionable plans on their own;
- positive-boost when quality is degraded/blocked/missing;
- be counted repeatedly as news sentiment, context sentiment, and transmission boost for the same evidence.

## Measurement

The context impact report must be able to summarize:
- macro and industry score distributions;
- label distributions;
- evidence/coverage/quality distributions;
- neutral reasons;
- score version distribution;
- plan exposure neutrality;
- transmission adjustment and action-reason impact.

`scripts/report_context_scoring_impact.py` supports ablation modes `normal`, `forced_neutral`, `quality_only`, `adverse_only`, and `mapped_exposure`. Use replay ablation before increasing positive context influence.

## Test requirements

Tests must prove:
- macro resolver reads old `context_score`/`context_label` rows;
- new macro context derives non-neutral support from directional primary news even when payload social label is neutral;
- new industry context derives non-neutral support from directional primary news even when payload social label is neutral;
- eventless context remains neutral;
- degraded/missing context remains capped;
- degraded or driverless industry context cannot create positive mapped support;
- downstream proposal/deep-analysis tests continue to expose context quality fields;
- context exposure mapper tests cover direct, inverse, unmapped, and mixed exposures;
- macro-shortlist tests prove mapped context remains resolver-only and point-in-time safe.
