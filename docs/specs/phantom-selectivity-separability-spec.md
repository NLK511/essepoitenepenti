# Phantom selectivity separability spec

**Status:** current and target behavior

The replay system now exposes a large `phantom_selectivity` evidence pool, but bounded threshold searches have not produced a stable candidate. Before running more tuning searches, the app must answer a simpler question: are `phantom_win` rows distinguishable from `phantom_loss` rows using already stored plan evidence?

## Goal

Produce a read-only audit artifact that decides whether phantom selectivity evidence is separable enough to justify candidate-specific replay, or whether this tuning layer should stop until upstream signal generation changes.

## Rules

- The audit must be read-only. It must not mutate tuning config, replay rows, broker settings, jobs, or orders.
- The audit must use replay evidence profile `phantom_selectivity` by default: intraday `phantom_win` and `phantom_loss` rows from accepted replay tiers.
- The audit must split evidence chronologically into discovery and selection partitions before ranking groups.
- A group is useful only if it first looks usable in discovery, then confirms in selection. It must have enough discovery and selection samples, enough distinct selection dates, positive discovery and selection expected value, and a selection win rate that beats the global selection baseline.
- Expected value must use stored candidate trade geometry, not fake +1/-1 labels.
- The artifact must report the global baseline, per-feature separability summaries, top groups, blockers, and a direct verdict.
- The audit must not recommend another large threshold search. If separability exists, the next step is candidate-specific replay for the concrete group/rule. If separability does not exist, the next step is to stop tuning this layer until upstream features or signal generation change.

## Feature groups

The first implemented audit uses only stored, rescore-safe features already present in replay-backed tuning records:

- setup family
- ticker
- context bias
- plan action
- intended/effective action
- confidence bucket
- cheap-scan volatility bucket
- reward/risk bucket
- risk bucket
- reward bucket

Features that are not reliably loaded into replay tuning records must not be guessed.

## Verdicts

- `candidate_replay_recommended` — at least one group passes the selection gates. The artifact must list candidate groups for canonical candidate-specific replay.
- `stop_threshold_search` — no group passes the gates. Further threshold or floor searches over the same stored phantom evidence are not justified.
- `thin_evidence` — the audit lacks enough phantom rows or selection dates to make a call.

Default gates:

- total rows: at least 500
- selection distinct dates: at least 10
- discovery group samples: at least 100
- selection group samples: at least 30
- selection group distinct dates: at least 5
- discovery expected value per observation: greater than 0
- discovery win-rate lift over global discovery baseline: at least 0 percentage points
- selection win-rate lift over global selection baseline: at least 5 percentage points
- selection expected value per observation: greater than 0

## Candidate policy replay

When separability recommends candidate replay, the replay must evaluate concrete group rules from the separability artifact. This is still read-only until a later operator-approved persistence step.

For selectivity candidates, replay means: take only intraday `phantom_win` and `phantom_loss` rows selected by a candidate group, treat them as rows the candidate policy would have emitted, and score them as closed candidate outcomes using the stored intraday-resolved trade geometry. This does not rerun cheap scan, deep analysis, or broker execution.

The replay artifact must include:

- one result per candidate group;
- one combined union result across candidate groups;
- discovery and selection metrics;
- selected-row counts and distinct-date counts;
- expected value from stored reward/risk geometry;
- a promotion-readiness verdict.

The combined union must de-duplicate only the same observation selected by multiple candidate groups. It must not collapse distinct same-day rows that share ticker, setup family, confidence, reward/risk, and outcome.

Promotion readiness requires:

- selection rows: at least 100
- selection distinct dates: at least 20
- selection expected value per observation: greater than 0
- selection win rate above the selection baseline from the separability artifact

If these gates fail, the result is a research candidate only. The next step is either more candidate replay dates/evidence or upstream signal improvement, not another broad threshold search.
