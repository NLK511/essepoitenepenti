# Input Access and Provenance Remediation Spec

Status: in progress
Last updated: 2026-06-28

## Why this exists

A US top 50 replay completed with hundreds of replay outcomes, but zero rows were eligible for plan-generation tuning because the replay coverage/provenance metadata was incomplete. The app had enough data to produce outcomes, but it could not prove that the inputs were point-in-time valid and complete enough for tuning.

This exposed a broader design problem: several parts of the app treat fetching/hydrating data, reading cached data, computing coverage, and attaching provenance as separate paths. Those paths can disagree.

## Core design rule

Every critical input access path must return both:

1. the data used by the caller, and
2. a validated audit trail describing coverage, freshness, point-in-time validity, source, warnings, blockers, and provenance hash.

Callers should not directly choose between "cache read" and "remote hydration". They should call one access service with an explicit policy.

## Scope

In scope:
- historical market bars
- replay market/news/context/fundamental coverage
- replay-generated plan provenance
- replay eligibility classification and reclassification
- service construction for replay and tuning workflows
- outcome population labeling for tuning/calibration
- validation of critical JSON artifacts

Out of scope for the first implementation slice:
- changing tuning objective math
- auto-promoting configs
- replacing all repositories
- redesigning broker execution

## Identified design gaps

### 1. Market bars have parallel paths

Current paths include:
- bar hydration from Yahoo
- direct cached bar reads
- replay coverage report construction
- outcome resolution price-history preparation
- bars refresh jobs and recovery scripts

These paths can disagree. A replay can resolve outcomes from bars while replay eligibility says coverage is missing.

### 2. Replay service dependencies are inconsistent

Some routes/builders construct `HistoricalReplayService` with market data services. Some research scripts allowed `historical_market_data=None`, which produced empty/ineligible coverage reports while replay still ran.

### 3. Critical artifacts are free-form JSON

Important state is stored in dict/JSON fields such as:
- run artifacts
- replay input summaries
- replay output summaries
- signal breakdown diagnostics
- replay eligibility diagnostics
- tuning run summaries

Missing fields can silently become `null` instead of failing early.

### 4. Point-in-time filters are duplicated

Different services independently apply rules such as:
- `available_at <= as_of`
- `computed_at <= as_of`
- `published_at <= as_of`
- `as_of + resolution_days`

This creates risk of inconsistent replay, tuning, and reporting semantics.

### 5. Outcome populations are fragmented

The app has multiple outcome concepts:
- live/paper recommendation outcomes
- effective normalized outcomes
- replay plan outcomes
- replay eligibility records
- phantom outcomes

These are useful distinctions, but every tuning/calibration report must explicitly state which population it used.

### 6. News/context/fundamental coverage has similar risks

Context and fundamental artifacts have coverage/freshness concepts, but they are not using one shared coverage/provenance language. Existing cleanup tooling for context snapshots without primary evidence indicates this problem has occurred before.

## Target architecture

### Common access result

Introduce a shared access-result contract for critical inputs:

```python
InputAccessResult:
    data: object
    coverage: InputCoverageReport
    provenance: ArtifactProvenance
    warnings: list[str]
    blockers: list[str]
```

### Common access policies

Supported policies:

- `cache_only`: read local persisted data only; never call remote providers.
- `cache_then_remote`: read local data, hydrate missing windows from remote providers when allowed, persist, then return the unified result.
- `remote_refresh`: refetch remote data even if local data exists, then persist and return.
- `fail_if_missing`: fail/degrade if local data is incomplete; do not hydrate.

### Common coverage fields

Every coverage report should include:

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

### Replay provenance fields

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

If mandatory provenance is missing, the replay slice must fail or be marked degraded. Tuning must not silently consume those rows.

## Task breakdown

### Phase 0 — Freeze risky evidence

- [ ] Mark replay batch 15 as warning/degraded in its batch artifact or summary.
- [ ] Mark salvage tuning run 37 as research-only and not promotion evidence.
- [ ] Add a guardrail summary when replay outcomes exist but eligible tuning rows are zero.

Acceptance:
- Operators cannot mistake batch 15 or run 37 for valid tuning evidence.

### Phase 1 — Define common contracts

- [x] Add typed models/dataclasses for `InputAccessPolicy`, `InputCoverageReport`, `TickerCoverageReport`, and `ArtifactProvenance`.
- [x] Add schema helpers for stable coverage/provenance hashing.
- [x] Add first validation guard for mandatory replay provenance fields in replay eligibility classification.
- [ ] Document tier semantics once and reuse them.

Acceptance:
- New replay/tuning code does not accept raw unvalidated coverage/provenance dicts.

### Phase 2 — Build unified market bars access

- [x] Add `HistoricalBarsAccessService`.
- [x] Implement first replay-oriented cache read, optional Yahoo hydration, persistence, reload-from-cache, and coverage report generation behind one method.
- [ ] Add explicit gap-window detection before remote hydration to avoid broad refetches.
- [ ] Support at least daily and 1-minute bars through typed access methods beyond the replay wrapper.
- [x] Add explicit replay input access policy so replay can build coverage from cache without remote hydration.
- [x] Add stable `input_coverage_hash` to replay market coverage reports.
- [x] Return data plus coverage/provenance for replay generation/resolution windows through a single bar-access method.
- [x] Replace direct market-bar access in replay coverage generation.
- [ ] Replace replay outcome resolution price-history preparation with the unified access path or with a compatibility wrapper around it.
- [ ] Update bars refresh/recovery scripts to call the unified service.

Acceptance:
- Cached bars and Yahoo-fetched bars produce the same coverage schema.
- Replay cannot silently produce an empty market coverage report when stored bars exist.

### Phase 3 — Enforce replay provenance

- [x] Attach replay provenance to generated recommendation plans, including compatibility backfill for orchestration implementations that persist plans directly.
- [x] Include replay batch ID, slice ID, as-of timestamp, code version, settings hash, input coverage hash, and tuning config hash.
- [x] Block replay tuning eligibility when mandatory provenance fields are missing.
- [ ] Fail or degrade replay slices when mandatory provenance cannot be built.
- [ ] Update replay eligibility classification to use typed provenance.

Acceptance:
- No replay-generated plan has null replay provenance.
- Missing provenance is reported as a clear blocker.

### Phase 4 — Add replay eligibility reclassification

- [x] Add `ReplayEligibilityReclassificationService`.
- [x] Add `scripts/reclassify_replay_eligibility.py --batch-id X`.
- [x] Rebuild market coverage from stored bars using `cache_only` when stored replay coverage is missing/empty.
- [x] Recompute fallback provenance hashes and eligibility tiers.
- [x] Report before/after tier counts and blocker counts.
- [ ] Optionally allow `--policy cache-then-remote` for explicit hydration repair.

Acceptance:
- Existing replay batches can be repaired or definitively marked unusable without rerunning full replay.

### Phase 5 — Centralize service construction

- [x] Add a canonical builder for historical replay execution.
- [x] Replace route/worker ad-hoc replay construction with the canonical builder.
- [x] Update the actionability-floor replay experiment helper to use a market data service in `cache_only` mode instead of `historical_market_data=None`.
- [ ] Ban `historical_market_data=None` outside explicit test fixtures.
- [ ] Add tests that core scripts/builders create replay services with required dependencies.

Acceptance:
- Replay execution always has an input-access service and explicit input policy.

### Phase 6 — Standardize news/context/fundamental access

- [ ] Add `HistoricalNewsAccessService` returning news plus coverage/provenance.
- [ ] Add `ContextSnapshotAccessService` returning macro/industry snapshots plus coverage/provenance.
- [ ] Add `FundamentalSnapshotAccessService` returning fundamental snapshots plus coverage/provenance.
- [ ] Update replay coverage to merge market/news/context/fundamental coverage using common fields.
- [ ] Update context refresh/reconstruction scripts to emit coverage and primary-evidence provenance.

Acceptance:
- Context/fundamental replay coverage uses the same tier/blocker/warning language as bars.
- Context artifacts cannot claim clean coverage without primary evidence or an explicit degraded status.

### Phase 7 — Clarify outcome boundaries

- [ ] Document outcome population semantics:
  - live/paper recommendation outcomes
  - effective normalized outcomes
  - replay plan outcomes
  - replay eligibility rows
  - phantom outcomes
- [ ] Add explicit outcome-population fields to tuning/calibration summaries.
- [ ] Add filters such as `execution_only`, `phantom_only`, `execution_plus_phantom`, `replay_tier_a_only`, and `replay_tier_a_b` where relevant.

Acceptance:
- Every tuning/calibration report states exactly which outcome population and eligibility tier it used.

### Phase 8 — Validate critical JSON envelopes

- [ ] Introduce validation wrappers for run artifacts, replay input summaries, replay output summaries, replay diagnostics, and tuning summaries.
- [ ] Validate before writing critical artifacts.
- [ ] Mark artifacts degraded rather than silently writing null mandatory fields.

Acceptance:
- Missing mandatory keys fail tests or produce explicit degraded artifacts.

## Immediate implementation path

Start with the path that unblocks replay/tuning:

1. common coverage/provenance contracts
2. unified market bars access
3. replay provenance enforcement
4. replay eligibility reclassification
5. reclassify batch 15
6. rerun/rescore US top 50 fixed-floor tuning

## Testing requirements

Add unit tests for:

- cache-only bars returning valid coverage
- cache-then-remote bars returning the same coverage schema
- replay coverage built from stored bars without hydration
- replay plans containing non-null provenance
- missing provenance blocking eligibility
- resolved intraday replay outcomes becoming tier A when coverage is valid
- reclassification before/after tier-count reporting
- scripts/builders not constructing replay execution without required input services

## Operational guidance

Until this remediation is implemented:

- Treat replay batches with zero eligible rows and nonzero outcomes as degraded.
- Do not promote plan-generation config changes from salvage rescoring.
- Prefer replay paths built through canonical API builders rather than ad-hoc scripts.
- Keep actionability-floor rescoring separated from broader parameter tuning evidence.
