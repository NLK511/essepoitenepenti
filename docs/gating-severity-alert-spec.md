# Gating severity alert spec

**Status:** implemented weekly observability monitor, scheduled job, dashboard banner, and Quality & Edge breakdown

## Goal

Detect when shortlist/signal gating may be too severe before the app silently spends days producing no actionable trades.

The alert is diagnostic. It must not automatically lower thresholds or promote tuning configs.

## Alert inputs

Use recent `recommendation_decision_samples` over a configurable rolling window, default 7 days. The default scheduled job runs once per week on Saturday at 05:00 UTC and reviews the previous 7 days.

Key signals:

- total decision samples
- shortlisted vs non-shortlisted count
- near-miss non-shortlisted count
- high-priority non-shortlisted count
- non-shortlisted samples with positive confidence gap
- generated actionable plan count
- benchmark coverage for non-shortlisted samples

## Severity rules

Emit `decision_gating.severity_check` as an observability event. The default job is `Auto: Gating Severity Check Weekly` with cron `00 05 * * SAT`.

- `info`: enough activity and no severe-gating symptoms.
- `warning`: possible severe gating, e.g. many high-confidence or near-miss candidates are not shortlisted.
- `critical`: possible severe gating plus zero actionable plans in the same window.

The monitor should report insufficient benchmark coverage separately because severe-gating suspicion is not proof of missed profit until non-shortlisted benchmarks resolve.

## Required operator interpretation

A warning/critical event means:

1. review non-shortlisted near-miss examples,
2. evaluate/resolve benchmark outcomes,
3. run signal-gating tuning dry-run,
4. only relax gates if benchmark/walk-forward evidence supports it.

It does **not** mean thresholds should be lowered immediately.

## UI exposure

- The dashboard shows a severity banner when the latest alert is `warning` or `critical`.
- The dashboard performance badge includes the latest gating severity.
- The Quality & Edge page shows the full latest alert breakdown: sample counts, shortlist rate, rejected near misses, high-priority rejects, positive-gap rejects, benchmark coverage, actionable plans, reasons, and alert window.
