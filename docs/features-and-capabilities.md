# Features and Capabilities

Trade Proposer App already covers the main operator loop: define what to watch, enqueue work, inspect recommendations, understand degraded runs, evaluate outcomes, review history, refresh shared sentiment, and adjust configuration without leaving the product.

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
- Inspect recent snapshots from the sentiment page and open snapshot detail views.
- Manually queue or immediately execute macro and industry refresh workflows.
- Trace which snapshot IDs were used by a run or recommendation through the detail views.
- Surface snapshot freshness in `/api/health` and `/api/health/preflight` so stale shared context shows up before operators trust new proposals.
- Macro refresh themes currently include U.S. rates/inflation, European monetary policy, and geopolitical risk topics such as war or military tensions.
- Nitter results are ranked by a relevance scorer so the strongest, most informative posts are kept first; see `docs/nitter-social-relevance-scoring.md`.

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

Recommendation generation now flows entirely through the app-native pipeline. `ProposalService` fetches price history via `yfinance`, builds technical features with `pandas`, normalizes them, applies the stored weights (`src/trade_proposer_app/data/weights.json`), and combines them with sentiment context.

That sentiment context is layered:
- **macro sentiment** comes from the latest shared macro snapshot
- **industry sentiment** comes from the latest shared industry snapshot for the ticker's mapped industry
- **ticker sentiment** is computed live during proposal generation
- **enhanced sentiment** may incorporate the summary narrative and technical context

News ingestion runs through `NewsIngestionService`, which pulls configured articles, deduplicates links, normalizes them into a unified `news_items` structure, and emits sentiment diagnostics that feed both the feature vector and the operator-facing payloads.

When operators select the `openai_api` or `pi_agent` backend, the app sends the digest and a concise technical snapshot to the summarizer. The resulting narrative and metadata are stored in `analysis_json.summary`; any failures are stored there too.

## What is strong

The product is most effective where one workflow feeds the next without leaving the app:
- proposal creation and execution
- auditable run persistence
- evaluation and optimization on the same data path
- structured diagnostics visible in the UI
- shared sentiment snapshots reused across many recommendations

That combination gives the app a clear operational identity instead of leaving it as a prototype shell.

## What is still weak or partial

The weakest areas are operational rather than analytical:
- scheduler and worker reliability still need more hardening around overlaps, crash recovery, and partial failures
- optimization thresholds and tuning controls are still not sufficiently operator-configurable
- auth, RBAC, tenancy, and broader deployment observability remain incomplete
- credential lifecycle work is behind the product's growing provider surface

The sentiment stack is also now coherent enough that the biggest remaining question is not feature completeness but measured effectiveness. More sentiment sources and heuristics should not be added faster than the team can evaluate whether they improve recommendation quality.

## Critical assessment

The overall feature set is directionally consistent with the stated goal of a self-contained, operator-facing trade workflow system. The strongest consistency is that proposal generation, evaluation, optimization, diagnostics, and shared sentiment now all live inside one product boundary.

The main inconsistency to avoid going forward is roadmap drift: once a capability is delivered, it should stop appearing as a major future deliverable in multiple docs. This repository had accumulated some of that drift around structured diagnostics, LLM summaries, and shared sentiment snapshots. Those duplicates have been reduced so the docs focus on current behavior and the remaining gaps.
