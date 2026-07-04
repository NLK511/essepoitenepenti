# Tuning workflow UX implementation plan

**Status:** in progress

Canonical spec: `specs/tuning-workflow-ux-spec.md`.

This plan breaks the work into small shippable phases. The goal is to give Aurelio one operator workflow from candidate discovery to candidate promotion, without removing the existing advanced replay and plan-generation tuning pages.

## Goals

- Create a coherent tuning workflow around a first-class experiment concept.
- Let the operator configure universe, windows, discovery size, replay shortlist size, objective, baseline, and promotion target.
- Clearly separate discovery evidence, replay validation, holdout validation, and promotion evidence.
- Keep replay cache-only and safe for the small VPS.
- Preserve deep links to raw replay batches, job runs, config versions, and artifacts.

## Non-goals for first version

- No unattended live promotion.
- No large brute-force search by default.
- No replacement of the existing historical replay page.
- No removal of the existing plan-generation tuning page; it becomes advanced/research.
- No remote Yahoo fetching during replay.

## Phase 0 — Design alignment and inventory

### Tasks

- [x] Re-read `specs/tuning-workflow-ux-spec.md`, `specs/plan-generation-tuning-spec.md`, and `specs/historical-playback-tuning-spec.md` before implementation.
- [x] Inventory existing tables/entities that can back the first workflow read model:
  - historical replay batches
  - historical replay slices
  - replay eligibility records
  - plan-generation tuning runs/candidates
  - config versions/promotions
  - job runs
  - app settings
- [x] Identify which experiment fields can be inferred from existing replay batch config metadata.
- [x] Identify fields that require a new persisted experiment table.
- [x] Decide whether v1 persists experiments or starts with a read-only inferred workflow.

Implementation choice: v1 now persists first-class `tuning_experiments` rows. Existing replay/tuning artifacts remain linked by ids and metadata in later phases. This avoids trying to infer operator hypothesis, windows, objective, and promotion target from replay batch config alone.

### Acceptance criteria

- [x] Implementation choice is documented in this plan.
- [ ] No code changes begin until the persistence/read-model approach is clear.

## Phase 1 — Backend experiment model/read model

### Tasks

- [x] Add a `TuningExperiment` persistence model or read-model adapter.
- [x] Represent required experiment fields:
  - name
  - notes/hypothesis
  - universe definition
  - discovery/training window
  - replay validation window
  - holdout window
  - candidate discovery search size
  - max candidates for replay
  - primary objective
  - baseline selection
  - promotion target
  - status/current stage
- [x] Represent advanced fields with conservative defaults:
  - candidate sources
  - parameter bounds
  - validation gates
  - data-quality policy
  - replay execution limits
  - evaluation horizons
  - manual review policy
  - stop conditions
- [x] Add service methods for create/list/get/update/archive experiments.
- [x] Add migration/tests for the new table.
- [x] Add initial lifecycle-state derivation for experiments:
  - setup incomplete
  - readiness needed
  - candidate discovery needed
  - shortlist needed
  - baseline needed
  - candidate replay needed/running/complete
  - stability validation needed
  - promotion proposal needed
  - promoted/rejected/archived

### Acceptance criteria

- [x] Unit tests cover experiment creation/defaults and read-model assembly.
- [x] Lifecycle state is deterministic from stored artifacts for setup/readiness stages.
- [x] Missing optional artifacts produce warnings/blockers, not crashes.

## Phase 2 — Workflow API endpoints

### Tasks

Add API routes under a new workflow namespace, for example `/api/tuning-workflow`.

- [x] `GET /api/tuning-workflow/experiments`
  - list experiments with status, current stage, and next action
- [x] `POST /api/tuning-workflow/experiments`
  - create an experiment from required setup fields
- [x] `GET /api/tuning-workflow/experiments/{id}`
  - return full workflow read model
- [x] `PATCH /api/tuning-workflow/experiments/{id}`
  - update setup/advanced settings when safe
- [x] `POST /api/tuning-workflow/experiments/{id}/archive`
  - archive experiment
- [x] Add initial response sections for:
  - setup completeness
  - evidence readiness
  - candidate pool
  - shortlist
  - baseline replay
  - candidate replay validation
  - stability validation
  - promotion proposal
  - post-promotion monitoring
- [x] Include computation labels in API responses where results are shown.
- [ ] Include deep links or ids for replay batches, tuning runs, job runs, config versions, and artifacts as artifacts become linked to experiments.

### Acceptance criteria

- [x] API tests cover create/get/list/update/archive.
- [x] API tests cover empty/incomplete states.
- [x] API response clearly distinguishes discovery-only, replay-validated, holdout-tested, and promotable sections in v1 placeholders.

## Phase 3 — Evidence readiness integration — partially implemented

### Tasks

- [x] Add service method to audit replay readiness for an experiment universe/window.
- [ ] Report:
  - cached bar coverage
  - expected Tier A ratio
  - repeated bar-gap tickers
  - missing outcome-window risk
  - degraded coverage warnings
  - cache-only policy confirmation
- [x] Add endpoint/action:
  - `POST /api/tuning-workflow/experiments/{id}/readiness-audit`
- [x] Add watchlist pruning recommendation payload for repeated gap tickers.
- [x] Ensure readiness audit does not fetch remote bars.

### Acceptance criteria

- [x] Tests prove readiness audit is cache-only.
- [x] Repeated bar gaps appear as warnings or pruning recommendations.
- [x] Candidate replay remains blocked when hard readiness gates fail, unless experiment is research-only and explicitly accepts risk.

## Phase 4 — Candidate discovery and shortlist management — partially implemented

### Tasks

- [x] Add candidate pool representation tied to an experiment metadata payload.
- [ ] Support candidate sources:
  - import prior large-search winners
  - fresh bounded search
  - manual config
  - strict quality-gate variants
  - risk/reward geometry variants
  - universe-filter variants
  - actionability-floor rescore candidates where valid
- [ ] Add source metadata:
  - data used
  - regenerates plans yes/no
  - promotion-capable yes/no
  - expected runtime/cost
- [ ] Add deduplication by config hash and similarity to baseline/existing candidates.
- [x] Add actions:
  - generate/import candidate pool
  - add manual candidate
  - reject candidate
  - select/unselect candidate for replay
- [x] Enforce max candidates for replay pass.
- [x] Store or return config changed keys/config hashes vs baseline.

### Acceptance criteria

- [x] Discovery-only candidates cannot be marked promotable.
- [x] Unknown config keys are rejected through existing parameter schema.
- [x] Shortlist cannot exceed experiment replay-pass limit.
- [ ] Tests cover source labeling and deduplication.

## Phase 5 — Baseline replay binding — partially implemented

### Tasks

- [ ] Add baseline selection to experiment:
  - current active config
  - selected config version
  - existing replay batch
  - rerun baseline replay
- [x] Add action to create/enqueue baseline replay for the experiment window/universe.
- [x] Add action to bind an existing replay batch as baseline.
- [ ] Add baseline summary:
  - batch id/status
  - slice progress
  - Tier A/B/C counts
  - outcomes
  - win rate
  - return/EV metrics
  - concentration warnings
- [x] Block candidate replay until baseline is selected and usable.

### Acceptance criteria

- [ ] Tests cover missing baseline block.
- [ ] Existing replay batch can be linked and summarized.
- [ ] Baseline replay creation preserves cache-only policy.

## Phase 6 — Candidate replay execution and comparison — partially implemented

### Tasks

- [x] Add action to create/enqueue candidate replay batches from shortlisted candidates.
- [ ] Default execution:
  - cache-only
  - sequential
  - max concurrency 1 on low resource profile
- [x] Add replay progress to workflow read model:
  - batch ids
  - slice progress
  - active/queued/failed/stale counts
  - linked worker/job run ids
- [x] Add comparison metrics against baseline:
  - Tier A sample count
  - win/loss/no-entry/open counts
  - win-rate delta
  - EV/return delta
  - MFE/MAE if available
  - ticker/setup concentration
  - data-quality warnings
- [ ] Add safe actions:
  - resume failed/stale replays
- [x] Add safe action metadata:
  - stop after current slice
  - view raw replay detail ids

### Acceptance criteria

- [x] Candidate replay batches carry scoped config overrides and do not mutate live settings.
- [x] Candidate comparison is unavailable until baseline metrics exist.
- [x] Tests cover replay queue creation for shortlisted candidates.
- [x] Stale/failed replay states surface clearly in workflow API.

## Phase 7 — Stability validation: walk-forward and holdout — partially implemented

### Tasks

- [ ] Add walk-forward action for a selected candidate.
- [ ] Label walk-forward as stability/overfit screen when it does not regenerate plans.
- [ ] Add holdout baseline replay action.
- [ ] Add holdout candidate replay action.
- [ ] Add stability summary:
  - qualified windows
  - worst-window delta
  - average delta
  - holdout batch ids
  - holdout Tier A metrics
  - pass/warn/fail status
- [ ] Detect and warn if holdout overlaps training/discovery window.
- [ ] Warn when the same holdout has been reused too many times for candidate selection.

### Acceptance criteria

- [ ] Tests cover non-overlap validation.
- [ ] Walk-forward alone does not make a candidate promotable.
- [ ] Holdout replay comparison can satisfy promotion evidence only when required gates pass.

## Phase 8 — Promotion proposal and execution — partially implemented

### Tasks

- [x] Add promotion proposal service/read model.
- [ ] Produce a gate table covering:
  - sample gates
  - baseline improvement gates
  - holdout gates
  - concentration gates
  - data-quality gates
  - stability gates
  - promotion target eligibility
- [ ] Add proposal outcomes:
  - blocked
  - needs more validation
  - recommended for paper
  - recommended for guarded live, only if allowed by broader autonomy gates
- [ ] Add actions:
  - create paper config proposal
  - reject proposal
  - request more validation
  - export report
- [x] Add promotion execution action for paper config creation.
- [x] Persist promotion reason, actor/mode, evidence links, target config, and rollback config for paper proposals.
- [x] Keep live promotion disabled unless the existing live/autonomy gates are explicitly satisfied.

### Acceptance criteria

- [ ] Tests cover blocked proposal reasons.
- [ ] A discovery-only or walk-forward-only candidate cannot be promoted.
- [ ] Paper promotion records evidence links and rollback config.
- [ ] Live promotion path fails closed by default.

## Phase 9 — Post-promotion monitoring — partially implemented

### Tasks

- [x] Add pending monitoring summary for paper-promoted config.
- [ ] Add live outcome monitoring summary for promoted config:
  - days active
  - plans generated
  - resolved outcomes
  - win rate/EV/return metrics
  - drift vs replay expectation
  - concentration warnings
  - rollback triggers
- [ ] Add actions:
  - extend paper trial
  - rollback
  - approve guarded live rollout, if supported
  - open performance details
- [ ] Integrate with existing recommendation-quality/performance endpoints where possible.

### Acceptance criteria

- [x] Monitoring summary appears for paper-promoted configs.
- [ ] Rollback action records reason and source/target config.
- [ ] Monitoring can show pending/insufficient evidence without implying success.

## Phase 10 — Frontend workflow page

### Tasks

- [x] Add route `/research/tuning-workflow`.
- [x] Add navigation label: `Tuning Workflow`.
- [x] Build top lifecycle banner:
  - experiment name
  - current stage
  - candidate funnel counts
  - recommendation
  - next action
  - blockers
- [x] Build initial cards:
  1. Experiment setup
  2. Evidence readiness
  3. Candidate discovery
  4. Candidate shortlist
  5. Baseline replay
  6. Candidate replay validation
  7. Walk-forward / holdout
  8. Promotion proposal
  9. Promotion execution
  10. Post-promotion monitoring
- [x] Use explicit computation labels on all result cards.
- [x] Add create/setup form with required fields.
- [ ] Add edit form and advanced settings drawers.
- [ ] Add deep links to:
  - historical replay batch
  - run detail
  - worker logs
  - plan-generation tuning run
  - config version
  - promotion report
- [x] Avoid raw JSON by default.

### Acceptance criteria

- [x] Operator can create an experiment and see incomplete/missing next steps.
- [x] Operator can move from discovery to shortlist and record replay evidence from one page.
- [x] Operator can queue fresh replay batches directly from one page.
- [x] UI never labels discovery-only candidates as winners or validated.
- [x] UI clearly blocks promotion until all required gates pass.

## Phase 11 — Existing page cleanup

### Tasks

- [x] Add banner to current Plan Generation Tuning page:
  - “Use Tuning Workflow for normal optimization; this page is advanced/research.”
- [ ] Rename ambiguous UI copy:
  - `stored_plan_rescore` → `Diagnostic stored-plan rescore`
  - large search → `Research-only candidate discovery`
  - walk-forward → `Stability walk-forward check`
- [ ] Keep existing historical replay page as raw replay diagnostics.
- [ ] Add links from old pages back to the workflow page when artifacts belong to an experiment.

### Acceptance criteria

- [x] Existing advanced controls remain accessible.
- [x] Normal operator path points to the workflow page.
- [x] Initial copy matches `specs/tuning-workflow-ux-spec.md` operator-copy rules.

## Phase 12 — Tests, docs, and rollout

### Tasks

- [ ] Add backend unit tests for repositories/services/routes.
- [ ] Add frontend tests where project conventions support them.
- [ ] Add API fixtures for empty, running, blocked, and promotable experiments.
- [ ] Update `operator-page-field-guide.md` with the new workflow once implemented.
- [ ] Update `features-and-capabilities.md` after rollout.
- [ ] Run full test suite.
- [ ] Manually smoke-test on Docker with one small cache-only experiment.
- [ ] Commit and push after a coherent milestone.

### Acceptance criteria

- [ ] Existing replay and tuning tests still pass.
- [ ] New workflow tests pass.
- [ ] Docker worker/API paths can display linked replay progress/logs.
- [ ] Documentation reflects implemented vs target behavior.

## Suggested milestone order

1. **Read-only workflow dashboard**
   - API read model plus frontend cards using existing artifacts.
2. **Experiment setup and persistence**
   - create/edit/archive experiments with required inputs.
3. **Candidate pool and shortlist**
   - import/generate/select candidates.
4. **Replay orchestration**
   - baseline and candidate replay actions from workflow.
5. **Promotion proposal**
   - gate table and paper proposal.
6. **Post-promotion monitoring**
   - paper-trial monitoring and rollback support.

## Risks and mitigations

### Risk: workflow becomes another large confusing page

Mitigation:
- show one current recommendation and next action at the top
- keep advanced settings collapsed
- use stage cards with clear status and blockers

### Risk: operators overfit to holdout

Mitigation:
- warn on reused holdout windows
- require separate windows
- keep candidate counts small

### Risk: replay overloads VPS

Mitigation:
- default concurrency 1
- default candidate replay count 5
- cache-only replay
- stop conditions and stale recovery surfaced in UI

### Risk: discovery results are mistaken for validation

Mitigation:
- mandatory computation labels
- copy rules from spec
- promotion blocked unless replay/holdout gates pass

## Open implementation decisions

- [ ] Persist `tuning_experiments` now, or infer v1 from replay batch metadata?
- [ ] Store candidate pool in a new table, or attach to experiment config JSON initially?
- [ ] Should candidate discovery jobs be separate job type(s), or reuse `plan_generation_tuning` with workflow metadata?
- [ ] Should watchlist pruning proposals be persisted or generated on demand?
- [ ] Which default objective should be selected for the first production workflow: Tier A win rate, 5d return, or balanced score?
