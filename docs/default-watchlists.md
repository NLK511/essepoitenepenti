# Default Watchlists

**Status:** canonical seed-watchlist reference

This document explains the curated default watchlists deployed by:
- `scripts/deploy_watchlists.py`

That script is the source of truth for the exact seeded ticker lists and jobs. This doc explains the rationale behind those defaults.

## Goals

The default watchlist set is designed to:
1. seed a broad but finite universe of **750 equities**
2. keep exposure balanced at **250 U.S. / 250 Europe / 250 Asia-Pacific**
3. divide the universe by **region + macro-industry**
4. keep names compact and scan-friendly
5. stagger schedules to reduce API spikes

## Universe design

The seeded universe is intentionally curated and static.

Selection principles:
- favor very large-cap or highly traded equities
- prefer names repeatedly useful in macro-sensitive review
- include equities only, not ETFs
- avoid duplicate assignments across watchlists
- use local-market tickers where practical for Europe and Asia-Pacific

The goal is practical default coverage, not index replication.

## Naming convention

Watchlists use:
- `<REGION>-<GROUP>`

Examples:
- `US-Tech`
- `EU-Fin`
- `APAC-Cyc`

This format is short, sortable, and easy to interpret in the UI.

## Macro-industry groups

Each region is divided into five broad groups:
- `Tech`
- `Fin`
- `Health`
- `Cons`
- `Cyc`

These groups are intentionally broad so each watchlist stays useful and the default set stays manageable.

Group intent:
- `Tech` — software, semis, internet, payments, platform growth
- `Fin` — banks, insurers, brokers, exchanges, diversified financials
- `Health` — pharma, biotech, medtech, diagnostics, healthcare equipment/services
- `Cons` — staples, retail, travel, autos, telecom/media defensives, consumer-sensitive names
- `Cyc` — industrials, energy, materials, transport, chemicals, capital goods, other cyclicals

## Scheduling rationale

Schedules are staggered by region and group so they do not overlap.

Proposal-generation jobs stay near local opening windows and are spaced by **10 minutes**.
The default deployment also adds three shared-context refresh jobs:
- two macro refreshes per day
- one industry refresh in the midday gap

Regional schedule blocks:
- **Asia-Pacific:** `00:00` to `00:40` UTC
- **Europe:** `07:00` to `07:40` UTC
- **United States:** `13:00` to `13:40` UTC

Why this matters:
- avoids multiple seeded jobs firing at once
- reduces burst pressure on market-data and news APIs
- leaves room for manual or custom jobs
- makes debugging easier because runs appear in a predictable cadence

## Default schedule map

| Watchlist | Region | Group | UTC schedule |
|---|---|---|---:|
| `APAC-Tech` | Asia-Pacific | Tech | `00:00` |
| `APAC-Fin` | Asia-Pacific | Fin | `00:10` |
| `APAC-Health` | Asia-Pacific | Health | `00:20` |
| `APAC-Cons` | Asia-Pacific | Cons | `00:30` |
| `APAC-Cyc` | Asia-Pacific | Cyc | `00:40` |
| `EU-Tech` | Europe | Tech | `07:00` |
| `EU-Fin` | Europe | Fin | `07:10` |
| `EU-Health` | Europe | Health | `07:20` |
| `EU-Cons` | Europe | Cons | `07:30` |
| `EU-Cyc` | Europe | Cyc | `07:40` |
| `US-Tech` | United States | Tech | `13:00` |
| `US-Fin` | United States | Fin | `13:10` |
| `US-Health` | United States | Health | `13:20` |
| `US-Cons` | United States | Cons | `13:30` |
| `US-Cyc` | United States | Cyc | `13:40` |

Shared-context refresh jobs:

| Job | Scope | UTC schedule |
|---|---|---:|
| `Auto: Macro Support Refresh AM` | Macro | `06:00` |
| `Auto: Macro Support Refresh PM` | Macro | `18:00` |
| `Auto: Industry Support Refresh` | Industry | `10:30` |

## Coverage summary

The default script seeds:
- **15 watchlists**
- **18 scheduled jobs**
  - 15 proposal jobs
  - 2 macro refresh jobs
  - 1 industry refresh job
- **750 unique equities total**

Regional split:
- **U.S.:** 5 watchlists / 250 equities
- **Europe:** 5 watchlists / 250 equities
- **Asia-Pacific:** 5 watchlists / 250 equities

## Operational notes

Run the seed script with:

```bash
.venv/bin/python scripts/deploy_watchlists.py
```

The script:
- creates missing watchlists
- updates existing seeded watchlists by name
- creates or updates matching `Auto: ...` jobs
- rejects duplicate ticker assignment across watchlists
- validates that the seeded default set still contains exactly **750** tickers

## Maintenance rule

If the default watchlists change:
- update `scripts/deploy_watchlists.py`
- keep the rationale here in sync
- preserve compact naming and non-overlapping schedule discipline unless there is a strong operational reason not to
