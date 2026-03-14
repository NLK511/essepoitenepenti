# Features and Capabilities

Trade Proposer App already covers the main operator loop: define what to watch, enqueue work, inspect the resulting recommendations, understand degraded runs, evaluate recommendation outcomes, review recommendation history, and adjust the summary configuration without leaving the product. The current implementation is still intentionally lightweight, but it is no longer just a shell around scripts.

## What operators can do now

The dashboard surfaces the latest recommendations and runs as separate things, makes degraded execution visible at a glance, and links directly to jobs, watchlists, settings, docs, the debugger, and ticker drill-down pages. Watchlists can be created and stored in the database. Jobs can be created, edited inline, deleted, executed through the worker path, and converted into a watchlist. Jobs now also support first-class workflow types: proposal generation, recommendation evaluation, and weight optimization. Proposal-generation jobs still use exactly one source: either manual tickers or a single watchlist. Evaluation and optimization jobs are maintenance workflows and do not require ticker sources.

Successful proposal runs persist recommendation records with direction, confidence, entry, stop loss, take profit, recommendation state, and a compact indicator summary. Failed runs remain visible as failures with error context rather than being replaced with synthetic outputs. Recommendation history supports filtering by ticker, direction, recommendation state, and warning state, plus sorting and pagination. Evaluation workflows now also run through the shared scheduler/worker path and persist run summaries in the app. Operators can queue both full evaluation runs and single-recommendation evaluation runs from the UI, and those manual actions now create normal auditable run records instead of bypassing run history. Evaluation and optimization runs now render in the debugger and run detail pages as workflow-specific result cards instead of mostly opaque JSON blobs, including evaluation scope/trigger details and optimization backup/fingerprint summaries. Weight optimization workflows now persist both run summaries and artifact metadata, including before/after `weights.json` fingerprints and backup metadata. From recommendation history or the dashboard, operators can open a ticker drill-down page that combines app-side recommendation history with prototype trade-log outcome data for the same ticker.

## Diagnostics, debugging, and documentation

The product already treats diagnostics as first-class output, but diagnostics now belong to the run/output investigation workflow rather than to the core recommendation object itself. Run detail and debugger views surface warning and failure context directly, while richer raw details remain available on demand through `analysis_json`, `raw_output`, timestamps, and timing breakdowns. For optimization workflows, those views now also surface nested backup and fingerprint metadata more clearly instead of hiding them inside raw JSON blobs. Recommendation detail pages focus on the trade-ready object first and link back to the source run for traceability. Ticker pages expose raw prototype analysis payloads so an operator can compare a ticker’s recommendation history with the prototype’s recorded trade outcomes.

The in-app docs browser is also part of the operator workflow. It indexes `README.md` and every markdown document under `docs/`, supports full-text search, renders markdown directly, and now groups documents into collapsible sections so setup and user-oriented material stays near the top while product and engineering references stay lower in the page. It also includes dedicated reference material for raw-details fields and recommendation methodology.

## Summary engine and prototype-backed analysis

Recommendation generation still flows through the integrated prototype subprocess path. Summary generation is configurable from `/settings`: operators can choose `pi_agent` or `openai_api`, set a model, adjust timeout and max tokens, and edit the summary prompt. Provider credentials are persisted encrypted at rest and passed through to the prototype subprocess using the environment variables the prototype actually expects.

The integrated summarizer now maintains a persistent article-summary cache. Cache reuse is conservative: it depends on normalized article identity, an article-content fingerprint, and a summary-configuration fingerprint. Repeated articles can therefore reuse prior per-article summaries across future runs, but if the cache-assisted path fails, the summarizer falls back to the older whole-payload summary path so recommendation generation still proceeds.

Supported external news and social services used by the integrated prototype:
- Yahoo Finance: https://finance.yahoo.com/
- NewsAPI: https://newsapi.org/
- Alpha Vantage: https://www.alphavantage.co/
- Finnhub: https://finnhub.io/
- Alpaca News: https://alpaca.markets/
- Nitter instances: https://github.com/zedeus/nitter/wiki/Instances

## What is only partial or still missing

Queued execution and worker processing are already in place, and the self-improvement loop is now present in the product shape: scheduled recommendation evaluation and scheduled weight optimization are first-class app workflows. What remains incomplete is hardening and polish around those workflows: scheduler behavior still needs further hardening, optimization rollback support is not implemented, optimization thresholds are not yet app-configurable, and evaluation truth still depends on prototype trade-log synchronization. The app has improved secret handling through encryption at rest, but it still lacks credential rotation. Auth, RBAC, tenancy, and broader deployment monitoring are also not implemented yet.

## Current strengths and next needs

The strongest current operator capabilities are straightforward local startup, visible failure handling, persisted recommendation history, ticker-specific review, configurable summarization, and in-product documentation. The most important next steps are stronger scheduler guarantees, credential rotation, broader operational hardening, and incremental frontend polish without adding unnecessary client-side complexity.
