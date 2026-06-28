# Operator Page & Field Guide

**Status:** reference

Quick reference for navigating the app, reading main fields, and choosing the right page for an investigation. For terms use `glossary.md`; for payload detail use `raw-details-reference.md`; for methodology use `recommendation-methodology.md`.

## Product map

Main page groups:
- **Operate:** Dashboard, Trade Review, Quality & Edge, Execution & Risk
- **Evidence & diagnostics:** Context review, Data quality, Run debugger, Run detail, Snapshot detail, Worker logs
- **Configure:** Watchlists, Jobs, Settings
- **Research Lab:** lab launcher, signal-gating tuning, plan-generation tuning, decision samples, candidate signals
- **Help:** Docs

Simple mental model:
- Dashboard = what needs attention now
- Trade Review = current plan/trade review queue
- Quality & Edge = authoritative edge/performance verdict
- Execution & Risk = broker safety, exposure, reconciliation, and order audit
- Context review = reusable macro/industry backdrop
- Data quality = provider/ticker input blockers
- Run debugger = fast run triage

## UI principles

Pages should support this journey: monitor → review trades → validate edge/risk → investigate only when needed → tune/administer.

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

Use for first-pass triage: safety, effective performance, input health, and work queue.

Important nuance: `edge_validation_gate` is authoritative for autonomy; `policy_health` is only a compact headline. Policy-selected evidence uses the effective confidence threshold and excludes low-confidence paper-exploration records even if paper order execution relaxes actionability.

Use trendlines only when comparing windows. If input health is degraded, go to Data quality or Context review. If runs look bad, go to Run debugger.

### 2. Trade Review

Use for primary plan/trade review. This page is a queue and plan-inspection surface, not the system-performance authority.

Filters: ticker, action, run id, setup family, resolved/unresolved, outcome, stats window.

Important fields: action, confidence, entry/stop/take-profit, horizon, thesis, action reason, setup family, raw/calibrated confidence, decision thresholds, context bias/alignment/window, latest outcome, run/plan links.

Nuances:
- non-shortlisted names usually remain cheap-scan decision samples without full plan rows
- shortlisted names may still become `no_action` after deep analysis/policy gating
- only deep-analysis rejected plans with intended direction/levels can later produce phantom outcomes
- `expired` is horizon elapsed without terminal win/loss and is excluded from default win-rate denominators
- phantom outcomes are tuning/actionability evidence, not realized broker P&L
- threshold labels must stay precise: upstream effective confidence controls selection evidence, while `effective_action_threshold_percent` is the downstream actionability gate shown in plan `decision_thresholds`

### 3. Quality & Edge

Use for the authoritative edge/performance verdict.

Read first:
- `edge_validation_gate` — autonomy/edge gate; authoritative
- policy health — compact headline only
- effective/broker outcome counts and win rate/P&L
- calibration, reliability, evidence concentration, setup-family stance
- next actions and walk-forward promotion state

Live tuning settings, latest narrative assessment, and simulation-only entry diagnostics are supporting details. Do not use Research Lab as a second performance authority.

### 4. Execution & Risk

Use for broker safety, exposure, reconciliation, Alpaca paper submissions, raw request/response payloads, and manual resubmit/cancel.

Important fields: risk state, kill switch, open/submitted/closing exposure, broker sync freshness, action-required orders, status, run/plan id, entry/stop/take-profit, client/broker order ids, position lifecycle, raw payloads.

### 5. Context review

Use to check reusable macro/industry backdrop. This remains distinct from Data quality.

Actions: queue macro refresh, queue industry refresh, reload.

Important fields: context trust, computed/expires, drivers, coverage, saliency, confidence, state/read badges, actor badges, diagnostics.

Use it when plans look plausible but backdrop seems stale, thin, or wrong. Go to Data quality when provider/no-news/no-bars problems explain degraded context.

### 6. Data quality

Use for no-bars, no-news, stale coverage, broker rejects, and ticker/provider input blockers.

Read first: input status, tickers checked, tickers with issues, blocking issues, degraded issues, affected tickers.

### 7. Run debugger

Use for fast run triage. It shows recent runs, status, workflow type, counts, and a selected-run “why this matters” summary. Use it to find failed/warning-heavy runs before opening Run detail.

### 8. Run detail

Use for full execution review of one run.

Tabs: Overview, Shortlist, Signals, Plans, Broker orders, Context.

Important fields: source kind, execution path, effective horizon, watchlist policy, shortlist limits/rejection reasons, signal/plan counts, created context objects.

### 9. Watchlists

Use for reusable universes.

Important fields: name, region, exchange, timezone, default horizon, tickers, allow shorts, optimize evaluation timing.

### 10. Jobs

Use for creating/scheduling workflows.

Important fields: name, workflow type, schedule, manual tickers, watchlist, enabled.

Common workflow types: `proposal_generation`, `recommendation_evaluation`, `plan_generation_tuning`, `macro_context_refresh`, `industry_context_refresh`.

### 11. Settings

Use for setup, providers, ingestion controls, broker execution, kill switch/risk limits, evaluation realism, and advanced research controls.

Check early when startup, provider health, or run quality looks off.

### 12. Research Lab

Use as a launcher for advanced tools, not as a second performance workbench.

Open tuning only when Quality & Edge points to a justified action:
- Signal gating tuning = upstream recall/selection threshold work
- Plan generation tuning = downstream plan construction/entry/risk/reward work; default mode is point-in-time replay, while stored-plan rescore is only a diagnostic/regression mode (`specs/plan-generation-tuning-spec.md`, `specs/historical-playback-tuning-spec.md`)
- Historical replay = replay batch/slice coverage and replay-generated plan/outcome audit surface for replay tuning (`historical-playback-tuning-plan.md`)
- Decision samples = sample-level review for discarded/borderline signals
- Candidate signals = shortlist/pre-plan diagnostic artifact

### 13. Ticker drill-down

Use to review one ticker over time via `/tickers/{ticker}` or ticker links.

Important fields: win rate, total profit, plan/order/bar counts, stored/actionable plans, wins/losses/open plans, average confidence, plan history, resolution source, and price chart overlays for entry/stop/take-profit/resolution.

### 14. Snapshot detail

Use for auditing one stored context snapshot.

Sections: summary, drivers, evidence/warnings, source mix, ontology context, diagnostics JSON.

### 15. In-app docs

Use for methodology and reference material inside the app.

## Which page should I use?

- First open: Dashboard → Trade Review if plans need review → Quality & Edge for performance verdict
- Safety/execution: Dashboard → Execution & Risk → Settings if limits/toggles need changes
- Repeatable workflow: Watchlists → Jobs → Dashboard/Run debugger
- Why selected: Candidate signals → Run detail → Trade Review
- Trade ideas: Trade Review → Ticker drill-down → Run detail
- Stale backdrop: Context review → Snapshot detail → Data quality if evidence is missing
- Input blockers: Data quality → Settings/preflight if provider setup is wrong
- Bad run: Run debugger → Run detail → Worker logs/Settings if systemic
- Confidence trust: Quality & Edge → Research Lab only when a tuning action is justified

## Practical playbooks

Daily loop:
1. Dashboard
2. Trade Review for current plans
3. Execution & Risk if broker exposure/orders need attention
4. Quality & Edge for edge/performance verdict
5. Context review, Data quality, or Run debugger only when a blocker appears

Research loop:
1. Quality & Edge
2. identify the justified action
3. Research Lab
4. tuning page or decision samples
5. return to Quality & Edge after enough new evidence

Failure loop:
1. Run debugger
2. Run detail
3. Worker logs if active/stalled
4. Data quality or Settings/preflight if systemic

## Interpretation cautions

Do not over-read one confidence number, confuse attention with actionability, ignore stale context, or treat `watchlist`/`no_action` as failures.

## See also

- `glossary.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `raw-details-reference.md`
