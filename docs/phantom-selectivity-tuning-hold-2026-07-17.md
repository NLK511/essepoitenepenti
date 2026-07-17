# Phantom selectivity tuning hold - 2026-07-17

## Status

This activity is on hold.

The tuning layer is not proven deployable. Broad parameter and threshold searches should stop until more time-spread candidate replay evidence exists.

The work did not prove that the app can win money. It did find a narrow research lead: a six-group phantom-selectivity policy has strongly positive candidate replay metrics, but only across 15 selection dates. The promotion gate remains 20 selection dates, so this is research-only.

## Why the work started

Replay/evaluator repair increased resolved evidence, but promotion-grade closed trade evidence stayed too thin:

- broad tier-A replay evidence was large;
- strict closed-trade promotion evidence was tiny;
- most high-quality tier-A rows were `phantom_win`, `phantom_loss`, or `expired`, not real closed trade rows.

That meant stop/take-profit geometry tuning from real closed trades was not justified. The better question became: can phantom winners be separated from phantom losers well enough to convert missed opportunities into real candidate trades?

## Commits in this phase

- `9a24a6fb` - Tighten replay evidence for large search
- `362244cc` - Add phantom selectivity replay search profile
- `b2ec896c` - Score phantom selectivity evidence by actionability
- `8f5df642` - Broaden phantom selectivity research search
- `4935d8a6` - Add phantom selectivity separability audit
- `0e97ea2e` - Add phantom selectivity candidate replay

Related earlier evaluator/evidence repair commits:

- `023f6a95` - Speed up replay outcome refresh
- `375132b4` - Stage replay refresh price history loading
- `b0313b2b` - Let large search use replay evidence

## What changed

### Evidence profiles

Large search now separates replay evidence by purpose:

- `promotion` - closed intraday `win`, `loss`, `flat` only.
- `phantom_selectivity` - intraday `phantom_win`, `phantom_loss` only; research-only.
- `research` - broad replay diagnostics.

Replay-backed large search defaults to promotion-grade evidence and labels phantom work as research-only.

### Preflight gates

Large search artifacts now report:

- evidence source/profile;
- eligible counts;
- discovery/selection/locked-holdout record counts;
- distinct-date counts;
- whether promotion search is possible;
- whether candidate-specific replay is required.

If evidence is thin, the run is downgraded to research instead of pretending promotion is possible.

### Phantom scoring

The first phantom diagnostic exposed a scorer bug: phantom rows were being scored as ambiguous because the normal scorer expected closed trade labels and execution-floor semantics.

The fix:

- `phantom_win` / `phantom_loss` are scored directly as research labels.
- `global.actionable_confidence_floor_percent` is used instead of the execution floor.
- EV still comes from stored adjusted reward/risk geometry.
- Walk-forward and stability scoring receive the replay evidence profile instead of silently falling back to normal closed-trade scoring.

### Expanded phantom selectivity search

`phantom_selectivity_research` was added as a separate campaign. It varies only rescore-safe knobs:

- global actionability floor;
- setup-family research floor delta;
- tailwind floor delta;
- headwind floor delta;
- volatility floor slope.

This avoided broad all-knobs searching and kept the path research-only.

### Separability audit

`scripts/audit_phantom_selectivity_separability.py` was added.

It checks whether `phantom_win` rows differ from `phantom_loss` rows using stored features:

- ticker;
- setup family;
- context bias;
- action/effective action;
- confidence bucket;
- volatility bucket;
- reward/risk bucket;
- risk bucket;
- reward bucket.

The first audit version found groups that only looked good in selection. That was selection leakage risk. The audit was tightened so groups must be positive in discovery first, then confirm in selection.

### Candidate policy replay

`scripts/replay_phantom_selectivity_candidates.py` was added.

It replays concrete candidate groups from the separability artifact as if the candidate policy had emitted those phantom rows as trades. It remains read-only and artifact-only. It does not mutate active config, replay eligibility, broker settings, or orders.

## Key artifacts

- `.prod-run/workers/artifacts/large-search-phantom-selectivity-diagnostic-20260717-fixed.json`
- `.prod-run/workers/artifacts/large-search-phantom-selectivity-expanded-20260717.json`
- `.prod-run/workers/artifacts/phantom-selectivity-separability-20260717-strict.json`
- `.prod-run/workers/artifacts/phantom-selectivity-candidate-replay-20260717.json`

## Results

### Promotion evidence preflight

Strict promotion-grade replay evidence was too thin:

- promotion-grade rows: 164
- discovery: 118 records across 18 dates
- selection: 46 records across 5 dates
- locked holdout: 0 records across 0 dates
- blockers:
  - `selection_distinct_dates_below_minimum`
  - `insufficient_dates_for_locked_holdout`

Conclusion: a serious large tuning search over promotion evidence was not justified.

### Phantom selectivity threshold search

Bounded `phantom_selectivity + selectivity_only` search:

- eligible phantom rows: 16,226
- discovery: 13,180 rows across 46 dates
- selection: 3,046 rows across 12 dates
- final best: baseline/no-op
- improvement finalists: 0

Conclusion: changing only the global actionability floor did not produce a better candidate.

### Expanded phantom selectivity search

Bounded `phantom_selectivity + phantom_selectivity_research` search:

- eligible phantom rows: 16,226
- discovery: 13,180 rows across 46 dates
- selection: 3,046 rows across 12 dates
- broad discovery evaluated 1,212 unique candidates
- stability screen evaluated 200 survivors
- stability survivors: 1
- final best: baseline/no-op
- improvement finalists: 0

Conclusion: broader rescore-safe selectivity knobs did not produce a stable search candidate.

### Strict separability audit

Strict discovery-first separability audit:

- verdict: `candidate_replay_recommended`
- usable phantom rows: 16,226
- discovery: 11,874 rows across 43 dates
- selection: 4,352 rows across 15 dates
- passing groups: 6

Passing groups:

| Group | Discovery WR | Selection WR | Selection EV/obs | Selection rows | Selection dates |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ticker=HUM` | 73.5% | 81.8% | 2.5577 | 33 | 5 |
| `ticker=PANW` | 67.8% | 78.2% | 3.6720 | 78 | 12 |
| `ticker=AMAT` | 51.5% | 50.0% | 0.6564 | 48 | 8 |
| `ticker=ORCL` | 50.3% | 60.8% | 2.1557 | 74 | 12 |
| `confidence_bucket=45-50` | 41.1% | 57.5% | 1.3859 | 214 | 13 |
| `ticker=LRCX` | 39.3% | 65.1% | 2.8883 | 86 | 8 |

Conclusion: the layer is not dead. There is narrow separability, mostly ticker-specific plus one low-confidence bucket.

### Candidate policy replay

Candidate replay over the six groups:

- verdict: `research_candidate_only`
- promotion ready: false
- combined union selection rows: 488
- combined union selection dates: 15
- combined union win rate: 66.80%
- combined union EV: 1188.6389
- combined union EV/observation: 2.4357
- win-rate lift over selection baseline: +23.88 percentage points
- blocker:
  - `selection_dates_below_promotion_minimum`

Conclusion: the six-group policy is promising but not deployable. The blocker is time-spread evidence, not another threshold parameter.

## Current decision

Stop broad tuning searches for this layer.

Do not run another large search over:

- actionability floor;
- phantom selectivity floor modifiers;
- context/volatility/setup threshold combinations.

These have already failed to produce a stable candidate.

Do not promote the six-group policy yet. It has only 15 selection dates. The gate remains at least 20 selection dates.

## Resume criteria

Resume this activity only when at least one of these is true:

1. New replay/candidate evidence extends the six-group policy to at least 20 selection dates.
2. More historical intraday coverage can be added and replayed for the same six-group policy.
3. The upstream signal model changes materially enough that phantom separability should be audited again.

When resuming, do this first:

```bash
docker compose exec -T api sh -lc 'python scripts/audit_phantom_selectivity_separability.py \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-resume.json'
```

Then replay the candidates:

```bash
docker compose exec -T api sh -lc 'python scripts/replay_phantom_selectivity_candidates.py \
  --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-resume.json \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-candidate-replay-resume.json'
```

Proceed only if candidate replay reports:

- `promotion_candidate_ready=true`;
- selection rows at least 100;
- selection distinct dates at least 20;
- positive selection EV/observation;
- selection win rate above baseline.

If candidate replay still fails after enough dates, call this tuning layer exhausted and move upstream.

## Upstream quality improvement handoff

The next work should focus upstream, not on tuning thresholds:

- improve signal generation features that separate winners from losers before actionability;
- inspect why profitable candidate groups are mostly ticker-specific;
- add richer durable features to replay records, such as sector, regime, catalyst tags, market regime, and signal-source contributions;
- improve plan generation so candidate actionability is driven by causal signal quality, not post-hoc ticker filters;
- keep the six-group policy as a research benchmark while upstream changes are evaluated.

The immediate upstream question:

> Why are `HUM`, `PANW`, `ORCL`, `LRCX`, `AMAT`, and the `45-50` confidence bucket separable in replay while the general policy is not?

Answering that is more likely to improve the bot than another tuning search.

