# Plan generation tuning spec

**Status:** current + target behavior

Binding reference for recommendation plan-generation tuning. If implementation conflicts with this spec, update the spec first or change the implementation.

## Purpose and boundary

Plan-generation tuning improves **actionable recommendation plans after upstream signal gating**. It tunes trade framing and actionable precision, not broad ticker selection.

It may tune parameters that materially affect:
- actionable vs non-actionable decisions
- entry, stop-loss, and take-profit construction
- confidence/selectivity logic that directly changes plan actionability
- setup-family, regime, direction, technical, volatility, or context adjustments used in plan framing

It must not tune:
- market-data ingestion/vendor policy
- outcome-resolution semantics
- broker execution/risk-management behavior
- upstream signal-gating thresholds
- unrelated model/UI settings

Related division of labor:
- **signal gating tuning** = upstream recall/shortlist control
- **plan-generation tuning** = downstream trade framing/precision
- **quality, calibration, baseline, and walk-forward reports** = trust and promotion evidence

The legacy weight optimizer is retired. Do not revive its workflow, job type, active settings, or rollback path. `weights.json` may remain only as a normal scoring input where still needed.

## Current implementation snapshot

Live behavior includes:
- dedicated routes, persistence, runs, candidates, config versions, and config promotion
- research UI for runs, grouped candidates, campaign plan, config history, and manual controls
- stored automation readiness flags (`auto_enabled`, `auto_promote_enabled`)
- live consumption of the active plan-generation config during plan construction
- bounded deterministic local perturbations around live config, plus small deterministic refinement passes
- family-aware entry offsets, actionable confidence floor, and volatility-normalized stop controls
- candidate ranking by win rate, win count, then expected value with explicit tie tolerances
- batched wide/explore evaluation with memory guardrails
- full dry-run tuning must avoid duplicate eligible-record loads; final walk-forward validation should reuse the already loaded eligible record set rather than querying the same large outcome universe again

Not fully autonomous yet:
- the complete daily evolution workflow
- all target diversity/concentration/stability protections as sole unattended promotion policy
- unattended auto-promotion beyond current validation/baseline/tie checks

`auto_enabled` and `auto_promote_enabled` are stored readiness/configuration flags. They are not proof that unattended autonomous promotion is fully active.

## Product modes

The system supports:
1. **Manual research** — inspect runs, compare candidates, manually promote or reject.
2. **Automatic evolution** — scheduled dry-run/evaluation and conservative auto-promotion only when every safety rule passes.

Automatic mode must default conservative and improve gradually, not chase noise.

## Canonical objective and ranking

Candidates rank lexicographically:
1. maximize actionable win rate
2. maximize actionable win count
3. maximize actionable expected value
4. if still tied, prefer closer-to-live config
5. if still tied, prefer fewer changed parameters

Tie tolerances:
- win rate: `0.25 percentage points`
- win count: `1 win`
- expected value: `0.02R` or the implementation's equivalent normalized unit

A materially lower win-rate candidate must not outrank a higher win-rate candidate only because it trades more.

For exploration runs, ranking metrics must come from rolling walk-forward validation, not one tail split.

## Parameter schema

Every tunable key must be registered before use. Candidate configs containing unknown keys must be rejected.

Required metadata per parameter:
- `key`, `label`, `description`
- `type`: `float`, `int`, `bool`, or `enum`
- `scope`: `global`, `setup_family`, `regime`, `direction`, or a documented combination
- `default_value`, `current_live_value`
- `min_value`/`max_value` or enum options
- numeric `step`
- `exploration_mode`: `grid`, `mutation`, `baseline_only`, or `fixed`
- `materiality_class`: `critical`, `secondary`, or `experimental`

Current live knob classes include:
- family-aware entry band multiplier
- actionable confidence floor
- volatility-normalized stop multiplier

Keep knobs bounded, deterministic, replayable, and covered by live-framing/tuning parity tests before widening the surface.

## Data eligibility and leakage policy

Use all meaningful data only after strict eligibility checks.

Canonical sources:
- `RecommendationPlan`
- `RecommendationPlanOutcome`
- `RecommendationDecisionSample`
- linked context snapshots
- linked ticker-signal snapshots
- derived replay/backtest artifacts that reproduce plan-generation inputs without leakage

Eligible records need:
- reproducible plan-generation inputs or sufficient stored artifacts
- known generation timestamp
- known directional/actionable interpretation
- resolved or scoreable outcome for win/loss/EV metrics, including scoreable broker outcomes and `phantom_win`/`phantom_loss` for `no_action`/`watchlist` plans with `intended_action`

Exclude records with unresolved required metrics, corrupted/missing features, uncertain reconstruction, future-data leakage, or unsafe backfill/recompute semantics.

Evidence tiers:
- **Tier A**: fully reproducible/resolved; allowed for ranking and promotion
- **Tier B**: minor non-critical gaps; research summaries only
- **Tier C**: weak/incomplete; diagnostics only

Auto-promotion must rely primarily on Tier A data.

Anti-leakage rules:
- candidate scoring may use only generation-time inputs plus later labels for evaluation
- outcome-period bars/post-generation metrics are evaluation-only unless explicitly allowed
- replay baselines and thresholds must come from candidate config and admissible historical context
- training/search windows must end before validation windows

## Replay and candidate generation

Replay must deterministically answer, for each eligible record:
- would the candidate produce an actionable plan?
- what entry/stop/take-profit would it produce?
- how would that plan resolve under canonical resolution semantics?
- what opportunity was filtered out if non-actionable?

Use `recommendation-plan-resolution-spec.md` as the outcome authority. Do not invent separate outcome semantics.

Candidate generation must be deterministic and capped. Allowed sources:
- live baseline config
- small local perturbations around baseline
- top promoted/non-promoted historical configs when safe
- bounded mutations within schema limits

Current simplified exploration policy:
- include baseline plus deterministic local perturbations
- optional small refinement around top seeds
- optional targeted smaller-step probe around the leading candidate's best key when it already beats baseline
- no random/history-heavy rescue paths
- process eligible records in deterministic chunks and abort cleanly on memory guardrail breach

Default limits unless overridden:
- scheduled/manual candidates: `17`
- wide research candidates: `49`
- internal eligible-record batch size: `250`
- max changed keys per candidate: `1`
- max step distance: manual `1`, explore `2`, wide `3`

Initial exploration envelope:

| Parameter key | Min | Max |
| --- | ---: | ---: |
| `global.entry_band_risk_fraction` | `0.00` | `0.25` |
| `global.headwind_stop_multiplier` | `0.84` | `1.02` |
| `setup_family.breakout.stop_distance_multiplier` | `0.65` | `1.05` |
| `setup_family.breakout.take_profit_distance_multiplier` | `0.95` | `1.45` |
| `setup_family.mean_reversion.stop_distance_multiplier` | `0.88` | `1.32` |
| `setup_family.mean_reversion.take_profit_distance_multiplier` | `0.72` | `1.08` |
| `setup_family.catalyst_follow_through.take_profit_distance_multiplier` | `1.05` | `1.50` |
| `setup_family.macro_beneficiary_loser.take_profit_distance_multiplier` | `1.00` | `1.30` |

Default first campaign budget: `16` perturbation candidates plus baseline before deduplication.

## Scoring outputs

Persist for every candidate:
- rank, status, promotion eligibility, rejection reasons
- candidate config and changed keys
- baseline delta summary
- actionable count, resolved count, wins, losses, win rate, expected value
- filtered-out count and coverage rate
- setup-family, direction, and regime breakdowns where available
- sample-size and validation flags

## Promotion rules

A candidate is invalid for promotion if it:
- lacks minimum sample quality
- creates impossible/invalid price geometry
- degrades protected secondary metrics beyond limits
- uses unregistered schema keys
- fails holdout/walk-forward validation

Minimum auto-promotion sample thresholds:
- actionable resolved plans: `50`
- wins: `20`
- Tier A eligible records: `200`
- distinct tuning dates: `20 market days`
- distinct tickers: `20`

Protected secondary guardrails relative to baseline:
- actionable count drop must not exceed `40%`
- actionable resolved drop must not exceed `35%`
- expected value drop must not exceed `0.10R`
- any major setup family with at least `20` resolved actionables must not lose more than `15pp` win rate
- top-1 ticker concentration must not exceed `25%` unless baseline already exceeds it and candidate improves concentration

Minimum improvement for auto-promotion:
- actionable win rate improves by at least `1.0pp`, or
- improves by at least `0.5pp` and actionable win count increases by at least `10%`

Auto-promotion must pass both full-backtest and recent holdout/rolling validation. Default holdout split is oldest `80%` for search/aggregation and newest `20%` for validation; insufficient samples force research-only mode.

Promotion modes:
- `dry_run`
- `manual_promote`
- `auto_promote`
- `rollback`

Auto-promotion must fail closed unless the shared edge-validation gate has explicit passing baseline-comparison, drawdown, and loss-streak evidence, plus walk-forward, concentration, degraded-input, and broker-reconciliation inputs. Manual promotion may target any candidate passing promotion checks and does not require the autonomy edge gate.

Rollback must persist source config, target config, reason, actor/mode, and timestamp.

## Persistence and settings

Required entities:
- `plan_generation_tuning_runs`
- `plan_generation_tuning_candidates`
- `plan_generation_tuning_config_versions`
- `plan_generation_tuning_events`

Minimum run fields: status, mode, objective, promotion mode, timestamps, baseline/winner/promoted references, eligible/candidate/validation counts, summary/filter JSON, error, code version.

Minimum candidate fields: run, rank, status, baseline flag, promotion eligibility, config, changed keys, score/breakdown/sample/validation JSON, rejection reasons, created time.

Minimum config fields: version label, status, source, parent, source run/candidate, config JSON, schema version, create/activate/deactivate times.

Minimum event fields: event type, run/config/candidate references, actor, payload, created time.

Active config must be readable atomically without scanning history. Promotion must atomically switch the active reference. Live plan generation must read only the active plan-generation config.

## API contract

Required endpoints:
- `GET /api/plan-generation-tuning`
- `GET /api/plan-generation-tuning/runs`
- `GET /api/plan-generation-tuning/runs/{run_id}`
- `POST /api/plan-generation-tuning/run`
- `POST /api/plan-generation-tuning/configs/{config_version_id}/promote`
- `POST /api/plan-generation-tuning/configs/{config_version_id}/rollback`
- `GET /api/plan-generation-tuning/configs`
- `GET /api/plan-generation-tuning/configs/{config_version_id}`
- `GET /api/plan-generation-tuning/parameters`
- `POST /api/plan-generation-tuning/settings`

Response rules:
- paginated endpoints return `{ items, total, limit, offset }`
- run details include baseline and winner references
- config details include provenance
- promotion decisions include explicit promotion/rejection reasons

Optional endpoints may expose candidate detail, config comparison, or skipped scheduled-run history.

## UI contract

Research UI must show:
- active config, scheduler/automation state, latest run
- run history with status/mode/date/promotion filters
- run detail with baseline vs winner, candidate ranking, eligibility, guardrails, and manual promote actions
- config history with active/superseded state and rollback where allowed

Safety requirements:
- distinguish `dry_run`, `manual_promote`, and `auto_promote`
- label rankable-but-not-promotable candidates
- default to eligible candidates, with blocked candidates behind a toggle
- show guardrail failures and active config provenance

## Tuning job names

Use these operator-facing names to avoid confusing monitors, tuning searches, and promotion:

- **Standard tuning search**: the default bounded plan-generation tuning run (`mode=manual`).
- **Exploratory tuning search**: a broader plan-generation tuning run (`mode=explore`).
- **Wide tuning search**: the broadest built-in deterministic plan-generation tuning run (`mode=wide`).
- **Plan Generation Large Tuning Search**: offline, non-schedulable, research-only coarse/fine parameter search from `large-parameter-search-spec.md`.

## Operator research workflow

The tuning page must support a research workflow, not just a raw candidate table:

- promoted configuration management: list config versions, active status, nominal source-candidate performance, scored historical performance, and inferred active periods; non-active configurations may be retired/deleted from the active management view. The UI may load this portfolio after the main page shell for responsiveness, but historical rescoring must use the full eligible evidence set; eligible record snapshots should be persisted instead of rebuilt from scratch on every page load.
- job launch controls for standard, wide, exploratory, and large-search runs
- paged job-run history across standard/wide/exploratory and large-search jobs, with run datetime, status, duration, mode/search kind, and inline best-result summary
- expandable run details with candidates, summaries, artifacts, rejection reasons, and raw payloads where useful
- baseline-vs-candidate/config comparison using the currently promoted config or a selected baseline version
- walk-forward validation for selected candidates/configs/raw configs with operator-specified lookback days, validation-window days, step days, and minimum resolved validation rows

Large-search artifacts remain research-only and are not promotion-capable by themselves. A large-search candidate must be revalidated with walk-forward and operator review before any equivalent configuration is promoted through normal config-version controls.

The hidden worker-backed system job for normal UI/API tuning runs is named `__system__:plan-generation-tuning-standard-search`. It is not operator-schedulable.

## Jobs, failures, and observability

Scheduled/manual runs must use durable worker/job records and prevent concurrent active scheduled runs. Scheduled automatic mode defaults to dry-run; auto-promotion is separately toggleable.

Each scheduled run loads active config, loads eligible data, generates/evaluates/ranks candidates, validates the winner, promotes only if all rules pass, and persists summary/history.

Failure rules:
- failed runs never partially activate configs
- failed auto-promotion leaves active config unchanged
- partial candidate evaluation is allowed only with no promotion and a partial marker
- every failure persists a human-readable error

Persist observability metadata: code version, schema version, sample summary, holdout summary, baseline/winner metrics, promotion decision, and skipped/no-promotion reasons.

## Acceptance criteria

Complete behavior requires:
- dedicated run/candidate/config/event persistence
- atomic active-config loading by live plan generation
- manual dry-run, manual promote, state, history, and config APIs
- scheduled runs with conservative auto-promotion guardrails
- deterministic/auditable candidate ranking
- UI visibility into active config, runs, candidates, guardrails, and provenance
- rollback support and audit trail
- no automatic drift outside registered schema or sample/holdout/guardrail checks

## Non-goals

Do not add reinforcement learning, black-box Bayesian optimization, self-mutating schemas, unrelated-domain tuning, or unbounded unsupervised mutation until the deterministic bounded system is proven stable and explicitly re-specified.

## Amendment rule

Update this spec before changing objective order, promotion policy, eligibility rules, schema boundaries, persistence semantics, or automatic-mode safety guarantees.

## Related docs

- `../recommendation-methodology.md`
- `recommendation-plan-resolution-spec.md`
- `../decision-sample-tuning-guide.md`
- `../signal-gating-tuning-guide.md`
- `../raw-details-reference.md`
- `../operator-page-field-guide.md`
