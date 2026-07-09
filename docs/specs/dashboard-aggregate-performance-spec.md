# Dashboard aggregate performance spec

**Status:** current behavior

Dashboard windows must not rescan large raw tables when a compact aggregate can answer the operator question.

## Current implementation

- Daily dashboard snapshots are stored in `dashboard_trend_snapshots`.
- The 7-day and 1-month dashboard windows are served from:
  - completed daily snapshots for prior days, plus
  - one live partial-day aggregate for today.
- The response shape stays the same as the raw dashboard metrics:
  - `dashboard_summary`
  - `technical_summary`
- Aggregated payloads include `aggregate_source: daily_snapshots_plus_today`.

## Why

The dashboard and quality widgets are operator safety surfaces. Opening a 1-month view must be fast and must not create 504 errors or browser crashes by repeatedly scanning raw plan, bar, news, order, and outcome rows.

## Rules

- Use raw live queries for short/current views where they are cheap.
- Use daily snapshots for weekly/monthly dashboard windows.
- Recompute rates from aggregate counts when possible.
- Sum absolute values such as P&L, order counts, news counts, and bar counts.
- Dashboard `technical_summary.news_processed` means news rows processed/ingested during the selected dashboard window. It must use `ingested_at` with a safe fallback to row `created_at`/`published_at`; it must not use only `published_at`, because macro and industry refreshes can process articles today that were published yesterday.
- Use weighted averages for average-return fields when the sample count is available.
- Keep raw detailed diagnostics on detail pages; keep dashboard payloads compact.
- Dashboard `latest_runs` and `recent_runs` are compact run summaries only. They must include identity, type, status, error, timestamps, and duration, and must not include heavy run artifacts, summaries, or timing payloads. Full run artifacts belong on run-detail/research pages.
- Dashboard work-queue headline counts must describe the selected window, not just the number of rows loaded for preview lists. `plans_in_window` comes from the selected-window plan count, while `plan_rows_loaded` is only a preview/debug count. `major_failures` must count failed runs in the selected window with a direct failed-run query, not by filtering the capped `recent_runs` preview list. Warning-pattern headline counts must use the full grouped warning set before display truncation.

## Recommendation-quality page guardrail

The quality page uses bounded UI windows (`1d`, `7d`, `1m`) and a bounded sample limit for interactive loading. Longer horizon analysis belongs in offline research/tuning jobs or a future persisted `quality_aggregate_snapshots` read model, not in the synchronous page-load path.

## Known next step

If quality still becomes slow, add a dedicated persisted `quality_aggregate_snapshots` read model using the same pattern: daily base snapshots plus weekly/monthly rollups.
