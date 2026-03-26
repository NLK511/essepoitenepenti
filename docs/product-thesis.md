# Product Thesis

## What this product is

Trade Proposer App is an operator-facing system for generating, inspecting, evaluating, and improving systematic trade recommendations inside one product boundary.

Near-term, the most realistic interpretation of that goal is an explainable market-analysis, candidate-ranking, and trade-framing system. Stronger predictive claims should follow only after recommendation outcomes show measurable edge and confidence calibration.

It is not just a model runner and it is not just a dashboard. Its value comes from combining:
- execution workflows
- auditable diagnostics
- historical traceability
- shared market context
- operator control

## Core goal

The goal is not to produce the maximum number of signals.

The goal is to produce trade recommendations that are:
- inspectable
- reproducible
- operationally manageable
- honest about degraded inputs

A weaker but flashy system can always fabricate confidence. This product should prefer truthful uncertainty over hidden guesswork.

## Governing principle

### Signal integrity over cosmetic completeness

If an input is missing, stale, or failing, the app should say so explicitly.

That means:
- missing data should become warnings or neutral values
- stale shared macro or industry context/sentiment should degrade health/preflight rather than disappear silently
- provider failures should remain visible in stored diagnostics
- fallback behavior must never pretend to be equivalent to healthy input

This principle is the product's most important consistency rule.

## Product shape

The app should continue to feel like one coherent operating system for this workflow:
- define watchlists and jobs
- run proposal generation
- inspect runs, redesign recommendation plans, and recommendation-plan outcomes as the main operator truth path
- inspect legacy recommendations only where compatibility still requires them
- review shared sentiment snapshots and newer context objects
- evaluate historical outcomes
- optimize weights
- read the docs in-product

The user should not have to leave the app to understand what happened.

## What makes the current design effective

1. **Single backend-owned contract**
   The backend owns execution, persistence, diagnostics, and workflow semantics. This reduces drift between what happened and what the UI claims happened.

2. **Runs and trade outputs are distinct**
   Runs are execution records. Legacy recommendations and redesign recommendation plans are trade outputs. Keeping that distinction visible improves operator judgment.

3. **Shared context and sentiment artifacts are auditable**
   Macro and industry sentiment snapshots remain inspectable system artifacts, and the redesign is adding context objects as a more context-first surface.

4. **Evaluation and optimization stay inside the product**
   This gives the app a real learning loop instead of a fragmented toolchain.

5. **In-app docs reduce operational ambiguity**
   Documentation is part of the product experience, not an external afterthought.

## What threatens effectiveness

The largest risks are now operational, not conceptual:
- scheduler and worker reliability gaps
- weak observability for a multi-process workflow system
- incomplete credential lifecycle management
- adding more signal sources faster than their quality can be measured
- documentation drift that confuses shipped behavior with future plans

## Strategic priority order

The project should prioritize work in this order:

1. **Reliability**
   Harden queueing, scheduling, overlap handling, and recovery behavior.

2. **Observability**
   Make it easy to understand what happened across API, worker, scheduler, and external providers.

3. **Security and credential lifecycle**
   The provider surface should not expand faster than secret handling and auth maturity.

4. **Evidence of recommendation quality**
   Measure whether sentiment enrichments and weight changes actually improve outcomes.

5. **Feature expansion**
   Only add more providers or broader product scope after the above are in better shape.

## What to avoid

- treating speculative integrations as near-term priorities
- duplicating roadmap language across many docs
- adding fallback heuristics that hide degraded inputs
- expanding into multi-user scope before the single-user model is operationally strong

## Standard for future decisions

A proposed feature is a good fit if it does at least one of these:
- improves operator trust
- improves reproducibility
- improves diagnosability
- improves workflow reliability
- measurably improves recommendation quality

A proposed feature is a poor fit if it mainly adds complexity, provider surface area, or narrative polish without improving those outcomes.
