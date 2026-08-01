# eToro demo migration plan

**Status:** active plan
**Created:** 2026-07-24
**Mode constraint:** eToro demo only; no real-money mutation.

## Progress update - 2026-07-24

Completed locally:

- Phases 0-4 implementation and focused test coverage.
- Phase 5 controlled eToro Demo lifecycle validation for `AAPL`.
- Phase 7 pilot was advanced from shadow evidence to actual eToro Demo submissions after
  operator approval.
- Live eToro Demo read/precheck validation artifact:
  `artifacts/etoro-demo-validation.json`.
- Live eToro Demo lifecycle reconciliation artifact:
  `artifacts/etoro-demo-lifecycle-reconciliation.json`.
- Live eToro Demo symbol validation artifacts for `PYPL`, `MRK`, `COR`, `PANW`,
  `OKTA`, and `EXPE`.
- Disabled/manual-only default eToro demo broker account bootstrap:
  `etoro-demo-main`.
- Release-readiness dry-run artifact:
  `artifacts/etoro-release-readiness-dry-run.json`.

Live demo lifecycle evidence:

- Open order `368568527` filled for `AAPL`, instrument `1001`.
- Position `3567504740` was opened and then closed.
- Close order `368563966` reached close status id `3`.
- Post-close demo portfolio reconciliation found the position no longer open.

Live autonomous eToro Demo pilot evidence:

- Broker account `etoro-demo-main` is enabled for demo autonomous execution only.
- Per-position notional cap is `25` USD.
- Open-order cap is `3` positions/orders and open-notional cap is `75` USD.
- Symbol allowlist is empty, which means eToro Demo attempts all generated tickers.
  Unsupported, ambiguous, unresolved, ineligible, or cost-invalid instruments are
  persisted as skipped broker-order evidence.
- `PYPL` broker execution `2352` submitted eToro Demo order `368528997`;
  eToro lookup reported `Filled` and position `3567506772`. Local sync now marks
  the order `filled` and position `742` `open`.
- `MRK` broker execution `2353` submitted eToro Demo order `368568636`;
  eToro lookup reported `Filled` and position `3567507810`. Local sync now marks
  the order `filled` and position `741` `open`.
- `COR` broker execution `2354` submitted eToro Demo order `368529002`;
  eToro lookup reported `WaitingForMarket`, with no position execution yet. Local
  sync marks the order `accepted`.
- Post-submit demo portfolio reconciliation found two open positions: `PYPL` and
  `MRK`. `COR` remains a pending demo order.
- Global-market validation evidence after removing the narrow allowlist:
  `6976.T`, `EZJ.L`, and `7012.T` resolved successfully in eToro Demo.
  `1303.TW` and obvious aliases `1303.T`, `1303.HK`, and `1303` did not resolve,
  so those should remain auditable skips unless eToro exposes a matching
  `symbolFull` later.

Implementation corrections learned from live eToro behavior:

- Market search returns thin `instrumentId` rows and requires display-data enrichment.
- Order lookup requires exactly one of `orderId` or `referenceId`.
- Demo close requires `InstrumentID` in the JSON body.
- Filled position IDs are returned under `positionExecutions`.
- Demo order and cost payloads must use the current unified order shape.

Current remaining gates:

- Continue side-by-side paper observation with actual eToro Demo submissions.
- Add fractional eToro exposure columns or another broker-neutral exposure model.
  Current local `broker_positions.quantity` is integer-shaped for Alpaca; exact
  eToro fractional units are preserved in raw broker payload evidence for now.
- Continue improving ticker alias coverage from observed failed mappings. Current
  code tries exact symbol first, then safe punctuation/exchange variants such as
  `BRK-B`/`BRK.B` and `.US` removal; it still requires exact eToro `symbolFull`
  evidence before treating a mapping as tradable.
- Produce `ETORO_LIVE_SHADOW_EVIDENCE_ID` before release readiness can pass without
  `--allow-missing-external-artifacts`.
- Resolve or explicitly waive unrelated full-suite failures before any release/cutover.

## Status review - 2026-08-01

This plan is still active and not ready for cutover. The current implementation remains demo/live-shadow oriented, and real-money eToro mutation remains fail-closed.

Out-of-date findings:

- The remaining gates above are still valid; no plan text should imply release readiness.
- Release-readiness artifacts now include explicit `remaining_gates` so missing external evidence and OpenAPI drift are visible in JSON reports.
- The weekly performance report did not provide trading-edge evidence that would justify increasing broker autonomy.

Current implementation focus:

- Keep demo observation and reconciliation evidence accumulating.
- Keep ticker alias failures auditable rather than guessing tradability.
- Use release-readiness dry runs as local diagnostics only until all required external artifact ids exist.

This plan turns the existing Alpaca-paper-first broker path into an eToro-demo-first path while preserving fail-closed real-money behavior. It follows the Aurelio development protocol: specs are updated before implementation, tests encode the specs, broker config and runtime state are not changed by implementation work unless a phase explicitly calls for an operator-approved rollout step.

## Current facts

- eToro's live OpenAPI check on 2026-07-24 returned `v1.311.0`, newer than the attached `v1.302.0` guide.
- The repo already has broker-account abstraction, Alpaca adapter support, eToro adapter plumbing, account-scoped safety controls, and eToro live fail-closed behavior.
- Alpaca paper is still the documented active automated broker path.
- The current eToro demo client paths appear stale against OpenAPI `v1.311.0`.
- Real eToro mutation must remain disabled. The live adapter must continue returning `etoro_live_mutation_disabled`.

Current OpenAPI demo endpoints to verify and encode before implementation:

- `POST /api/v2/trading/execution/demo/orders` - create demo order
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}` - cancel pending demo order
- `GET /api/v2/trading/info/demo/orders:lookup` - lookup demo order and position details
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}` - close demo position
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}` - cancel pending demo close
- `GET /api/v1/trading/info/demo/portfolio` - demo portfolio breakdown
- `GET /api/v1/trading/info/demo/pnl` - demo P&L and portfolio details
- `GET /api/v1/trading/info/demo/aggregate-portfolio` - demo aggregate portfolio snapshot
- `GET /api/v1/trading/info/demo/close-orders/{orderId}` - demo close-order lookup
- `GET /api/v1/trading/info/trade/demo/history` - demo trade history
- `POST /api/v2/trading/info/demo/eligibility` - demo instrument eligibility
- `POST /api/v2/trading/info/demo/costs` - demo what-if costs
- `PATCH /api/v2/trading/demo/positions/{positionId}` - demo stop-loss and take-profit modification

## Non-negotiable rules

1. No real-money eToro endpoint may be called by this migration.
2. No Real credentials may be required for this migration.
3. eToro demo credentials must be stored as a separate broker account from any future eToro live account.
4. The signal engine must not call eToro directly. It produces candidates; the broker adapter and risk/reconciliation layers own broker interaction.
5. Every eToro demo mutation must persist a request id and sanitized request payload before the call.
6. Ambiguous demo execution results must enter `needs_review` and activate the broker-account circuit breaker. Demo is where the production reflex is trained.
7. Alpaca must not be deleted until eToro demo has passed parity and rollback gates.
8. Specs and tests must change before implementation code for each phase.

## Phase 0 - Documentation and schema lock

**Goal:** make the intended migration reviewable before code changes.

Tasks:

- Refresh `docs/specs/etoro-live-trading-integration-spec.md` against OpenAPI `v1.311.0`.
- Either rename or supplement that spec with an explicit demo-first current target section.
- Update `docs/specs/multi-broker-execution-risk-spec.md` so eToro demo is a first-class account mode, not only a live-shadow stepping stone.
- Update `docs/specs/alpaca-paper-order-execution-spec.md` to label Alpaca paper as legacy fallback once eToro demo is defaulted.
- Document that eToro MCP may be used for live documentation lookup only, not for broker mutation during this migration.

Acceptance criteria:

- Specs list exact eToro demo endpoints, method, path, idempotency, required prechecks, and reconciliation evidence.
- Specs state that eToro Real writes are out of scope and fail-closed.
- Specs define when Alpaca paper can be considered deprecated, not just replaced in code.
- No application code changes are included in this phase.

## Phase 1 - eToro documentation access and MCP setup

**Goal:** make live eToro documentation lookup repeatable.

Tasks:

- Add the official eToro MCP server to the local agent/editor setup only after operator approval:
  ```json
  {
    "mcpServers": {
      "etoro-public-api": {
        "url": "https://mcp.public-api.etoro.com"
      }
    }
  }
  ```
- Keep MCP use read/documentation-only unless a future explicit task authorizes demo API calls through it.
- Add a small developer runbook section or script note for fetching:
  - `https://api-portal.etoro.com/llms.txt`
  - `https://api-portal.etoro.com/api-reference/openapi.json`
  - `https://builders.etoro.com/changelog`
- Record the observed OpenAPI version in the eToro release-readiness artifact.

Acceptance criteria:

- A developer can reproduce the live docs check without relying on memory.
- The plan or operational docs say MCP must not receive Real credentials.
- OpenAPI version drift is treated as a release-readiness finding.

## Phase 2 - Adapter contract correction

**Goal:** make the eToro demo adapter match current official endpoints.

Tasks:

- Correct stale demo endpoint paths in `EtoroClient`.
- Split demo and real read methods where current OpenAPI has separate paths.
- Add demo methods for eligibility, what-if costs, rates lookup, aggregate portfolio, close-order lookup, trade history, and SL/TP modification.
- Ensure every JSON mutation request sends `Content-Type: application/json`.
- Preserve redaction for `x-api-key`, `x-user-key`, `api_key`, `user_key`, tokens, and request headers.
- Preserve `EtoroLiveBrokerAdapter` fail-closed behavior.

Acceptance criteria:

- Unit tests prove the demo adapter calls the exact OpenAPI `v1.311.0` paths.
- Unit tests prove no live mutation path is called by a demo account.
- Unit tests prove the live adapter rejects submit, cancel, close, and amend with `etoro_live_mutation_disabled`.
- Secret redaction tests include eToro header and snake_case variants.

## Phase 3 - Demo credential and read-only validation

**Goal:** validate eToro demo credentials and account state before any demo order.

Tasks:

- Add credential validation that distinguishes `demo`, `live`, `read_only`, `write`, invalid, expired, missing, and wrong-environment states when eToro exposes enough evidence.
- Add a read-only validation command or service method that fetches demo portfolio/P&L and records a redacted artifact.
- Add broker-account UI/API fields for demo validation status, last validation time, OpenAPI version, and last redacted evidence.
- Block eToro demo autonomous execution when validation is missing, stale, failed, or contradicts account mode.

Acceptance criteria:

- Validation can run without submitting an order.
- Missing or invalid demo credentials produce stable skip/block reasons.
- UI/API exposes validation status without leaking credentials.
- Tests cover wrong-environment credentials and missing validation.

## Phase 4 - Instrument, market-data, eligibility, and cost gates

**Goal:** prevent eToro demo orders from being submitted from weak assumptions.

Tasks:

- Resolve tickers through `GET /api/v1/market-data/search`.
- Store eToro `instrumentId` and enough metadata to detect ambiguity.
- Fetch fresh rates through `GET /api/v1/market-data/instruments/rates`.
- Check demo eligibility through `POST /api/v2/trading/info/demo/eligibility`.
- Check demo what-if costs through `POST /api/v2/trading/info/demo/costs`.
- Demo may run with an empty symbol allowlist once read-only validation and
  lifecycle evidence are present. Empty allowlist means all generated tickers are
  attempted, but each order still must pass exact eToro symbol resolution,
  fresh market rates, demo eligibility, what-if costs, and account risk caps.
- Fail closed for unsupported product type, currency, market session, leverage, protection constraints, stale price, or ambiguous symbol mapping.

Acceptance criteria:

- A plan cannot reach demo submission without instrument resolution, fresh rates, eligibility, costs, and risk approval.
- Ambiguous ticker mappings persist skipped audit rows.
- Unsupported settlement, leverage, product, or protection constraints persist skipped audit rows.
- Tests cover exact-one sizing field and exact-one instrument identifier rules.

## Phase 5 - Manual eToro demo order lifecycle

**Goal:** prove one controlled demo order lifecycle before autonomy.

Tasks:

- Add a manual-only demo submit action behind broker-account controls.
- Build the payload from the normalized broker-order request, not directly from raw plan fields.
- Persist request id, sanitized request body, endpoint, strategy/run/plan context, and precheck evidence before submission.
- After submission, immediately reconcile via order lookup, portfolio/P&L, and open positions.
- Add manual cancel, close, and refresh for eToro demo records.
- Treat timeout or connection reset on submit/cancel/close as `needs_review`, with circuit breaker activation.

Acceptance criteria:

- One manually selected plan can complete submit, lookup, refresh, cancel or close in demo.
- An HTTP success is stored as submission evidence only, not as proof of fill.
- Ambiguous outcomes cannot be retried until reconciliation evidence resolves them.
- Tests cover accepted, rejected, rate-limited, timeout, malformed JSON, and not-found responses.

## Phase 6 - Broker-position reconciliation and lifecycle normalization

**Goal:** make eToro demo outcomes usable for performance measurement.

Tasks:

- Normalize eToro order IDs, reference IDs, position IDs, close-order IDs, open units, entry price, exit price, fees/costs, stop loss, take profit, status, and timestamps.
- Keep order IDs and position IDs distinct.
- Add lifecycle states for pending open, open position, pending close, closed, canceled, rejected, unknown, and needs review.
- Prefer broker evidence over simulated plan outcome in operator-facing status when eToro demo broker records exist.
- Update broker-position steering logic only where it relies on Alpaca bracket child-order assumptions.

Acceptance criteria:

- Broker-backed eToro demo rows can resolve win/loss/open without Alpaca-specific bracket assumptions.
- Portfolio/P&L reconciliation can identify untracked demo exposure.
- Operator UI/API can explain every eToro demo order and position state from persisted evidence.
- Tests prove simulated outcomes do not override broker-backed eToro demo evidence.

## Phase 7 - Side-by-side Alpaca paper and eToro demo trial

**Goal:** compare operational behavior before changing defaults.

Tasks:

- Enable eToro demo and Alpaca paper as separate broker accounts for the same eligible plan candidates.
- Keep notional small and demo-only.
- Run for a fixed trial window, initially 10 market sessions or at least 30 attempted broker candidates, whichever is later.
- Compare:
  - skip/reject reasons
  - fills and pending orders
  - stale or ambiguous states
  - slippage and spread behavior
  - protective-order acceptance
  - lifecycle normalization
  - P&L accounting
  - rate-limit behavior
- Produce a trial report with a stop/go recommendation.

Acceptance criteria:

- No unresolved eToro demo `needs_review` older than one market session.
- No duplicate eToro demo submissions for the same `(run_id, plan_id, broker_account_id)`.
- Reconciliation explains all active eToro demo exposure.
- Alpaca paper remains available as rollback during the trial.

## Phase 8 - Default broker flip to eToro demo

**Goal:** make eToro demo the default paper-trading path after evidence exists.

Tasks:

- Change default broker-account ordering and UI copy so eToro demo is primary.
- Disable new Alpaca paper autonomous submissions by default, while preserving manual fallback.
- Update docs and operator workflows from Alpaca paper to eToro demo.
- Update release-readiness checks so eToro demo validation is required for broker execution readiness.
- Keep Alpaca regression tests until the fallback removal phase.

Acceptance criteria:

- New broker execution candidates target eToro demo by default.
- Alpaca paper does not receive autonomous submissions unless explicitly re-enabled.
- Docs, UI labels, and health summaries no longer describe Alpaca paper as the active default.
- Rollback is a settings change, not a code revert.

## Phase 9 - Alpaca deprecation and cleanup

**Goal:** remove old complexity only after eToro demo is stable.

Tasks:

- Archive Alpaca paper implementation-specific plan history.
- Remove Alpaca-specific language from broker-neutral specs and UI.
- Remove direct Alpaca client exception handling from generic broker routes where the adapter path can represent the error.
- Keep or remove the Alpaca adapter based on rollback need after a documented stability window.
- Remove unused Alpaca credential settings only after confirming no operator workflows depend on them.

Acceptance criteria:

- The remaining broker execution architecture is broker-account-first and adapter-first.
- No active spec requires Alpaca bracket assumptions for generic lifecycle behavior.
- Alpaca removal, if performed, has a rollback note and migration note.
- Full backend and frontend checks pass.

## Phase 10 - Future live-readiness boundary

**Goal:** make clear where this demo migration stops.

Tasks:

- Keep eToro Real accounts read-only or disabled.
- Keep live mutation code fail-closed.
- Keep live release gates in `production-readiness-plan.md` separate from this migration.
- Require a new operator-approved plan before any Real write implementation.

Acceptance criteria:

- The codebase can run eToro demo by default without any Real write capability being enabled.
- Release-readiness checks still fail closed for Real mutation unless separate live artifacts and implementation approval exist.
- No test requires Real credentials.

## Autonomous working checklist

Use this checklist when implementing the plan:

1. Read current specs and update the relevant spec before code.
2. Fetch live eToro docs and record OpenAPI version in notes/artifacts.
3. Write or update focused tests for the phase.
4. Implement the smallest code change that satisfies the updated spec.
5. Run targeted tests for changed broker, risk, reconciliation, and API code.
6. Run broader regression before changing defaults.
7. Do not change broker credentials, broker-account enabled flags, scheduler state, orders, or runtime config unless the current phase and operator approval require it.
8. Preserve unrelated dirty worktree changes.
9. Report any doc/schema conflict as a blocker instead of guessing.

## Risk register

- **Schema drift:** OpenAPI has already moved from the guide's `v1.302.0` to observed `v1.311.0`; release checks must catch drift.
- **Stale local eToro paths:** current code appears to use outdated demo route ordering.
- **World-market complexity:** ticker mapping, exchanges, currencies, calendars, settlement types, leverage, and product eligibility can all vary.
- **Lifecycle mismatch:** Alpaca bracket-order assumptions do not map cleanly to eToro order/position/close-order evidence.
- **Rate limits:** eToro uses shared endpoint pools; execution mutations share a 20-per-60-second budget.
- **Ambiguous outcomes:** timeouts on money-moving routes require reconciliation before retry, even in demo.
- **Credential separation:** demo and real keys must never be interchangeable.
- **False confidence from demo:** paper execution proves integration behavior, not trading edge.
- **MCP misuse:** the official MCP is useful for docs lookup, but must not become an uncontrolled execution path.
