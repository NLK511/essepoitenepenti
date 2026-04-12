# Tech debt remediation plan

**Status:** archived implementation plan

Most of this cleanup has landed. Keep this document only as historical execution context.

## Goals
- rename context refresh job types to canonical keys
- retire `SupportSnapshot` completely
- converge runtime, tests, frontend, scripts, and docs on context-native terminology
- harden health, logging, and worker/scheduler diagnostics for moderate production use

## Phases

1. **Terminology lock**
   - publish `docs/terminology.md`
   - treat legacy job type keys as temporary compatibility aliases only

2. **Job type migration**
   - rename persisted values to `macro_context_refresh` and `industry_context_refresh`
   - accept old keys for one release, but normalize immediately on write

3. **SupportSnapshot retirement**
   - stop writing or reading `SupportSnapshot`
   - persist `ContextSnapshot` directly from refresh payloads
   - hard-delete the legacy table and repository

4. **Implementation rename pass**
   - rename refresh services, builders, route wording, test names, and seeded jobs from support-oriented language to context-oriented language

5. **Operational hardening**
   - add structured worker/scheduler logging
   - expose scheduler heartbeat, worker heartbeat, stale-run counts, and context freshness in `/api/health`
   - tighten run recovery semantics and failure visibility

6. **Compatibility removal**
   - remove legacy parsing and aliases after the validation window

## Success criteria
- no runtime code depends on `SupportSnapshot`
- no canonical code writes `*_sentiment_refresh`
- health endpoints distinguish service status, dependency preflight, worker status, scheduler status, and freshness
- tests cover migration aliases, context refresh execution, and stale-run recovery
