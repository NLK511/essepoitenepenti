# Upstream Decision Benchmarking Spec

**Status:** current shipped behavior
**Goal:** Provide a follow-through label for decision samples, especially early rejections that never reached trade framing.

## The Benchmark Logic

Every `RecommendationDecisionSample` is evaluated against historical price action starting from the signal timestamp.

### 1. Directional Context
- If the sample has an `action` of `long` or `short`, use that.
- If the sample is `no_action`, use the underlying signal direction as `benchmark_direction`.

### 2. Targets
- **1-Day Quick Move:** did price move **2%** in the favorable direction within 24 hours?
- **5-Day Trend:** did price move **5%** in the favorable direction within 5 days?

### 3. Evaluation Precision
- Use the best available historical bars for the ticker and signal time.
- Prefer intraday bars when present; fall back to daily bars when intraday coverage is missing.
- A hit is recorded if price touches the target percentage at any point within the window.

## Persistence

The decision sample record stores the benchmark fields so the tuning job can reuse them without recomputing everything on every run:

| Field | Type | Description |
|-------|------|-------------|
| `benchmark_direction` | String | The direction (long/short) being graded. |
| `benchmark_status` | String | `pending`, `evaluated`, or `failed` (for example, missing data). |
| `benchmark_target_1d_hit` | Boolean | True if the 2% move was reached in 1 day. |
| `benchmark_target_5d_hit` | Boolean | True if the 5% move was reached in 5 days. |
| `benchmark_max_favorable_pct` | Float | The maximum favorable excursion within 5 days. |
| `benchmark_evaluated_at` | DateTime | When the evaluation was performed. |

## Usage in Tuning

The **Signal Gating Tuning Service** treats these benchmarks as valid labels when plan outcomes are unavailable:
- A **"Missed Win"** is a rejected sample where the 1d or 5d benchmark target is hit in the signal direction.
- A **"Good Reject"** is a rejected sample where neither target is hit.
- The decision-samples page can surface `pending`, `evaluated-hit`, and `evaluated-miss` benchmark cohorts for operator review.
- A resolved `RecommendationPlanOutcome` still wins when it exists, because it carries the stop-loss / take-profit truth that benchmarks cannot capture.
