# Redesign

This area contains the new target architecture for evolving the app from a sentiment-oriented analysis tool into a short-horizon recommendation engine.

Across these docs, the redesign should be interpreted realistically: near-term the product is becoming a stronger operator-facing analysis, candidate-ranking, and trade-framing system. Broader predictive claims should follow only after recommendation outcomes and confidence calibration show measurable evidence of edge.

## Documents

### 1. Principles
- `principles.md`
- Core product principles, including observability, trust, no hidden fallbacks, and practical recommendation standards.

### 2. Target architecture
- `target-architecture.md`
- High-level system design across context, exposure, ticker setup, and trade-plan construction.

### 3. Data model and persistence
- `data-model-and-persistence.md`
- Proposed PostgreSQL-backed storage model, major entities, and schema direction.

### 4. Migration plan
- `migration-plan.md`
- Phased path from the current sentiment-oriented implementation to the new saliency-first architecture.

### 5. Transmission modeling spec
- `transmission-modeling-spec.md`
- Concrete rules for mapping macro and industry context into ticker-level exposure, transmission bias, conflict handling, and timing windows.

### 6. Calibration governance spec
- `calibration-governance-spec.md`
- Rules for sample-aware, operator-visible use of outcome history in action gating and calibration review.

### 7. Setup family playbook
- `setup-family-playbook.md`
- Concrete setup-family expectations for entry, invalidation, take-profit, context interaction, and evaluation.

### 8. Measured success criteria
- `measured-success-criteria.md`
- Defines what counts as redesign success beyond shipping more schemas, heuristics, or UI.

### 9. Legacy convergence plan
- `legacy-convergence-plan.md`
- Defines how and when the app should narrow or retire remaining legacy sentiment/recommendation paths.

### Full combined reference
- `short-horizon-recommendation-architecture.md`
- Full consolidated design document containing all sections together.

## Summary

The redesign centers on four ideas:

1. **Macro context** should identify salient market-moving developments.
2. **Industry context** should combine macro transmission with industry-native developments.
3. **Ticker analysis** should estimate short-horizon swing setups and classify setup families where possible.
4. **Recommendation plans** should be practical trade plans with entry, take profit, stop loss, horizon, confidence, and explicit warnings.

## Operating rules

Across all redesign work, the app should preserve these rules:

- no hidden fallbacks
- explicit degraded states
- structured warnings
- clear source provenance
- no false confidence
