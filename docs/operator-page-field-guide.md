# Operator Page & Field Guide

**Status:** reference

Quick reference for navigating the app, reading main fields, and choosing the right page for an investigation. For terms use `glossary.md`; for payload detail use `raw-details-reference.md`; for methodology use `recommendation-methodology.md`.

## Product map

Main page groups:
- **Operate:** Dashboard, Jobs, Watchlists, Settings
- **Review:** Recommendation plans, Ticker signals, Ticker drill-down
- **Investigate:** Run debugger, Run detail, Broker Orders, Context review, Snapshot detail
- **Research:** Research overview, calibration/baseline/evidence pages, signal-gating tuning, plan-generation tuning

Simple mental model:
- Dashboard = what to check next
- Recommendation plans = actual trade plans
- Ticker signals = why a ticker got attention
- Run detail = how a workflow produced its outputs
- Context review = reusable macro/industry backdrop

## UI principles

Pages should support this journey: monitor → review → investigate → tune → administer.

Rules:
- one primary question per page
- summary first, detail on demand
- filters should stay lightweight
- raw diagnostics and secondary comparisons belong behind progressive disclosure
- never hide warnings, degraded inputs, provenance, or evaluated-vs-resolved distinctions
- mobile should use stacked cards/collapsible detail, not cramped desktop tables

## Common concepts

- **Status:** common values include `queued`, `running`, `completed`, `completed_with_warnings`, `failed`, `fresh`, `stale`, `expired`.
- **Direction:** signal bias such as `long`, `short`, neutral.
- **Action:** plan state such as `long`, `short`, `watchlist`, `no_action`.
- **Attention:** triage score for whether a ticker deserves deeper review; not plan confidence.
- **Confidence:** evidence-weighted trust/actionability estimate; not a guarantee.
- **Transmission:** how macro/industry context is believed to affect the ticker (`tailwind`, `headwind`, `mixed`, `unknown`).
- **Warnings:** stale context, thin coverage, provider failures, and contradictions are decision-relevant.
- **Time windows:** shared toggles are `1D`, `7D`, `1M`, `3M`, `6M`, `1Y`, `ALL`; `1D` starts at local midnight.

Context confidence/saliency bands:
- light: `<40` or `<0.40`
- moderate: `40–64.9` or `0.40–0.64`
- strong: `65–84.9` or `0.65–0.84`
- dominant: `85+` or `0.85+`

Research terms:
- **cohort:** comparison group, e.g. setup family or confidence bucket
- **segment:** subgroup by attribute, e.g. horizon or bias
- **bucket:** numeric range, usually confidence band
- **slice:** bounded cut of data, often a time window
- **promotion gate:** whether a tuning candidate may become live

Research reads:
- calibration asks whether confidence deserves trust
- baselines ask whether the workflow beats simpler alternatives
- evidence asks where results are strongest/weakest
- walk-forward asks whether a change still works later

## Page guide

### 1. Dashboard

Use for first-pass triage: plans waiting for review, recent runs, watchlists/jobs, context freshness, policy trust, broker/effective performance, actionability gap, and attention items.

Important nuance: `edge_validation_gate` is authoritative for autonomy; `policy_health` is only a compact headline. Policy-selected evidence uses the effective confidence threshold and excludes low-confidence paper-exploration records even if paper order execution relaxes actionability.

Use trendlines for the last seven daily snapshots. If freshness is degraded, go to Context review. If runs look bad, go to Run debugger.

### 2. Jobs

Use for creating/scheduling workflows.

Important fields: name, workflow type, schedule, manual tickers, watchlist, enabled.

Common workflow types: `proposal_generation`, `recommendation_evaluation`, `plan_generation_tuning`, `macro_context_refresh`, `industry_context_refresh`.

Prefer watchlist-backed proposal jobs over ad hoc ticker lists.

### 3. Watchlists

Use for reusable universes.

Important fields: name, region, exchange, timezone, default horizon, tickers, allow shorts, optimize evaluation timing.

Default horizon is the base time assumption for sourced plans.

### 4. Recommendation plans

Use for primary trade review.

Filters: ticker, action, run id, setup family, resolved/unresolved, outcome, stats window.

Main modes/tabs:
- Review queue
- Advanced analytics: Overview, Calibration, Baselines, Evidence, Setup families

Read tabs as:
- Calibration = do higher-confidence plans behave better?
- Baselines = does workflow beat simpler comparisons?
- Evidence = which cohorts are strongest/weakest?
- Setup families = which trade archetypes carry or hurt results?

Important fields: action, confidence, entry/stop/take-profit, horizon, thesis, action reason, setup family, raw/calibrated confidence and threshold, context bias/alignment/window, latest outcome, open/expired/win-rate stats.

Nuances:
- non-shortlisted names usually remain cheap-scan decision samples without full plan rows
- shortlisted names may still become `no_action` after deep analysis/policy gating
- only deep-analysis rejected plans with intended direction/levels can later produce phantom outcomes
- non-shortlisted names are hidden by default but can be revealed for audit coverage
- `expired` is horizon elapsed without terminal win/loss and is excluded from default win-rate denominators
- phantom outcomes are tuning/actionability evidence, not realized broker P&L

### 5. Ticker signals

Use for shortlist and pre-plan triage: why did a ticker get attention?

Important fields: mode, attention score, shortlisted, rank, lane, reasons, catalyst proxy, alignment, expected window, warnings.

Cheap-scan components include trend, momentum, and breakout scores.

### 6. Run debugger

Use for fast run triage. It shows recent runs, status, workflow type, timing, and summary counts. Use it to find failed/warning-heavy runs before opening Run detail.

### 7. Run detail

Use for full execution review of one run.

Tabs: Overview, Shortlist, Signals, Plans, Broker orders, Context.

Important fields: source kind, execution path, effective horizon, watchlist policy, shortlist limits/rejection reasons, signal/plan counts, created context objects.

Use it to answer why tickers/plans were rejected, whether context affected gating, and which broker orders were created/canceled/resubmitted.

### 8. Context review

Use to check reusable macro/industry backdrop.

Actions: queue macro refresh, queue industry refresh, reload.

Important fields: computed/expires, drivers, coverage, saliency, confidence, state/read badges, actor badges, diagnostics.

Use it when plans look plausible but backdrop seems stale, thin, or wrong. Current cards may show top theme/driver, escalation/easing/stabilizing/mixed state, fear/relief/inflation/growth read, and leading actor/trigger when recoverable.

### 9. Snapshot detail

Use for auditing one stored context snapshot.

Sections: summary, drivers, evidence/warnings, source mix, ontology context, diagnostics JSON.

Stored event rows may include persistence, transition, catalyst, interpretation, actor/role/source, and grounded “why now” text. Read this as a lower-level storage view.

### 10. Broker Orders

Use for Alpaca paper submissions, raw request/response payloads, manual resubmit/cancel, and broker steering history.

Important fields: status, run/plan id, entry/stop/take-profit, client/broker order ids, raw payloads, steering decision history, action buttons.

### 11. Settings

Use for setup, providers, ingestion controls, broker steering, and advanced research controls.

Check early when startup, provider health, or run quality looks off.

### 12. Ticker drill-down

Use to review one ticker over time via `/tickers/{ticker}` or ticker links.

Important fields: win rate, total profit, plan/order/bar counts, stored/actionable plans, wins/losses/open plans, average confidence, plan history, resolution source, and price chart overlays for entry/stop/take-profit/resolution.

Recommendation-quality entry-miss/actionability diagnostics are simulation-only setup/entry debugging aids, not broker-preferred P&L evidence.

Use the plan selection toggles and standard time windows (`1d`, `7d`, `1m`, `3m`, `6m`, `1y`, `all`).

### 13. In-app docs

Use for methodology and reference material inside the app.

## Which page should I use?

- First open: Dashboard → Settings/preflight if degraded → Recommendation plans
- Repeatable workflow: Watchlists → Jobs → Dashboard/Run debugger
- Why selected: Ticker signals → Run detail → Recommendation plans
- Trade ideas: Recommendation plans → Ticker drill-down → Run detail
- Stale backdrop: Context review → Snapshot detail → Settings/preflight
- Bad run: Run debugger → Run detail → Settings/preflight if systemic
- Confidence trust: Recommendation plans → Calibration/Baselines/Evidence

## Practical playbooks

Daily loop:
1. Dashboard
2. freshness/recent runs
3. Recommendation plans
4. Ticker signals for shortlist questions
5. Run detail for deeper investigation
6. queue evaluation later

Context-first loop:
1. Context review
2. refresh if stale
3. Jobs
4. review plans

Failure loop:
1. Run debugger
2. Run detail
3. review warnings and persisted objects
4. check Settings/preflight if broad

## Interpretation cautions

Do not over-read one confidence number, confuse attention with actionability, ignore stale context, or treat `watchlist`/`no_action` as failures.

## See also

- `glossary.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `raw-details-reference.md`
