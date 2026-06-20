# Main docs consolidation audit — 2026-06-20

**Status:** audit record

## Scope

This is the second full main-docs audit, performed after executing the requested further consolidation from the prior audit's point 6. The other open product decisions from the prior audit remain deliberately unresolved.

Audited active docs in:

- `docs/*.md` — lean narrative/reference/active-plan surface
- `docs/specs/*.md` — detailed behavior contracts

Archive docs were checked only for navigation context, not as current truth.

## Consolidation performed

Moved detailed contracts from the root docs directory into `docs/specs/`.

Root docs before consolidation: 49 files.
Root docs after consolidation: 21 files.
Detailed specs moved to `docs/specs/`: 28 files.
Archive docs after this pass: 51 files.

The root is now reserved for:

- start-here/navigation docs
- product/architecture/methodology narrative
- operator guides
- active plans/trackers
- stable references such as ER/raw-details/scripts/default watchlists

`docs/specs/` is now reserved for detailed contracts such as broker safety, outcome semantics, calibration, ontology, provider behavior, and read-model specs.

## Files moved to `docs/specs/`

Recommendation/quality/outcomes:

- `recommendation-plan-resolution-spec.md`
- `effective-plan-outcome-spec.md`
- `plan-reliability-report-spec.md`
- `plan-policy-evaluator-spec.md`
- `confidence-calibration-spec.md`
- `edge-validation-standard.md`
- `signal-gating-benchmark-spec.md`
- `plan-generation-tuning-spec.md`
- `large-parameter-search-spec.md`
- `gating-severity-alert-spec.md`

Context/data/analysis:

- `ticker-exposure-ontology-spec.md`
- `market-intelligence-analysis-spec.md`
- `fundamental-analysis-snapshot-spec.md`
- `fundamental-valuation-integration-spec.md`
- `news-provider-eligibility-spec.md`
- `news-provider-reliability-spec.md`
- `nitter-social-relevance-scoring.md`
- `data-quality-audit-spec.md`
- `bars-refresh-spec.md`

Broker/safety:

- `alpaca-paper-order-execution-spec.md`
- `broker-risk-management-spec.md`
- `broker-position-lifecycle-spec.md`
- `broker-position-steering-spec.md`
- `multi-broker-execution-risk-spec.md`
- `etoro-live-trading-integration-spec.md`
- `account-risk-state-spec.md`

UI/read model/observability:

- `dashboard-aggregate-performance-spec.md`
- `observability-spec.md`

## Follow-up fixes applied after moving specs

- Rewrote `docs/docs-index.md` to explain the new root/specs/archive split.
- Updated active markdown references from root docs to `specs/...` paths.
- Updated moved specs so root-doc references use `../...` where required.
- Updated frontend in-app docs links for moved docs so doc slugs now use the generated `specs-...` slug form.
- Updated `docs/archive/README.md` to point current-truth readers to `../specs/` for detailed behavior contracts.
- Fixed one root doc reference from `docs/default-watchlists.md` to `default-watchlists.md`.

## Verification performed

### Counts

- Root docs: 21
- Specs docs: 28
- Archive docs: 51
- Active docs total, excluding archive: 49

### Status labels

Across `docs/*.md` and `docs/specs/*.md`:

- `current behavior`: 23
- `current + target behavior`: 10
- `active plan`: 6
- `reference`: 10

No non-taxonomy status labels remain in active docs.

### Link checks

Checked markdown references in `docs/*.md` and `docs/specs/*.md`:

- missing active markdown links: 0

### Stale phrase scan

Scanned active docs for common stale phrases:

- `target behavior, not implemented`: no active status occurrences
- `active implementation`: no active status occurrences
- old implementation-status phrases such as `implemented for read-time`, `implemented weekly`, `implemented offline`: removed from status lines
- `Broker Orders /`: removed from active docs
- `Broker Orders page`: only retained in `glossary.md` as an explicit backward-compatible old label note

### Frontend docs links

The in-app docs route builds nested slugs by joining path parts. After moving specs, a doc such as `docs/specs/edge-validation-standard.md` has slug `specs-edge-validation-standard`. Frontend links were updated accordingly for moved docs.

## Second-pass audit findings

### 1. Consolidation outcome

Verdict: successful.

The active root docs are now much leaner without deleting detailed contracts. The docs surface now has a clearer hierarchy:

1. root narrative/reference docs for humans getting oriented
2. `specs/` for detailed behavior contracts
3. `archive/` for history

This is better than the prior flat 49-file root because operators and developers can distinguish “read this first” from “contract detail.”

### 2. Completeness after consolidation

Verdict: complete enough.

No current behavior contract was deleted. Moving specs did not remove source-of-truth detail. The index still lists every active detailed spec under an appropriate domain group.

Potential gap found and fixed:

- Some external references, bookmarks, or old in-app links may still use old slugs. Frontend links known in the repo were updated, and the docs API/frontend now expose and resolve aliases for moved spec docs so old `/docs?doc=edge-validation-standard` style URLs still resolve to the new `specs-edge-validation-standard` document.

### 3. Consistency after consolidation

Verdict: improved.

The root docs now better match the desired mental model:

- `features-and-capabilities.md` answers “what can it do?”
- `roadmap.md` answers “what next?”
- `recommendation-methodology.md` answers “how does the recommendation path work?”
- `operator-page-field-guide.md` answers “where do I do this in the UI?”
- `specs/` answers “what is the exact contract?”

No active-doc contradiction was found against the core goals:

- decision support over unproven autonomous prediction
- live mutation disabled unless gates/evidence pass
- broker-preferred outcomes for execution/calibration truth
- context/fundamentals/ontology as conservative, auditable evidence
- degraded inputs visible rather than hidden

### 4. Redundancy after consolidation

Verdict: reduced but not fully solved.

The consolidation solved navigational redundancy, not semantic redundancy.

Still semantically redundant areas, intentionally left open per instruction:

- quality/calibration/tuning docs overlap
- industry context vs ticker ontology boundary remains open
- fundamental snapshot vs valuation integration split remains open
- eToro-specific spec overlaps with generic multi-broker risk spec

These are the same product/document-shape decisions identified in the prior audit. I did not collapse them because you asked to leave those points open for now.

### 5. Ambiguity after consolidation

Verdict: lower navigation ambiguity, remaining product ambiguity is explicit.

Resolved ambiguity:

- Readers can now tell narrative docs from detailed specs.
- Current+target specs live under `specs/`, not mixed into the main start path.
- The docs index explicitly says specs are detailed contracts, not the first reading path.

Remaining explicit ambiguity:

- Whether generated ontology profiles should drive stronger decisions after validation.
- Whether fundamentals can impose threshold/cap constraints before positive boost validation.
- Whether industry context remains decision-affecting or becomes evidence backdrop after ontology validation.
- Whether eToro live spec should remain detailed while live mutation is disabled.

These are product decisions, not documentation mechanics.

## Updated open decisions from prior audit

The requested consolidation addresses prior D6. The other decisions remain open.

### D1 — Keep or archive `recommendation-quality-improvement-plan.md`?

Still open.

### D2 — Collapse tuning docs or keep separate?

Still open.

### D3 — Future role of `industry-context-improvement-plan.md` after ontology?

Still open.

### D4 — Fundamental action-affecting policy before positive boosts?

Still open.

### D5 — eToro spec length while live mutation is disabled?

Still open.

### D6 — Main docs target size

Resolved mechanically by creating `docs/specs/`:

- Root docs reduced from 49 to 21.
- Active detailed contracts remain available in `docs/specs/`.
- No active contract was archived merely to shrink the root.

## New issue discovered by consolidation

### C1 — Backward-compatible docs slugs

Moving docs into `specs/` changed generated in-app docs slugs. Known frontend links were updated, and alias support was added so old root slugs for moved specs resolve to the new nested documents.

Status: fixed in this pass.

## Recommended next actions

1. Keep D1-D5 open until there is a product decision.
2. In future audits, treat active docs as two surfaces:
   - root = lean narrative/reference/plan surface
   - `specs/` = detailed behavior contracts
3. Avoid putting transient implementation plans into `specs/`; use `archive/implementation-plans/` when they are complete.

## Final assessment

The documentation is now leaner without becoming incomplete. The main docs root is suitable as a human reading path, while `specs/` preserves detailed source-of-truth behavior.

Remaining problems are mostly product/design decisions rather than accidental documentation drift.
