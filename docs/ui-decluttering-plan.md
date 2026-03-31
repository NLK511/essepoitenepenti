# UI Decluttering Plan

**Status:** active implementation plan

This document reviews the current duplication problem in the app UI and proposes a concrete decluttering path.

## Why this exists

The app exposes a lot of useful diagnostic detail, but several pages repeat the same information multiple times:

- the same confidence number appears in headers, tables, helper text, and detail blocks
- warnings appear as badges, inline notes, and full lists
- LLM provenance is shown in multiple slightly different forms
- transmission/context metadata is restated at several levels of the same page

The result is a dense UI that is rich in data but harder to scan.

## Design goal

Keep the app information-rich, but make each fact appear in **one canonical place per page**.

Use progressive disclosure so operators see:

1. the main decision signal first
2. one compact explanation second
3. the raw details only when they expand them

## Implementation status

The first refactor pass is underway in the frontend:

- `frontend/src/components/decision-surface.tsx` now provides shared compact surfaces for scores, metric clusters, warnings, and provenance
- the context review page now uses the shared score / provenance / warning surfaces for history and summary cards, and the latest cleanup pass is collapsing the remaining macro / industry event summaries into shared compact rows
- the run detail, recommendation plans, ticker signals, dashboard, and ticker detail pages are being gradually collapsed toward the same compact patterns

This plan remains the checklist for the remaining declutter work.

## Second-pass status

The next pass is focusing on the remaining table-density and row-density issues, especially:

- recommendation-plan confidence / execution / transmission columns
- run-detail plan and context rows
- any remaining shortlist / transmission helper-text duplication in signal tables

The goal is to keep the pages rich, but make each row say one thing instead of five versions of the same thing.

## Third-pass status

A third cleanup pass is now focusing on `run-detail-page.tsx`, especially:

- plan table row density
- context row density
- compressed lifecycle / warning summaries
- keeping the canonical links while trimming repeated helper text

The latest run-detail pass is collapsing the context snapshots into shared compact rows and shortening the shortlist / transmission / calibration helper text so each table cell carries fewer repeated fragments.

The recommendation-plans page is now also being tightened so horizon, setup, calibration, and transmission details use fewer helper lines per row, and the latest pass is turning each plan row into a compact summary with an expandable detail panel so entry, stop, and take-profit fields stay visible at a glance. The row layout now also uses explicit column widths and clamped thesis previews so the table stays readable instead of letting cells overlap on narrower screens.

The ticker-signals page has moved into its cleanup pass, with shortlist, transmission, and cheap-scan details being collapsed into fewer shared summary lines per card.

The dashboard / ticker overview cards are also in the same cleanup sweep, with the remaining helper-text density being collapsed into fewer lines.

A fourth cleanup pass is now focusing on the dashboard and ticker overview cards, especially the repeated provenance and outcome summaries in the overview surfaces. The latest edits collapsed more of that repeated wording into single-line summaries, and the final pass is trimming the remaining overview-card copy.

The latest dashboard pass condensed the freshness/context cards and the recommendation-plan cards. The latest ticker pass condensed the overview and history cards so the most important summary facts stay in one line.

The context snapshot detail page is now the next cleanup area, with the top summary, provenance, event list, and warnings being moved onto the same shared compact primitives used elsewhere.

The next cleanup pass is tightening the context review history blocks by using shared compact event summary rows instead of repeating the same label/value scaffolding in each list item.

The dashboard and ticker overview cards are now the final remaining cleanup area in this phase.

This pass should leave the run page as the deep forensic surface, but with much less repeated phrasing inside each row.

## Core rules

### 1. One canonical surface per concept
Each concept should have one primary home:

- **Run detail**: execution diagnostics and orchestration state
- **Recommendation plans**: calibrated confidence, action framing, and outcome review
- **Context review**: macro / industry backdrop and support-snapshot state
- **Ticker signals**: signal generation and shortlist behavior
- **Ticker detail**: ticker-level performance and history

Other pages may reference those concepts, but should not restate them in full.

### 2. Summary once, details on demand
Every page should follow the same hierarchy:

- **Top summary**: the 3–5 most important facts
- **Supporting detail**: a small number of grouped sections
- **Raw detail**: behind an expandable panel or drill-down link

### 3. Prefer compact chips over repeated text
If a value is shown more than once, compress it into a chip, badge, or single-line summary.

Examples:

- `confidence 72.4%`
- `warnings 2`
- `LLM openai_api`
- `saliency 0.63`
- `coverage good`

### 4. Use canonical links instead of duplication
If a page is repeating a detail that already has a dedicated page, show a link to the canonical page instead of copying the full payload.

### 5. Hide raw diagnostics by default
Warnings, provider errors, raw JSON, and provenance internals should be collapsible by default.

---

## Shared components to add

Create a small set of reusable frontend primitives so pages stop hand-building the same blocks.

### `frontend/src/components/decision-surface.tsx`

Purpose: reusable compact surfaces for dense decision pages.

Current exports:

- `ScoreBadge`
  - one-line labeled score display with optional tone
- `MetricCluster`
  - compact row for 2–5 key metrics
- `WarningSummary`
  - warning count plus optional one-line list
- `ProvenanceStrip`
  - LLM / fallback provenance strip with optional summary warning flag
- `ContextScoreSummary`
  - compact macro / industry score summary row
- `ContextEventSummary`
  - compact summary row for a single context event / driver / theme

The long-term shape can still grow into separate provenance / warning / context modules if the patterns continue to expand.

---

## Page-by-page refactor plan

### 1. `frontend/src/pages/context-review-page.tsx`

**Current problem**
- confidence appears in several spots
- saliency, coverage, and warnings are repeated in both compact and verbose forms
- macro / industry blocks echo the same summary patterns

**Keep**
- one top summary card for macro
- one top summary card for industry
- one event list per context

**Remove / collapse**
- repeated confidence badges in both the summary row and inline metric row
- duplicate warning text shown both inline and in full lists
- repeated saliency numbers where the event label already implies importance

**Replace with**
- `ContextScoreSummary`
- `WarningSummary`
- `ContextEventSummary` + expandable `ContextEventList`

**Outcome**
- one macro summary block
- one industry summary block
- one warnings block per snapshot, collapsible by default

---

### 2. `frontend/src/pages/run-detail-page.tsx`

**Current problem**
- run-level diagnostics and plan-level diagnostics are both shown in multiple places
- LLM provenance is repeated in headers and detail sections
- warnings appear in several nested blocks

**Keep**
- one run header with status, timing, and provenance
- one run summary strip
- one canonical diagnostics section

**Remove / collapse**
- repeated LLM summary strings in table rows and helper text
- duplicated warning lists in both run summary and plan detail areas
- repeated confidence text when the plan table already shows it

**Replace with**
- `ProvenanceStrip` in the header
- `WarningSummary` near the top
- one diagnostics accordion for raw run payloads
- `DecisionMetricRow` for the small set of primary scores

**Outcome**
- the run page becomes the canonical forensic page without repeating the same diagnostics three times

---

### 3. `frontend/src/pages/recommendation-plans-page.tsx`

**Current problem**
- confidence appears in the table, calibration panel, and plan detail areas
- calibration state is re-explained in multiple headings and helper texts
- transmission details can become visually noisy

**Keep**
- table confidence column
- calibration overview section
- a compact transmission summary per plan

**Remove / collapse**
- duplicate confidence helper text under every row
- repeated calibration explanations in section subtitles and helper text
- repeated transmission tags when a single summary string is enough

**Replace with**
- `ScoreChip` for confidence
- a single calibration summary strip at the top of the page
- expandable plan details for raw transmission and evidence breakdowns

**Outcome**
- the page remains decision-oriented without re-describing calibration on every row

**Status update**
- the latest pass compressed the table cells further by merging horizon/setup, transmission channels, and calibration references into shorter combined summaries

---

### 4. `frontend/src/pages/ticker-signals-page.tsx`

**Current problem**
- each signal row carries too many diagnostic fragments
- the same shortlist / transmission / conflict metadata appears in the row and again in the expanded section
- warnings are repeated as text and badges

**Keep**
- row-level status
- confidence
- attention
- shortlist state
- one transmission summary

**Remove / collapse**
- repeated shortlist reasons in both table and detail
- repeated transmission labels and channel lists in the row summary
- raw warning text outside an expandable diagnostics block

**Replace with**
- compact row chips for shortlist / bias / attention
- one expandable detail card per signal
- `WarningSummary` for warnings

**Outcome**
- the page becomes a scanning surface first and a detail surface second

**Status update**
- the latest pass condensed the signal cards into fewer summary lines for shortlist, transmission, and cheap-scan state

---

### 5. `frontend/src/pages/context-snapshot-detail-page.tsx`

**Current problem**
- context detail pages can restate titles, labels, keys, and confidence in multiple places
- events/drivers can get verbose without adding new information

**Keep**
- snapshot identity
- score
- freshness
- active event / driver list

**Remove / collapse**
- repeated label/key fields unless they differ in a meaningful way
- duplicate score presentation in multiple metric rows

**Replace with**
- one compact summary header
- one metadata strip
- event list with optional detail lines

**Outcome**
- the detail page stays readable even when the snapshot has many events

**Status update**
- the latest pass is moving the detail page onto shared score, provenance, event, and warning primitives so the top summary and event list stay compact without losing the stored payloads

---

### 6. `frontend/src/pages/dashboard-page.tsx`

**Current problem**
- dashboard cards may echo summary info that already appears on the canonical detail pages

**Keep**
- status overview
- freshness and queue health
- latest context / run / plan links

**Remove / collapse**
- verbose provenance strings
- repeated confidence explanations

**Replace with**
- compact summary cards and canonical links

**Outcome**
- dashboard becomes an overview, not a duplicate detail page

---

### 7. `frontend/src/pages/ticker-page.tsx`

**Current problem**
- ticker performance views can repeat confidence, warnings, and outcome notes in several places

**Keep**
- performance summary
- latest plan outcomes
- recent signal history

**Remove / collapse**
- repeated warning text in tables and cards
- confidence duplication between summary stat and per-row detail

**Replace with**
- one performance summary row
- one compact outcomes table
- expandable per-plan detail if needed

---

## Suggested information hierarchy

### Level 1: orient
Show only:
- status
- primary score
- freshness
- one-line summary
- warning count

### Level 2: explain
Show:
- key drivers
- calibration summary
- context alignment
- shortlist reason summary

### Level 3: forensic detail
Hide behind expanders:
- full warnings
- raw diagnostics JSON
- full LLM provenance
- full transmission payloads
- full evidence lists

---

## Implementation order

### Phase 1: shared primitives
Add the shared components first:
- `decision-surface.tsx`
- `provenance-strip.tsx`
- `warning-summary.tsx`
- `context-summary.tsx`

### Phase 2: high-duplication pages
Refactor in this order:
1. `context-review-page.tsx`
2. `run-detail-page.tsx`
3. `recommendation-plans-page.tsx`
4. `ticker-signals-page.tsx`

### Phase 3: secondary cleanup
Then clean up:
- `context-snapshot-detail-page.tsx`
- `dashboard-page.tsx`
- `ticker-page.tsx`

### Phase 4: wording pass
Normalize labels so the same concept is not described differently across pages.

---

## Acceptance criteria

The decluttering pass is successful if:

- no page repeats the same confidence value in more than two places
- warnings are shown as one summary + one expandable list
- LLM provenance is rendered through one shared component
- table rows stay compact and scannable
- detailed diagnostics remain available on demand
- canonical pages own the full detail; other pages link rather than duplicate

---

## Related docs

- `operator-page-field-guide.md` — what each page is for
- `raw-details-reference.md` — what the stored payloads contain
- `recommendation-methodology.md` — how scores are formed
- `docs-index.md` — navigation guide
