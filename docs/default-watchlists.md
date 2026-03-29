# Default Watchlists

**Status:** canonical seed-watchlist reference

This document explains the curated default watchlists deployed by:
- `scripts/deploy_watchlists.py`

That script is the operational source of truth for the exact seeded ticker lists and scheduled jobs. This document explains the design rationale behind those defaults.

## Goals

The default watchlist set was redesigned around five goals:

1. seed a broad but finite default universe of **300 equities**
2. keep regional exposure balanced at **100 U.S. / 100 Europe / 100 Asia-Pacific**
3. divide the universe by **continent + macro-industry** rather than by one giant regional bucket
4. keep watchlist names **compact and scan-friendly**
5. stagger schedules so runs are **region-aware** and **non-overlapping** to reduce API quota spikes

## Universe construction rationale

The seeded universe is intentionally curated and static.

Selection principles:
- favor **very large-cap** or **very actively traded** equities
- prefer names that are repeatedly useful in macro-sensitive market review
- include only **equities**, not ETFs
- avoid duplicate assignments across watchlists
- use local-market tickers when practical for Europe and Asia-Pacific exposure
- accept that this is a practical operator seed set, not a benchmark-licensing product or an exact index replica

This means the seeded lists are designed to be:
- broad enough for useful default coverage
- liquid enough for recurring analysis
- stable enough to seed a new environment without depending on an external screener API

## Naming convention rationale

The watchlists use:
- `<REGION>-<GROUP>`

Examples:
- `US-Tech`
- `EU-Fin`
- `APAC-Cyc`

Why this format:
- short enough to fit cleanly in the UI
- easy to sort visually
- clear region first, which matters for scheduling and session interpretation
- clear macro-industry second, which matters for operator intent and run review

## Macro-industry grouping rationale

The 300 names are divided into five broad macro-industry buckets per region:
- `Tech`
- `Fin`
- `Health`
- `Cons`
- `Cyc`

These are intentionally broad.

Why broad groups instead of many narrow sectors:
- they keep each watchlist large enough to be useful
- they reduce naming clutter
- they map more cleanly to how operators often think about session leadership
- they provide a practical compromise between sector purity and manageable default setup

Group intent:
- `Tech`: software, semis, internet, payments, telecom-tech, and platform-heavy growth
- `Fin`: banks, insurers, brokers, exchanges, and diversified financials
- `Health`: pharma, biotech, medtech, diagnostics, and healthcare equipment / services
- `Cons`: staples, brand-heavy demand, retail, travel, autos, telecom/media defensives, and consumer-sensitive names
- `Cyc`: industrials, energy, materials, transport, chemicals, capital goods, and other macro-sensitive cyclicals

## Scheduling rationale

The seeded schedules are staggered by region and by macro-industry so they do not overlap.
The default deployment also adds a small support-refresh trio: two macro runs per day in the quiet windows between regional batches, plus one industry refresh in the midday gap.

Regional schedule blocks:
- **Asia-Pacific:** `00:00` to `02:00` UTC
- **Europe:** `07:00` to `09:00` UTC
- **United States:** `13:00` to `15:00` UTC

Within each region, runs are spaced by **30 minutes**.

Why this matters:
- avoids multiple seeded jobs firing at the same moment
- reduces burst pressure on market-data and news APIs
- leaves room for other manual or custom jobs
- makes debugging easier because default runs appear in a predictable cadence

Why the order inside a region is not arbitrary:
- `Tech` tends to benefit from early session information and overnight repricing
- `Fin` is more useful after early rate / open noise begins to settle
- `Health` often benefits from a cleaner read on risk-on vs defensive rotation
- `Cons` is often more informative after session tone is established
- `Cyc` is placed later so industrial, commodity, and transport names can reflect broader session leadership and macro tape direction

## Default watchlist schedule map

| Watchlist | Region | Group | UTC schedule | Rationale summary |
|---|---|---|---:|---|
| `APAC-Tech` | Asia-Pacific | Tech | `00:00` | near Asia open for immediate platform / semiconductor repricing |
| `APAC-Fin` | Asia-Pacific | Fin | `00:30` | after initial opening noise for rates / bank sensitivity |
| `APAC-Health` | Asia-Pacific | Health | `01:00` | after tone stabilizes enough to read defensive rotation |
| `APAC-Cons` | Asia-Pacific | Cons | `01:30` | once consumer, auto, and travel demand names have real volume |
| `APAC-Cyc` | Asia-Pacific | Cyc | `02:00` | after commodity and early futures tone become clearer |
| `EU-Tech` | Europe | Tech | `07:00` | near Europe open for tech, semis, and payments repricing |
| `EU-Fin` | Europe | Fin | `07:30` | after opening auction pressure settles for banks / insurers |
| `EU-Health` | Europe | Health | `08:00` | once market preference for defense vs growth is clearer |
| `EU-Cons` | Europe | Cons | `08:30` | after FX and demand-sensitive signals become more reliable |
| `EU-Cyc` | Europe | Cyc | `09:00` | later read for autos, industrials, chemicals, and energy |
| `US-Tech` | United States | Tech | `13:00` | pre-open / early U.S. risk window for large-cap growth tone |
| `US-Fin` | United States | Fin | `13:30` | after premarket yields and opening futures direction settle |
| `US-Health` | United States | Health | `14:00` | cleaner view on defensive vs high-beta preference |
| `US-Cons` | United States | Cons | `14:30` | after leadership rotation shows whether staples / media are favored |
| `US-Cyc` | United States | Cyc | `15:00` | later read for energy, transports, and macro cyclicals |

Support-refresh jobs:

| Job | Scope | UTC schedule | Rationale summary |
|---|---|---:|---|
| `Auto: Macro Support Refresh AM` | Macro | `06:00` | before Europe opens, when the macro read can refresh without colliding with seeded watchlist jobs |
| `Auto: Macro Support Refresh PM` | Macro | `18:00` | after the U.S. block, when the full-session macro read can complete without overlapping other jobs |
| `Auto: Industry Support Refresh` | Industry | `10:30` | between Europe and U.S. batches, when industry context can refresh in a quiet window |

## Coverage summary

The default script seeds:
- **15 watchlists**
- **18 scheduled jobs**
  - 15 proposal-generation jobs, plus 2 macro refresh jobs and 1 industry refresh job
- **300 unique equities total**

Regional split:
- **U.S.:** 5 watchlists / 100 equities
- **Europe:** 5 watchlists / 100 equities
- **Asia-Pacific:** 5 watchlists / 100 equities

## Operational notes

Run the seed script with:

```bash
.venv/bin/python scripts/deploy_watchlists.py
```

Properties of the script:
- creates missing watchlists
- updates existing seeded watchlists by name
- creates or updates matching `Auto: ...` jobs
- rejects duplicate ticker assignment across watchlists
- validates that the seeded default set still contains exactly **300** tickers

## Maintenance rule

If the default watchlists are changed in the future:
- update `scripts/deploy_watchlists.py`
- keep the total-universe and scheduling rationale in sync here
- preserve compact naming and non-overlapping schedule discipline unless there is a strong operational reason not to
- keep the support-refresh windows in the midday / off-peak gaps so they do not collide with the seeded equity batches
