# Evidence and tuning operations runbook

**Status:** current operator workflow

This is the single entry point for Aurelio evidence repair, tuning, phantom selectivity, upstream signal-quality audits, and prospective monitoring.

Use this document before running any large search or interpreting any tuning report. The goal is to avoid rediscovering the same process from scattered specs, commits, scripts, and artifact files.

## Current state

The plan-generation tuning layer is on hold.

The app does not yet have a deployable money-winning tuning. Broad threshold searches did not find a stable candidate. The only active lead is a research-only phantom-selectivity policy that looked positive across 15 selection dates, below the 20-date promotion gate.

Do not run another broad large tuning search just because evidence exists. Follow the workflow below.

## Weekly performance report

The standing weekly report is called the **weekly performance report**.

Schedule:

- every Saturday at 04:00 UTC;
- run from the main deployed Docker Compose environment;
- post the summary back to the operator chat;
- archive every generated artifact under a dated folder.

Artifact archive folder:

```text
.prod-run/workers/artifacts/weekly-performance-report/YYYY-MM-DD/
```

The weekly report must include:

- tag monitor verdict and top blockers;
- whether prospective tags are absent, accumulating, or ready for review;
- evidence date-window alignment: prospective tagged plans, replay-labeled tagged plans, phantom-selectivity eligible records, and candidate replay discovery/selection windows;
- replay freshness status, including whether newer tagged plans are flowing into phantom-selectivity replay eligibility;
- candidate replay split math: total eligible dates, selection fraction, current selection date count, promotion date gate, and estimated total eligible dates needed;
- phantom separability verdict if run;
- candidate replay verdict if run;
- candidate replay concentration cautions, split into broad reusable feature candidates and ticker-specific candidates;
- discovery-vs-selection baseline drift cautions;
- upstream audit/drilldown verdicts if run;
- performance read: what improved, what weakened, what is still unproven;
- concrete improvement proposals;
- explicit stop/go decision for tuning;
- exact artifact folder path.

Report style:

- concise;
- ordered by decision importance;
- no raw JSON dump;
- mention only the artifact paths needed to resume;
- call out when evidence is too thin instead of dressing it up.

If the tag monitor reports `no_prospective_tagged_evidence` or `prospective_tags_accumulating`, the weekly report may stop after the monitor and should not run the full audit chain unless there is a clear reason.

## Golden rule

Every tuning action must answer one question:

> Is there enough clean, time-spread, out-of-sample evidence to justify changing behavior?

If the answer is no, stop searching and either wait for more evidence or improve upstream signal generation.

## Evidence classes

- `promotion`: closed intraday `win`, `loss`, `flat` rows only. This is the only evidence class that can support deployable plan-generation tuning.
- `phantom_selectivity`: intraday `phantom_win`, `phantom_loss` rows. Research-only. Use it to find missed-opportunity/selectivity leads, not to promote behavior directly.
- `research`: broad replay diagnostics. Useful for repair and investigation, not promotion.
- pending/open/daily/cache-gap rows: repair queue only.

## Stop conditions

Stop and do not run more searches when any of these are true:

- promotion evidence has fewer than 20 selection dates or no locked holdout;
- a phantom/selectivity search returns baseline/no-op after stability screening;
- candidate replay is positive but below the date gate;
- a lead is ticker-concentrated and not reusable across dates/tickers;
- the prospective tag monitor says `no_prospective_tagged_evidence` or `prospective_tags_accumulating`.

## Resume criteria for tuning

Resume plan-generation tuning only when at least one condition is true:

- strict promotion-grade replay evidence has at least 20 selection dates and enough closed intraday rows;
- the six-group phantom-selectivity policy reaches at least 20 selection dates in candidate replay;
- the upstream signal model materially changes and phantom separability needs a fresh audit;
- the prospective tag monitor reports `prospective_tags_ready_for_review`.

## Canonical workflow

### 1. Check prospective upstream tags first

Run this after new recommendations and replay labels have accumulated:

```bash
docker compose exec -T api sh -lc 'python scripts/monitor_upstream_signal_driver_tags.py \
  --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-tag-monitor-latest.json'
```

Read:

- `verdict`
- `record_counts.tagged_plans`
- `record_counts.replay_labeled_tagged_plans`
- each tag `tag_verdict`
- each tag `blockers`
- `phantom_outcome_metrics`

Decisions:

- `no_prospective_tagged_evidence`: wait for new plans generated after commit `4780cfd9`.
- `prospective_tags_accumulating`: keep collecting evidence and replay labels.
- `prospective_tags_ready_for_review`: inspect tag cohorts and then rerun upstream/phantom audits.

Do not change scoring from tag monitor output alone.

Do not read `promotion_watchable` as positive evidence. It means a tag has enough coverage for review. If phantom expected value is negative, say that plainly.

### 2. If tags are ready, rerun phantom separability

```bash
docker compose exec -T api sh -lc 'python scripts/audit_phantom_selectivity_separability.py \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json'
```

Read:

- `verdict`
- `candidate_specific_replay_recommended`
- `record_counts`
- `date_counts`
- `date_windows`
- `selection_split`
- `baseline_shift`
- `candidate_group_count`
- `blockers`

Decisions:

- If `candidate_specific_replay_recommended=false`, stop. Do not tune this layer.
- If candidate groups are mostly ticker-only, treat as upstream diagnosis, not general policy.
- If candidate groups pass discovery-first and selection gates, run candidate replay.

### 3. Replay candidate phantom policies

```bash
docker compose exec -T api sh -lc 'python scripts/replay_phantom_selectivity_candidates.py \
  --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/phantom-selectivity-candidate-replay-latest.json'
```

Proceed only when the report has:

- `promotion_candidate_ready=true`
- selection rows at least 100
- selection distinct dates at least 20
- `selection_split`
- `baseline_shift`
- broad feature candidates versus ticker-specific candidates
- combined union with and without ticker-only groups
- concentration warnings
- positive selection EV/observation
- win rate above selection baseline
- no single ticker/date/setup dominating the result

If the candidate replay is positive but below date coverage, keep it research-only and wait.

If prospective tagged evidence is newer than phantom-selectivity candidate replay evidence, do not assume waiting alone will fix the date gate. Run the evidence lineage audit and verify that new tagged plans are entering replay eligibility.

### Evidence lineage audit

Use this when a weekly report shows fresh prospective tags but stale or thin candidate replay evidence:

```bash
docker compose exec -T api sh -lc 'python scripts/audit_evidence_lineage.py \
  --artifact /app/.prod-run/workers/artifacts/evidence-lineage-latest.json'
```

Read:

- `freshness_alignment.verdict`
- latest prospective tag date
- latest replay-labeled tag date
- latest phantom-selectivity eligible date
- lag in calendar days
- artifact-version pass/fail counts
- replay tier, resolution source, and outcome mixes

Decisions:

- `aligned`: new tagged evidence is represented in replay eligibility.
- `tagged_ahead_of_replay`: prospective tags are fresher than candidate replay evidence. Investigate replay labeling or eligibility generation.
- `replay_stale_or_filtered`: replay rows exist but are being filtered out by tier, resolution source, outcome class, or artifact version.
- `no_tagged_evidence` / `no_phantom_selectivity_evidence`: wait or repair the missing evidence source.

### 4. Audit upstream signal drivers

Use this when candidate replay is research-positive or separability finds leads that need explanation:

```bash
docker compose exec -T api sh -lc 'python scripts/audit_upstream_signal_drivers.py \
  --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-audit-latest.json'
```

Read:

- `verdict`
- `top_reusable_candidate_win_loss_drivers`
- `ticker_diagnostics`
- `reusable_signal_feature_coverage_percent`

Decisions:

- `upstream_feature_lead`: drill down concrete drivers.
- `ticker_artifact_only`: do not generalize; inspect ticker-specific generation.
- `insufficient_feature_coverage`: improve instrumentation before searching.

### 5. Drill down upstream drivers

```bash
docker compose exec -T api sh -lc 'python scripts/drilldown_upstream_signal_drivers.py \
  --separability-artifact /app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json \
  --upstream-audit-artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-audit-latest.json \
  --replay-tier tier_a \
  --artifact /app/.prod-run/workers/artifacts/upstream-signal-driver-drilldown-latest.json'
```

Read:

- `verdict`
- each driver `driver_verdict`
- driver metrics
- ticker concentration
- setup/action/context mix
- example phantom wins and losses

Decisions:

- `reusable_driver_leads`: inspect generation code and instrument future rows.
- `ticker_concentrated_driver_leads`: do not change broad policy.
- `thin_driver_evidence`: wait or improve feature persistence.

### 6. Only then consider behavior changes

Behavior changes are allowed only after evidence passes the gates above.

Allowed next changes:

- conservative upstream signal-generation constraints;
- better feature persistence/explainability;
- candidate-specific shadow policy tagging;
- no-action/watchlist conversion research.

Not allowed from current evidence:

- broad actionability threshold changes;
- broad confidence weight changes;
- promotion from phantom labels alone;
- another large search over the same historical rows.

## Current July 2026 facts

Known current state:

- strict promotion-grade evidence was too thin: 164 closed intraday win/loss rows;
- broad tier-A phantom evidence was large: about 16k rows;
- simple actionability search failed;
- expanded phantom selectivity research search failed;
- strict separability found six candidate groups;
- candidate replay was positive but research-only;
- promotion blocker: 15 selection dates, below the 20-date gate;
- upstream driver drilldown found reusable leads;
- prospective driver tags were added in commit `4780cfd9`;
- prospective tag monitor was added in commit `e2c71bd9`;
- live monitor immediately after deployment reported `no_prospective_tagged_evidence`, which is expected until new plans are generated.

## Important documents

- `docs/phantom-selectivity-tuning-hold-2026-07-17.md` — detailed July 2026 hold/resume record.
- `docs/specs/large-parameter-search-spec.md` — large search contract and evidence profiles.
- `docs/specs/phantom-selectivity-separability-spec.md` — phantom separability and candidate replay contract.
- `docs/specs/upstream-signal-driver-audit-spec.md` — upstream driver audit, drilldown, tags, and monitor contract.
- `docs/operational-scripts-reference.md` — script reference.

## Important scripts

- `scripts/large_plan_generation_parameter_search.py`
- `scripts/audit_phantom_selectivity_separability.py`
- `scripts/replay_phantom_selectivity_candidates.py`
- `scripts/audit_upstream_signal_drivers.py`
- `scripts/drilldown_upstream_signal_drivers.py`
- `scripts/monitor_upstream_signal_driver_tags.py`

Use Docker Compose for database-backed scripts unless a local environment is explicitly configured:

```bash
docker compose exec -T api sh -lc 'python scripts/<script>.py ...'
```

## Artifact discipline

The artifact directories contain many historical files. Do not browse them as the workflow.

Use stable `*-latest.json` names for current reruns:

- `/app/.prod-run/workers/artifacts/upstream-signal-driver-tag-monitor-latest.json`
- `/app/.prod-run/workers/artifacts/phantom-selectivity-separability-latest.json`
- `/app/.prod-run/workers/artifacts/phantom-selectivity-candidate-replay-latest.json`
- `/app/.prod-run/workers/artifacts/upstream-signal-driver-audit-latest.json`
- `/app/.prod-run/workers/artifacts/upstream-signal-driver-drilldown-latest.json`

Use dated artifact names only for immutable milestones that must be referenced later.

When a new artifact matters, record it in this runbook or the hold document. Otherwise it is disposable evidence.

For the weekly performance report, write all generated artifacts into the weekly archive folder first. If a latest artifact is also useful, copy or regenerate it with the stable `*-latest.json` name after the dated archive artifact exists.

## Quick decision table

| Report | Good verdict | Bad or wait verdict | Next action |
| --- | --- | --- | --- |
| prospective tag monitor | `prospective_tags_ready_for_review` | `no_prospective_tagged_evidence`, `prospective_tags_accumulating` | Wait or rerun separability |
| phantom separability | `candidate_replay_recommended` | stop/blocked verdicts | Candidate replay |
| candidate replay | `promotion_candidate_ready=true` | `research_candidate_only` | Promotion preflight or wait |
| upstream driver audit | `upstream_feature_lead` | `ticker_artifact_only`, `insufficient_feature_coverage` | Drilldown or instrument |
| upstream driver drilldown | `reusable_driver_leads` | `ticker_concentrated_driver_leads`, `thin_driver_evidence` | Inspect code or stop |

## What not to forget

- Tuning is not the same as signal quality.
- Phantom evidence is research-only.
- Positive EV on 15 selection dates is not deployable.
- A report without an explicit gate decision should not change behavior.
- If a workflow is not in this runbook, it is not an operating workflow yet.
