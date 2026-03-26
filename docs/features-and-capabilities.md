# Features and Capabilities

Trade Proposer App already covers the main operator loop: define what to watch, enqueue work, inspect recommendations, understand degraded runs, evaluate outcomes, review history, refresh shared sentiment, and adjust configuration without leaving the product.

In realistic terms, the product is now strongest as an operator-facing analysis, candidate-ranking, and trade-framing system. It is not yet a validated universal short-horizon predictor, and the docs should reflect that explicitly.

## Governing principle: signal integrity

Any component that contributes to recommendation generation must be transparent about missing inputs. When keywords, providers, snapshots, or aggregators are unavailable the app emits explicit `NEUTRAL`/zero outputs and surfaces diagnostics rather than inventing fallback heuristics that could hide upstream problems.

This principle is consistently applied in the best parts of the product. It is also the right constraint to keep, even when it makes the outputs look less flattering, because it preserves operator trust.

## What operators can do now

### Workflow operations
- Create, edit, delete, and execute jobs.
- Run proposal generation, recommendation evaluation, weight optimization, and sentiment refresh through the same auditable run system.
- Convert proposal jobs into watchlists and schedule them.
- Inspect queued, running, completed, failed, cancelled, and warning-heavy runs from the debugger and run detail pages.

### Recommendation lifecycle
- Persist proposal outputs with direction, confidence, entry, stop loss, take profit, recommendation state, and compact indicator summaries.
- Store structured diagnostics beside each recommendation (`analysis_json`, feature vectors, aggregations, confidence weights, warnings, and raw output).
- Evaluate recommendations through the app-native price-history path rather than a prototype script.
- Review ticker pages with recommendation history and app-derived outcome summaries.

### Shared sentiment operations
- Persist shared macro and industry sentiment as reusable snapshots.
- Generate a short snapshot summary for each macro/industry refresh that stays anchored to the prior snapshot's summary so operators can see continuity and the latest change in one glance.
- Inspect recent snapshots from the sentiment page and open snapshot detail views.
- Manually queue or immediately execute macro and industry refresh workflows.
- Trace which snapshot IDs were used by a run or recommendation through the detail views.
- Surface snapshot freshness in `/api/health` and `/api/health/preflight` so stale shared context shows up before operators trust new proposals.
- Macro refresh themes currently include U.S. rates/inflation, European monetary policy, and geopolitical risk topics such as war or military tensions.
- Nitter results are ranked by a relevance scorer so the strongest, most informative posts are kept first; see `docs/nitter-social-relevance-scoring.md`.
- A settings toggle can restrict Nitter to macro and industry sentiment only, leaving ticker sentiment to other sources.

### Redesign execution path now present
- Persist watchlists with richer trading and scheduling metadata: `description`, `region`, `exchange`, `timezone`, `default_horizon`, `allow_shorts`, and `optimize_evaluation_timing`.
- Inspect derived watchlist timing and warnings through `GET /api/watchlists/{watchlist_id}/policy`, `GET /api/watchlists/policies`, and the frontend watchlist/run-detail operator views.
- Watchlist-backed proposal jobs now run through a real staged orchestration flow:
  1. cheap scan across all watchlist tickers
  2. shortlist selection using a dedicated cheap-scan signal model
  3. deep analysis only for shortlisted names
  4. persistence of redesign outputs for every scanned ticker
- Persist redesign-domain objects for:
  - macro context snapshots
  - industry context snapshots
  - ticker signal snapshots
  - recommendation plans
  - recommendation outcomes
- Macro and industry refresh runs now also write first-generation context snapshots, so those redesign objects are no longer schema-only for context refresh jobs.
- Those context writers now use primary news first and social evidence second, while still warning explicitly when news coverage is thin or degraded.
- Query those new objects through read APIs:
  - `GET /api/context/macro`
  - `GET /api/context/industry`
  - `GET /api/context/ticker-signals`
  - `GET /api/recommendation-plans`
  - `GET /api/recommendation-outcomes`
- Filter redesign objects by `run_id` and inspect them directly from run detail.
- Browse ticker signals and recommendation plans outside individual runs through dedicated UI pages.
- Queue global or scoped recommendation-plan evaluation runs from the recommendation-plans workflow and inspect the latest stored outcome directly on each plan.
- Inspect cheap-scan diagnostics, component scores, shortlist rules, rejection counts, and per-ticker shortlist decisions in persisted run payloads and redesign objects.
- Review shortlist reasoning directly in operator workflows: run detail now shows shortlist thresholds, lane limits, catalyst thresholds, rejection counts, and per-ticker shortlist outcomes, while ticker-signal views show shortlist rank, lane, catalyst proxy, transmission bias/alignment, and rejection reasons without forcing operators into raw JSON first.
- Watchlist orchestration now uses a redesign-native `TickerDeepAnalysisService` path for deep analysis instead of routing normal watchlist deep analysis through `ProposalService.generate(...)`.

Current limitation:
- manual ticker proposal jobs still use the legacy per-ticker proposal path
- macro and industry refresh runs do now write context objects through event-ranked, news-first transitional writers that prioritize stronger official/trade/major sources before social confirmation, but they are still heuristic rather than a fully mature event pipeline
- watchlist deep analysis now runs through its own native execution path, but it still reuses some legacy proposal-service internals and payload conventions rather than a fully separated ticker engine
- recommendation-plan outcome persistence and evaluation are now first-class, watchlist-backed plan generation now records setup-family and decomposed confidence details, operator workflows can inspect grouped calibration summaries by confidence bucket and setup family, watchlist-backed action gating now applies calibration-aware confidence-threshold adjustments for underperforming buckets/setup families, recommendation-plan workflows now expose baseline cohort comparisons (actual actionable plans vs high-confidence, cheap-scan-attention, momentum-lane, and catalyst-lane slices), and watchlist orchestration now carries richer ticker transmission summaries plus a small catalyst/event shortlist lane so purely technical ranking does not dominate every deep-analysis slot; run detail and recommendation-plan browse views now surface transmission bias/alignment, action reasons, and effective threshold context alongside the stored plans; full recalibration remains early and heuristic

> **Enable the Nitter source**
>
> Toggle `social_sentiment_enabled` and `social_nitter_enabled` to `true` through the Settings screen (or POST `/api/settings/social`).
> Point `social_nitter_base_url` at your running Nitter instance and adjust the timeout, item, and window controls (`social_nitter_timeout_seconds`,
> `social_nitter_max_items_per_query`, `social_nitter_query_window_hours`, `social_nitter_include_replies`) as needed. Once those settings are saved, the macro and industry refresh jobs query the configured Nitter endpoint for the macro/industry keyword profiles.

### Diagnostics and explainability
- Render structured `analysis_json` sections in the run detail UI instead of forcing operators to parse raw blobs.
- Show news coverage, sentiment coverage, context flags, feature vectors, aggregations, and weights.
- Keep workflow-specific cards for evaluation and optimization runs so those outputs are not hidden inside opaque JSON.
- Preserve warnings, provider errors, and timing metadata as first-class investigation artifacts.

### Documentation and operator UX
- Browse markdown docs in-app with full-text search.
- Use responsive navigation and condensed layouts on smaller screens.
- Configure summarization and providers from the settings UI.

## Analysis pipeline

Recommendation generation now flows entirely through the app-native pipeline. `ProposalService` fetches price history via `yfinance`, builds technical features with `pandas`, normalizes them, applies the stored weights (`src/trade_proposer_app/data/weights.json`), and combines them with broader context and sentiment.

That broader context is currently layered as:
- **macro sentiment/context** from the latest shared macro snapshot or context object
- **industry sentiment/context** from the latest shared industry snapshot or context object for the ticker's mapped industry
- **ticker sentiment** computed live during proposal generation
- **enhanced sentiment** that may incorporate the summary narrative and technical context

News ingestion runs through `NewsIngestionService`, which pulls configured articles, deduplicates links, normalizes them into a unified `news_items` structure, and emits sentiment diagnostics that feed both the feature vector and the operator-facing payloads.

The redesign direction is now explicitly:
- macro and industry should become more event-centric and saliency-first
- source quality should matter more than raw source count
- social should remain supporting evidence for macro/industry rather than the primary truth layer
- cheap scan should remain a cost-saving shortlist layer, not the main trade-quality engine

When operators select the `openai_api` or `pi_agent` backend, the app sends the digest and a concise technical snapshot to the summarizer. The resulting narrative and metadata are stored in `analysis_json.summary`; any failures are stored there too.

## What is strong

The product is most effective where one workflow feeds the next without leaving the app:
- proposal creation and execution
- auditable run persistence
- evaluation and optimization on the same data path
- structured diagnostics visible in the UI
- shared sentiment/context snapshots reused across many recommendations
- watchlist orchestration that now makes shortlist and rejection logic operator-visible

That combination gives the app a clear operational identity instead of leaving it as a prototype shell.

## What is still weak or partial

The weakest areas are operational rather than analytical:
- scheduler and worker reliability still need more hardening around overlaps, crash recovery, and partial failures
- optimization thresholds and tuning controls are still not sufficiently operator-configurable
- auth, RBAC, tenancy, and broader deployment observability remain incomplete
- credential lifecycle work is behind the product's growing provider surface

The biggest product-level gap is now the **remaining redesign migration**:
- watchlist-backed proposal jobs do have a redesigned write/orchestration path, but manual ticker proposal jobs still run through the legacy path
- macro and industry refresh runs now write context objects through event-ranked, news-first transitional writers, but those writers still need richer multi-step event extraction and source hierarchy beyond their current heuristic saliency model
- ticker signals and recommendation plans are now produced by a real watchlist orchestration path, and deep analysis now executes natively for watchlist runs, but the underlying analysis logic still reuses parts of the legacy proposal engine internals
- outcome tracking for `RecommendationPlan` objects is now first-class, but setup-family evaluation and confidence calibration still need to mature beyond stored fields and buckets

The biggest analytical caution is that coherent outputs do not yet equal measured edge. Right now the product can realistically claim strong operator support, explainability, and trade-candidate structuring. It should not yet claim broad predictive skill across all names and regimes until recommendation outcomes show that the redesign path is actually improving decision quality.

The sentiment stack is also now coherent enough that the biggest remaining question is not feature completeness but measured effectiveness. More sentiment sources and heuristics should not be added faster than the team can evaluate whether they improve recommendation quality.

## Critical assessment

The overall feature set is directionally consistent with the stated goal of a self-contained, operator-facing trade workflow system. The strongest consistency is that proposal generation, evaluation, optimization, diagnostics, and shared sentiment now all live inside one product boundary.

The most realistic near-term product identity is:
- operator-facing market analysis
- watchlist triage and candidate ranking
- explainable trade framing
- recommendation storage that can later be truth-tested against outcomes

The app is not yet a justified "few-day swing predictor" in the strong sense. The missing pieces are not mainly more UI or more schemas; they are recommendation outcome measurement, redesign-native deep analysis, event-centric context extraction, setup-aware recommendation logic, and confidence calibration.

The main inconsistency to avoid going forward is roadmap drift: once a capability is delivered, it should stop appearing as a major future deliverable in multiple docs. This repository had accumulated some of that drift around structured diagnostics, LLM summaries, and shared sentiment snapshots. Those duplicates have been reduced so the docs focus on current behavior and the remaining gaps.
