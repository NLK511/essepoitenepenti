# Operator Page & Field Guide

**Status:** operator reference

This guide explains what each main UI page is for and how to read the most important fields.

Use it when you want quick answers to questions like:
- where should I start?
- which page should I use for this investigation?
- what do confidence, transmission, shortlist, and outcome fields mean?

If you are new to the app, use this reading order:
1. this guide for page orientation
2. `glossary.md` for shared terms such as cohort, slice, and calibration
3. `recommendation-methodology.md` for the live recommendation path
4. `raw-details-reference.md` only when you need payload detail

For payload-level storage details, see `raw-details-reference.md`.

## How to read the product

The UI is easiest to understand in four groups:

1. **Operate**
   - Dashboard
   - Jobs
   - Watchlists
   - Settings
2. **Review**
   - Ticker signals
   - Recommendation plans
   - Ticker drill-down
3. **Investigate**
   - Run debugger
   - Run detail
   - Context review
   - Snapshot detail
4. **Research**
   - Research overview
   - Calibration tab
   - Advanced review: Decision samples
   - Tuning: Signal gating tuning
   - Tuning: Plan generation tuning

A simple mental model:
- **Dashboard** = what to check next
- **Recommendation plans** = actual trade plans
- **Ticker signals** = why a ticker got attention
- **Run detail** = how the workflow got there
- **Context review** = the broader market backdrop reused by the app

## Common concepts across pages

### Status
Common status values:
- `queued`
- `running`
- `completed`
- `completed_with_warnings`
- `failed`
- `fresh`
- `stale` / `expired`

### Direction vs action
- **Direction** = signal bias, usually `long`, `short`, or neutral
- **Action** = plan state, such as `long`, `short`, `watchlist`, or `no_action`

A ticker can have direction without being tradeable enough for an actionable plan.

### Confidence
Confidence is an evidence-weighted trust and actionability estimate.

Read it as:
- higher = cleaner setup, stronger alignment
- lower = weaker, thinner, or more conflicted evidence

It is not a guarantee.

For **macro context** and **industry context**, confidence is an operator trust score rather than a prediction probability.

Context confidence bands:
- `0.0–39.9` = light
- `40.0–64.9` = moderate
- `65.0–84.9` = strong
- `85.0+` = dominant

### Attention score
Attention is a triage score used mainly on ticker signals.

It answers:
> does this ticker deserve deeper review?

It is not the same as plan confidence.

### Transmission
Transmission describes how macro or industry context is believed to carry through to the ticker.

Common reads:
- `tailwind`
- `headwind`
- `mixed`
- `unknown`

### Warnings
Warnings are part of the output.

Treat stale context, thin coverage, provider failures, and contradiction warnings as decision-relevant information.

### Research-page reading terms
These terms appear often on calibration, baseline, evidence, replay, and tuning pages.

- **Cohort** = a comparison group with a shared rule, such as one setup family, one confidence bucket, or one time window
- **Segment** = a subgroup defined by a shared attribute, such as horizon or transmission bias
- **Bucket** = a numeric range, usually a confidence band used for calibration review
- **Slice** = one bounded cut of data, often a time window or one analytics breakdown
- **Promotion gate** = the rule that decides whether a tuning candidate is allowed to become the live config

Quick mental model:
- calibration asks whether confidence deserves trust
- baselines ask whether the full workflow beats simpler alternatives
- evidence asks where results are strongest or weakest
- walk-forward validation asks whether a change still works on later data slices

Current division of labor across research pages:
- **Signal gating tuning** = upstream shortlist and threshold control
- **Plan generation tuning** = downstream trade framing and actionable precision
- **Recommendation quality / calibration / walk-forward** = trust, validation, and promotion discipline

### Context saliency
For macro and industry context, saliency measures how prominent the current top events or drivers are relative to the rest of the stored context evidence.

It is a bounded `0.00–1.00` prominence score, not a probability.

Context saliency bands:
- `0.00–0.39` = light
- `0.40–0.64` = moderate
- `0.65–0.84` = strong
- `0.85+` = dominant

## Page guide

## 1. Dashboard

**Use it for:** first-pass triage.

Typical cards include:
- plans waiting for review
- recent runs
- watchlists and jobs counts
- macro and industry freshness
- attention items

Go here first. If freshness looks degraded, go to **Context review**. If recent runs look bad, go to **Run debugger**.

## 2. Jobs

**Use it for:** creating and scheduling workflows.

Important fields:
- **Name**
- **Workflow type**
- **Schedule**
- **Manual tickers**
- **Watchlist**
- **Enabled**

Typical workflow types:
- `proposal_generation`
- `recommendation_evaluation`
- `plan_generation_tuning`
- `macro_context_refresh`
- `industry_context_refresh`

The UI and docs describe these as macro/industry context refresh workflows, and the persisted job-type keys now match that naming.

Prefer watchlist-backed proposal jobs over ad hoc ticker lists when possible.

## 3. Watchlists

**Use it for:** defining reusable universes.

Important fields:
- **Name**
- **Region**
- **Exchange**
- **Timezone**
- **Default horizon**
- **Tickers**
- **Allow shorts**
- **Optimize evaluation timing**

Read **Default horizon** as the base time assumption for plans sourced from the watchlist.

## 4. Recommendation plans

**Use it for:** primary trade review.

This is the main operator decision page.

Common filters:
- ticker
- action
- run id
- setup family
- resolved / unresolved
- specific outcome such as `win`, `loss`, `phantom_win`, `phantom_loss`, or `expired`
- stats window such as day, week, month, or year

Main page modes:
- **Review queue**
- **Advanced analytics**

Advanced analytics tabs:
- **Overview**
- **Calibration**
- **Baselines**
- **Evidence**
- **Setup families**

Plain-English read:
- **Calibration** = do higher-confidence plans actually behave better?
- **Baselines** = does the live workflow beat simpler comparison groups?
- **Evidence** = which cohorts look strongest or weakest right now?
- **Setup families** = which trade archetypes are carrying or hurting measured performance?

Most important fields:
- **Action**
- **Confidence**
- **Entry / Stop / Take profit**
- **Horizon**
- **Thesis**
- **Action reason**
- **Setup family**
- **Raw confidence / Calibrated confidence / Threshold**
- **Context bias / Alignment / Expected transmission window**
- **Latest outcome**
- **Open plans / expired plans / win rate** stats for the current filter set

Important nuance:
- non-shortlisted names usually remain cheap-scan-only `no_action` plans
- shortlisted names may still end as `no_action` after deep analysis and policy gating
- only those deep-analysis-derived rejected plans can later produce phantom outcomes, because they retain intended direction and trade levels
- on the recommendation-plans page, non-shortlisted names are hidden by default so the main review queue stays focused on deeper-review candidates; operators can still reveal them with the filter toggle when they want full audit coverage

Suggested review order:
1. review the queue first
2. open individual plan details only when needed
3. switch to advanced analytics for calibration / baselines / evidence

Important interpretation note:
- `expired` means the plan passed its intended horizon without a terminal win/loss outcome
- default win-rate surfaces exclude `expired`, `phantom_*`, and other non-win/loss outcomes from the denominator
- phantom outcomes (`phantom_win`, `phantom_loss`) are visible via outcome filters but only used by tuning engines, not headline stats
- resolved/unresolved filters are broader lifecycle filters than the more granular outcome filter

## 5. Ticker signals

**Use it for:** shortlist and pre-plan triage.

This page answers:
> why did this ticker get attention?

Important fields:
- **Mode**: cheap scan vs deep analysis
- **Attention score**
- **Shortlisted**
- **Shortlist rank**
- **Selection lane**
- **Shortlist reasons**
- **Catalyst proxy**
- **Alignment**
- **Expected window**
- **Warnings**

Useful cheap-scan components:
- trend score
- momentum score
- breakout score

## 6. Run debugger

**Use it for:** fast run triage.

It shows recent runs with status, workflow type, timing, and summary counts.

Use it to find failed or warning-heavy runs, then jump to **Run detail**.

## 7. Run detail

**Use it for:** full execution review for one run.

Main tabs:
- **Overview**
- **Shortlist**
- **Signals**
- **Plans**
- **Context**

Important fields:
- **Source kind**
- **Execution path**
- **Effective horizon**
- **Watchlist policy**
- **Shortlist limits and rejection reasons**
- **Signal and plan counts**
- **Created context objects**

Use this page to answer questions like:
- why did a run generate many `no_action` plans?
- why was a ticker rejected before deep analysis?
- did context contradictions affect gating?

## 8. Context review

**Use it for:** checking reusable macro and industry backdrop.

Main actions:
- queue macro refresh
- queue industry refresh
- reload

Important fields:
- **Computed / Expires**
- **Drivers**
- **Coverage**
- **Saliency**
- **Confidence**
- **State / Read badges**
- **Actor badges** when a material trigger source is identified
- **Diagnostics**

Context badge quick guide:
- **Saliency** measures prominence of the current stored events or drivers
- **Confidence** measures how trustworthy the context read is given evidence quality, source mix, contradictions, and degradation
- both badges are heuristic operator aids, not guarantees or prediction probabilities

Saliency quick guide:
- `0.00–0.39` light
- `0.40–0.64` moderate
- `0.65–0.84` strong
- `0.85+` dominant

Confidence quick guide:
- `0.0–39.9` light
- `40.0–64.9` moderate
- `65.0–84.9` strong
- `85.0+` dominant

Use this page when plans look plausible but the market backdrop seems stale, thin, or wrong.

Current context cards now try to show not just the top theme/driver, but also:
- whether the current read looks escalating, easing, stabilizing, or mixed
- whether the market read looks more like fear, relief, inflationary pressure, or growth support
- the leading actor or trigger source when one is recoverable from the evidence

## 9. Snapshot detail

**Use it for:** auditing one shared snapshot.

Typical sections:
- header summary
- primary drivers
- evidence and warnings
- source mix
- ontology context for industry snapshots
- diagnostics JSON

Stored event rows on this page may now include:
- persistence
- transition
- catalyst
- interpretation
- actor
- actor role
- actor source
- short "why now" text grounded in top evidence

Read this page as a lower-level storage-oriented view.

Important fields:
- **Coverage**
- **Source breakdown**
- **Ontology context**
- **Diagnostics**

Relationship read-throughs, governed labels, and transmission details may appear here and on newer review pages as readable labeled fields instead of raw internal keys.

## 10. Settings

**Use it for:** setup, providers, ingestion controls, and advanced research controls.

Key areas:
- **System and providers**
- **Summarization**
- **News ingestion**
- **Social/Nitter settings**
- **Advanced research controls**

Go here early when startup or run quality looks off.

## 11. Ticker drill-down

**Use it for:** reviewing one ticker over time.

Important fields:
- stored plans
- actionable plans
- wins / losses / open plans
- average confidence
- plan history with action, setup family, horizon, run link, and latest outcome

Use it to decide whether a ticker deserves repeated operator attention.

## 12. In-app docs

**Use it for:** reading methodology and reference material without leaving the app.

## Which page should I use?

### I just opened the app
1. Dashboard
2. Settings/preflight if health looks degraded
3. Recommendation plans

### I want repeatable workflows
1. Watchlists
2. Jobs
3. Dashboard or Run debugger after execution

### I want to know why a ticker was selected
1. Ticker signals
2. Run detail
3. Recommendation plans if it became actionable

### I want actual trade ideas
1. Recommendation plans
2. Ticker drill-down
3. Run detail for execution context

### I suspect stale or misleading backdrop
1. Context review
2. Snapshot detail
3. Settings/preflight

### I want to investigate a bad run
1. Run debugger
2. Run detail
3. Settings/preflight if it looks systemic

### I want to know whether confidence is trustworthy
1. Recommendation plans → Calibration
2. Recommendation plans → Baselines
3. Recommendation plans → Evidence

## Interpretation cautions

- do not over-read one confidence number
- do not confuse attention with actionability
- do not ignore stale context
- do not treat `watchlist` or `no_action` as failures

## Practical playbooks

### Daily loop
1. Dashboard
2. freshness and recent runs
3. Recommendation plans
4. Ticker signals for shortlist questions
5. Run detail for deeper investigation
6. queue evaluation later

### Context-first loop
1. Context review
2. refresh if stale
3. Jobs
4. review plans

### Failure investigation loop
1. Run debugger
2. Run detail
3. review warnings and persisted objects
4. check Settings/preflight if broad

## See also
- `glossary.md`
- `features-and-capabilities.md`
- `recommendation-methodology.md`
- `raw-details-reference.md`
- `user-journeys.md`
- `architecture.md`
