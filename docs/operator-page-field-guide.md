# Operator Page & Field Guide

**Status:** operator reference

This document explains the main UI pages, the fields you will see most often, and the kinds of tasks each page is good for.

Use this guide when you already understand the product at a high level and want help answering questions like:
- where should I start each day?
- which page should I use for a given investigation?
- what do the confidence, transmission, shortlist, and outcome fields actually mean?
- which fields are decision inputs versus workflow diagnostics?

For payload-level storage details, see `raw-details-reference.md`.
For product behavior and limits, see `features-and-capabilities.md`.
For methodology, see `recommendation-methodology.md`.

---

## How to read the product overall

The app is easiest to use if you separate pages into three roles:

1. **Operate**
   - Dashboard
   - Jobs
   - Watchlists
   - Settings

2. **Review trade objects**
   - Recommendation plans
   - Ticker signals
   - Ticker drill-down

3. **Investigate execution and context**
   - Run debugger
   - Run detail
   - Context snapshots
   - Snapshot detail

A simple way to think about it is:
- **Dashboard** shows what to look at next
- **Recommendation plans** show the actual trade plans
- **Ticker signals** show why a ticker was promoted, deprioritized, or blocked
- **Run detail** shows how the workflow got there
- **Context snapshots** show the broader market backdrop the app reused

---

## Common concepts used across pages

### Status
You will see status badges on runs, signals, plans, and snapshots.

Typical meanings:
- `queued`: waiting for worker execution
- `running`: currently executing
- `completed`: finished without notable warnings
- `completed_with_warnings`: finished, but degraded or incomplete in some way
- `failed`: execution failed
- `fresh`: snapshot is still within its intended validity window
- `expired` / `stale`: stored context may still be readable but should be trusted less

### Action vs direction
These are related but not identical.

- **Direction** is the directional bias of a signal, usually `long`, `short`, or neutral.
- **Action** is the trade recommendation state on a plan, such as:
  - `long`
  - `short`
  - `watchlist`
  - `no_action`

A ticker can have directional pressure but still end up as `watchlist` or `no_action` if execution quality, context quality, or confidence is not good enough.

### Confidence
Confidence is the app’s estimate of how trustworthy and actionable a plan or signal is.

Read it as:
- **higher confidence** = the setup looks cleaner and the evidence lines up better
- **lower confidence** = the evidence is weaker, thinner, more conflicted, or pushed down by calibration

Do **not** read confidence as a guarantee of success. The docs are explicit that this is an evidence-weighted planning number, not proof of predictive edge.

### Attention score
Used mainly on ticker signals.

This is a triage score. It answers:
> does this ticker deserve deeper analysis attention?

It is useful for ranking and shortlist review, not as a direct substitute for plan confidence.

### Transmission
Transmission fields describe how macro and industry context is believed to carry through to a ticker.

Common values:
- `tailwind`: broader context supports the setup
- `headwind`: broader context works against the setup
- `mixed` / `unknown`: context is unclear, conflicted, or weak

Transmission is there to answer a practical question: why should this ticker react now?

### Warnings and missing inputs
Warnings are part of the output, not extra noise.

Examples:
- missing or stale snapshots
- thin news coverage
- failed providers
- contradictory context
- weak technical structure

Treat warnings as part of the output, not as decoration.

---

## Page guide

## 1. Dashboard

**Best use cases**
- first page to open each day
- quick workspace triage
- decide whether to go to plans, runs, settings, or context

### Main sections

#### Metrics cards
Typical cards include:
- **Plans waiting for review**: recently persisted recommendation plans
- **Active watchlists**: how many tracked universes you currently have
- **Configured jobs**: saved workflows
- **Recent runs**: latest execution records
- **Macro context freshness** / **Industry context freshness**: quick read on whether shared context is likely trustworthy

### How to use it
If freshness looks degraded, go to **Context snapshots** or **Settings/preflight** before over-trusting new plans.
If there are recent warning-heavy runs, go to **Run debugger**.
If plans are present and health looks fine, go to **Recommendation plans**.

### Field meanings
- **Freshness labels**: shorthand for whether the shared context artifacts are recent enough to trust normally
- **Recent runs**: operational context, not trade quality by itself
- **Recommendation plan cards**: compact summary of the latest trade-ready outputs

---

## 2. Jobs and execution

**Best use cases**
- create recurring workflows
- manually queue proposal generation, evaluation, optimization, or snapshot refresh
- inspect which workflows are enabled and how they are sourced

### Main sections

#### New job form
Important fields:
- **Name**: human label for the workflow
- **Workflow type**:
  - `proposal_generation`
  - `recommendation_evaluation`
  - `weight_optimization`
  - `macro_sentiment_refresh`
  - `industry_sentiment_refresh`
- **Schedule**: cron-like schedule for automatic enqueueing
- **Manual tickers**: comma-separated source when not using a watchlist
- **Watchlist**: reusable source universe for proposal jobs

#### Saved jobs table
Important columns:
- **Workflow**: what kind of work this job does
- **Source**: watchlist or manual ticker source when relevant
- **Schedule**: automation cadence
- **Enabled**: whether the job can run on schedule
- **Actions**: enqueue, edit, delete, or convert to watchlist where supported

### How to use it well
- prefer **watchlist-backed** proposal jobs over ad hoc ticker lists when possible
- keep schedules realistic and interpretable
- use manual tickers for one-off checks, not as the main operating model

### Field meanings
- **Enabled**: scheduler may enqueue it if due
- **Watchlist source**: generally preferred because it carries policy metadata too
- **No ticker source required**: normal for evaluation, optimization, and refresh jobs

---

## 3. Watchlists

**Best use cases**
- define the markets you care about
- group names by market, style, or strategy universe
- make scheduling and later review more interpretable

### Main sections

#### Watchlist creation form
Important fields:
- **Name**: short descriptive label
- **Description**: optional practical context
- **Region**: e.g. `US`, `EU`
- **Exchange**: e.g. `NASDAQ`
- **Timezone**: useful for schedule interpretation and evaluation timing
- **Default horizon**: `1d`, `1w`, or `1m`
- **Tickers**: comma-separated list
- **Allow shorts**: whether short recommendations are allowed
- **Optimize evaluation timing**: whether evaluation timing should be adapted to the market/exchange context

#### Saved watchlists review
Visible fields often include:
- market metadata
- count of tickers
- shorts enabled/disabled
- timing optimized/standard
- schedule source and cron summary from policy
- shortlist strategy
- policy warnings

### Field meanings
- **Default horizon**: the base time assumption for plans sourced from the watchlist
- **Allow shorts**: expands the decision space; useful only if you genuinely trade both directions
- **Optimize evaluation timing**: mainly about better timing discipline in later outcome evaluation
- **Shortlist strategy**: summary of how the watchlist is expected to feed the cheap-scan → shortlist → deep-analysis flow

### Suggested watchlist use cases
- **Core tech swing basket**: liquid names you review daily
- **Earnings / catalyst basket**: names where event-driven setups matter more
- **Macro-sensitive basket**: banks, semis, energy, defensives, rate-sensitive names
- **Regional basket**: one watchlist per exchange/timezone to keep scheduling clean

---

## 4. Recommendation plans

**Best use cases**
- primary operator decision review page
- compare plan quality across tickers, runs, and setup families
- review calibration and cohort evidence before trusting confidence too much
- queue evaluations

This is one of the main review pages in the product.

### Main sections

#### Filter bar
Common filters:
- **Ticker**
- **Action**
- **Run id**
- **Setup family**
- **Limit**

Use these to narrow review by ticker, one workflow run, or a family of setups.

#### Review workspace tabs
- **Overview**: compact summary of current review posture
- **Calibration**: grouped outcome review by buckets and slices
- **Baselines**: compares actual output to simpler cohorts
- **Evidence**: strongest and weakest measurable cohorts
- **Setup families**: dedicated family-by-family outcome review

#### Results table
This is where trade plans are read directly.

### Important plan fields

#### Trade fields
- **Action**: `long`, `short`, `watchlist`, `no_action`
- **Confidence**: current usable confidence after any calibration adjustments
- **Entry**: exact or ranged entry zone
- **Stop**: invalidation / risk line
- **Take profit**: expected target
- **Horizon**: intended time window

#### Explanation fields
- **Thesis**: compact “why this trade exists” summary
- **Action reason**: why the plan was promoted or blocked
- **Action reason detail**: more specific explanation
- **Setup family**: the pattern or archetype the plan belongs to
  - e.g. breakout, continuation, mean_reversion, catalyst_follow_through

#### Execution-style fields
These usually come from `evidence_summary` and tell you how the app wants the trade to be approached:
- **Entry style**: how the entry should be interpreted
- **Stop style**: what logic defined the stop
- **Target style**: what logic defined the target
- **Timing expectation**: when the move is expected to matter
- **Invalidation summary**: what would break the thesis
- **Evaluation focus**: what later outcome review should pay attention to

#### Calibration fields
These are especially important if you want to avoid false precision:
- **Raw confidence**: confidence before calibration adjustments
- **Calibrated confidence**: confidence after evidence-based adjustment
- **Adjustment**: how much confidence was raised or lowered
- **Threshold**: effective threshold required for action under current cohort evidence
- **Calibration status / review status**: whether calibration logic had enough evidence to be informative

#### Transmission fields
These summarize broader context influence:
- **Context bias**: tailwind/headwind/mixed
- **Alignment percent**: how aligned ticker setup and broader context are
- **Expected transmission window**: estimated timeframe for context to matter
- **Primary drivers**: the main macro/industry reasons influencing the ticker
- **Conflict flags**: contradictions in context
- **Transmission tags**: compact labels for transmission characteristics

#### Outcome fields
- **Latest outcome**: latest stored evaluation result
- **1d / 5d returns**: fixed-horizon performance checkpoints
- **win / loss / open**: quick resolved state

### How to use the page well
- start in **Overview**
- if confidence looks attractive, check **Calibration** before over-trusting it
- use **Baselines** to ask whether complexity is beating simpler filters
- use **Evidence** to see where the app is doing better or worse
- only then read the individual plan rows in detail

### Suggested use cases
- daily trade review
- compare all plans from one run
- filter one setup family and test whether it should get more operator attention
- queue evaluation after enough time has passed

---

## 5. Ticker signals

**Best use cases**
- understand the shortlist before reading full plans
- inspect why a ticker was shortlisted, rejected, or only lightly promoted
- compare cheap-scan behavior across names

Treat this page as **pre-plan triage**.

### Main sections

#### Summary metrics
- **Signals loaded**
- **Shortlisted**
- **Deep analysis**
- **Tailwind context**

#### Signal cards
Each card usually shows:
- ticker
- status
- direction
- mode (`cheap_scan` vs `deep_analysis`)
- confidence
- attention
- shortlist state and rank
- transmission bias
- cheap-scan component summary
- warnings

### Important signal fields
- **Mode**: whether the ticker only went through cheap scan or received deeper analysis
- **Attention score**: triage importance
- **Shortlisted**: whether the ticker advanced into a deeper lane
- **Shortlist rank**: relative standing among candidates
- **Selection lane**: which path promoted it, such as a main technical lane or catalyst/event lane
- **Shortlist reasons**: explicit reasons for promotion or eligibility
- **Catalyst proxy**: rough event/catalyst intensity estimate
- **Alignment**: context-to-ticker fit
- **Expected window**: anticipated timing of context transmission

### Cheap-scan component fields
These are useful for understanding rank mechanics:
- **trend score**: broad directional structure
- **momentum score**: strength and persistence of movement
- **breakout score**: breakout-style technical pressure
- sometimes also volatility, liquidity, and directional aggregate values in run detail

### Suggested use cases
- answer “why did this name make the shortlist?”
- detect when cheap scan over-favors one type of setup
- compare catalyst-lane names versus momentum-lane names
- investigate why a name never becomes a plan despite repeated attention

---

## 6. Run debugger

**Best use cases**
- fast run triage
- inspect recent failures and warning-heavy runs
- choose which run needs deeper review

### Main sections

#### Run list
Shows recent runs with:
- run id
- job type
- job id
- status
- created/scheduled time

#### Selected run summary
Shows:
- status
- duration
- plans written
- signals written
- full run link

### How to use it
The debugger is for **fast investigation**, not for full trade review.
For proposal runs:
- use debugger to find the interesting run
- then move to **Run detail**, **Recommendation plans**, or **Ticker signals**

### Suggested use cases
- identify failed or warning-heavy runs from overnight execution
- verify whether a scheduled workflow actually produced plans
- quickly estimate whether the run is worth opening in detail

---

## 7. Run detail

**Best use cases**
- canonical execution review for one workflow run
- understand what was scanned, shortlisted, persisted, and warned about
- diagnose degraded runs without leaving the app

This is the main execution-forensics page.

### Main sections

#### Run header and metrics
Shows:
- run status
- job id / job type
- duration
- created, scheduled, started, completed times
- links to created snapshots if relevant
- counts of signals, plans, and context objects

#### Redesign orchestration tabs
- **Overview**
- **Shortlist**
- **Signals**
- **Plans**
- **Context**

### Important overview fields
- **Source kind**: whether the run came from a watchlist or manual tickers
- **Execution path**: which orchestration path was used
- **Effective horizon**: actual horizon applied in this run
- **Watchlist policy**: schedule source, timezone, cron, default horizon, shortlist strategy, warnings

### Important shortlist fields
- **Limit**: total number of names allowed into deeper consideration
- **Core limit**: primary lane budget
- **Catalyst lane limit**: reserved budget for event-driven or catalyst-heavy names
- **Minimum confidence percent**: minimum confidence to advance
- **Minimum attention score**: minimum triage importance to advance
- **Minimum catalyst proxy score**: catalyst floor for event lane consideration
- **Allow shorts**: whether negative-direction names were allowed
- **Rejections**: grouped reasons names were excluded

#### Shortlist decision table
Useful fields:
- **Outcome**: shortlisted or rejected
- **Lane**: technical/catalyst or other selection path
- **Rank**: overall ordering
- **Confidence / attention / catalyst proxy**: main inputs to promotion logic
- **Reasons**: operator-readable explanation of the decision

### Signals tab fields
Adds more detailed signal-level review:
- direction
- confidence
- attention
- shortlist info
- transmission info
- cheap-scan components
- status

### Plans tab fields
This is like a run-scoped version of the recommendation plans page.
Use it when you want to answer:
> what plans did this run actually create, and how were they framed?

### Context tab fields
Shows macro and industry context objects created by the run.
Common fields include:
- **summary text**
- **event lifecycle counts**: new, escalating, fading
- **contradictions**: conflicting event labels or evidence

### Suggested use cases
- investigate why a run generated many `no_action` plans
- understand why a ticker was rejected before deep analysis
- inspect whether context contradictions caused gating
- compare watchlist policy assumptions with actual run output

---

## 8. Context snapshots

**Best use cases**
- inspect reusable macro and industry backdrop
- trigger the shared macro/industry refresh jobs manually
- decide whether proposal outputs are being produced on stale foundations

### Main sections

#### Action buttons
- queue macro refresh
- run macro now
- queue industry refresh
- run industry now
- reload

#### Metrics and latest summaries
You usually see:
- latest macro context or top macro event
- macro freshness / confidence signals
- latest industry context or top industry driver
- latest transitional sentiment snapshot status

#### History lists
Recent macro and industry context snapshots, plus the transitional macro/industry sentiment history, with links to detail pages.

### Important snapshot fields
- **Label**: high-level polarity or state
- **Score**: numeric sentiment/context value
- **Computed**: when it was produced
- **Expires**: freshness boundary
- **Drivers**: main reasons behind the snapshot
- **Coverage**: how much source material backed it
- **Diagnostics**: provider errors, warnings, or source notes

### How to use it
If plans look plausible but market backdrop feels wrong, inspect context snapshots first.
If the supporting sentiment snapshots are stale, refresh them before generating too many new plans.

### Suggested use cases
- morning macro refresh before proposal generation
- sector backdrop checks before trusting ticker-level long/short calls
- diagnosing why multiple unrelated tickers all look degraded or neutral

---

## 9. Snapshot detail

**Best use cases**
- full audit of one shared snapshot
- inspect exact stored coverage, source breakdown, signals, and diagnostics
- follow a plan or run back to the market context it used

### Main sections
- header summary
- primary drivers
- coverage JSON
- source breakdown JSON
- normalized signals JSON
- diagnostics JSON

### Field meanings
- **Coverage**: quantity and shape of evidence found
- **Source breakdown**: where evidence came from
- **Signals**: normalized fields used to characterize the snapshot
- **Diagnostics**: what may have gone wrong or degraded quality

This page is intentionally closer to raw storage than the higher-level review pages.

---

## 10. Settings

**Best use cases**
- first-time setup
- preflight troubleshooting
- provider credential management
- summary engine configuration
- social/Nitter configuration
- optimization guardrails and rollback

### Main sections

#### Metrics cards
- **Internal pipeline health**: overall preflight status
- **Summary backend**: current summary mode
- **Optimization threshold**: minimum resolved outcomes needed for optimization
- **Weight backups**: available rollback safety count

#### Core operator controls
- **Confidence threshold**: application-level threshold used in gating/behavior

#### Optimization guardrails
- **Minimum resolved plan outcomes**: minimum evidence required before optimization should mutate weights
- **Current weights file** / **Backup directory**: operational safety references
- **Available backups**: rollback targets for `weights.json`

#### Summary engine
Fields include:
- **Backend**: `news_digest`, `openai_api`, or `pi_agent`
- **Model**
- **Timeout seconds**
- **Max tokens**
- **pi command** / **PI_CODING_AGENT_DIR** / **pi CLI args**
- **Summary prompt**

#### Social signals
Fields include:
- **Social sentiment enabled**
- **Nitter source enabled**
- **Nitter base URL**
- **Request timeout**
- **Results per query**
- **Query window**
- **Include replies**
- **Use Nitter for ticker sentiment**

#### Internal preflight
Shows the current checks, their statuses, and messages.
This is one of the first places to look when startup or run quality seems off.

### Suggested use cases
- set up the app before first real use
- confirm why startup is blocked by preflight
- keep social enabled for macro/industry only, not ticker sentiment, if you want a more conservative setup
- restore a previous weights backup after a questionable optimization run

---

## 11. Ticker drill-down

**Best use cases**
- answer “is this ticker worth repeated attention?”
- review plan history for one ticker
- compare current app-side behavior with legacy prototype trade history

### Main sections
- **Overview**
- **Plans**
- **Prototype trades**
- **Raw payloads**

### Important overview fields
- **Stored plans**: all recommendation plans recorded for the ticker
- **Actionable plans**: long and short plans only
- **Win / loss**: resolved plan outcomes
- **Open plans**: not yet resolved
- **Avg confidence**: average plan confidence for the ticker
- **Prototype trades**: historical reference-only legacy data

### Plan history fields
- action
- setup family
- horizon
- run link
- confidence
- thesis summary
- entry / stop / take profit
- latest outcome and note

### How to use it
Use this page when you want to know whether the app keeps finding usable setups in the same ticker or whether the name mostly produces weak, warning-heavy, or conflicting plans.

### Suggested use cases
- decide whether a ticker should stay on a watchlist long term
- compare repeated setups in one name over time
- judge whether one name tends to work only in certain setup families

---

## 12. In-app docs

**Best use cases**
- read methodology without leaving the app
- look up setup and operating guidance
- cross-check what the product claims versus what it actually ships

Use docs when you are confused about behavior, and use page-level workflows when you are investigating a specific run or trade object.

---

## Which page should I use?

### I just opened the app. Where do I start?
1. Dashboard
2. Settings/preflight if health looks degraded
3. Recommendation plans

### I want to create repeatable workflows.
1. Watchlists
2. Jobs
3. Dashboard or Run debugger after execution

### I want to know why a ticker was selected.
1. Ticker signals
2. Run detail → Shortlist or Signals tab
3. Recommendation plans if it became actionable

### I want to review actual trade ideas.
1. Recommendation plans
2. Ticker drill-down for one name
3. Run detail for execution context

### I suspect the market backdrop is stale or misleading.
1. Context snapshots
2. Snapshot detail
3. Settings/preflight

### I want to investigate a bad run.
1. Run debugger
2. Run detail
3. Settings/preflight if the issue looks systemic

### I want to know whether the app’s confidence is trustworthy.
1. Recommendation plans → Calibration
2. Recommendation plans → Baselines
3. Recommendation plans → Evidence

---

## Field interpretation cautions

### Do not over-read a single confidence number
Always check:
- warnings
- calibration status
- transmission conflicts
- freshness of shared context

### Do not confuse attention with actionability
A ticker can be highly interesting and still not deserve a trade plan.

### Do not treat stale context as invisible
If snapshots are stale, the app’s design expects that to remain visible and meaningful.

### Do not ignore `watchlist` or `no_action`
Those are valid successful outputs, not just failed recommendations.

---

## Practical operator playbooks

### Daily operator loop
1. Open Dashboard
2. Check freshness and recent runs
3. Review Recommendation plans
4. Use Ticker signals for “why this was shortlisted” questions
5. Use Run detail only for deeper investigation
6. Queue evaluation later to keep outcome review current

### Morning context-first loop
1. Open Context snapshots
2. Refresh macro or industry if stale
3. Open Jobs and enqueue proposal generation
4. Review plans

### Failure investigation loop
1. Run debugger
2. Open the failed or warning-heavy run
3. Review warnings, shortlist decisions, and persisted objects
4. Check Settings → preflight if the issue seems broad

### Setup-family review loop
1. Open Recommendation plans
2. Filter by setup family
3. Review calibration and family slices
4. Check evidence concentration before expanding usage of that family

---

## See also
- `features-and-capabilities.md` — what the app can do today
- `recommendation-methodology.md` — how the pipeline works
- `raw-details-reference.md` — field and payload reference
- `user-journeys.md` — current operator workflows
- `architecture.md` — system structure behind the UI
