# Main docs audit — 2026-06-20

**Status:** audit record

## Scope

Audited the active/main docs surface under `docs/*.md` after transient implementation plans and dated audits were archived. Archive docs were not treated as current truth, except for checking that active docs do not point to removed paths.

Main-doc count at audit time: 49 files.

## Audit method

Checks performed:

1. Read the navigation/index path and the high-authority docs:
   - `docs-index.md`
   - `product-thesis.md`
   - `features-and-capabilities.md`
   - `roadmap.md`
   - `architecture.md`
   - `recommendation-methodology.md`
   - `operator-page-field-guide.md`
2. Cross-checked broker, eToro, fundamentals, ontology, calibration, and roadmap docs against recently implemented behavior.
3. Scanned all active docs for:
   - nonstandard status labels
   - stale “not implemented” claims
   - old page names such as “Broker Orders” where the active UI is “Execution & Risk”
   - stale seeded-universe/ontology claims
   - target/current ambiguity
   - obvious broken links from active docs
4. Re-ran a main-doc link check for markdown references in `docs/*.md`; no missing active-doc markdown links remained.
5. Challenged the main docs against the product goals:
   - decision support, not unproven autonomous prediction
   - safety before live mutation
   - broker-preferred/effective outcomes before calibration claims
   - context/fundamentals as conservative evidence until validated
   - docs should be complete but lean

## Executive assessment

The main docs are materially cleaner after archiving, but they are not yet as lean as they could be.

Strong points:

- The start path is now clear: README → Getting Started → Operator Guide → Glossary → Methodology.
- The main product goal is consistent: decision support and measured edge, not autonomous prediction claims.
- Safety principles are consistent across broker, eToro, calibration, edge validation, fundamentals, and ontology docs.
- Current-vs-target ambiguity was reduced for multi-broker, eToro, fundamentals, calibration, gating alerts, large search, and ticker ontology.
- Active docs no longer link to removed top-level audit/implementation-plan paths.

Remaining weaknesses:

- There are still too many active docs for a “lean” surface; many are legitimate specs, but some overlap heavily.
- Several active plans contain historical checklists that are partly complete and partly aspirational.
- Some specs are precise but too long for operators; they need summaries or consolidation, not deletion.
- Some domain boundaries are still split across multiple docs in ways that require tribal knowledge.

## Fixes applied during this audit

### 1. Normalized status labels

Changed nonstandard or stale status labels so active docs fit the documented taxonomy:

- `confidence-calibration-spec.md`: now `current behavior`
- `gating-severity-alert-spec.md`: now `current behavior`, with implementation note below status
- `large-parameter-search-spec.md`: now `current behavior`, with implementation note below status
- `ticker-exposure-ontology-spec.md`: now `current + target behavior`
- `fundamental-analysis-snapshot-spec.md`: now `current + target behavior`
- `multi-broker-execution-risk-spec.md`: now `current + target behavior`
- `etoro-live-trading-integration-spec.md`: now `current + target behavior`

After this change, active status distribution is:

- `current behavior`: 23
- `current + target behavior`: 10
- `active plan`: 6
- `reference`: 10

### 2. Corrected stale implementation claims

Updated these docs from stale “target/not implemented” language to current reality:

- `multi-broker-execution-risk-spec.md`
  - broker-account model, adapter abstraction, fan-out, per-account risk/drawdown/circuit breakers, broker-aware UI/API, reconciliation evidence, and broker-agnostic price normalization are now documented as implemented.
  - remaining target items are external eToro demo/live validation, live mutation enablement, production evidence, and measured edge.

- `etoro-live-trading-integration-spec.md`
  - read-only plumbing, demo/mock lifecycle, live-shadow audit, broker-account gates, UI/API safety indicators, release-readiness script, and fail-closed live adapter are now documented as implemented.
  - live mutation remains target/gated and explicitly fail-closed with `etoro_live_mutation_disabled`.

- `fundamental-analysis-snapshot-spec.md`
  - persistence, refresh jobs/routes, point-in-time lookup, integration, compact payloads, and initial validation-slice plumbing are now documented as implemented.
  - stale-coverage UI/observability polish and action-affecting positive contribution remain target/gated.

### 3. Aligned methodology with ontology and fundamentals

Updated `recommendation-methodology.md` so it now explicitly says:

- the ticker exposure ontology adds explicit business-driver, macro-sensitivity, event-sensitivity, peer/customer/supplier, source, confidence, and version metadata for every taxonomy ticker.
- new deep-analysis runs emit `ontology_context` with coverage status, coverage reasons, matched exposures, transmission paths, directional support, and bounded alignment adjustment.
- ontology adjustments do not bypass calibration, actionability, broker, or risk gates.
- fundamental snapshots are current behavior, not only target behavior.

### 4. Fixed page-name ambiguity

The active page is now “Execution & Risk,” while some docs still said “Broker Orders.” Updated active docs to reduce ambiguity:

- `features-and-capabilities.md`
- `glossary.md`
- `alpaca-paper-order-execution-spec.md`
- `broker-risk-management-spec.md`
- `multi-broker-execution-risk-spec.md`
- `etoro-live-trading-integration-spec.md`

The glossary now says old docs/payload labels may still refer to “Broker Orders,” but the active UI concept is “Execution & Risk.”

### 5. Reduced stale roadmap wording

Updated `roadmap.md` so it no longer implies missing work that has already partially landed:

- partial-persistence work is now framed as needing soak/testing under real worker crashes, not absent semantics.
- provider/broker observability is now framed as needing presentation/polish, not a complete absence of lifecycle events.
- broker-agnostic price normalization and broker-account risk/reconciliation were added to shipped live-safety baseline.
- recommendation-quality validation now explicitly includes ontology/transmission and fundamental-context slices.

### 6. Clarified fundamentals implementation plan

Updated `fundamental-analysis-snapshot-implementation-plan.md` so it is a remaining-work plan rather than a broad shipped-work checklist.

## Main-doc consistency review by topic

### Product goal and autonomy

Verdict: mostly consistent.

Consistent claims:

- `product-thesis.md`, `features-and-capabilities.md`, `recommendation-methodology.md`, `edge-validation-standard.md`, `confidence-calibration-spec.md`, `production-readiness-plan.md`, and `roadmap.md` all agree that the system is not yet a proven autonomous money-making engine.
- Expansion requires broker-backed/replay-backed evidence, edge validation, calibration honesty, and broker safety.

Remaining ambiguity:

- Some active plans still use broad “improve quality” language that could be read as roadmap authority even though the actual gates live in `edge-validation-standard.md`, `confidence-calibration-spec.md`, and `plan-generation-tuning-spec.md`.

Recommended next cleanup:

- Make `edge-validation-standard.md` the single explicit “can we expand autonomy?” authority in all quality/tuning docs.

Needs user input:

- Decide whether `recommendation-quality-improvement-plan.md` should remain an active plan or be rewritten as a compact “quality operating cadence” doc. It is useful, but much of it is historical or generic now.

### Recommendation pipeline

Verdict: consistent after methodology updates.

Consistent claims:

- Cheap scan is upstream triage, not final calibrated confidence.
- Deep analysis/plan framing generates raw confidence and plan actionability.
- Calibration is downstream and should not be silently confused with cheap-scan calibration.
- Decision samples are tuning/review artifacts, not plan outcomes.
- Phantom outcomes are recall/research diagnostics, not live execution calibration by default.

Remaining ambiguity:

- The relationship between `signal-gating-tuning-guide.md`, `plan-generation-tuning-spec.md`, `recommendation-quality-improvement-plan.md`, and `confidence-calibration-spec.md` still requires reading multiple docs.

Recommended next cleanup:

- Add one small “tuning responsibility map” section to `recommendation-methodology.md` or `docs-index.md`:
  - signal gating = shortlist/recall
  - plan-generation tuning = downstream framing/actionability thresholds
  - confidence calibration = confidence-to-outcome mapping for plan outcomes
  - quality/edge = promotion/autonomy authority

Needs user input:

- Should the project keep separate user-facing docs for signal gating and plan-generation tuning, or should they be collapsed under one “Tuning and validation guide” with separate sections?

### Broker execution and eToro

Verdict: much improved, but still complex.

Consistent claims after fixes:

- Alpaca paper is the active automated mutation path.
- Broker-account abstraction exists.
- eToro read-only/demo/mock/live-shadow plumbing exists.
- eToro real-money mutation remains fail-closed.
- Live expansion requires external evidence, production gates, and measured edge.

Remaining ambiguity:

- `multi-broker-execution-risk-spec.md` and `etoro-live-trading-integration-spec.md` overlap substantially on risk gates, circuit breakers, UI/API requirements, and release validation.
- This overlap is defensible because one is broker-agnostic and one is eToro-specific, but it is long and easy to drift.

Recommended next cleanup:

- Keep both specs, but add a short table near the top of the eToro spec: “inherits from multi-broker spec; this doc only adds eToro-specific rules.”
- Consider moving common risk/circuit-breaker language out of the eToro spec if it duplicates the broker-agnostic spec exactly.

Needs user input:

- Should eToro remain a detailed standalone spec while live mutation is disabled, or should most eToro live-mutation details move to an archived/target appendix until external validation starts?

### Context, ontology, and industry context

Verdict: directionally consistent, but boundary needs tightening.

Consistent claims:

- Macro/industry context is a reusable evidence layer.
- Context remains heuristic and must expose degraded/missing evidence.
- Ticker exposure ontology now provides explicit per-ticker profiles and bounded matching.
- Positive context boosts remain conservative and gated.

Remaining ambiguity:

- `industry-context-improvement-plan.md` still has unchecked tasks for evidence state, coverage state, confidence gating, and measurement. Some of these may now be partially complete or superseded by ontology work.
- `ticker-exposure-ontology-spec.md` now overlaps with parts of `industry-context-improvement-plan.md` around subject resolution, relationship matching, and measurement.

Recommended next cleanup:

- Re-audit `industry-context-improvement-plan.md` against current ontology implementation and mark which tasks are still real.
- If ontology becomes the primary subject-resolution layer, shrink the industry-context plan to only evidence collection/quality and retire ontology-like tasks from it.

Needs user input:

- Should industry context remain a decision-influencing layer after ontology validation, or should it become mostly evidence collection/readable backdrop while ontology handles ticker transmission?

### Fundamentals and valuation

Verdict: mostly consistent after fixes, but split across too many docs.

Docs involved:

- `fundamental-analysis-snapshot-spec.md`
- `fundamental-analysis-snapshot-implementation-plan.md`
- `fundamental-valuation-integration-spec.md`
- `recommendation-methodology.md`
- `raw-details-reference.md`

Consistent claims:

- Fundamental snapshots are point-in-time.
- Sparse payloads must not appear healthy.
- Fundamentals are conservative/passive at first.
- Positive confidence boosts are blocked pending validation.
- Valuation/mispricing context should initially constrain/diagnose more than boost.

Remaining ambiguity:

- The boundary between “snapshot spec” and “valuation integration spec” is clear to a developer but probably not to an operator.
- The implementation plan still contains phase detail; it is now a remaining-work tracker but may become archival soon.

Recommended next cleanup:

- Once stale-coverage UI/observability and richer validation metrics are done, archive `fundamental-analysis-snapshot-implementation-plan.md` and keep only the snapshot spec plus valuation spec.

Needs user input:

- Should valuation-based risk caps/threshold increases be allowed before positive confidence boosts, or should all action-affecting fundamental behavior wait for the same walk-forward evidence gate?

### Calibration, quality, and edge validation

Verdict: safe principles are consistent; docs are somewhat redundant.

Consistent claims:

- Confidence is ranking/selection until calibrated.
- Live/autonomous calibration uses execution-only outcomes by default.
- Phantom outcomes are separated and operator-controlled.
- Weekly persisted calibration snapshots are the live plan-generation source.
- Missing calibration snapshot means calibration unavailable/disabled, not silently recomputed.
- Edge validation is the autonomy gate.

Remaining ambiguity:

- `recommendation-quality-improvement-plan.md` has old checklist items for calibration/statistical mapping that are partially superseded by `confidence-calibration-spec.md`.
- `edge-validation-standard.md`, `plan-policy-evaluator-spec.md`, `plan-reliability-report-spec.md`, and `effective-plan-outcome-spec.md` are individually useful but cognitively heavy as a group.

Recommended next cleanup:

- Keep the specs, but create one compact current-state “Quality and edge model” section in `recommendation-methodology.md` linking to the detailed specs.

Needs user input:

- Should `recommendation-quality-improvement-plan.md` remain a live backlog, or should the active quality backlog move to roadmap/issues and this doc be archived?

### UI/operator process

Verdict: mostly consistent after the previous archive pass.

Consistent claims:

- Dashboard is the daily entry point.
- Trade Review is for plan review.
- Quality & Edge is the performance/edge authority.
- Execution & Risk owns broker safety/exposure/reconciliation/order audit.
- Context review and Data quality are diagnostics, not primary performance authorities.

Remaining ambiguity:

- Some raw route names and older labels still leak into docs/payloads. The glossary now handles “Broker Orders” as an old label, but future UI docs should consistently say Execution & Risk.

Recommended next cleanup:

- Periodically scan active docs for old route/page names after frontend renames.

Needs user input:

- None immediate.

### Data quality and provider behavior

Verdict: consistent but possibly under-integrated.

Consistent claims:

- Missing coverage and broker untradability are separate labels.
- News provider eligibility rejects unsafe future leakage in replay.
- Reliability specs prefer explicit degraded output over silent fallback.

Remaining ambiguity:

- Data quality audit, news provider eligibility, news provider reliability, bars refresh, and market intelligence each define related provider-health behavior. This is accurate but distributed.

Recommended next cleanup:

- Add a small “input health responsibility map” to `features-and-capabilities.md` or `docs-index.md`.

Needs user input:

- Should input-health docs stay as separate low-level specs, or should operator-facing input health be consolidated into one `input-health-spec.md` with these as implementation details?

## Redundancy findings

### Redundancy that is acceptable

- `features-and-capabilities.md` and `roadmap.md` both mention shipped baseline. This is acceptable because features answers “what can it do?” and roadmap answers “what next?”
- `recommendation-methodology.md` and detailed specs overlap, but methodology is the narrative entry point while specs are contracts.
- Broker/eToro specs overlap on safety because one is generic and one is broker-specific.

### Redundancy that should be reduced later

1. `recommendation-quality-improvement-plan.md`
   - overlaps with calibration, plan reliability, policy evaluator, edge validation, signal gating, and plan-generation tuning docs.
   - likely should become a short cadence/backlog doc or be archived.

2. `fundamental-analysis-snapshot-implementation-plan.md`
   - now mostly a remaining-work tracker.
   - archive after stale-coverage UI/observability and validation metric follow-ups are done.

3. `industry-context-improvement-plan.md`
   - likely overlaps with ticker ontology work.
   - needs a focused review before deciding whether to shrink or archive.

4. `etoro-live-trading-integration-spec.md`
   - intentionally detailed, but much of its generic risk language is inherited from multi-broker spec.
   - could be shortened if we keep only eToro-specific deltas.

## Ambiguity findings

1. **“Usable ontology” vs “curated ontology.”**
   - Current docs say generated templates are usable when based on valid broad industry economics.
   - They also say generated profiles are not equivalent to curated company-specific profiles.
   - This is safe, but operators may still over-trust “usable.”
   - Recommended fix: UI/reporting should show source (`curated`, `template_generated`, `taxonomy_generated`) next to coverage status.

2. **“Fundamentals can constrain” vs “fundamentals are passive.”**
   - Docs consistently block positive boosts, but there is a product decision pending around whether conservative threshold increases/caps are allowed before positive boosts.
   - Needs user/product decision.

3. **“Live eToro target” vs “fail-closed current implementation.”**
   - Fixed in status/implementation sections, but the spec remains long enough that readers may miss it.
   - Recommended fix: add a prominent warning box to every live-mutation section if the doc remains long.

4. **“Plan confidence” vs “cheap-scan confidence.”**
   - Methodology explains the distinction, but docs spread tuning/calibration across several files.
   - Recommended fix: add a one-page confidence lifecycle diagram or concise section.

## Completeness findings

### Complete enough

- Broker price precision remediation is now reflected in broker specs.
- Execution-only weekly calibration snapshots are reflected in calibration docs and methodology.
- Ontology coverage and generation are reflected in ontology docs and methodology.
- eToro fail-closed state is now documented clearly.

### Incomplete by design / still active

- Production readiness: security hardening, backup/restore, staging soak, incident response.
- eToro external validation and any live mutation enablement.
- Outcome validation for ontology/fundamentals before stronger action-affecting use.
- Cheap-scan-specific calibration curve/dataset.
- Full cleanup of old taxonomy-only transmission plumbing after ontology validation.
- Industry context evidence-quality improvement or retirement/shrink decision.

## Consistency with goals and safety logic

The docs now consistently support these rules:

1. Do not expand autonomy without edge validation.
2. Broker evidence beats simulated outcomes for execution performance.
3. Live mutation remains disabled unless external validation and gates pass.
4. Confidence calibration must be auditable and snapshot-based for live generation.
5. Phantom outcomes are research/recall evidence, not silently mixed into live calibration.
6. Context, ontology, market intelligence, and fundamentals should constrain/diagnose before boosting.
7. Missing/degraded provider evidence must remain visible.

No active-doc contradiction was found against these principles after the fixes above.

## Open decisions requiring user input

### D1 — Keep or archive `recommendation-quality-improvement-plan.md`?

Options:

- **A. Keep and rewrite** as a compact quality operating cadence/backlog.
- **B. Archive** it and let `roadmap.md`, `edge-validation-standard.md`, and detailed specs carry active quality work.

Recommendation: A if you want an operator-facing quality review cadence; B if you want the leanest docs surface.

### D2 — Collapse tuning docs or keep separate?

Options:

- **A. Keep separate** `signal-gating-tuning-guide.md` and `plan-generation-tuning-spec.md` because they tune different layers.
- **B. Add a consolidated `tuning-and-validation-guide.md` and make the current docs lower-level specs.

Recommendation: B for operator clarity, A for developer precision.

### D3 — What should happen to `industry-context-improvement-plan.md` after ontology?

Options:

- **A. Keep industry context as a decision-affecting layer** and complete the evidence-quality tasks.
- **B. Shrink industry context to evidence collection/readable backdrop** and let ticker ontology own transmission decisions.
- **C. Keep both but require validation to decide per setup family.

Recommendation: C until fresh ontology-context outcomes exist.

### D4 — Fundamental action-affecting policy before positive boosts

Should fundamentals be allowed to raise thresholds/cap actionability before there is evidence for positive confidence boosts?

Options:

- **A. Yes, allow conservative risk caps/threshold increases before positive boosts.**
- **B. No, keep all action-affecting fundamental behavior passive until the same validation gate passes.**

Recommendation: A for severe downside/event-risk flags only, with explicit validation and no positive boosts.

### D5 — eToro spec length while live mutation is disabled

Options:

- **A. Keep detailed eToro live spec active** so future implementation has exact safety requirements.
- **B. Move detailed live-mutation sections to an appendix/archive and keep active doc focused on current fail-closed state plus gate summary.

Recommendation: A until external validation starts; then split if the doc becomes hard to operate from.

### D6 — Main docs target size

The active docs root is 49 files after archiving. Is that acceptable?

Options:

- **A. Accept 49 because most are focused specs.**
- **B. Target ~35 by merging small provider/data-quality/read-model specs.**
- **C. Target ~25** by keeping only narrative docs in root and moving all detailed specs under `docs/specs/`.

Recommendation: B as the next lean-doc pass if you want less surface area without losing detail.

## Suggested next docs cleanup sequence

1. Decide D1/D2/D3 because they determine the quality/context docs shape.
2. Add a compact confidence/tuning responsibility map to `recommendation-methodology.md`.
3. Add source/coverage caveat language for ontology in operator-facing docs.
4. Re-audit `industry-context-improvement-plan.md` after a fresh ontology-enabled plan run.
5. Archive `fundamental-analysis-snapshot-implementation-plan.md` after remaining UI/observability/validation follow-ups are complete.
6. Consider a `docs/specs/` subdirectory if the active root remains too large.

## Verification artifacts

- Active main-doc markdown links checked: no missing markdown links from `docs/*.md`.
- Status labels normalized to the documented taxonomy.
- Active docs no longer reference removed `docs/audits/...` paths.
- Old “Broker Orders” page naming mostly replaced with “Execution & Risk,” with glossary backward-compatibility note.
