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

### Replay eligibility tier semantics

- `tier_a`: point-in-time generation coverage is sufficient, intraday resolution bars exist, the outcome is resolved from intraday evidence, and mandatory replay provenance is present. This is the preferred tuning evidence tier.
- `tier_b`: point-in-time generation coverage is sufficient and the outcome is resolved, but resolution uses daily fallback evidence rather than intraday evidence. This may be used only by workflows that explicitly accept daily-resolution replay evidence.
- `tier_c`: the replay row has some usable artifacts but is not valid promotion evidence, commonly because the outcome is still open/unresolved or resolution bars are missing.
- `ineligible`: generation coverage, resolution evidence, or mandatory provenance is missing enough that the row must not be consumed as tuning evidence.

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

- [x] Mark replay batch 15 as warning/degraded in its batch artifact or summary.
- [x] Mark salvage tuning run 37 as research-only and not promotion evidence.
- [x] Add a guardrail summary when replay outcomes exist but eligible tuning rows are zero.

Acceptance:
- Operators cannot mistake batch 15 or run 37 for valid tuning evidence.

### Phase 1 — Define common contracts

- [x] Add typed models/dataclasses for `InputAccessPolicy`, `InputCoverageReport`, `TickerCoverageReport`, and `ArtifactProvenance`.
- [x] Add schema helpers for stable coverage/provenance hashing.
- [x] Add first validation guard for mandatory replay provenance fields in replay eligibility classification.
- [x] Document tier semantics once and reuse them.

Acceptance:
- New replay/tuning code does not accept raw unvalidated coverage/provenance dicts.

### Phase 2 — Build unified market bars access

- [x] Add `HistoricalBarsAccessService`.
- [x] Implement first replay-oriented cache read, optional Yahoo hydration, persistence, reload-from-cache, and coverage report generation behind one method.
- [x] Add explicit gap-window detection before remote hydration to avoid broad refetches.
- [x] Support at least daily and 1-minute bars through typed access methods beyond the replay wrapper.
- [x] Add explicit replay input access policy so replay can build coverage from cache without remote hydration.
- [x] Add stable `input_coverage_hash` to replay market coverage reports.
- [x] Return data plus coverage/provenance for replay generation/resolution windows through a single bar-access method.
- [x] Replace direct market-bar access in replay coverage generation.
- [x] Replace replay outcome resolution price-history preparation with the unified access path or with a compatibility wrapper around it.
- [x] Update bars refresh/recovery scripts to call the unified service.

Acceptance:
- Cached bars and Yahoo-fetched bars produce the same coverage schema.
- Replay cannot silently produce an empty market coverage report when stored bars exist.

### Phase 3 — Enforce replay provenance

- [x] Attach replay provenance to generated recommendation plans, including compatibility backfill for orchestration implementations that persist plans directly.
- [x] Include replay batch ID, slice ID, as-of timestamp, code version, settings hash, input coverage hash, and tuning config hash.
- [x] Block replay tuning eligibility when mandatory provenance fields are missing.
- [x] Fail or degrade replay slices when mandatory provenance cannot be built.
- [x] Update replay eligibility classification to use typed provenance.

Acceptance:
- No replay-generated plan has null replay provenance.
- Missing provenance is reported as a clear blocker.

### Phase 4 — Add replay eligibility reclassification

- [x] Add `ReplayEligibilityReclassificationService`.
- [x] Add `scripts/reclassify_replay_eligibility.py --batch-id X`.
- [x] Rebuild market coverage from stored bars using `cache_only` when stored replay coverage is missing/empty.
- [x] Recompute fallback provenance hashes and eligibility tiers.
- [x] Report before/after tier counts and blocker counts.
- [x] Optionally allow `--policy cache-then-remote` for explicit hydration repair.

Acceptance:
- Existing replay batches can be repaired or definitively marked unusable without rerunning full replay.

### Phase 5 — Centralize service construction

- [x] Add a canonical builder for historical replay execution.
- [x] Replace route/worker ad-hoc replay construction with the canonical builder.
- [x] Update the actionability-floor replay experiment helper to use a market data service in `cache_only` mode instead of `historical_market_data=None`.
- [x] Ban `historical_market_data=None` outside explicit test fixtures.
- [x] Add tests that core scripts/builders create replay services with required dependencies.

Acceptance:
- Replay execution always has an input-access service and explicit input policy.

### Phase 6 — Standardize news/context/fundamental access

- [x] Add `HistoricalNewsAccessService` returning news plus coverage/provenance.
- [x] Add `ContextSnapshotAccessService` returning macro/industry snapshots plus coverage/provenance.
- [x] Add `FundamentalSnapshotAccessService` returning fundamental snapshots plus coverage/provenance.
- [x] Update replay coverage to merge market/news/context/fundamental coverage using common fields.
- [x] Update context refresh/reconstruction scripts to emit coverage and primary-evidence provenance.

Acceptance:
- Context/fundamental replay coverage uses the same tier/blocker/warning language as bars.
- Context artifacts cannot claim clean coverage without primary evidence or an explicit degraded status.

### Phase 7 — Clarify outcome boundaries

Outcome population semantics:

- `execution_only`: real/paper actionable recommendation outcomes only (`win`, `loss`, `no_entry`, `open`, etc.); excludes phantom outcomes.
- `phantom_only`: hypothetical outcomes for `no_action`/`watchlist` plans with complete intended trade framing (`phantom_win`, `phantom_loss`, `phantom_no_entry`, etc.); research only unless explicitly promoted by a spec.
- `execution_plus_phantom`: execution outcomes plus phantom outcomes; useful for actionability-floor research, not confidence honesty unless the report explicitly says so.
- `replay_tier_a_only`: replay eligibility rows with tier `tier_a`; preferred promotion evidence because point-in-time generation coverage, intraday resolution, resolved outcome, and mandatory provenance are present.
- `replay_tier_a_b`: replay eligibility rows with tier `tier_a` or `tier_b`; accepts daily fallback resolution and must be labeled less strict than tier-A-only evidence.
- `effective normalized outcomes`: broker/replay outcomes normalized into win/loss/no-entry/open families for aggregate EV/win-rate math; reports must still disclose whether source rows were execution, phantom, replay, or eligibility rows.

- [x] Document outcome population semantics:
  - live/paper recommendation outcomes
  - effective normalized outcomes
  - replay plan outcomes
  - replay eligibility rows
  - phantom outcomes
- [x] Add explicit outcome-population fields to tuning/calibration summaries.
- [x] Add filters such as `execution_only`, `phantom_only`, `execution_plus_phantom`, `replay_tier_a_only`, and `replay_tier_a_b` where relevant.

Acceptance:
- Every tuning/calibration report states exactly which outcome population and eligibility tier it used.

### Phase 8 — Validate critical JSON envelopes

- [x] Introduce validation wrappers for run artifacts, replay input summaries, replay output summaries, replay diagnostics, and tuning summaries.
- [x] Validate before writing critical replay input/output artifacts.
- [x] Mark artifacts degraded rather than silently writing null mandatory fields.

Acceptance:
- Missing mandatory keys fail tests or produce explicit degraded artifacts.

## Immediate implementation path

Start with the path that unblocks replay/tuning:

1. common coverage/provenance contracts — done
2. unified market bars access — done
3. replay provenance enforcement — done
4. replay eligibility reclassification — done
5. reclassify batch 15 — done
6. rerun/rescore US top 50 fixed-floor tuning — in progress

### Phase 9 — Rerun validated batch 15 tuning rescore

- [x] Add a reusable replay plan-generation rescore script that consumes only `replay_eligibility_records.eligible_for_tuning = true` rows by default.
- [x] Include explicit outcome-population and replay-tier labels in the generated tuning run/artifact.
- [x] Run the script for batch 15, fixed floor 48, 20 candidates.
- [x] Save artifact under `artifacts/` and mark the run as validated replay evidence only if it uses repaired eligibility rows, not salvage phantom-only rows.

Result: run `38` completed from repaired replay eligibility rows for batch `15`, fixed floor `48`, 20 candidates. It is valid as repaired replay evidence, but not promotion evidence: the winning candidate was the baseline/current config, search actionable count was `1`, validation actionable count was `0`, and the outcome population was dominated by phantom rows (`172` phantom vs `2` execution rows).

### Phase 10 — Promotion evidence-quality guardrails

- [x] Add replay promotion guardrails that reject phantom-dominated replay evidence unless execution-row coverage meets the minimum validation sample.
- [x] Surface the evidence-quality rejection reason in automatic replay promotion and manual replay candidate promotion checks.
- [x] Preserve dry-run/research reporting for phantom-heavy evidence; only block promotion.

### Phase 11 — Replay evidence audit report

- [x] Add a reusable replay evidence audit service/script for completed replay batches and tuning runs.
- [x] Flag zero-eligible, unresolved-heavy, and phantom-dominated evidence with machine-readable promotion readiness.
- [x] Write audit artifacts under `artifacts/` so future tuning decisions can cite the evidence-quality state directly.

Result: batch `15` audit and tuning run `38` audit both reject promotion readiness. Batch `15` is unresolved-heavy (`177/351` open or unresolved outcomes) and phantom-dominated (`172/174` eligible rows are phantom outcomes). Run `38` is also phantom-dominated without enough execution rows (`2` execution rows vs minimum `8`).

### Phase 12 — Replay outcome refresh for stale open rows

- [x] Add a reusable replay outcome refresh service/script that re-resolves existing replay plan outcomes from persisted bars.
- [x] Default to refreshing only open/unresolved replay outcomes and preserve already resolved outcomes unless `--include-resolved` is explicit.
- [x] Reclassify eligibility after refresh so audit/tuning uses current outcome state.
- [x] Re-audit batch `15` after refresh and decide whether another repaired rescore is warranted.

Result: batch `15` refresh converted `177` open/unresolved replay outcomes to resolved `expired` outcomes using cache-only persisted bars and reclassified eligibility. Audit after refresh shows unresolved ratio `0.0`, but promotion readiness still fails because eligible evidence remains phantom-dominated (`172/174` eligible rows are phantom outcomes, only `2` execution rows). Another repaired rescore is not warranted until a replay batch produces enough execution-row evidence.

### Phase 13 — Maintainability harmonization pass

- [x] Remove replay refresh monkeypatching/private remote-block hacks and expose explicit cache-only price-history preparation.
- [x] Replace duplicate stable-hash and JSON object loading helpers with common utilities where touched by remediation code.
- [x] Keep replay audit/refresh services small and policy-driven; avoid new one-off abstractions unless they are reused.
- [x] Run focused tests and a broader replay/tuning validation slice after refactor.

Result: replay outcome refresh now uses an explicit `allow_remote_fetch` price-history option instead of monkeypatching the evaluator downloader. Touched remediation code now reuses common `stable_hash` and `loads_json_object` helpers. Focused replay/tuning validation passed (`35 passed`).

### Phase 14 — Second maintainability harmonization pass

- [x] Centralize input-access policy constants and remote-fetch semantics so scripts/services do not repeat policy string sets.
- [x] Replace remaining remediation-local JSON object loader duplicates with common utilities.
- [x] Keep behavior unchanged and validate replay/input-access paths after the cleanup.

Result: input-access policies now have shared constants plus a common `input_policy_allows_remote_fetch` helper. Replay refresh, historical bar access, and replay utility scripts use those shared semantics. Historical replay, replay reclassification, plan-generation tuning routes, and job execution now use common JSON payload helpers instead of local duplicate loaders. Validation passed (`225 passed`).

### Phase 15 — Third maintainability harmonization pass

- [x] Extract replay evidence-quality checks shared by replay audit and replay tuning promotion gates.
- [x] Keep caller-specific rejection reason wording while using one implementation for phantom/execution sample math.
- [x] Validate replay audit and plan-generation tuning promotion guardrails after refactor.

Result: replay evidence quality now lives in `replay_evidence_quality.py`. Replay audit and plan-generation tuning promotion checks share the same phantom/execution math while preserving their existing public rejection reasons. Validation passed (`227 passed`).

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
