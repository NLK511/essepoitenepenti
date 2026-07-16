# Input Access and Provenance Remediation Spec

**Status:** current behavior

Last updated: 2026-07-16

## Purpose

Replay/tuning evidence is only useful when the app can prove which inputs were available at decision time. A replay may produce outcomes, but it must not become tuning or promotion evidence unless market, news, context, fundamental, outcome, and provenance coverage are explicit and point-in-time safe.

This spec defines the shared input-access rule used by replay, tuning, calibration, and remediation scripts.

## Core rule

Every critical input access path must return both:

1. the data used by the caller
2. an audit trail covering coverage, freshness, point-in-time validity, source, warnings, blockers, and a stable provenance hash

Callers should not manually choose between cache reads and remote hydration. They should call one access service with an explicit policy.

## Scope

In scope:

- historical market bars
- replay market/news/context/fundamental coverage
- replay-generated plan provenance
- replay eligibility classification and reclassification
- service construction for replay and tuning workflows
- outcome population labels for tuning/calibration
- validation of critical JSON artifacts

Out of scope:

- changing tuning objective math
- auto-promoting configs
- redesigning broker execution
- replacing every repository

## Design problems this prevents

- cached-bar reads, remote hydration, replay coverage, and outcome-resolution paths disagreeing
- replay services being built without required market-data dependencies
- free-form JSON artifacts silently missing mandatory fields
- duplicate point-in-time filters leaking future data into historical decisions
- reports mixing execution, phantom, replay, and eligibility populations without labeling them

## Canonical access result

Input-access services return a typed result equivalent to:

```python
InputAccessResult(
    data=<T>,
    coverage=InputCoverageReport(...),
    provenance=ArtifactProvenance(...),
)
```

At minimum, coverage/provenance payloads include:

```json
{
  "as_of": "...",
  "requested_start": "...",
  "requested_end": "...",
  "covered_start": "...",
  "covered_end": "...",
  "source": "cache|remote|cache_plus_remote",
  "tier": "tier_a|tier_b|tier_c|ineligible",
  "blockers": [],
  "warnings": [],
  "point_in_time_filter": "...",
  "input_coverage_hash": "..."
}
```

## Access policies

Supported policies are explicit:

- `cache_only` — use persisted data only; required for strict replay and validation
- `cache_then_remote` — use cache first and hydrate known gaps when allowed
- `remote_allowed` / live equivalents — only for current live analysis, not strict historical replay

Shared helpers define whether a policy allows remote fetching. Scripts and services should not repeat policy string checks.

## Replay eligibility tiers

- `tier_a`: point-in-time generation coverage is sufficient, intraday resolution bars exist, the outcome is resolved from intraday evidence, and mandatory replay provenance is present. Preferred promotion evidence.
- `tier_b`: generation coverage is sufficient and the outcome is resolved, but resolution uses daily fallback evidence. Usable only by workflows that explicitly accept daily-resolution replay evidence.
- `tier_c`: some artifacts are usable, but the row is not valid promotion evidence, usually because the outcome is open/unresolved or resolution bars are missing.
- `ineligible`: mandatory generation coverage, resolution evidence, or provenance is missing.

## Replay intraday coverage states

Replay outcome repair must not leave generic `pending` rows when the bar-cache reason is knowable. Intraday coverage diagnostics and repair tools classify each replay outcome window as:

- `covered`: required 1m bars exist in cache for the bounded resolution window.
- `current_session_incomplete`: the requested end falls on a market session that has not completed in cache yet.
- `internal_cache_gap`: the ticker has 1m history around the window, but one or more required sessions or large intraday spans are missing.
- `outside_local_intraday_cache`: the required start is older than the earliest local 1m bar for the ticker.
- `ticker_not_in_cache`: the ticker has no local 1m bars.
- `loader_limit_truncated`: bars exist, but the access layer used too small a row limit for the requested 1m window.
- `missing_daily_fallback`: daily bars are also unavailable for a row that could otherwise be daily-prefiltered.

Rows outside the local intraday cache are not repair candidates unless another provider/source is explicitly added. Rows in the current incomplete session are retry-later candidates. Recent internal gaps are repair candidates while the provider can still return 1m bars.

## Mandatory replay provenance

Every replay-generated signal/plan must include non-null replay provenance:

```json
{
  "as_of": "...",
  "replay_batch_id": 0,
  "replay_slice_id": 0,
  "code_version": "...",
  "settings_hash": "...",
  "input_coverage_hash": "...",
  "plan_generation_config_hash": "..."
}
```

Missing mandatory provenance must degrade/fail the replay slice and block tuning eligibility.

## Outcome population labels

Every tuning/calibration/reporting artifact must state which population it used:

- `execution_only`: real/paper actionable outcomes only; excludes phantom outcomes
- `phantom_only`: hypothetical `no_action`/`watchlist` outcomes; research only unless separately promoted by spec
- `execution_plus_phantom`: mixed execution and phantom outcomes; useful for recall/actionability research, not confidence honesty by default
- `replay_tier_a_only`: preferred replay promotion evidence
- `replay_tier_a_b`: accepts tier B daily-resolution fallback and must be labeled less strict
- `effective_normalized_outcomes`: broker/replay outcomes normalized for aggregate win-rate/EV math; reports must still disclose row source

## Current implementation snapshot

Implemented remediation includes:

- typed coverage/provenance models and stable hashing helpers
- `HistoricalBarsAccessService` with cache-only/cache-then-remote semantics and daily/1m access methods
- replay provenance attachment and replay eligibility blocking for missing provenance
- replay eligibility reclassification service/script
- canonical replay service construction so replay execution has required input services
- historical news, context snapshot, and fundamental snapshot access services returning coverage/provenance
- outcome population labels in tuning/calibration summaries
- validation wrappers for critical replay/tuning JSON artifacts
- replay evidence audit and replay outcome refresh scripts/services
- replay bar coverage diagnostics for blocked replay outcomes
- batch-oriented replay outcome refresh profiling, lightweight plan loading, and bulk outcome persistence
- shared replay evidence-quality checks for audit and promotion gates
- maintainability cleanup around remote-fetch policy helpers, JSON helpers, stable hashing, and bar-access internals

## Operational rules

- Treat replay batches with outcomes but zero eligible rows as degraded evidence.
- Do not promote plan-generation configs from salvage rescoring or phantom-dominated evidence.
- Prefer replay paths built through canonical API/builders over ad-hoc scripts.
- Keep actionability-floor rescoring separate from broader parameter tuning evidence unless the artifact labels both mode and population clearly.
- Refresh/reclassify old replay batches before using them for tuning if coverage or outcome state was repaired after the original run.
- Replay eligibility reclassification must reuse reconstructed coverage within a batch. A slice with missing stored coverage may rebuild its coverage from cache once, but repeated outcomes for the same slice must not trigger repeated bar-coverage scans.
- Replay outcome refresh tooling must support source-targeted refreshes so pending-source rows can be repaired without reprocessing already clean intraday rows from the same batch.
- Replay outcome refresh must not use wall-clock `now` for historical repair unless explicitly requested. Repair mode must use a bounded plan horizon or latest complete cached session per ticker.
- Replay outcome refresh must be batch-oriented for historical repair. It must not hydrate full UI/broker execution context per plan, must support bounded `--limit` profiling runs, and must report timing for row selection, plan loading, price-history loading, outcome resolution, persistence, and reclassification.
- Replay outcome persistence must support bulk upsert by `(replay_slice_id, recommendation_plan_id, candidate_config_hash)` so historical repair commits by batch/chunk rather than once per outcome row.
- 1m bar access for bounded replay windows must not silently truncate at a fixed 2,000 rows. The caller must request enough rows for the window or use an uncapped bounded range query with a safe guard.
- Bars refresh must audit recent session continuity. A ticker with a fresh latest bar can still have an internal recoverable gap.
- Old replay rows that need 1m bars older than the local/provider window must be marked with an explicit unrecoverable reason and excluded from repeated repair queues.

## Testing requirements

Tests should cover:

- cache-only and cache-then-remote bars returning the same coverage schema
- replay coverage built from stored bars without hydration
- replay plans containing non-null provenance
- missing provenance blocking eligibility
- resolved intraday replay outcomes becoming tier A when coverage is valid
- reclassification before/after tier-count reporting
- reclassification reusing reconstructed coverage for repeated outcomes from the same replay slice
- outcome refresh selecting rows by resolution source for targeted pending-source repair
- outcome refresh using a lightweight replay plan loader instead of per-row full plan hydration
- outcome refresh bulk-upserting replay outcomes without per-row commits
- outcome refresh `--limit` and profiling artifacts for controlled batch repair runs
- replay bar coverage diagnostics distinguishing current-session, pre-cache, internal-gap, ticker-missing, and loader-limit cases
- replay outcome refresh using plan-horizon/latest-complete cached-session cutoffs instead of wall-clock `now`
- bounded 1m replay windows returning complete ranges beyond 2,000 rows
- bars refresh artifacts reporting recent per-session coverage gaps
- scripts/builders refusing to construct replay execution without required input services
- evidence-quality gates rejecting phantom-dominated promotion evidence

## Related docs

- `historical-playback-tuning-spec.md`
- `plan-generation-tuning-spec.md`
- `large-parameter-search-spec.md`
- `news-provider-eligibility-spec.md`
- `fundamental-analysis-snapshot-spec.md`
- `../archive/implementation-plans/historical-playback-tuning-operating-plan.md`
