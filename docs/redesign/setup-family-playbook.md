# Setup Family Playbook

## Purpose

This document specifies how setup families should influence recommendation-plan generation, not just labeling.

The goal is to make setup families drive:
- trade construction
- invalidation logic
- evaluation expectations
- calibration review
- operator explanation
- operator-visible cohort review

## Core rule

A setup family is only useful if it changes behavior.

The redesign should avoid treating setup family as a cosmetic tag attached after a generic recommendation has already been built.

## Current primary setup families

The redesign should currently standardize around:
- `continuation`
- `breakout`
- `breakdown`
- `mean_reversion`
- `catalyst_follow_through`
- `macro_beneficiary_loser`
- `no_action`
- `uncategorized`

Additional families should be added only when they drive distinct plan logic and evaluation value.

## Per-family expectations

## 1. Continuation
### Typical shape
- existing trend remains intact
- pullbacks are being bought or sold predictably
- context is supportive or at least not hostile

### Preferred conditions
- trend structure intact
- momentum not collapsing
- no major hostile catalyst
- acceptable execution quality

### Entry style
- pullback entry
- reclaim after shallow retracement
- continuation break above nearby structure

### Stop logic
- below pullback low for longs
- above pullback high for shorts
- volatility buffer allowed

### Take-profit logic
- trend extension target
- measured move
- next resistance/support

### Common failure mode
- trend exhaustion or failed continuation

## 2. Breakout
### Typical shape
- range compression or resistance test resolves upward
- volume / participation improves
- follow-through matters quickly

### Preferred conditions
- clear level
- breakout is recent or imminent
- catalyst or supporting context helps
- not badly extended before entry

### Entry style
- break above resistance
- retest hold after break

### Stop logic
- below breakout level minus buffer
- below local structure low

### Take-profit logic
- measured move
- next major resistance
- minimum risk/reward gate

### Common failure mode
- false breakout / failed follow-through

## 3. Breakdown
### Typical shape
- support fails to hold
- bearish continuation or deterioration accelerates

### Preferred conditions
- clean support failure
- risk-off or hostile context helps
- borrow/short policy permits the trade

### Entry style
- breakdown through support
- failed retest of lost level

### Stop logic
- above failed support / reclaimed level

### Take-profit logic
- next support
- measured move
- volatility-adjusted downside target

### Common failure mode
- squeeze or failed breakdown reclaim

## 4. Mean reversion
### Typical shape
- move appears stretched
- price is moving toward a more normal range after an overreaction

### Preferred conditions
- extension is identifiable
- catalyst is fading or over-discounted
- liquidity is adequate
- not fighting a fresh strong macro or company-specific shock

### Entry style
- reversal confirmation near exhaustion
- reclaim / rejection around extreme move

### Stop logic
- beyond local extreme with volatility buffer

### Take-profit logic
- return toward moving-average / range midpoint / prior value area

### Common failure mode
- trend keeps running and reversion never arrives

## 5. Catalyst follow-through
### Typical shape
- important news or event creates repricing
- move still has room to continue over the target horizon

### Preferred conditions
- catalyst freshness is high
- source quality is credible
- transmission into the ticker is explainable
- event is still being confirmed rather than fading immediately

### Entry style
- post-catalyst continuation
- reclaim after initial digestion
- sympathy continuation with clear read-through

### Stop logic
- below catalyst impulse low for longs
- above impulse high for shorts
- invalidation if event confirmation weakens sharply

### Take-profit logic
- event follow-through target
- post-gap continuation objective
- nearby structural level if closer than event target

### Common failure mode
- catalyst fades faster than expected

## 6. Macro beneficiary / loser
### Typical shape
- ticker is moving primarily as an exposure expression of broader context
- industry and macro drivers dominate ticker-specific narrative

### Preferred conditions
- exposure channel is explicit
- macro / industry driver is active and not stale
- direction matches the exposed business profile

### Entry style
- trend continuation in exposed name
- sympathy move after sector confirmation
- pullback within broader context move

### Stop logic
- invalidation of exposure trade thesis
- break of sector sympathy structure
- volatility buffer around recent swing point

### Take-profit logic
- context continuation window target
- sector-relative extension level

### Common failure mode
- regime shifts or transmission weakens abruptly

## Cross-family rules

## Entry policy
The plan builder should choose entry style based on family first, then technical details.

## Stop policy
Stop placement should reflect family-specific invalidation, not a generic fixed formula.

## Take-profit policy
Take profit should reflect how that family typically realizes edge.

## Family-specific `no_action`
A family may still result in `no_action` when:
- structure is visible but invalidation is unclear
- catalyst is visible but fading too fast
- context is supportive but price is too extended
- setup exists but execution quality is poor
- family is present but confidence/calibration gating blocks promotion

## Evaluation expectations by family

The evaluation system should eventually compare family-specific behavior such as:
- breakout: follow-through speed, false-break frequency
- continuation: persistence vs stall rate
- mean reversion: reversion completion rate
- catalyst follow-through: decay speed, day-1 vs day-5 quality
- macro beneficiary / loser: transmission persistence and regime sensitivity

## Interaction with transmission

Family logic should interact with context explicitly.

Examples:
- breakout + context tailwind = favorable
- breakout + context headwind = higher bar for promotion
- mean reversion + fresh hostile catalyst = usually lower-quality setup
- catalyst follow-through + stale catalyst = downgrade risk
- macro beneficiary / loser without clear exposure channel = weak thesis

## Interaction with calibration

Calibration should evaluate families separately and, where useful, by:
- horizon
- transmission bias
- context regime

Family labels should be treated as first-class evaluation cohorts, not just descriptive metadata.

## Operator visibility

Operators should be able to see:
- selected family
- why that family was chosen
- family-specific risks
- family-specific invalidation framing
- whether calibration penalized that family

## Success criteria

This playbook is helping if:
- recommendation plans feel meaningfully different across families
- `no_action` explanations become more precise
- evaluation review can identify which families actually work
- family labels improve both explanation quality and plan quality
