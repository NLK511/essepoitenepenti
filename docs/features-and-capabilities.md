# Features and Capabilities

Trade Proposer App already covers the main operator loop: define what to watch, enqueue work, inspect recommendations, understand degraded runs, evaluate outcomes, review history, and adjust the summary configuration without leaving the product. The implementation stays lightweight while keeping core workflows inside this repo.

Signal integrity policy: Any component that contributes to recommendation generation must be transparent about missing inputs. When keywords, providers, or aggregators are unavailable we emit explicit `NEUTRAL`/zero outputs and surface diagnostics rather than inventing fallback heuristics that could hide upstream issues.

## What operators can do now

The dashboard surfaces the latest recommendations and runs, highlights degraded execution, and links directly to jobs, watchlists, settings, docs, the debugger, and ticker pages. Watchlists can be created and stored in the database. Jobs can be created, edited inline, deleted, executed through the worker path, and converted into a watchlist. Jobs support first-class workflow types: proposal generation, recommendation evaluation, and weight optimization. Proposal-generation jobs still use exactly one source: either manual tickers or a single watchlist. Evaluation and optimization jobs are maintenance workflows and do not require ticker sources.

Successful proposal runs persist recommendation records with direction, confidence, entry, stop loss, take profit, recommendation state, and a compact indicator summary plus the normalized diagnostic payloads that the internal pipeline emits (`analysis_json`, `feature_vector_json`, `aggregations_json`, and the confidence weights). Failed runs remain visible as explicit failures with error context. Recommendation history supports filtering by ticker, direction, state, and warning count, plus sorting and pagination. Evaluation workflows run through the shared scheduler/worker path and persist run summaries in the app; operators can queue both full evaluation runs and single-recommendation evaluation runs from the UI, and those manual actions now create normal auditable run records instead of bypassing run history. The evaluation runner now inspects historical price data (via the same `yfinance` history the proposal pipeline uses) to determine whether stop, take-profit, or combined thresholds resolved each recommendation, so outcomes stay on the app-native code path rather than calling any external prototype script. Evaluation and optimization runs render in the debugger and run detail pages as workflow-specific result cards instead of mostly opaque JSON blobs, including evaluation scope/trigger details and optimization backup/fingerprint summaries. Weight optimization workflows persist run summaries and artifact metadata, including before/after `weights.json` fingerprints and backup metadata. From recommendation history or the dashboard, operators can open a ticker drill-down page that shows app-side recommendation history and internally derived outcome summaries.

The optimizer now reads resolved recommendations straight from the app database, applies the tracked `weights.json`, and creates backups/rollback metadata so the scheduled job never needs to call a prototype script.

## Diagnostics, debugging, and documentation


Diagnostics are treated as first-class investigation artifacts. Run detail and debugger views surface warning and failure context directly, while richer raw details remain available on demand through the pipeline payloads, timestamps, and timing breakdowns. The run detail page now renders the structured `analysis_json` sections (news digest, context flags, feature vectors, aggregations, and weights) in addition to the raw output so operators never have to manually parse JSON to inspect those signals. Numeric fields inside those sections (normalized highlights, confidence, sentiment, news scores) also use hue-based color cues so green/red/orange gradients immediately flag good, neutral, or bad readings. For optimization workflows, those views include nested backup and fingerprint metadata clearly instead of hiding them inside raw JSON blobs. Recommendation detail pages focus on the trade-ready object first and link back to the source run for traceability. Ticker pages combine app-generated recommendation history with the latest outcome tracking the worker derives from price action.

### Run deletion and lifecycle

Operators can now delete completed, failed, or cancelled runs directly from the run detail page. The delete button triggers a warning confirmation in the UI, removes the run plus its recommendations and diagnostics from the database, and emits a success toast. Queued or running executions are protected and cannot be deleted from the UI or API; attempting to delete them returns a 400 error and explains that only terminal runs can be removed. This keeps the run record history actionable while letting operators clean up noise when experimentation produces short-lived or noisy entries.

The in-app docs browser indexes `README.md` and every markdown document under `docs/`, supports full-text search, renders markdown directly, and groups documents into collapsible sections so setup and user-oriented material stays near the top while product and engineering references stay lower in the page. It also includes dedicated reference material for raw-details fields and recommendation methodology.

## Mobile and responsive UI

- The SPA now switches to a dedicated mobile navigation toggle that slides in a theme-aware overlay panel, keeping the desktop menu available on wider screens while the overlay inherits the current color scheme.
- Navigation labels render both expanded and compact variants so that the desktop nav shows descriptive names while phones receive minimal text (e.g., ‘Jobs’ → ‘Jobs’, ‘Recommendations’ → ‘Recs’).
- Helper text, subtitles, document paths, and other descriptive copy collapse on narrow devices, and the primary cards/metrics grids stack to avoid horizontal scrolling.
- Section titles and list headers truncate with ellipsis when necessary so the UI keeps breathing room even on very small widths.

## Summary engine and analysis pipeline

Recommendation generation now flows entirely through the app-native pipeline. `ProposalService` fetches price history via `yfinance`, builds technical features with `pandas`, normalizes them, applies the stored weights (`src/trade_proposer_app/data/weights.json`), lands on direction/confidence/price signals, and stores the generated diagnostics. It routes news ingestion through `NewsIngestionService`, which pulls the latest articles from the configured providers (NewsAPI, Finnhub, etc.), deduplicates links, normalizes each payload into the unified `news_items` list, and emits `sentiment_score`, `polarity_trend`, `sentiment_volatility`, and context-tag flags that feed both the feature vector and the diagnostics.

Every successful run persists the structured `analysis_json` (version 2.0) so downstream tooling can parse metadata, the trade output, the summary narrative, the `news` section (feeds used, feed errors, item counts, the `items` array, and the associated keyword sentiment diagnostics), the `sentiment` block (base score/label and `enhanced` fused contributions), context flags, the raw/normalized feature vectors, aggregations, confidence/aggregation weights, and diagnostics. The headline digest remains saved as `analysis_json.news.digest`, but when operators select the `openai_api` or `pi_agent` backend the same digest and a concise technical snapshot are sent to the in-app LLM summarizer. The resulting narrative (text, backend/model/runtime metadata, and any errors) is stored in `analysis_json.summary`, and the fused tone plus the technical indicators populate `analysis_json.sentiment.enhanced`, so the scoring weights can use the richer signal while audits can still inspect the keyword-only components.

The confidence calculation now honors conservative weights for enhanced sentiment, medium-term momentum, news coverage, context richness, polarity trend, and the volatility of the sentiment signal (in addition to the existing SMA+RSI/ATR weights). That lets the diagnostics capture how each of those signals nudges the score without dominating the recommendation when coverage is sparse. Entry, stop-loss, and take-profit targets also leverage the aggregator weights: the `entry` aggregator nudges the entry price toward the prevailing trend, while the `risk` aggregator adjusts the ATR-based stop and reward distances based on momentum and sentiment volatility, so even the price levels reflect the combined signal footprint rather than just the raw ATR band. To keep runs resolvable, stop distances stay below roughly 3% of entry and take-profit distances stay below roughly 4.5%, which helps the evaluation workflow close trades faster without exposing operators to excessively wide risk windows.

Supported external news services ingested directly by the app-native pipeline:
- NewsAPI: https://newsapi.org/
- Finnhub: https://finnhub.io/

Additional connectors (Alpha Vantage, Alpaca News, Yahoo Finance, Nitter, etc.) remain on the roadmap for subsequent enrichments.

## What is only partial or still missing

Queued execution and worker processing remain in place, and the self-improvement loop is now present in the product shape: scheduled recommendation evaluation and scheduled weight optimization are first-class app workflows. Optimization rollback support is now provided through the weight backup and restore tooling, and the remaining work focuses on hardening and polish: scheduler behavior still needs further hardening (better handling of overlapping jobs, multi-ticker partial failures, and recovery from worker crashes), optimization thresholds are not yet app-configurable, and evaluation truth still depends on the outcome-tracking path that interprets price action versus the generated stop/take-profit levels.

The sentiment analyzer still depends on the keyword dictionaries inside `NaiveSentimentAnalyzer`, but that dictionary is now richer (e.g., `guidance`, `exceed`, `resilient`, `downturn`), matches multi-word cues such as “beats expectations” or “misses guidance”, and gives headlines a 1.7× boost while summaries retain a 1.2× boost. A tighter smoothing constant (0.25) keeps each article’s compound score within [-1.0, +1.0] yet lets even sparse matches pull the aggregate score away from strict neutrality, while `coverage_insights` and `keyword_hits` keep every remaining zero explicitly documented. `analysis_json.sentiment.coverage_insights` now records those zero-score causes (e.g., no articles fetched, no keyword matches, or provider errors), `keyword_hits` counts matched sentiment tokens, and the run detail diagnostics surface both so operators can tell when a neutral score simply reflects missing coverage. Each insight is a short explanation such as `news: no articles fetched; providers may be missing or rate limited` or `news: articles arrived but no sentiment keywords matched`, making the lack of coverage explicit whenever the analyzer returns neutral.

The app has improved secret handling through encryption at rest, but it still lacks credential rotation. Auth, RBAC, tenancy, and broader deployment monitoring are also not implemented yet.

## Current strengths and next needs

The strongest operator capabilities are straightforward local startup, visible failure handling, persisted recommendation history, ticker-specific review, the structured diagnostics (`analysis_json`, feature vector/aggregation payloads, weights), the new news-digest summary plus the optional LLM narrative, and in-product documentation. Sentiment now contributes by default through a conservative `confidence.sentiment` weight (5.0) so historical data can capture its impact before we tune it aggressively. The most important next steps are stronger scheduler guarantees, expanded credential rotation, broader operational hardening, improved summarization diagnostics, and incremental frontend polish without adding unnecessary client-side complexity.

## Suggested session-aligned watchlists

Each of the following watchlists stays inside a single regional session or thematic window so the associated job can run at a reliable moment of the trading day. All cron expressions assume UTC and weekdays only (`MON-FRI`).

### 1. U.S. Tech Momentum (run ~10:30 ET)
- **Target window**: Early Nasdaq/Nyse surge.
- **Tickers**: AAPL, MSFT, NVDA, AMZN, META, GOOG, CRM, ORCL, PYPL, SHOP, SAPH, INTC, AVGO, AMD, NOW.
- **Cron**: `30 14 * * MON-FRI` (14:30 UTC = 10:30 ET).

### 2. European Midday Reversion (run ~12:30 CET)
- **Target window**: Mid-CET calm before the U.S. open.
- **Tickers**: ASML, SAN, BP, SHEL, LVMUY, OR, DAI, ING, UBS, RIO, AIR, SIEGY, BASFY, ENGIY, NOVN.
- **Cron**: `30 11 * * MON-FRI` (11:30 UTC = 12:30 CET).

### 3. Asia-Pacific Opening Range (run ~09:15 local)
- **Target window**: HK/Tokyo/Singapore open-range pulse.
- **Tickers**: 0700.HK, 0005.HK, 9984.T, 7203.T, 6758.T, 9432.T, 2914.T, 8035.T, BHP.AX, RIO.AX, CSL.AX, WES.AX, A2M.AX, 3888.HK, 3690.HK.
- **Cron**: `15 0 * * MON-FRI` (00:15 UTC ≈ 08:15 HKT/Tokyo, 10:15 AEST).

### 4. Macro News & Rates Pulse (run ~08:30 ET)
- **Target window**: U.S. macro release and pre-open noise.
- **Tickers**: SPY, QQQ, TLT, IEF, GLD, USO, VNQ, XLF, XLE, XLK, UUP, TIP, IWM, XLY, XLI.
- **Cron**: `30 12 * * MON-FRI` (12:30 UTC = 08:30 ET).

### 5. Energy & Commodities Morning Sweep (run ~09:00 CT)
- **Target window**: NYMEX oil/gas desk’s morning heartbeat.
- **Tickers**: CVX, COP, OXY, SLB, HAL, KMI, XOM, BKR, EQT, NBL, NOV, TALO, CHK, PE, VLO.
- **Cron**: `00 15 * * MON-FRI` (15:00 UTC = 10:00 ET / 09:00 CT).

### 6. AI & Automation Leaders (run ~09:45 ET)
- **Target window**: U.S. catalyst window once the market opens.
- **Tickers**: LRCX, CDNS, SNPS, AMAT, CRWD, PANW, FTNT, ZS, MDB, OKTA, TEAM, MTTR, SNOW, ADSK, PLTR.
- **Cron**: `45 13 * * MON-FRI` (13:45 UTC = 09:45 ET).

### 7. Healthcare & Biotech Defensive Shift (run ~13:00 ET)
- **Target window**: Afternoon defensive rotation before the close.
- **Tickers**: JNJ, PFE, MRK, LLY, ABBV, BMY, AMGN, GILD, ZTS, UNH, TDOC, HCA, ILMN, MRNA, REGN.
- **Cron**: `00 17 * * MON-FRI` (17:00 UTC = 13:00 ET).

Run `python scripts/deploy_watchlists.py` to provision these watchlists and their scheduled proposal-generation jobs automatically. The script creates or updates the records to match the UTC cron times listed above and logs every watchlist/job outcome.
