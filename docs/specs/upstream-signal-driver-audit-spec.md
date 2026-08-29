# Upstream signal driver audit spec

**Status:** target behavior

The phantom selectivity tuning layer is on hold. Broad threshold searches did not find a stable policy, but the strict separability audit found six narrow candidate groups and candidate replay showed positive research-only performance with too few selection dates for promotion.

The next useful work is to inspect upstream signal quality. The app must explain whether the candidate groups are supported by reusable signal features, or whether they are only ticker-specific artifacts that should not drive more tuning.

## Goal

Produce a read-only audit artifact that compares the candidate phantom-selectivity groups against the broader tier-A phantom evidence pool using raw stored plan signal fields.

The audit must answer:

- Are candidate rows enriched for reusable upstream features such as setup family, context bias, transmission tags, catalyst intensity, volatility, intended action, decision tier, confidence components, or shortlist metadata?
- Inside the candidate rows, do any reusable features distinguish phantom wins from phantom losses?
- If no reusable feature explains the lift, is the apparent edge mostly ticker identity?

## Rules

- The audit must be read-only. It must not mutate tuning config, replay rows, plans, broker settings, jobs, orders, or scheduler state.
- The audit must use replay evidence profile `phantom_selectivity` by default: intraday `phantom_win` and `phantom_loss` rows from accepted replay tiers.
- Candidate rows must be selected from the separability artifact candidate groups, not rediscovered by a fresh threshold search.
- The audit must hydrate raw `signal_breakdown_json` from stored recommendation plans. It must not rely only on the narrowed tuning snapshot.
- Expected value must use stored candidate trade geometry, as in phantom selectivity replay.
- Ticker identity may be reported, but it must not be treated as reusable upstream signal quality by itself.
- Missing or sparse signal fields must be reported explicitly.

## Feature families

The first implementation must inspect these reusable feature families when present:

- setup family
- context bias
- plan action and effective intended action
- confidence bucket
- cheap-scan volatility bucket
- transmission tags
- expected transmission window
- catalyst intensity bucket
- decision tier
- shortlist flag and shortlist rank bucket
- confidence component buckets
- calibration review direction or action when available
- fundamental coverage/status buckets when available

The audit may also report ticker enrichment as a diagnostic, but ticker-only enrichment must produce a weaker verdict.

## Verdicts

- `upstream_feature_lead` — candidate rows and candidate wins are explained by at least one reusable non-ticker signal feature with enough support and positive expected value.
- `ticker_artifact_only` — candidate performance is present, but no reusable non-ticker signal feature has enough support. Further work should avoid tuning and inspect ticker-specific upstream generation.
- `insufficient_feature_coverage` — raw signal fields are too sparse to support a conclusion.

Default gates:

- total candidate rows: at least 100
- candidate distinct dates: at least 10
- minimum feature support in candidate rows: at least 30
- minimum feature support in candidate selection dates: at least 5
- minimum reusable feature coverage: 60 percent of candidate rows must have at least one reusable feature
- reusable feature candidate win-rate lift over candidate baseline: at least 5 percentage points
- reusable feature expected value per observation: greater than 0

## Output

The artifact must include:

- input separability artifact path and replay evidence profile;
- candidate group count;
- population and candidate metrics;
- reusable feature coverage;
- top reusable feature enrichments in candidate rows versus all phantom rows;
- top reusable feature win/loss drivers inside candidate rows;
- ticker diagnostics;
- verdict, blockers, and recommendation.

If the verdict is `upstream_feature_lead`, the next work is to inspect or improve upstream generation around the listed reusable features, then rerun candidate replay after enough new evidence accumulates.

If the verdict is `ticker_artifact_only`, the next work is not another tuning search. It is ticker-specific upstream diagnosis for the passing tickers.

If the verdict is `insufficient_feature_coverage`, the next work is instrumentation: persist the missing signal features consistently before trying more optimization.

## Driver drilldown

When the audit returns `upstream_feature_lead`, the next artifact must drill into concrete feature/value drivers instead of creating new search knobs.

The drilldown must:

- use the upstream audit artifact as input;
- use the same candidate groups from the separability artifact;
- inspect concrete feature/value drivers from `top_reusable_candidate_win_loss_drivers` by default;
- report driver metrics, ticker concentration, setup/context/action mix, transmission tag mix, and date spread;
- include compact example rows for phantom wins and phantom losses;
- include enough raw signal fields to explain why the row belongs to the driver without dumping the entire plan payload;
- classify each driver as reusable, ticker-concentrated, or thin.

Driver drilldown verdicts:

- `reusable_driver_leads` — at least one driver has enough rows, enough dates, positive expected value, and is not dominated by one ticker.
- `ticker_concentrated_driver_leads` — drivers are positive but mostly explained by one ticker.
- `thin_driver_evidence` — drivers do not have enough rows or dates for a useful upstream-quality read.

Default driver gates:

- driver rows: at least 30
- driver distinct dates: at least 5
- driver tickers: at least 5 to be considered reusable
- driver expected value per observation: greater than 0
- maximum single ticker share for reusable status: 50 percent

The drilldown is still read-only. A passing drilldown does not promote a tuning policy. It only identifies the upstream signal-generation code paths worth inspecting or changing.

## Prospective driver tags

When the drilldown finds reusable driver leads, new plans must persist non-behavioral tags for the exact upstream signal-quality drivers that matched at generation time.

These tags are instrumentation only:

- they must not change `action`, confidence, thresholds, entry, stop, take-profit, jobs, or broker behavior;
- they must live in `signal_breakdown.upstream_signal_quality_drivers`;
- each tag must include a stable key, feature, value, and short reason;
- the tag rules must be deterministic and based only on fields already present in the plan signal breakdown.

Initial prospective tags are limited to driver buckets proven by the July 2026 drilldown:

- `shortlist_rank_bucket=35-40`
- `shortlist_rank_bucket=45-50`
- `volatility_bucket=30-40`
- `confidence_component_bucket=catalyst_confidence:60-70`
- `confidence_component_bucket=data_quality_cap:90-100`
- `confidence_bucket=35-40`
- `confidence_component_bucket=execution_clarity:0-10`
- `confidence_component_bucket=data_quality_cap:60-70`

These tags create a clean prospective cohort for future replay and promotion preflight. They are not a deployment signal by themselves.

## Prospective tag monitor

After prospective driver tags are emitted, the app must provide a read-only monitor artifact for tagged plans.

The monitor must:

- inspect stored recommendation plans that contain `signal_breakdown.upstream_signal_quality_drivers`;
- count all tagged plans, even when outcome evidence is not available yet;
- use the canonical plan outcome evidence access layer instead of joining storage tables directly;
- treat historical replay eligibility labels as the strongest outcome source, and fall back to live recommendation evaluation outcomes when replay labels are not present;
- keep the evidence source explicit so live monitoring evidence is not confused with promotion-grade replay evidence;
- report tag cohorts by stable tag key, feature, value, setup family, ticker mix, action mix, date spread, evidence source mix, and outcome mix;
- report phantom win/loss expected value only for tagged rows that already have intraday-compatible outcome evidence and usable trade geometry;
- report closed trade outcome mix when win/loss/flat labels are available;
- mark whether each tag has enough coverage for review, is still accumulating evidence, or is empty;
- keep tag maturity separate from tag performance. A tag with enough rows/dates but negative phantom expected value must be reported as coverage-ready but not positive evidence;
- never change plan generation, replay state, tuning config, jobs, orders, scheduler state, or broker behavior.

Default prospective monitor gates:

- minimum tagged rows for a useful cohort: 30
- minimum tagged distinct dates for a useful cohort: 5
- minimum tagged replay-labeled rows for outcome quality: 30
- minimum tagged replay-labeled dates for outcome quality: 5
- promotion watch date floor: 20 distinct dates
- maximum single ticker share for a reusable cohort: 50 percent

Monitor verdicts:

- `prospective_tags_ready_for_review` — at least one tag has enough date-spread tagged evidence and replay-labeled outcome evidence to inspect before any policy change.
- `prospective_tags_accumulating` — tags are present but still below review gates.
- `no_prospective_tagged_evidence` — no stored plans contain prospective driver tags yet.

The monitor is the standing checkpoint while this tuning layer is on hold. It tells us when the newly tagged evidence is worth reviewing again without running another broad threshold search.

User-facing reports must not treat `promotion_watchable` as bullish by itself. It means the tag has enough coverage to inspect. Performance language must come from phantom/closed outcome metrics, not coverage gates.
