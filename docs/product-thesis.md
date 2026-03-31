# Product Thesis

**Status:** canonical product direction

## What this product is

Trade Proposer App is an operator-facing system for generating, inspecting, evaluating, and improving systematic trade recommendations inside one product boundary.

Near-term, this is an explainable market-analysis, candidate-ranking, and trade-framing system. Stronger predictive claims should wait until recommendation outcomes and calibration give real evidence.

It is not just a model runner and it is not just a dashboard. The point is to keep execution, review, diagnostics, and outcome tracking in one place.

## Core goal

The goal is not to produce the maximum number of signals.

The goal is to produce trade recommendations that are:
- inspectable
- reproducible
- operationally manageable
- honest about degraded inputs

The app should prefer visible uncertainty over hidden guesswork.

## Governing principle

### Signal integrity over cosmetic completeness

If an input is missing, stale, or failing, the app should say so explicitly.

That means:
- missing data should become warnings or neutral values
- stale shared macro or industry context should degrade health/preflight rather than disappear silently
- provider failures should remain visible in stored diagnostics
- fallback behavior must not pretend to be equivalent to healthy input

## Product shape

The app should feel like one place for this workflow:
- define watchlists and jobs
- run proposal generation
- inspect runs, recommendation plans, and recommendation-plan outcomes
- review shared context artifacts
- evaluate historical outcomes
- optimize weights
- read the docs in-product

The operator should not have to leave the app to understand what happened.

## Strategic priority order

The project should prioritize work in this order:

1. **Reliability**
   Make queueing, scheduling, overlap handling, and recovery more dependable.

2. **Observability**
   Make it easier to understand what happened across API, worker, scheduler, and external providers.

3. **Security and credential lifecycle**
   Do not expand provider surface area faster than secret handling and auth maturity.

4. **Evidence of recommendation quality**
   Measure whether changes in support/context signals, ticker analysis, and weights actually improve outcomes.

5. **Feature expansion**
   Add more providers or broader product scope only after the above are in better shape.

## What to avoid

- treating speculative integrations as near-term priorities
- duplicating roadmap language across many docs
- adding fallback heuristics that hide degraded inputs
- expanding into multi-user scope before the single-user model is operationally solid

## Standard for future decisions

A proposed feature is a good fit if it does at least one of these:
- improves operator trust
- improves reproducibility
- improves diagnosability
- improves workflow reliability
- measurably improves recommendation quality

A proposed feature is a poor fit if it mainly adds complexity, provider surface area, or narrative polish without improving those outcomes.

## See also

- `features-and-capabilities.md` — what the app can do today
- `recommendation-methodology.md` — how the pipeline works
- `roadmap.md` — current priorities
- `architecture.md` — system structure
