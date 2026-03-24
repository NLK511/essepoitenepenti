# Redesign

This area contains the new target architecture for evolving the app from a sentiment-oriented analysis tool into a short-horizon recommendation engine.

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

### Full combined reference
- `short-horizon-recommendation-architecture.md`
- Full consolidated design document containing all sections together.

## Summary

The redesign centers on four ideas:

1. **Macro analysis** should identify salient market-moving developments.
2. **Industry analysis** should combine macro transmission with industry-native developments.
3. **Ticker analysis** should estimate short-horizon swing setups.
4. **Recommendations** should be practical trade plans with entry, take profit, stop loss, horizon, confidence, and explicit warnings.

## Operating rules

Across all redesign work, the app should preserve these rules:

- no hidden fallbacks
- explicit degraded states
- structured warnings
- clear source provenance
- no false confidence
