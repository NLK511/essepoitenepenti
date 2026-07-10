# UI Page Content Refactor Spec — 2026-05-30

**Status:** archived implementation history

This archived record was Phase 0 of `ui-attention-audit-2026-05-30.md`.

It audits clutter inside the pages before final navigation, merging, or deletion decisions. Page removal is intentionally deferred: the final page topology should be based on simplified pages, not their current cluttered form.

## Rules for page refactors

- Each page gets one primary operator question.
- The first screen must answer that question with at most 3-5 decisive signals.
- Duplicated metrics should be replaced by compact badges and links to the authoritative page.
- Raw JSON, long tables, and verbose diagnostics should be collapsed or moved behind an advanced/details affordance unless they are the page's main job.
- Existing routes, backend payloads, audit evidence, broker safety controls, run logs, tuning histories, and research records stay intact until their replacement path is implemented and tested.
- Context review, Run debugger, and Worker logs remain distinct workflows per operator preference.

## Page content verdicts

### 1. Dashboard `/`

**Primary question:** What needs attention now, and is the system safe/trustworthy enough to review or operate today?

**Keep visible above the fold:**
- Edge/autonomy gate headline: authoritative `edge_validation_gate`, with policy health as secondary headline only.
- Broker/risk headline: kill switch, open/submitted/closing exposure, broker sync/reconciliation status.
- Input/provider/context headline: blocking provider failures, stale context, data-quality blockers.
- Current work headline: active runs/jobs and latest plans needing review.
- One compact effective-performance pulse for the selected window.

**Demote/collapse:**
- Pipeline volume metrics unless debugging throughput.
- Detailed warnings/failures lists after the top blockers.
- Any tuning-specific or calibration-detail panels that belong in Quality & Edge.

**Remove/replace duplicates:**
- Do not repeat calibration, setup-family, walk-forward, or evidence-concentration detail. Link to Quality & Edge.
- Do not show large run/debug tables. Link to Run debugger and Run detail.

**Unique actions/data to preserve:**
- Refresh/run actions that are actually daily-useful.
- Cross-links to Trade Review, Quality & Edge, Execution & Risk, Context review, Data quality, Run debugger.

**Implementation notes:**
- Refactor into a decision cockpit: `Safety`, `Performance`, `Inputs`, `Work queue`.
- Treat everything else as secondary diagnostics.

### 2. Recommendation plans / Trade Review `/jobs/recommendation-plans`

**Primary question:** Which current plans deserve human review or action, and why?

**Keep visible above the fold:**
- Review window and filters.
- Plan count/open count only as queue context.
- Compact current-window outcome status for the visible/filterable plan set.
- Main review queue table/cards with action, confidence, setup family, effective outcome/broker state, thesis, and links.

**Demote/collapse:**
- Broad analytics cards that duplicate Quality & Edge.
- Evidence concentration, setup-family, calibration, and baseline summaries.
- Large secondary tables not needed to choose a plan.

**Remove/replace duplicates:**
- Replace `Where results look strongest`, full win-rate analytics, baseline/cohort analytics with a small `Quality context` badge linking to Quality & Edge.

**Unique actions/data to preserve:**
- Plan filters.
- Manual evaluation/refresh actions.
- Plan-to-run, plan-to-ticker, plan-to-context links.
- Broker/effective outcome status and execution framing.

**Implementation notes:**
- Rename nav/page language to Trade Review only after content is narrowed.
- Keep the plan list authoritative for individual plan review, not system performance.

### 3. Recommendation quality / Quality & Edge `/recommendation-quality`

**Primary question:** Is there evidence of a real edge, where is it reliable, and what improvement action is justified?

**Keep visible above the fold:**
- `edge_validation_gate` state and missing evidence.
- Effective/broker-backed outcome counts, win rate/P&L/EV, and sample sufficiency.
- Calibration status and baseline comparison headline.
- Evidence concentration / setup-family standout summary.
- Next recommended action, if evidence supports one.

**Demote/collapse:**
- Live tuning settings and raw guardrail parameters.
- Detailed calibration buckets and reliability curves.
- Long latest assessment narrative.
- Simulated entry-miss diagnostics; keep clearly labeled as simulation-only and secondary.

**Remove/replace duplicates:**
- Do not duplicate Research home's performance-workbench layout here; absorb only the useful conclusions.
- Tuning pages should not restate quality; they should show tuning job state and candidate evidence.

**Unique actions/data to preserve:**
- Rolling windows.
- Edge gate details.
- Policy trust/effective outcomes/reliability report.
- Links to signal-gating and plan-generation tuning when the evidence indicates that specific action.

**Implementation notes:**
- Make this the only system-performance authority.
- The page should say `not enough evidence` clearly rather than filling space with weak metrics.

### 4. Broker orders / Execution & Risk `/broker-orders`

**Primary question:** Are broker-submitted/paper orders and positions safe, reconciled, and auditable?

**Keep visible above the fold:**
- Broker risk manager state: halted/allowed, kill switch reason, open exposure including submitted/closing.
- Today realized P&L and open notional.
- Reconciliation/sync freshness and errors.
- Orders needing action: failed, rejected, stale submitted, unreconciled, closing exposure.

**Demote/collapse:**
- Orders loaded/submitted/skipped counts as secondary.
- Full bracket order payload and broker response; keep under selected-order details.
- Low-value order rows that do not affect risk.

**Remove/replace duplicates:**
- Risk settings editing belongs in Settings; show current limits and link there.
- Performance belongs in Quality & Edge; this page owns broker safety and audit trail.

**Unique actions/data to preserve:**
- Manual refresh/status actions.
- Broker payload/response audit trail.
- Position lifecycle details.
- Links to run/plan.

**Implementation notes:**
- Add an `Action required` lane before raw order history.

### 5. Context review `/context`

**Primary question:** Is the shared macro/industry backdrop fresh, evidence-backed, and useful for current plans?

**Keep visible above the fold:**
- Macro freshness/status and latest summary.
- Industry coverage/freshness status and selected industry summary.
- Warnings: missing primary evidence, provider issues, contradictory drivers, stale snapshots.
- Refresh actions for macro/industry context.

**Demote/collapse:**
- Long active-driver/theme lists after the summary.
- Ontology/theme/transmission caveats unless investigating.
- Full history lists; show recent snapshots compactly and link to detail.

**Remove/replace duplicates:**
- Do not become Data quality. Link to Data quality when provider/no-news/no-bars issues explain context degradation.

**Unique actions/data to preserve:**
- Macro and industry tabs.
- Context refresh controls.
- Snapshot history and detail links.
- Driver/theme evidence.

**Implementation notes:**
- Keep distinct page as requested.
- Use a `Context trust` headline: fresh/usable, stale, degraded, missing evidence.

### 6. Data quality `/data-quality`

**Primary question:** Are bad inputs or provider failures invalidating scans, plans, or broker evaluation?

**Keep visible above the fold:**
- Issue count and blocker count.
- Top issue types: no bars, no news, stale coverage, broker rejects, provider failures.
- Affected ticker list prioritized by severity and recency.
- Filters for ticker and stale threshold.

**Demote/collapse:**
- Exhaustive issue detail rows after the prioritized list.
- Non-blocking counts when no action is needed.

**Remove/replace duplicates:**
- Do not show context narratives; link to Context review for context freshness/evidence.
- Dashboard should only show blocker summary and link here.

**Unique actions/data to preserve:**
- Audit endpoint results.
- Ticker-level issue details.
- Broker-reject message visibility.

**Implementation notes:**
- Add severity grouping: `blocking`, `degraded`, `informational`.

### 7. Run debugger `/jobs/debugger`

**Primary question:** What happened in a run, and where did it degrade or fail?

**Keep visible above the fold:**
- Filters and run list with status, warnings, duration, job type, run id.
- Selected run triage: status, warnings, persisted objects, links to full run detail and worker logs if applicable.
- Proposal-run guidance and persisted object counts.

**Demote/collapse:**
- Full metadata/artifact JSON.
- Large output excerpts unless selected.
- Delete action should remain available but visually secondary/destructive.

**Remove/replace duplicates:**
- Do not duplicate the complete run-detail walkthrough; link to Run detail for full chain.

**Unique actions/data to preserve:**
- Distinct debugger page and workflow.
- Run deletion if currently supported.
- Selection sidebar and quick triage.

**Implementation notes:**
- Keep as standalone page per operator preference.
- Add `Why this run matters` summary when warnings/failures exist.

### 8. Jobs `/jobs`

**Primary question:** What repeatable workflows exist, and what should be queued/configured now?

**Keep visible above the fold:**
- Enabled core workflows and next/manual queue actions.
- Create workflow only if the operator is in configuration mode.
- Workflow categories: generation/evaluation, context refresh, tuning/research.

**Demote/collapse:**
- Creation form by default after initial setup.
- Job counts by category unless useful as health.
- Rare research workflow controls.

**Remove/replace duplicates:**
- Watchlist configuration belongs in Watchlists.
- Run investigation belongs in Run debugger.

**Unique actions/data to preserve:**
- Create/edit/delete workflows.
- Enqueue runs.
- Schedule/enabled controls.

**Implementation notes:**
- Likely becomes part of Configure, but do not remove until workflow creation is cleaner.

### 9. Watchlists `/jobs/watchlists`

**Primary question:** Which universes are monitored and are their trading assumptions correct?

**Keep visible above the fold:**
- Watchlist count and tickers tracked.
- Saved watchlists with ticker membership and policy assumptions.
- Create/edit watchlist action.

**Demote/collapse:**
- Shorts/timing optimization stats unless they are warnings.
- Long metadata explanations.

**Remove/replace duplicates:**
- Job queueing belongs in Jobs/Dashboard actions.
- Performance belongs in Quality & Edge.

**Unique actions/data to preserve:**
- Watchlist CRUD.
- Policy display.
- Market metadata needed for scheduling/evaluation timing.

### 10. Settings `/settings`

**Primary question:** Are system credentials, execution controls, and safety/tuning defaults configured correctly?

**Keep visible above the fold:**
- Preflight/health status.
- Broker execution enabled/disabled and paper/live clarity.
- Kill switch/risk limit headline.
- Missing provider credentials or disabled required providers.

**Demote/collapse:**
- Advanced plan-generation tuning settings.
- Recent broker order table.
- Social/news fetch knobs unless provider setup is the current task.
- Slippage/friction once defaults are acceptable.

**Remove/replace duplicates:**
- Broker audit belongs in Execution & Risk.
- Tuning operations belong in Research Lab/tuning pages.

**Unique actions/data to preserve:**
- Provider credential update.
- Execution toggles and risk limits.
- Summary backend settings.
- Evaluation realism settings.

**Implementation notes:**
- Group into `Required setup`, `Execution safety`, `Data providers`, `Research/advanced`.

### 11. Research home `/research`

**Primary question:** Which advanced research or tuning workflow should be opened, if any?

**Keep visible above the fold:**
- Links/cards to Quality & Edge, Decision samples, Signal gating tuning, Plan generation tuning.
- Very compact current evidence status so the operator knows why a research action may be justified.

**Demote/collapse:**
- Full performance assessment sections.
- Confidence cohorts, entry-quality panels, rolling windows, calibration curves, walk-forward slices.

**Remove/replace duplicates:**
- Move system performance authority to Quality & Edge.
- Move calibration/baseline/evidence concentration detail to Quality & Edge.
- Move plan tuning validation detail to Plan generation tuning.

**Unique actions/data to preserve:**
- Manual performance assessment trigger if still useful.
- Links to advanced research pages.

**Implementation notes:**
- Convert to Research Lab launcher, not a duplicate workbench.

### 12. Signal gating tuning `/research/signal-gating/gating-job`

**Primary question:** Should upstream signal selection thresholds change based on decision-sample evidence?

**Keep visible above the fold:**
- Current threshold/offset and latest best result.
- Latest run status, applied/not applied, scoreable/resolved/benchmark samples.
- Controls to queue/apply tuning, with guardrail warning.

**Demote/collapse:**
- Full candidate table after top candidates.
- Manual parameter edit fields behind advanced controls.

**Remove/replace duplicates:**
- Do not explain overall edge; link to Quality & Edge.
- Do not use this page as a decision-sample browser except for tuning evidence.

**Unique actions/data to preserve:**
- Settings update.
- Tuning run history.
- Candidate result evidence.

### 13. Plan generation tuning `/research/plan-generation-tuning`

**Primary question:** Should downstream plan-construction parameters change based on guarded validation?

**Keep visible above the fold:**
- Active config, latest run, promotion gate state, whether promotion is recommended/blocked.
- Queue tuning controls.
- Winner vs baseline summary.

**Demote/collapse:**
- Process overview once the user has seen it; keep as help/disclosure.
- Search-shape detail.
- Full ranked candidate/config table behind advanced disclosure.

**Remove/replace duplicates:**
- Overall quality metrics link to Quality & Edge.
- Raw config version browsing only when investigating.

**Unique actions/data to preserve:**
- Queue/apply tuning.
- Run history.
- Promotion guardrails and config versions.
- Walk-forward validation result.

### 14. Ticker signals `/jobs/ticker-signals`

**Primary question:** Which candidates were shortlisted, blocked, or sent to deep analysis before plans were produced?

**Keep visible above the fold if retained:**
- Filters by window, ticker, run, shortlisted/deep-analysis status.
- Counts for shortlisted/deep-analysis/tailwind.
- Candidate list with reason, confidence, transmission bias, and links to run/ticker/plan if available.

**Demote/collapse:**
- Advanced signal diagnostics.
- Cheap-scan component details.

**Remove/replace duplicates:**
- Actionable plan review belongs in Trade Review.
- Upstream threshold evidence belongs in Signal gating tuning.

**Unique actions/data to preserve:**
- Signal snapshots and shortlist rationale.
- Linkage to source runs and downstream plans.

**Implementation notes:**
- This is still the strongest demotion candidate after internal cleanup. It may become a Trade Review advanced `Candidates` tab or stay as a Research Lab/debug page.
- **Done now:** page is titled Candidate signals under Research Lab, explicitly frames itself as a pre-plan diagnostic surface, and links to Trade Review and Signal gating tuning as the authoritative downstream destinations.

### 15. Ticker detail `/tickers/:ticker`

**Primary question:** Why does this single ticker need attention, and what ticker-specific context explains its latest plans?

**Keep visible above the fold:**
- Latest plan action/confidence and selected-window plan/order/bar availability.
- Price chart with actionable plan overlays.
- Links back to Trade Review and Quality & Edge.

**Demote/collapse:**
- Ticker-local win rate, profit, average confidence, and plan mix.
- Relationship and plan-history detail unless the operator opens overview/plans.

**Remove/replace duplicates:**
- Do not imply ticker-local performance is system edge; Quality & Edge remains authoritative.

**Unique actions/data to preserve:**
- Chart plan toggles.
- Latest plan context.
- Full ticker plan history.
- Raw ticker JSON link.

**Implementation notes:**
- **Done now:** page chrome now uses Evidence & diagnostics language, first screen leads with the ticker-attention question and latest-plan/data availability, links to Trade Review and Quality & Edge, and demotes ticker-local performance into a disclosure.

### 16. Run detail `/runs/:runId`

**Primary question:** What did this run produce, and where did the execution chain degrade?

**Keep visible above the fold:**
- Run status and warning/error headline.
- Counts for objects written, plans, and broker orders.
- Links back to Run Debugger and Trade Review.
- Section tabs for the full scan/shortlist/signal/plan/broker/context chain.

**Demote/collapse:**
- Timing, scheduling, identity, and support-artifact metadata.
- Long tables inside their selected chain section only.

**Remove/replace duplicates:**
- Run Debugger owns run triage/search; Run Detail owns full selected-run chain review.
- Trade Review owns current plan queue decisions.

**Unique actions/data to preserve:**
- Full chain sections.
- Delete run action.
- Broker order resubmit/cancel actions.
- Workflow result rendering for non-proposal runs.

**Implementation notes:**
- **Done now:** page chrome now uses Evidence & diagnostics language, first screen leads with run production/degradation signals, Run Debugger/Trade Review links are explicit, and timing/identity metadata is collapsed.

### 17. Context snapshot detail `/context/:scope/:snapshotId`

**Primary question:** Is this stored context snapshot fresh, covered, and supported by evidence?

**Keep visible above the fold:**
- Context score summary: confidence, saliency, coverage, freshness, and status.
- Snapshot summary text.
- Scope/status/id/industry badges.
- Links back to Context Review, Data Quality, and source run when available.

**Demote/collapse:**
- Summary provenance metadata.
- Source breakdown/provider mix.
- Ontology/raw JSON detail.

**Remove/replace duplicates:**
- Context Review owns the current backdrop verdict; this page owns one-snapshot evidence inspection.
- Data Quality owns provider/input failure follow-up.

**Unique actions/data to preserve:**
- Industry selector.
- Top events/drivers.
- Triaged primary evidence.
- Warnings/missing inputs.
- Raw metadata JSON.

**Implementation notes:**
- **Done now:** page chrome now uses Evidence & diagnostics language, first screen leads with the snapshot-evidence question, Context Review/Data Quality links are explicit, and summary provenance/source breakdown are collapsed as reference detail.

### 18. Docs `/docs`

**Primary question:** Which guide, spec, or reference page answers the current operating question?

**Keep visible above the fold:**
- Search and document navigation.
- Fast links to the operator guide, recommendation methodology, and edge-validation standard.
- Selected document content.

**Demote/collapse:**
- No removal of document tree or sections; docs browsing is the page's main job.

**Remove/replace duplicates:**
- Page chrome should use Help/Docs language, not imply operational authority.

**Unique actions/data to preserve:**
- Full-text search.
- Grouped document tree and section navigation.
- Markdown rendering, internal links, glossary tooltips, and Mermaid diagrams.

**Implementation notes:**
- **Done now:** Docs now opens with a documentation-map card for common operator questions while preserving full search/navigation and document rendering.

## Cross-page authority map

- **Daily authority:** Dashboard.
- **Plan/action authority:** Trade Review.
- **System performance/edge authority:** Quality & Edge.
- **Broker safety authority:** Execution & Risk.
- **Context authority:** Context review.
- **Input/provider authority:** Data quality.
- **Run investigation authority:** Run debugger + Run detail.
- **Worker investigation authority:** Worker logs.
- **Configuration authority:** Settings, Watchlists, Jobs.
- **Tuning authority:** Signal gating tuning and Plan generation tuning.

## Implementation sequence after this spec

1. Refactor Dashboard content hierarchy first. **Done:** dashboard first screen now uses Safety, Performance, Inputs, and Work queue cards; secondary performance, warning/failure lists, and pipeline volume are collapsed as supporting diagnostics.
2. Refactor Recommendation plans into Trade Review by removing duplicate analytics from the first screen. **Done:** page title now reads Trade review, the first screen explains that it is a plan queue rather than system-performance authority, and duplicated win-rate/evidence-concentration analytics were removed from the top context card in favor of a Quality & Edge link.
3. Refactor Recommendation quality into the single edge/performance authority. **Done:** page is now titled Quality & Edge, the first screen leads with the authoritative edge-validation gate, effective outcomes, reliability headlines, and evidence-backed next actions; live tuning settings and simulation-only entry diagnostics are demoted behind disclosures.
4. Refactor Broker orders into an action-required Execution & Risk page. **Done:** page is now titled Execution & Risk, first-screen metrics focus on risk state, kill switch, exposure, and sync freshness; an action-required lane appears before order history; order-volume counts and raw request/response payloads are collapsed as supporting audit detail.
5. Refactor Context review and Data quality separately, with cross-links but no merge. **Done:** Context review now leads with a Context trust card and links to Data quality while keeping macro/industry workflows distinct; industry aggregate coverage is collapsed as supporting evidence. Data quality now leads with input-trust severity, blocker/degraded counts, and a Context review link; raw issue-type counts are collapsed.
6. Refactor Run debugger while preserving it as a standalone diagnostics page. **Done:** debugger now starts with a run-triage card, preserves filters and the recent-run selector, and adds a selected-run `Why this run matters` summary before full run metadata; repeated warning display was removed from the lower summary card.
7. Convert Research home into a launcher after Quality & Edge absorbs its useful performance content. **Done:** Research is now a Research Lab launcher with compact evidence status, direct links to Quality & Edge, signal-gating tuning, plan-generation tuning, and decision samples; the assessment narrative and simulation-only entry-framing research are collapsed as reference diagnostics.
8. Re-evaluate nav/page topology only after steps 1-7. **Done:** navigation now groups pages by decision authority: Operate (Dashboard, Trade Review, Quality & Edge, Execution & Risk), Evidence & diagnostics (Context review, Data quality, Run debugger), Configure (Watchlists, Jobs, Settings), Research Lab (launcher, tuning, decision samples, candidate signals), and Help. No routes were removed.
9. Refocus configuration pages without removing setup capability. **Done:** Settings now leads with configuration status, broker execution, risk manager, provider credentials, and summarization; broker audit is labeled as reference-only with Execution & Risk as authority; news/evaluation realism controls are no longer open by default. Jobs now leads with workflow-configuration status and only opens the creation form by default when no jobs exist. Watchlists now leads with universe-configuration status and only opens the creation form by default when no watchlists exist.
10. Refocus tuning pages around evidence-backed action. **Done:** Signal gating tuning now leads with the upstream-selection question, links back to Quality & Edge, puts dry-run/apply controls in the first decision card, demotes manual parameter edits behind an advanced disclosure, and collapses stored run summary JSON. Plan generation tuning now leads with the downstream plan-framing question and Quality & Edge link; process overview, search shape, ranked candidate table, and config versions are collapsed as supporting evidence/audit detail.
11. Refocus decision samples as sample-level research evidence. **Done:** Decision samples now live under Research Lab language, lead with the question of which discarded/borderline signals deserve review, keep high-priority samples as the main path, and collapse the full archive plus usage guidance as reference detail.
12. Reconcile route chrome language. **Done:** layout route titles/descriptions now use direct authority labels instead of metaphorical page names, matching the new nav and operator guide.
13. Refocus ticker detail as a single-ticker diagnostic page. **Done:** ticker detail now leads with the single-ticker attention question, latest-plan/data availability signals, and links back to Trade Review/Quality & Edge; ticker-local performance and plan mix are collapsed as supporting context.
14. Refocus run detail as the full selected-run chain review. **Done:** run detail now leads with status, warning/error, object, plan, and broker-order counts; timing/identity metadata is collapsed; links back to Run Debugger and Trade Review clarify ownership.
15. Refocus context snapshot detail as one-snapshot evidence inspection. **Done:** context snapshot detail now leads with the freshness/coverage/evidence question, links back to Context Review and Data Quality, and collapses provenance/source breakdown as reference detail.
16. Refocus Docs as Help navigation. **Done:** Docs now leads with common operator documentation questions and fast links while preserving full-text search, grouped navigation, section links, Markdown rendering, glossary tooltips, and Mermaid support.

## Completion criteria for Phase 0

- Every candidate page has a one-question mandate.
- Every candidate page has explicit keep/demote/remove guidance.
- Operator preferences are encoded: Context review stays distinct, Run debugger stays distinct, Worker logs stay as-is.
- Route/nav removal remains deferred until the page-internal refactors are complete enough to evaluate real overlap.
