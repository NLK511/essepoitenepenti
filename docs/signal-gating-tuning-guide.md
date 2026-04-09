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

Plan-generation tuning is separate.

- **signal gating tuning** = upstream selection / recall
- **plan generation tuning** = downstream plan quality / precision

## Shipped UI surfaces

The app currently ships these operator-visible signal-gating surfaces:

- **Research home** → entry point for research workflows
- **Signal gating** page → overview and navigation for the gating workflow
- **Signal gating job** page → live configuration, tuning runs, and candidate review
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
4. adjust settings or run tuning
5. compare candidates and the latest run
6. apply only if the result is directionally credible
7. continue monitoring recommendation plans and outcomes downstream

## Relationship to recommendation plans

Signal gating tuning should be judged mainly by whether the upstream shortlist becomes healthier.

It should not be treated as the same thing as plan-generation tuning.
If the shortlist is acceptable but the actual trade plans are weak, use **plan generation tuning** instead.

## Future work

Likely next expansions include:
- broader candidate search
- richer explanations and comparison summaries
- stronger automation and scheduling rules
- tighter governance around promotion behavior

## Related docs

- `decision-sample-tuning-guide.md`
- `operator-page-field-guide.md`
- `recommendation-methodology.md`
- `plan-generation-tuning-spec.md`
- `docs-index.md`
