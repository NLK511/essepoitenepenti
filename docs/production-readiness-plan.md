# Production readiness plan

**Status:** active plan
**Created:** 2026-06-01

This plan turns the current multi-broker/eToro implementation into a production-ready, operator-safe deployment. It is intentionally concrete: every phase has evidence, commands, and a pass/fail gate.

## Definition of production-ready

Trade Proposer App is production-ready when all of these are true:

1. The deployed app can run unattended for market sessions without data loss, duplicate runs, or silent broker drift.
2. Secrets, auth, backups, and migrations have production-safe defaults and a documented recovery path.
3. Alpaca paper trading remains stable through full regression.
4. eToro real-money mutation remains disabled unless read-only, demo, live-shadow, and release evidence exist.
5. Operators can see and stop every autonomous broker action from the UI/API.
6. The system has a measured trading edge from broker-backed or replay-backed evidence before capital is increased.

## Phase 0 — Freeze current implementation and clean release branch

**Goal:** make the completed multi-broker/eToro work reviewable and reproducible.

Tasks:
- Run formatting and targeted regression suites.
- Run full backend tests.
- Run frontend type check.
- Produce a git diff summary and separate unrelated local scratch files from the release branch.
- Commit the completed multi-broker/eToro implementation only after tests pass.

Commands:
```bash
.venv/bin/ruff format src tests scripts
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
cd frontend && npm run check
```

Exit criteria:
- All tests pass locally.
- No temporary files under `/tmp` are part of the commit.
- Completed multi-broker/eToro implementation history is archived at `archive/implementation-plans/multi-broker-etoro-implementation-plan.md`; current release gates live in `specs/multi-broker-execution-risk-spec.md`, `specs/etoro-live-trading-integration-spec.md`, and this plan.

## Phase 1 — Production configuration hardening

**Goal:** prevent unsafe production startup.

Tasks:
- Add a production preflight command that fails when:
  - `SINGLE_USER_AUTH_ENABLED` is false.
  - API token/session secret is missing or default.
  - encryption key is missing, weak, or changed without rotation evidence.
  - database URL points to SQLite in production mode.
  - broker global halt is off before operator acknowledgement.
  - any eToro live account has live mutation enabled without artifact ids.
- Document the minimum production `.env`.
- Add tests for fail-closed preflight behavior.

Exit criteria:
- `scripts/preflight-prod` or equivalent returns non-zero for unsafe defaults.
- Production docs include exact environment variables and safe defaults.

## Phase 2 — Database, migration, and backup readiness

**Goal:** ensure upgrades and recovery are safe before unattended operation.

Tasks:
- Run Postgres migration validation using the Docker helper:
  ```bash
  newgrp docker <<'EOF'
  eval "$(.venv/bin/python scripts/start_test_postgres.py --print-export)"
  .venv/bin/python scripts/check_postgres_validation.py
  EOF
  ```
- Run the same validation against the intended production-like Postgres instance.
- Add a backup/restore smoke test:
  - create backup
  - restore into fresh database
  - run schema validation
  - run app startup bootstrap
- Document rollback limits for irreversible migrations.

Exit criteria:
- A dated migration validation artifact exists.
- A dated backup/restore artifact exists.
- Restore database contains `alpaca-paper-default` and broker-account safety tables.

## Phase 3 — Runtime observability and incident response

**Goal:** operators can diagnose failures without shell access.

Tasks:
- Ensure broker lifecycle events are emitted for:
  - candidate creation
  - skip reasons
  - submit/cancel/close/refresh attempts
  - reconciliation uncertainty
  - circuit-breaker activation/clear
  - drawdown warm-up and drawdown block
- Add dashboard/health visibility for:
  - stale worker/scheduler heartbeat
  - stale broker snapshot
  - active circuit breakers
  - open `needs_review` orders/positions
  - provider rate limits
- Create incident runbooks for:
  - ambiguous broker submit
  - eToro permission loss
  - stale broker snapshot
  - Postgres unavailable
  - worker crash during broker action

Exit criteria:
- Each runbook has detection signal, immediate action, recovery, and evidence to collect.
- UI/API shows active broker safety issues without querying logs.

## Phase 4 — Security and credential lifecycle

**Goal:** production secrets can be rotated and audited safely.

Tasks:
- Implement or document credential rotation for:
  - app auth token/session secret
  - credential encryption key
  - Alpaca credentials
  - eToro `x-api-key` and `x-user-key`
- Add an encrypted-credential re-encryption workflow or explicit manual procedure.
- Verify secret redaction in:
  - API responses
  - UI JSON/debug payloads
  - logs
  - observability events
  - release-readiness reports
- Decide whether an external secret backend is required for the first production deployment.

Exit criteria:
- Rotation procedure is tested on staging data.
- Redaction tests include `x-user-key`, `x_user_key`, `api_key`, and `api_secret`.

## Optional single-host Docker deployment track

Docker Compose deployment is an additive path for small single-host operation. It must pass the same safety checks as the host-level supervisor and must not replace `scripts/start-prod.sh` until a separate soak decision is recorded.

Required Docker evidence before use as the main deployment path:

- Compose starts Postgres, API, one worker, and one scheduler.
- Runtime heartbeats and lifecycle events are visible in authenticated health endpoints.
- Public `/api/health` remains minimal and internet-safe.
- Postgres backup and restore-smoke commands pass.
- Worker scaling remains opt-in and scheduler remains single-instance.
- Existing `scripts/start-prod.sh` still works unchanged.

## Phase 5 — Staging soak without real-money mutation

**Goal:** prove the runtime behaves over full market sessions.

Tasks:
- Deploy against production-like Postgres.
- Enable Alpaca paper and optional eToro read-only/demo accounts only.
- Keep global broker halt on for the first startup, then clear intentionally.
- Run at least 5 market sessions with:
  - scheduled jobs
  - broker reconciliation
  - drawdown state collection
  - circuit-breaker monitoring
  - no unreviewed `needs_review` older than one session
- Record daily artifacts:
  - health snapshot
  - broker workbench snapshot
  - open orders/positions report
  - failed jobs and stale runs report

Exit criteria:
- No duplicate autonomous broker submissions.
- No unresolved broker ambiguity older than one market session.
- No secret leakage in logs/artifacts.

## Phase 6 — eToro external validation gates

**Goal:** collect evidence required before any real-money path is considered.

Tasks:
1. Re-read current eToro docs and update `specs/etoro-live-trading-integration-spec.md` with exact current demo/live mutation endpoint mappings.
2. Run read-only validation with real credentials and record:
   - `ETORO_READONLY_VALIDATION_ARTIFACT_ID`
3. Run controlled demo lifecycle validation and record:
   - `ETORO_DEMO_VALIDATION_ARTIFACT_ID`
4. Run live-shadow for at least one full market session and record:
   - `ETORO_LIVE_SHADOW_EVIDENCE_ID`
5. Run release readiness:
   ```bash
   ETORO_READONLY_VALIDATION_ARTIFACT_ID=<id> \
   ETORO_DEMO_VALIDATION_ARTIFACT_ID=<id> \
   ETORO_LIVE_SHADOW_EVIDENCE_ID=<id> \
     .venv/bin/python scripts/check_etoro_release_readiness.py \
       --report-output artifacts/etoro-release-readiness.json
   ```

Exit criteria:
- Release readiness passes without `--allow-missing-external-artifacts`.
- eToro live adapter still rejects mutation unless a separate live-mutation implementation is reviewed.

## Phase 7 — Trading-edge validation before capital increase

**Goal:** avoid scaling a system that is operationally safe but unprofitable.

Tasks:
- Define a minimum evaluation window before increased autonomy:
  - at least 50 broker-backed paper/demo completed positions, or
  - at least 20 trading days of live-shadow evidence plus replay evidence.
- Compare against simple baselines:
  - no-trade baseline
  - equal-weight watchlist baseline
  - simple momentum baseline
- Report by cohort:
  - setup family
  - holding horizon
  - confidence bucket
  - market regime
  - ticker concentration
- Demote or disable cohorts with weak or negative evidence.

Exit criteria:
- A dated edge-validation report exists.
- The report identifies which cohorts are allowed, capped, or disabled.
- Capital cannot be increased without updating per-broker caps and recording operator approval.

## Phase 8 — Production rollout ladder

**Goal:** increase autonomy and capital only after each smaller step is stable.

Rollout steps:
1. **Prod read-only:** no autonomous broker actions; observe health and data flows.
2. **Prod paper:** Alpaca paper autonomous execution with strict caps.
3. **eToro read-only:** real credentials, no mutation.
4. **eToro demo:** demo lifecycle only.
5. **eToro live-shadow:** would-submit audit rows only.
6. **eToro live micro-size proposal:** separate implementation task after all previous gates pass.

Initial live-money defaults if implemented later:
- eToro live trading disabled by default.
- max `$25` per order.
- max 1 live order/day.
- long-only.
- leverage `1`.
- empty symbol allowlist until operator adds symbols.
- block on untracked exposure, missing drawdown baseline, stale snapshot, or active circuit breaker.

Exit criteria:
- Each rollout step has a dated operator sign-off.
- Regression tests and release-readiness checks pass before moving to the next step.

## Phase 9 — Ongoing production operations

**Goal:** keep the bot safe after launch.

Recurring checks:
- Daily:
  - health page review
  - broker workbench review
  - unresolved `needs_review` check
  - active circuit-breaker check
- Weekly:
  - backup restore smoke
  - performance/edge report
  - dependency/provider failure report
- Monthly:
  - credential rotation review
  - migration dry-run if pending migrations exist
  - cohort cap review

Exit criteria:
- Any failed daily safety check keeps broker halt active.
- Any weekly negative edge report prevents capital increases.

## Open decisions before production

1. Which host and Postgres provider will run the first production deployment?
2. Is external secret storage required for launch, or are encrypted DB credentials acceptable temporarily?
3. What is the first production watchlist and allowed trading universe?
4. What minimum evidence threshold is required before any real-money eToro mutation implementation is approved?
5. Who is the human operator responsible for daily safety review and emergency halt?
