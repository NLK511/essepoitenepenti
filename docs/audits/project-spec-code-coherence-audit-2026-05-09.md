# Project spec/code coherence audit

**Status:** reference

Here’s the honest audit.

## Bottom line
The project is **conceptually coherent**, but **not lean**.  
It is much better at being an inspectable decision-support system than a proven autonomous trading edge.

The specs mostly agree on the big picture:
- one modular monolith
- operator-visible uncertainty
- broker/effective outcomes as canonical
- context/recommendation/policy/reliability as separate contracts

But there is still a lot of **overlap, legacy language, and layered abstractions**, and the core “make money autonomously” goal is still **unproven**.

---

## What is coherent

### 1. Product direction is internally consistent
`docs/product-thesis.md`, `docs/roadmap.md`, `docs/features-and-capabilities.md`, and `docs/recommendation-methodology.md` all point to the same target:
- inspectable
- reproducible
- honest about degraded inputs
- operator-first
- not claim predictive edge prematurely

That part is solid.

### 2. Canonical contracts are improving
The following are now reasonably aligned:
- `EffectivePlanOutcome`
- `PlanReliabilityReport`
- `TradeDecisionPolicy`
- `SettingsDomainService` / `SettingsMutationService`
- broker workbench / research workbench read models

This is the right shape.

### 3. Tests cover many important specs
There is real coverage around:
- routes
- repositories
- plan evaluation
- calibration
- signal gating
- plan generation tuning
- order execution
- summary service
- context services
- ticker analysis

So this is not a spec-only system; a lot of the spec is actually encoded.

---

## Main inconsistencies / weak points

### 1. Canonical docs still mix “current state” and “future state”
The docs index says shipped features should live in current-state docs and roadmap language should be removed. But several canonical docs still contain:
- “still needed”
- “not yet fully aligned”
- “in progress”
- “future migrations”

That’s not fatal, but it makes the spec set heavier and less crisp than it should be.

### 2. `RecommendationPlan` is still overloaded
The simplification plan explicitly wants:
- `RecommendationPlan`
- `ExecutionCandidate`
- `EffectivePlanOutcome`
- `PlanReliabilityFeatures`

That means `RecommendationPlan` is still doing too much work conceptually. It’s better than before, but still not as clean as the spec claims it should become.

### 3. Plan resolution semantics are not fully reconciled
`docs/recommendation-plan-resolution-spec.md` says scheduled evaluation should process only open plans, while the architecture/refactor docs admit legacy behavior still exists in some paths.

So: **the canonical target is clear, but the code is not fully there yet**.

### 4. News/replay provider behavior is still incomplete
`docs/news-provider-reliability-spec.md` explicitly excludes topic-query retry policy, and `recommendation-methodology.md` admits topic-query providers do not yet share the same retry path.

That’s a real gap for a system that depends heavily on news context.

### 5. Context extraction is still heuristic-heavy
The specs repeatedly admit:
- event extraction is heuristic
- contradiction detection is heuristic
- context quality is bounded and imperfect

That’s honest, but it means the “macro/industry intelligence” layer is still fragile. It is useful, not decisive.

### 6. Broker risk v1 is still shallow for autonomous trading
`docs/broker-risk-management-spec.md` is explicit:
- no Alpaca account-level reconciliation
- no unrealized P&L
- no automatic liquidation/cancel on halt

For a system aiming at autonomous execution, this is a major limitation.

### 7. Observability is still weaker than the product complexity
Both architecture and roadmap docs say:
- logs are not structured enough
- daemon health is not surfaced well enough
- cross-process diagnosis is still hard

That is a serious weakness for a multi-process trading system.

---

## Redundancy / over-engineering

### Biggest redundancy: too many overlapping “truth” layers
You now have separate concepts for:
- outcome truth
- effective outcome truth
- policy evaluation truth
- reliability truth
- calibration truth
- quality-summary truth

They are all defensible individually, but together they create a lot of cognitive load.

### Likely over-engineered areas
- `RecommendationPlan` + `RecommendationDecisionSample` + `RecommendationPlanOutcome` + effective outcomes
- `PlanReliabilityReportService` + `TradePolicyEvaluationService` + calibration/report/baseline services
- `SettingsRepository` + `SettingsDomainService` + `SettingsMutationService`
- multiple backend workbenches to hide frontend stitching

These abstractions are useful, but there are too many of them for a product that still lacks proven edge.

### Docs are also somewhat over-specified
Several docs define:
- exact thresholds
- exact labels
- exact field semantics
- exact slice names

That helps testing, but it also creates maintenance burden and drift risk.

---

## Code/tests vs specs

### Good alignment
The codebase and tests appear strongly aligned with:
- broker/effective outcome precedence
- calibration/reporting
- policy evaluation
- tuning workflows
- UI read models
- summary/runtime fixes
- context and watchlist behavior

### Gaps
The main missing confidence is around:
- end-to-end autonomous execution behavior
- replay vs live news correctness across all provider types
- structured observability
- broker-account reconciliation
- fully consistent plan-resolution semantics

So the suite is **good at proving local contracts**, weaker at proving **whole-system trading behavior**.

---

## Is it effective for the stated goal?
**Partially.**

It is effective for:
- operator review
- diagnostics
- calibration
- research
- making the system safer and more inspectable

It is **not yet effective as proof of a winning autonomous trading edge**.

That distinction matters: the specs are currently better at building a trustworthy research/operator platform than a profitable autonomous trader.

---

## My verdict
- **Spec coherence:** 7.5/10
- **Code/spec coherence:** 6.5/10
- **Lean design:** 4.5/10
- **Readiness for autonomous profit:** 3/10

---

## Highest-value cleanup next
1. Finish reconciling plan resolution semantics.
2. Collapse overlapping quality/policy/report abstractions where possible.
3. Improve observability and broker reconciliation.
4. Tighten topic-query/news-provider reliability.
5. Trim docs so canonical current-state docs stop repeating roadmap language.

If you want, I can turn this into a **prioritized remediation list** with exact files and a recommended order.
