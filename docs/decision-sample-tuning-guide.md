# Decision sample tuning guide

**Status:** practical operator guide

This doc explains how to use `RecommendationDecisionSample` rows to tune the recommendation algorithm.

Decision samples are **review artifacts**, not the live trade decision itself. They help answer:

- was the planner too conservative?
- was it too permissive?
- did the ticker fail in shortlist selection or at the final plan gate?
- was the problem signal quality, calibration, or thresholding?

## What to inspect first

Start with these fields on each sample:

- `decision_type`
- `review_priority`
- `confidence_percent`
- `calibrated_confidence_percent`
- `effective_threshold_percent`
- `confidence_gap_percent`
- `shortlisted`
- `shortlist_rank`
- `shortlist_decision`
- `decision_reason`
- `setup_family`
- `transmission_bias`
- `context_regime`

## How to read the main signals

### `confidence_gap_percent`
This is usually the most useful tuning field.

Interpretation:
- near `0` = borderline
- positive = it cleared the gate
- negative = it missed the gate

Use it to detect whether the system is too strict or too loose.

### `decision_type`
Typical meanings:
- `actionable` — the system committed to `long` or `short`
- `near_miss` — close to becoming actionable
- `rejected` — shortlisted but not strong enough
- `no_action` — did not reach actionability
- `degraded` — input quality or availability was poor

### `review_priority`
This tells you where to spend human review time.

- `high` = inspect first
- `medium` = inspect if the pattern repeats
- `low` = lower priority

### `shortlisted` and `shortlist_decision`
These fields tell you whether the issue happened **before** the final trade decision.

Implementation status:
- **shortlisted samples** usually have a linked recommendation plan because downstream framing ran
- **non-shortlisted samples** may exist without any recommendation plan row because the ticker never reached downstream plan framing
- these discarded samples now also carry benchmark follow-through labels, so signal-gating tuning can detect missed opportunities even when no plan row was created
- the decision-samples page can filter benchmark `pending`, `hit`, `miss`, and `failed` rows so review can focus on follow-through labels before changing gates
- plan-linked outcomes still matter for stop-loss / take-profit truth, but decision-sample-only rows are no longer label-less audit records

If strong samples were never shortlisted, the problem is probably in:
- shortlist rules
- cheap-scan ranking
- lane selection

If they were shortlisted but not promoted, the issue is probably in:
- calibration
- thresholding
- final evidence quality

## Tuning playbook

### 1. Too many near-misses that look good
Likely the planner is too conservative.

Phantom trades now provide evidence: if `no_action` plans with an intended direction are producing `phantom_win` outcomes, the system is quantifiably missing profitable setups.

Possible actions:
- lower the threshold slightly
- reduce calibration penalty
- allow stronger shortlist lanes to promote borderline cases
- review whether one setup family deserves its own gate

### 2. Too many actionable plans look weak later
Likely the planner is too permissive.

Possible actions:
- raise the threshold
- tighten actionability requirements
- increase penalties for weak or conflicting evidence
- make degraded inputs less likely to pass

### 3. Lots of rejected samples with strong confidence
Likely shortlist selection is misweighted.

Possible actions:
- rebalance cheap-scan scores
- adjust shortlist promotion rules
- inspect whether one lane is crowding out another
- review whether confidence is being overestimated upstream

### 4. Lots of degraded samples
Likely this is a data-health issue, not a tuning issue.

Possible actions:
- fix missing market or news coverage
- reduce reliance on unstable inputs
- improve fallback handling
- keep degraded rows visible instead of blending them into normal cases

### 5. One setup family behaves differently from others
Likely global tuning is hiding family-specific behavior.

Possible actions:
- tune thresholds by setup family
- compare calibration slices by family
- check whether the family has different transmission behavior or evidence depth

## Recommended workflow

1. Filter to `near_miss` and `high` priority samples.
2. If a linked recommendation plan exists, open it. If not, stay on the signal / shortlist evidence because the ticker never reached downstream framing.
3. For signal-gating tuning defaults, prefer the sample window since the latest applied gating run so you are judging the currently active regime rather than an arbitrary newest-N slice.
4. Compare:
   - raw confidence
   - calibrated confidence
   - threshold
   - gap
   - shortlist decision
   - decision reason
5. Decide whether the problem is:
   - shortlist selection
   - calibration
   - thresholding
   - data quality
6. Change one lever at a time.

## Important rule

Do **not** treat decision samples as training labels that automatically define the right algorithm.

They are best used as a structured review layer for:

- threshold changes
- calibration changes
- shortlist rule changes
- degradation handling
- setup-family-specific adjustments

## Related docs

- `recommendation-methodology.md`
- `operator-page-field-guide.md`
- `raw-details-reference.md`
- `redesign/calibration-governance-spec.md`
