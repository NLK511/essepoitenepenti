# Dead-code and compatibility audit — 2026-05-29

**Status:** reference

Purpose: identify code that looks legacy or removable and decide whether it is safe to delete now.

## Verdict

No compatibility path in this audit is safe to delete immediately. The visible legacy sections still either preserve API/test compatibility, protect degraded live/replay behavior, or preserve operator diagnostics.

## Findings

### `ProposalService` compatibility exports

- `DEFAULT_SUMMARY_METHOD`, `DEFAULT_SUMMARY_TEXT`, and `_sanitize_for_json` are still imported by tests or compatibility callers.
- Action taken: shared defaults/sanitizer moved to `payload_utils`; `ProposalService` wrapper/export retained.
- Decision: keep wrappers until downstream imports are fully migrated and tests no longer import from `services.proposals`.

### Proposal price-history wrappers

- `_fetch_price_history`, `_fetch_price_history_remote`, `_fetch_price_history_from_local_store`, `_persist_price_history`, and `_latest_bar_time_iso` are referenced by tests and compatibility paths.
- Action taken: orchestration moved to `PriceHistoryFetcher`; wrappers retained.
- Decision: keep wrappers for now.

### `TickerDeepAnalysisService._analyze_with_compatibility_fallback`

- Used when native deep analysis raises `ProposalExecutionError`.
- It preserves degraded-analysis output rather than failing the full run.
- Decision: keep. Removing it would change failure semantics.

### Deprecated job-type aliases

- Legacy aliases in job routes/domain enums normalize older job type strings.
- Decision: keep unless API consumer inventory proves no stored jobs/clients use old labels.

### Provider observability compatibility events

- Legacy provider aggregate events remain alongside normalized `provider.request_failed` / `provider.request_skipped` events.
- Decision: keep until dashboard/API consumers rely only on normalized events.

### Large tests

- `tests/test_repositories.py` and `tests/test_routes.py` are oversized but not dead.
- Decision: split by domain later with no assertion changes.

## Next safe cleanup

1. Finish migrating internal imports away from `services.proposals` constants/helpers.
2. Split large tests by domain.
3. Add a temporary compatibility-removal checklist before deleting wrappers.
