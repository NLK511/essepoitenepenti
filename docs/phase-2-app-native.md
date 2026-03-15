# Phase 2: App-native Outcomes

This document captures the ongoing transition that makes Trade Proposer App fully self-contained. Phase 2 today means operating and improving the internal scoring pipeline without ever shelling out to a separate prototype repository, reintroducing the missing diagnostics/summary signals natively, and documenting the dependencies or fallbacks operators need to trust the outputs.

## Signal integrity policy

Every contribution that affects recommendation generation must be explicit when data is missing. The pipeline never invents a directional signal when its raw inputs are absent: missing keyword coverage, provider failures, or aggregator gaps must either emit `NEUTRAL`/zero outputs or surface a digestible warning/error before a new score is published. This policy (which already governs NaiveSentimentAnalyzer) extends to every feature, summary, or weight adjustment so future sessions—LLM-assisted or otherwise—cannot accidentally add the kind of “dummy” fallback heuristics that mask upstream problems.

## Progress recap

- **Self-contained scoring**: `ProposalService` now orchestrates the end-to-end pipeline (price ingestion via `yfinance`, feature construction with `pandas`, normalization, weights application, diagnostics, and the recommendation agreement workflow) all from within this repository.
- **App-native weight optimization**: The optimization workflow now reads resolved recommendations directly from the app database, adjusts the checked-in `weights.json`, and stores backups/artifacts without invoking the legacy prototype script so the job stays self-contained in this repo.
- **Rich diagnostics**: Each run persists `analysis_json` (now organized into metadata/trade/summary/news/sentiment/context/feature-vector sections), the raw/normalized feature vectors, aggregations, confidence weights, and RunDiagnostics details so every signal remains auditable without peeking into an external tool.
- **Sentiment coverage transparency**: `analysis_json.sentiment.coverage_insights` lists zero-score causes, `keyword_hits` counts the matched tokens, and the run detail diagnostics surface those fields in the Sentiment coverage block so neutral outputs always cite a missing data reason.
- **Structured diagnostics surfaced**: The run detail page and debugger now render those `analysis_json` sections (news items, summaries, context flags, feature vectors, aggregations, and weights) instead of exposing only raw JSON blobs, so operators can inspect the structured payloads directly.
- **Enhanced sentiment coverage**: `NaiveSentimentAnalyzer` now uses a broader keyword set while still honoring the signal integrity policy, so news-light runs report zero compound scores whenever the dictionaries miss instead of masking upstream gaps.
- **Configurable summarization**: `SummaryService` invokes the configured OpenAI or `pi_agent` CLI backend, parses the streamed JSON responses, and captures backend/model/runtime metadata plus `llm_error`/`summary_error`. When the summarizer does not run, the headline digest saved under `analysis_json.news.digest` is still available as the fallback narrative.
- **In-app news, sentiment, and Pi CLI coverage**: News ingestion, NaiveSentiment analysis, and the Pi CLI references now live in-app: `NewsIngestionService` produces unified `news_items` (title, summary, publisher, link, published_at, compound score), `analysis_json.news` exposed feed diagnostics, and the Pi CLI invocation reuses the configured directory/skill set via `PI_CODING_AGENT_DIR` and `pi_cli_args`.
- **App-native evaluation**: The evaluation service now downloads the same `yfinance` price history that drives proposals, inspects stop-loss and take-profit crossings for each recommendation, and updates the stored run/recommendation state entirely within this repository instead of invoking any prototype scripts.

## Gaps and truth checks

We reviewed the Phase 2 doc and identified a few areas that needed clarification or completion:

- The old summary plan still looked forward to the LLM pipeline even though it already existed; this document now states that the summarizer is implemented and highlights the fallback digest path for reliability.
- The doc previously described `analysis_json` as a flat bag of fields, which made it hard to trace which diagnostics were new; the new schema is explicit about where metadata, trade outputs, summary text, news items, sentiment scores, context flags, and weights live.
- The NaiveSentiment analyzer still returns pure zeros for tickers with no keyword coverage because the signal integrity policy forbids inventing fallback heuristics; we are instead concentrating on enriching the keyword sets, weighting headline versus summary hits, and documenting every zero-case so operators know when coverage is incomplete.

## Next steps

1. Monitor the enhanced sentiment coverage, document any remaining zero-score cases under the signal integrity policy (which forbids fallback heuristics), keep refreshing the keywords/weights before assuming the signal is fully complete, and leverage the new `coverage_insights`/`keyword_hits` diagnostics so missing coverage stands out in the structured payloads.
2. Harden the scheduler/worker reliability by refining how the evaluation pass handles multi-ticker runs, partial price-history availability, and overlapping schedules so outcome tracking stays dependable even when data signals are intermittent.
3. Keep refreshing operator docs (Phase 2, roadmap, raw details reference) whenever the schema or summary/sentiment features change so planning artifacts stay truthful.

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