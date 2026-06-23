# Historical playback tuning implementation plan

**Status:** in progress

This plan advances the app from the current compact stored-plan tuning workflow toward a point-in-time historical playback and tuning mechanism.

## Goal

For each historical `as_of` slice, the system should be able to:

1. load only generation inputs available at or before `as_of`
2. regenerate ticker signals and recommendation plans using current code/settings plus a candidate plan-generation tuning config
3. resolve resulting candidate plans with post-`as_of` bars under canonical plan-resolution semantics
4. compare candidate configs through search, validation, and walk-forward slices
5. promote only when sample quality and edge-validation gates pass

Eligible records remain, but their target meaning changes from "stored plan compact rescore row" to "quality-gated replay case".

## Modes

- `stored_plan_rescore`: current implementation. Re-scores existing recommendation plans using compact eligible records.
- `current_code_point_in_time_replay`: target implementation. Rebuilds decisions with current code and current non-tuned settings over point-in-time historical inputs.
- `historical_code_replay`: optional future audit mode. Attempts to replay old code/settings exactly; not required for tuning edge discovery.

## Phase 0 — Spec reconciliation

- [x] Create this implementation plan.
- [x] Create `docs/specs/historical-playback-tuning-spec.md` as the target/current boundary for replay-driven tuning.
- [x] Update `docs/specs/plan-generation-tuning-spec.md` so it explicitly distinguishes current stored-plan rescore from target point-in-time replay.
- [ ] Add cross-links from operator/research docs after the first replay-tuning mode lands.

Acceptance:
- Specs say what is already implemented and what is target behavior.
- Specs do not imply current tuning already regenerates plans for every historical slice/candidate.

## Phase 1 — Replay data coverage audit

- [x] Add initial replay coverage report for historical replay slices.
- [x] Report generation-time daily/intraday bar coverage using point-in-time `available_at <= as_of` filtering.
- [x] Report post-`as_of` outcome-resolution bar coverage separately from generation inputs.
- [x] Classify ticker/slice readiness into initial Tier A/B/C/ineligible labels.
- [x] Add historical news coverage to the report once news `available_at` exists.
- [x] Add context snapshot and fundamental snapshot coverage to the report.
- [x] Surface coverage report in the historical replay API via `GET /api/historical-replay/slices/{slice_id}/coverage`.
- [ ] Surface coverage report in the historical replay UI once a dedicated replay page exists.

Acceptance:
- For a replay batch/slice, operators can see why each ticker is or is not usable for full replay tuning.
- Generation input coverage and outcome-resolution coverage are not mixed.

## Phase 2 — Historical news point-in-time hardening

- [x] Add `available_at` to `historical_news_items`.
- [ ] Add `ingested_at` if distinct from row `created_at`.
- [x] Backfill legacy rows with `available_at = published_at` plus inferred-availability metadata/confidence.
- [x] Update historical news repository queries to filter replay requests by `available_at <= as_of`.
- [x] Update replay diagnostics to expose whether database news was filtered by availability time.
- [x] Add tests proving future-available news is excluded from generation-time replay.

Acceptance:
- Replay news selection is explicitly point-in-time bounded.
- No replay path silently falls back to live-only providers.

## Phase 3 — Connect historical replay to plan generation

- [x] Add a replay execution path that runs cheap scan, deep analysis, signal generation, and recommendation plan generation for a slice when watchlist orchestration is configured.
- [x] Pass `as_of` through replay plan generation orchestration.
- [x] Persist replay-generated signal and plan artifacts through the existing watchlist orchestration repositories.
- [x] Persist explicit replay provenance on every generated signal/plan: batch id, slice id, `as_of`, code version, settings hash, data coverage summary, input warnings.
- [x] Add tests proving replay plan generation passes the slice `as_of` through to generation orchestration and attaches replay provenance.
- [x] Add deeper integration tests proving concrete cheap-scan/deep-analysis fetchers reject post-`as_of` generation inputs.

Acceptance:
- Running one historical slice can produce replay-generated recommendation plans, not only market-input summaries.

## Phase 4 — Candidate config overrides

- [x] Add a scoped plan-generation tuning config override for replay/tuning calls.
- [x] Reject unknown override keys through the existing parameter schema.
- [x] Ensure overrides do not mutate the active live config.
- [x] Add live/replay parity tests for identical inputs and identical configs.
- [x] Add tests proving candidate config changes affect plan levels through shared plan-framing logic.

Acceptance:
- Replay tuning can evaluate candidate configs safely without changing production settings.

## Phase 5 — Canonical candidate resolution

- [x] Resolve replay-generated candidate plans through `PlanResolutionEngine` via the canonical evaluation service path.
- [x] Prefer post-`as_of` intraday bars for final stop/take ordering.
- [x] Use daily bars only as prefilter/fallback according to `recommendation-plan-resolution-spec.md`.
- [x] Store replay candidate outcomes separately from live outcomes in `replay_plan_outcomes`.
- [x] Add tests for both stop and target touched, same-bar ties, no-entry, and expiration.

Acceptance:
- Replay tuning no longer depends primarily on compact MFE/MAE/horizon-return shortcuts.

## Phase 6 — Replay eligibility builder

- [x] Create replay eligibility records tied to replay batch/slice/plan/outcome/candidate config.
- [x] Tier A: point-in-time generation inputs plus intraday canonical outcome resolution.
- [x] Tier B: minor generation gaps or accepted fallback resolution.
- [x] Tier C: diagnostics only.
- [x] Preserve current compact eligible records under `stored_plan_rescore` labeling.
- [x] Add tests for each eligibility tier and rejection reason.

Acceptance:
- Eligibility becomes a quality gate over replayed cases, not a substitute for playback.

## Phase 7 — Replay-based plan-generation tuning

- [x] Add tuning modes `point_in_time_replay` and `wide_point_in_time_replay`.
- [x] Aggregate metrics from existing replay eligibility records for replay modes.
- [x] Add a deterministic bridge that creates/enqueues historical replay batches for ranked candidate configs over the replay artifact slice window.
- [x] Aggregate completed per-candidate replay batch eligibility/outcome results back to ranked tuning candidates.
- [x] Add bounded synchronous execution of candidate replay batches from a tuning run through the job execution service.
- [x] Integrate optional synchronous candidate replay execution and post-run aggregation payloads into the main tuning `run()` workflow.
- [x] Rerank candidates from completed replay batch outcomes using eligible counts, Tier A/B mix, and win/loss counts.
- [x] Use replay-reranked winners for safe promotion decisions inside the main tuning `run()` workflow.
- [x] Include baseline config in every run.
- [x] Reuse existing replay eligibility artifacts carrying `as_of/ticker/candidate_config_hash/input_coverage_hash` keys in replay aggregation mode.
- [x] Invalidate replay artifacts for tuning aggregation when code/settings artifact versions do not match the current process.
- [x] Add deterministic repeatability tests for replay-artifact aggregation mode.

Acceptance:
- Candidate ranking can be computed from replay-generated decisions rather than existing stored plans.

## Phase 8 — Walk-forward and promotion hardening

- [x] Require Tier A replay evidence for unattended auto-promotion.
- [ ] Keep manual promotion possible for research candidates that pass non-autonomous checks.
- [ ] Compare replay candidate vs baseline over rolling walk-forward windows.
- [ ] Require baseline, drawdown, loss-streak, concentration, degraded-input, and broker-reconciliation gates before auto-promotion.
- [x] Add tests proving auto-promotion fails closed when replay coverage/gates are missing.

Acceptance:
- Auto-promotion never relies only on stored-plan rescore evidence.

## Phase 9 — Operator visibility

- [ ] Show tuning mode on tuning run detail.
- [ ] Show Tier A/B/C counts and skipped-slice reasons.
- [ ] Show intraday vs daily resolution split.
- [ ] Show replay data coverage report on historical replay slice detail.
- [ ] Add links from tuning candidates to replay slices/plans/outcomes.

Acceptance:
- A human operator can audit why a candidate won and whether the evidence is trustworthy.

## Phase 10 — Default migration

- [ ] Make replay-based tuning the default for scheduled/auto tuning once stable.
- [ ] Keep `stored_plan_rescore` as a manual diagnostic/regression mode.
- [ ] Update docs and UI labels so old eligible-record tuning is not mistaken for full replay.
- [ ] Remove any obsolete promotion path that can auto-promote from compact stored-plan evidence alone.

Acceptance:
- The production tuning loop is based on point-in-time replay evidence.
