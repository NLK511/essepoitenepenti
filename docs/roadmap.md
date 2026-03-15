# Roadmap

## Current status
Trade Proposer App is now executing its critical workflows entirely inside this repository:
- **Persistent state**: Watchlists, jobs, runs, recommendations, and settings live in a single schema and remain queryable from the UI or API.
- **Operator UI**: The React/Vite SPA offers the dashboard, debugger, jobs, watchlists, settings, docs browser, and ticker views required for each workflow.
- **Execution model**: The worker-backed queue persists job metadata, honors concurrency limits, and logs timing/diagnostic payloads for reproducibility.
- **Feature-rich diagnostics**: Every run emits structured `analysis_json` (metadata/trade/summary/news/sentiment/context/feature vectors/weights/diagnostics), plain JSON versions of the raw/normalized feature vectors, aggregations, and the confidence weights used for scoring.
- **LLM/context pipeline**: The summary toggle now supports the default headline digest, OpenAI, and a configurable Pi CLI backend (`pi_agent`). The summarizer stores the narrative text, backend/model/runtime metadata, and any `summary_error` or `llm_error` inside `analysis_json.summary`, while news ingestion feeds unified `news_items` with per-item sentiment scores into the diagnostics and the fused `analysis_json.sentiment.enhanced` block.

- **App-native weight optimization**: Scheduled optimization jobs now read resolved recommendations from the app DB, adjust the tracked `weights.json`, and keep backups/artifacts so the maintenance workflow requires no prototype dependencies.

## Phase 1: Operational hardening (completed)
The immediate risk-reduction efforts are now in place:
- **Scheduler correctness**: Cron-like scheduling, atomic job claiming, and clearer crash recovery heuristics went live with the worker/queue implementation.
- **Structured pipeline contract**: The app documents and enforces `analysis_json`, the feature vectors, aggregations, confidence weights, and timing metadata so downstream tools and dashboards parse the outputs reliably.
- **Worker reliability and diagnostics**: The worker now surfaces categorized diagnostics, provider errors, and warnings in the debugger/run detail views so operators can filter and group by failure type.
- **Preflight guardrails**: `AppPreflightService` verifies `pandas`, `yfinance`, and the checked-in `weights.json` file, and `/api/health/preflight` reports those statuses for early warning.

## Phase 2: Self-contained intelligence (in progress)
We continue shrinking the prototype’s surface while rebuilding its signals inside this repo:
- **App-native scoring**: `ProposalService` now handles history ingestion, feature engineering, normalization, inference, and diagnostics without touching the prototype repo. The pipeline stores `analysis_json` version 2.0 (metadata, trade, summary, news, sentiment, context flags, feature vectors, aggregations, weights, diagnostics) alongside the run so all tooling sees the same structured payload.
- **App-native weight optimization**: The optimization workflow now uses resolved recommendations from the app database, adjusts the in-repo `weights.json`, and keeps backups/artifacts in-sync so the scheduled job no longer depends on any prototype scripts.
- **Enhanced sentiment coverage**: `NaiveSentimentAnalyzer` now inspects a broader keyword/fallback heuristic set so headline-only runs still produce calibrated compound scores instead of defaulting to zero.
- **LLM-enhanced sentiment & summaries**: The internal summary service calls either OpenAI or the configured `pi_agent` CLI (respecting the shared `PI_CODING_AGENT_DIR`, CLI args, and workspace) to produce the long-form narrative, persists backend/model/runtime metadata, and records fallback diagnostics whenever the service cannot complete. That narrative merges with the news sentiment and technical indicators to produce `analysis_json.sentiment.enhanced` in addition to the insured headline digest (`analysis_json.news.digest`).
- **Evaluation truth & diagnostics**: The evaluation workflow now lives entirely inside Trade Proposer App; it downloads the same recent price history that `ProposalService` uses, compares entry/stop/take snapshots against the recorded stops, and persists WIN/LOSS/PENDING states without shelling out to the prototype. This keeps outcome tracking, diagnostics, and audit trails on the app-native code path while prototype logs remain available purely for reference.
- **Remaining Phase 2 work**:
  - Continue enriching `NaiveSentimentAnalyzer` so more keywords yield non-zero compound scores and the analyzer can weight headlines/summaries differently.
  - Surface the structured analysis payloads (news items, summary metadata, context flags, feature vectors) inside the UI debugger and run detail page for easier operator validation.
  - Keep polishing scheduler/worker reliability (e.g., ensuring multi-ticker runs surface partial failures via the same in-app scoring logic) before retiring the legacy prototype flags entirely.

## Phase 3: Security & production readiness
- **Credential lifecycle**: Implement rotation, re-encryption, and optionally support external secret backends.
- **Authentication baseline**: Introduce lightweight single-user auth (with RBAC/tenancy left for later).
- **Observability**: Structured logging, run-level correlation IDs, and system health heartbeats for production deployments.

## Phase 4: Expansion (lower priority)
- **Exporting/reporting**: Historical run exports and reporting helpers.
- **Retry logic**: Dead-letter queues and intelligent retries for transient external failures.
- **Service extraction**: Optional extraction of ingestion or analysis workloads into microservices if scale demands.

## Related docs
- `architecture.md`: System design and component boundaries.
- `getting-started.md`: Setup and local development guide.
- `features-and-capabilities.md`: Detailed product feature list.
- `phase-2-app-native.md`: Strategy, diagnostics, and nagging gaps for Phase 2.
