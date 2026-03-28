# Measured Success Criteria

**Status:** archival redesign history

## Purpose

This document defines what counts as meaningful redesign progress.

The redesign is not complete merely because:
- more objects are persisted
- more UI surfaces exist
- more heuristics are added

It should be judged by whether operator usefulness and measured recommendation quality improve.

## Core principle

The redesign should be treated as successful in phases.

## Phase 1: Operator workflow success
The redesign is succeeding at Phase 1 if it reliably improves:
- watchlist triage
- shortlist transparency
- trade framing
- `no_action` discipline
- outcome traceability

This phase does **not** require proof of strong predictive edge.

## Phase 2: Evaluation maturity success
The redesign is succeeding at Phase 2 if it produces:
- enough stored outcomes for repeated review
- usable cohort summaries by horizon/setup/transmission
- operator-visible threshold logic
- operator-visible bounded confidence re-scaling rather than hidden calibration magic
- evidence-concentration views that show where the app is strongest and weakest
- fewer unjustified promotions of weak setups
- stable review workflows for wins, losses, and missed opportunities

## Phase 3: Measured recommendation quality success
The redesign should only be treated as succeeding at Phase 3 if it shows repeated evidence of quality improvement relative to simple heuristics.

## Required metrics

The app should keep reviewing, at minimum:
- total analyzed tickers
- shortlisted tickers
- actionable plan rate
- `no_action` rate
- resolved trade-plan count
- win rate
- average return `1d`
- average return `3d`
- average return `5d`
- average MFE
- average MAE
- baseline cohort comparisons
- calibration bucket behavior

## Required cohort views

Measured review should be possible by:
- overall
- horizon
- setup family
- confidence bucket
- transmission bias
- context regime
- horizon + setup family

## What counts as a meaningful improvement

Near-term, meaningful improvement means one or more of:
- better win rate than simple heuristic cohorts
- better average `5d` return than simple heuristic cohorts
- lower promotion of obviously weak/conflicted plans
- clearer separation between strong and weak confidence cohorts
- more useful operator triage with fewer noisy deep-analysis promotions

## What does not count as success by itself

These are not enough on their own:
- more recommendations generated
- more aggressive action rates
- more complexity in signals
- nicer summaries
- more stored metadata
- isolated anecdotal wins

## Minimum evidence before stronger product claims

Before describing the app as having meaningful short-horizon predictive quality, there should be:
- a substantial resolved trade-plan sample
- repeated cohort review across horizons
- evidence that some setup families outperform weaker cohorts consistently enough to matter
- evidence that calibration gating reduces poor promotions
- evidence that baseline comparisons are not trivially matched by simpler heuristics

The exact threshold may evolve, but the qualitative bar should remain high.

## Recommended operator review questions

Every redesign review cycle should ask:
1. Did shortlist quality improve?
2. Did `no_action` discipline improve?
3. Which setup families are actually working?
4. Which horizons are degrading?
5. Are transmission-supported plans better than transmission-conflicted plans?
6. Did calibration block bad plans or hide good ones?
7. Is cheap scan still dominating too much?

## Failure signals

The redesign should be treated as off-track if:
- actionable plans increase without better measured quality
- calibration changes move often on thin samples
- setup-family labels exist but do not change outcomes or plan logic
- transmission metadata grows without measurable effect
- operator workflows still require raw JSON spelunking for key decisions
- the product starts making stronger predictive claims than the evidence supports

## Release-gating guidance

## Safe to expand operator usage when:
- workflows are stable
- review surfaces are transparent
- threshold logic is inspectable
- outcome persistence is healthy

## Not safe to make stronger predictive claims when:
- cohort counts are still thin
- horizon/regime behavior is unstable
- confidence buckets are poorly separated
- baseline advantages are weak or inconsistent

## Success statement template

A realistic status statement should look like:

> The redesign is currently successful as an operator-facing shortlist, setup-review, and trade-framing workflow with measurable outcomes. Predictive claims remain provisional until outcome history, calibration, and cohort comparisons show stronger evidence of repeatable edge.
