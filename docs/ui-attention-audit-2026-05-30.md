# UI Attention Audit and Remediation Plan — 2026-05-30

**Status:** active plan

This audit judges the UI by one question: does this screen help an operator decide whether the app is performing well enough to trust, improve, or stop it?

The answer today is: not cleanly enough. The app has valuable evidence, but it spreads that evidence across too many pages with overlapping summaries, diagnostics, and run artifacts. This makes the operator spend attention on navigation instead of edge validation, data quality, broker risk, and plan review.

## Non-negotiable constraints

- Do not remove backend data, repositories, diagnostics, audit records, or research capabilities just because their current page is noisy.
- Daily UI must lead with performance, risk, freshness, and current trade-review work.
- Research/tuning tools must remain reachable, but they should not compete with daily operating pages.
- Debug pages should be link-driven from a failing run, plan, provider, worker, or tuning record; they should not be top-level destinations unless they answer a daily operator question.
- Broker exposure, broker reconciliation, edge validation, and effective outcomes must stay first-class.

## Severe findings

1. **The nav is organized by implementation artifact, not operator decision.**
   - Examples: Jobs, Ticker signals, Run debugger, Context review, Data quality, Research home, Decision samples, and two separate tuning pages are exposed as peers.
   - Impact: the user cannot tell which page is authoritative for performance.

2. **Performance evidence is fragmented.**
   - Dashboard, Recommendation plans, Recommendation quality, Research home, Decision samples, and tuning pages all present pieces of quality/performance.
   - Impact: the user can cherry-pick a favorable page or miss the authoritative edge-validation gate.

3. **Diagnostics pages are over-promoted.**
   - Run debugger, Worker logs, Context detail, Decision samples, Data quality, and Ticker signals are useful when investigating a problem, but most do not deserve daily nav slots.
   - Impact: attention is wasted on raw artifacts before the UI explains whether there is a performance or safety problem.

4. **The Jobs area mixes operations, configuration, and review.**
   - Watchlists, job scheduling, run history/debugging, ticker signals, and recommendation plans sit under one bucket.
   - Impact: the operator sees workflow plumbing instead of a clear daily loop.

5. **Context and data health are separate despite answering the same question.**
   - Context review and Data quality both answer whether inputs are trustworthy.
   - Impact: stale/noisy data can be missed because the user checked only one health page.

6. **Research home overlaps the actual research pages.**
   - It repeats performance-workbench material that already belongs in Recommendation quality and tuning-specific pages.
   - Impact: another partial source of truth for quality.

7. **Ticker signals is mostly a transitional artifact.**
   - Signals matter, but standalone signal review is secondary to plans, missed-opportunity analysis, and tuning diagnostics.
   - Impact: it encourages reviewing candidates that may not be actionable.

8. **Docs and Settings are necessary, but not performance surfaces.**
   - They should be available as utility/reference actions, not primary operating destinations.

## Page-by-page verdict

| Page | Current value | Attention verdict | Remediation |
|---|---|---|---|
| Dashboard `/` | Best candidate for operating cockpit, but must be more decisive. | **Keep and strengthen.** | Make it the only daily starting point: edge gate, broker risk, effective performance, provider/input health, open actions. |
| Recommendation plans `/jobs/recommendation-plans` | Main plan/outcome review surface. | **Keep as core.** | Rename/position as Trade Review. Keep filters and plan detail links. Remove duplicate high-level analytics once Quality owns them. |
| Broker orders `/broker-orders` | Essential for paper/live execution, reconciliation, exposure, kill-switch review. | **Keep as core when broker mode exists.** | Surface broker risk headline on Dashboard; keep page for reconciliation/exposure drilldown. |
| Recommendation quality `/recommendation-quality` | Closest thing to authoritative edge/performance page. | **Keep and make authoritative.** | Own edge-validation gate, effective outcomes, calibration, setup-family, concentration, walk-forward, tuning recommendations. |
| Watchlists `/jobs/watchlists` | Needed to define monitored universes. | **Keep as configuration, not daily review.** | Move under Configure/Lab; dashboard should show only watchlist health/actions. |
| Jobs `/jobs` | Queue/schedule operation; overlaps Watchlists and Run debugger. | **Merge/demote.** | Fold run/job controls into Watchlists or Dashboard actions. Remove from primary daily nav. |
| Ticker signals `/jobs/ticker-signals` | Useful artifact for shortlisted/cheap-scan candidates. | **Hide from primary nav.** | Link from plans, runs, and tuning diagnostics. Consider folding into Trade Review as an advanced Candidates tab. |
| Run debugger `/jobs/debugger` | Useful when a run fails/degrades. | **Replace top-level page with link-driven run detail.** | Keep Run detail; use a small recent-runs panel on Dashboard/Trade Review. |
| Run detail `/runs/:runId` | Necessary investigation page. | **Keep deep link only.** | Do not show as nav; ensure all warnings/plans link here. |
| Worker logs `/workers/:workerId` | Operational debugging only. | **Keep deep link only.** | Link from worker health/status, not nav. |
| Context review `/context` | Useful for macro/industry freshness and evidence. | **Merge with Data quality.** | Create one Evidence Health page with context freshness, provider reliability, stale/no-bars/no-news, and coverage warnings. |
| Context detail `/context/:scope/:snapshotId` | Useful evidence drilldown. | **Keep deep link only.** | Link from Evidence Health, ticker, plan, and run detail. |
| Data quality `/data-quality` | Critical input-health diagnostics. | **Keep capability, merge page.** | Merge into Evidence Health. Dashboard should summarize blocking input problems. |
| Ticker page `/tickers/:ticker` | Useful investigation by symbol. | **Keep deep link/search result only.** | Link from plans/signals/context; do not put in main nav. |
| Research home `/research` | Broad workbench, overlaps Quality and tuning. | **Drop as standalone source of truth.** | Redirect to Recommendation quality or replace with a minimal Research Lab index that only links to tools. |
| Decision samples `/research/decision-samples` | Useful for gating/tuning audits. | **Hide under tuning/debug.** | Link from Signal gating tuning and Quality diagnostics. |
| Signal gating tuning `/research/signal-gating/gating-job` | Important self-improvement tool. | **Keep in Research Lab only.** | Enter from Quality when upstream recall/precision problems appear. |
| Plan generation tuning `/research/plan-generation-tuning` | Important self-improvement tool. | **Keep in Research Lab only.** | Enter from Quality when downstream plan construction underperforms. |
| Settings `/settings` | Necessary setup and safety toggles. | **Keep utility.** | Move to utility nav/header. Preserve broker/safety toggles visibility. |
| Docs `/docs` | Useful reference, not performance. | **Demote to help/reference.** | Keep route; remove from main performance nav. |
| Login `/login` | Required. | **Keep.** | No change. |

## Proposed target information architecture

### Primary nav: four destinations

1. **Dashboard**
   - Decision: what needs attention now?
   - Must show: edge-validation gate, policy health headline, broker exposure/risk/kill switch, provider/input health, latest effective performance, active runs/jobs, open manual actions.

2. **Trade Review**
   - Decision: which current plans are worth human review or action?
   - Source: recommendation plans, broker/effective outcome status, current plan filters, plan-to-run/ticker/context links.

3. **Quality & Edge**
   - Decision: is the system developing a real edge, and where is it failing?
   - Source: Recommendation quality as authority; absorb useful Research home performance summaries. Link to tuning only when evidence indicates a specific problem.

4. **Execution & Risk**
   - Decision: are submitted/paper broker actions safe and reconciled?
   - Source: Broker orders/workbench. Dashboard mirrors only the headline.

### Secondary utility area

- **Evidence Health**: merged Context review + Data quality + provider reliability. It is important, but it supports the primary decisions.
- **Configure**: Settings, Watchlists, Jobs/schedules.
- **Research Lab**: Signal gating tuning, Plan generation tuning, Decision samples; reachable from Quality and utility nav, not daily nav.
- **Help**: Docs.

### Deep-link pages only

- Run detail
- Worker logs
- Context snapshot detail
- Ticker detail
- Decision sample detail/list if retained
- Ticker signals if not folded into Trade Review

## Remediation plan

### Phase 1 — Make authority explicit without deleting capability

- Update `operator-page-field-guide.md` and route labels so Dashboard, Trade Review, Quality & Edge, and Execution & Risk are the only daily pages.
- Demote Docs, Settings, Watchlists, Jobs, tuning, debugger, and diagnostics into utility/advanced groups.
- Add page-level notices where a page is no longer authoritative, e.g. Research home points to Quality & Edge.
- Acceptance: no route removed yet; no data loss; primary nav clearly answers daily performance questions.

### Phase 2 — Collapse duplicate performance surfaces

- Make Recommendation quality the single authority for edge/performance.
- Remove or replace overlapping Research home performance panels with links/cards into Quality & Edge.
- Remove duplicate high-level analytics from Recommendation plans where they distract from plan review; keep compact badges and links to Quality.
- Acceptance: edge gate, calibration, setup-family, concentration, walk-forward, and tuning recommendations have one primary page.

### Phase 3 — Merge input-health pages

- Create Evidence Health page by combining Data quality and Context review.
- Preserve context snapshot detail pages as drilldowns.
- Dashboard shows only blocking input/provider/context warnings and links to Evidence Health.
- Acceptance: no-bars/no-news/stale coverage/provider failures/context freshness are visible in one place.

### Phase 4 — Replace artifact pages with drilldowns

- Remove Ticker signals and Run debugger from primary nav.
- Add recent/degraded runs panel to Dashboard or Trade Review with direct links to Run detail.
- Link ticker signals from run detail, ticker detail, and tuning diagnostics; optionally fold signal list into Trade Review advanced tab.
- Acceptance: every debug artifact remains reachable from the object that caused the investigation.

### Phase 5 — Simplify configuration and research entry points

- Move Watchlists, Jobs, and Settings into Configure.
- Convert Research home into a small Research Lab launcher, or redirect it to Quality & Edge if the launcher adds no value.
- Keep Signal gating and Plan generation tuning pages behind Research Lab and contextual Quality links.
- Acceptance: self-improvement capability is preserved, but research controls no longer compete with daily performance review.

### Phase 6 — Remove dead UI only after telemetry-free proof by references

- Search internal links and redirects before deleting any page component.
- Keep compatibility redirects for old paths.
- Delete a page only when its unique data/actions have been moved or are intentionally abandoned.
- Acceptance: app effectiveness and future potential are not reduced; only duplicate attention surfaces are removed.

## What should not be removed

- Effective outcomes, broker reconciliation, edge validation, policy trust, provider observability, context snapshots, decision samples, tuning run history, and run logs.
- These are evidence assets. The audit targets UI prominence and duplication, not evidence collection.

## Success criteria

- A daily operator can answer in under one minute:
  1. Is the app safe to operate right now?
  2. Is the latest performance good, bad, or inconclusive?
  3. What plan/trade needs review now?
  4. Is any input/provider/broker issue invalidating the result?
  5. Which research/tuning action is justified by evidence?
- The number of primary nav destinations drops from many artifact pages to four decision pages plus utility/advanced access.
- No research, audit, broker safety, or tuning capability disappears without an explicit replacement path.
