# Phase 2: App-native Outcomes

This document captures the ongoing transition that makes Trade Proposer App fully self-contained. Phase 2 today means operating and improving the internal scoring pipeline without ever shelling out to a separate prototype repository, reintroducing the missing diagnostics/summary signals natively, and documenting the dependencies or fallbacks operators need to trust the outputs.

## Progress recap

- **Self-contained scoring**: `ProposalService` now orchestrates the end-to-end pipeline (price ingestion via `yfinance`, feature construction with `pandas`, normalization, weights application, diagnostics, and the recommendation agreement workflow) all from within this repository.
- **Rich diagnostics**: Each run persists `analysis_json` (now organized into metadata/trade/summary/news/sentiment/context/feature-vector sections), the raw/normalized feature vectors, aggregations, confidence weights, and RunDiagnostics details so every signal remains auditable without peeking into an external tool.
- **Configurable summarization**: `SummaryService` invokes the configured OpenAI or `pi_agent` CLI backend, parses the streamed JSON responses, and captures backend/model/runtime metadata plus `llm_error`/`summary_error`. When the summarizer does not run, the headline digest saved under `analysis_json.news.digest` is still available as the fallback narrative.
- **In-app news, sentiment, and Pi CLI coverage**: News ingestion, NaiveSentiment analysis, and the Pi CLI references now live in-app: `NewsIngestionService` produces unified `news_items` (title, summary, publisher, link, published_at, compound score), `analysis_json.news` exposed feed diagnostics, and the Pi CLI invocation reuses the configured directory/skill set via `PI_CODING_AGENT_DIR` and `pi_cli_args`.
- **App-native evaluation**: The evaluation service now downloads the same `yfinance` price history that drives proposals, inspects stop-loss and take-profit crossings for each recommendation, and updates the stored run/recommendation state entirely within this repository instead of invoking any prototype scripts.

## Gaps and truth checks

We reviewed the Phase 2 doc and identified a few areas that needed clarification or completion:

- The old summary plan still looked forward to the LLM pipeline even though it already existed; this document now states that the summarizer is implemented and highlights the fallback digest path for reliability.
- The doc previously described `analysis_json` as a flat bag of fields, which made it hard to trace which diagnostics were new; the new schema is explicit about where metadata, trade outputs, summary text, news items, sentiment scores, context flags, and weights live.
- The NaiveSentiment analyzer still returns pure zeros for tickers with no keyword coverage, so we are actively exploring keyword set enrichment/weighting and adding upstream fallback indicators before we declare that signal mature.

## Next steps

1. Expand the news/sentiment coverage so `NaiveSentimentAnalyzer` reports fewer zero results (keyword enrichment, headline weighting, fallback heuristics) and document why zeros still occur when no keywords match.
2. Surface more diagnostics (feature vectors, aggregations, weights, news items) in the UI debugger/run detail so operators can compare the new structured payloads without decoding raw JSON.
3. Harden the scheduler/worker reliability by refining how the evaluation pass handles multi-ticker runs, partial price-history availability, and overlapping schedules so outcome tracking stays dependable even when data signals are intermittent.
4. Keep refreshing operator docs (Phase 2, roadmap, raw details reference) whenever the schema or summary/sentiment features change so planning artifacts stay truthful.

## LLM-enhanced summaries and sentiment

### Delivered

- A summarizer now consumes the unified `news_items` payload and a compact technical snapshot (price, ATR, RSI, SMA deltas) and sends it to the selected backend (OpenAI or `pi_agent`). The configured Pi CLI command, working directory, and optional `pi_cli_args` reuse the same skills/config the interactive Pi instance uses via `PI_CODING_AGENT_DIR`.
- The pipeline records the returned narrative under `analysis_json.summary.text` with metadata (`method`, `backend`, `model`, `runtime_seconds`, `metadata`) and exposes any `summary_error` or `llm_error` so failures are obvious in the UI.
- The summary toggle in `/settings` now covers the digest-only option plus the LLM backends, including Pi-specific helpers; the run detail page renders the LLM narrative when available and still shows the digest fallback.
- `analysis_json.sentiment.enhanced` captures the fused score, label, and component contributions (news sentiment, LLM tone, technical indicators) so the scoring weights can optionally use the richer signal while diagnostics still expose the raw keyword-based components.

### Remaining work

1. Continue enriching the keyword dictionaries and weighting so `NaiveSentimentAnalyzer` produces non-zero compound ratings more frequently, especially when feed coverage is sparse.
2. Monitor the new `analysis_json` sections and ensure any future provider adds items to `news_items` and `news.sentiment.sources` so diagnostics remain complete.
3. Keep the UI/RunDiagnostics surfaces aligned with the schema changes (summary section, news section, sentiment block, context flags) and document any further schema refinements in the live docs.

Once these deliverables land, the prototype’s long-form narratives, sentiment rationale, evaluation truth, instrumentation, and diagnostics will all live inside Trade Proposer App, leaving the legacy repository purely as a historical reference rather than a runtime dependency.