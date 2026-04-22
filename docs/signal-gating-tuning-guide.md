# Signal gating tuning guide

**Status:** current shipped behavior

This document describes the signal-gating tuning workflow that is available in the app today.

Use it to understand:
- what signal gating tuning is for
- which UI pages and API routes exist now
- what parts are live today versus still future work

## Purpose

Signal gating tuning is the **upstream recall-oriented** tuning surface.

It is responsible for shortlist-selection behavior before downstream plan generation runs.

Use it when you want to answer questions like:
- is the current threshold too strict?
- are too many near-misses being rejected?
- is the shortlist too narrow or too permissive?
- are degraded cases being over-penalized or under-penalized?

*(Note: Recall optimization uses two labels: `phantom_win` / `phantom_loss` on framed `no_action` or `watchlist` plans, and benchmarked follow-through on discarded signals that never reached trade framing. The tuning engine uses both to estimate whether the shortlist is too tight.)*

Plan-generation tuning is separate.

- **signal gating tuning** = upstream selection / recall
- **plan generation tuning** = downstream plan quality / precision
- **recommendation-quality review and walk-forward validation** = trust, calibration, and promotion discipline

## Current role in the broader system

Signal-gating tuning is still valuable, but it is no longer the only or main quality surface.

Its current role is to act as an **upstream control layer**:
- adjust shortlist strictness
- review near-misses and degraded borderline cases
- reduce junk before deeper analysis and plan construction
- recover skipped opportunities when the gate is too conservative

It should not be treated as the final proof that recommendation quality improved.

Recommendation quality now depends on several layers working together:
- **signal gating tuning** decides what gets through upstream
- **plan generation tuning** adjusts how actionable trades are framed downstream
- **recommendation-quality summaries, calibration review, evidence concentration, and walk-forward validation** decide whether a change deserves trust and promotion

So the intended reading is:
- use **signal gating tuning** when shortlist recall or selectivity looks wrong
- use **plan generation tuning** when trade framing and actionable precision look wrong
- use **recommendation-quality and walk-forward surfaces** to judge whether any tuning change is actually credible

## Shipped UI surfaces

The app currently ships these operator-visible signal-gating surfaces:

- **Research home** → entry point for research workflows
- **Signal gating tuning** page → live configuration, tuning runs, and candidate review
- **Decision samples** page → shared evidence surface used by gating review and other research workflows

## Shipped backend surfaces

Current routes include:
- `GET /api/signal-gating-tuning`
- `GET /api/signal-gating-tuning/runs`
- `POST /api/signal-gating-tuning/run`
- `POST /api/settings/signal-gating-tuning`

## Current behavior

The current shipped implementation supports:
- persisted active signal-gating tuning settings
- deterministic tuning runs over stored recommendation decision samples and outcomes
- default tuning windows anchored to the latest applied signal-gating tuning run instead of a blind newest-samples slice
- dry-run versus apply behavior
- candidate comparison storage
- operator review of recent tuning runs
- live proposal-generation use of the active gating tuning config
- richer sample filtering by shortlist state, setup family, transmission bias, and context regime
- calibration-report inspection through the shared research/calibration surfaces

The current surface is real shipped research tooling.
It is not just a placeholder.

## Current intent and boundaries

This workflow is still intentionally bounded.

It is meant to help operators tune shortlist-selection behavior during development and early usage without pretending to be a fully autonomous production optimizer.

What it does now:
- lets operators inspect the active gating settings
- runs a bounded candidate search over shortlist-related parameters
- by default, uses decision samples created since the latest applied signal-gating tuning run; if nothing has ever been applied, it uses all matching samples unless the operator supplies a narrower filter
- records run results and candidate comparisons
- can write the winning config back into active settings

What it does not fully do yet:
- broad autonomous scheduling and rollout governance
- sophisticated multi-stage search beyond the current bounded candidate surface
- full production-grade safety policy comparable to the stricter plan-generation tuning target spec

## How to use it

Suggested operator loop:
1. review **Decision samples**
2. identify recall problems or threshold drift
3. open **Signal gating job**
4. run tuning on the post-last-applied window first so the comparison matches the live gating regime
5. compare candidates and the latest run
6. apply only if the result is directionally credible
7. continue monitoring recommendation plans and outcomes downstream

## Relationship to recommendation plans

Signal gating tuning should be judged mainly by whether the upstream shortlist becomes healthier.

It should not be treated as the same thing as plan-generation tuning.
If the shortlist is acceptable but the actual trade plans are weak, use **plan generation tuning** instead.

It also should not be treated as a replacement for recommendation-quality validation.
A gating change that looks locally better still needs to be checked against calibration, baselines, evidence concentration, and later time slices before operators trust it.

## Related docs

- `decision-sample-tuning-guide.md`
- `operator-page-field-guide.md`
- `recommendation-methodology.md`
- `plan-generation-tuning-spec.md`
- `docs-index.md`
