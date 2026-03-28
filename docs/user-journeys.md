# User Journeys

**Status:** canonical workflow framing

These journeys describe how the product is meant to be used today.

They are here to keep UI and workflow decisions tied to real operator tasks instead of wishlist features.

## Journey 1: First-time setup

### Persona
Solo trader or operator bringing up the app locally or on a VPS.

### Steps
1. User starts the app.
2. User logs in.
3. User opens Settings and verifies health/preflight.
4. User configures provider credentials and summary settings if needed.
5. User creates a watchlist.
6. User creates a proposal job.
7. User runs the job.
8. User reviews the resulting trade outputs and the source run.

### Success outcome
The user gets the first recommendation or recommendation plan without needing to inspect raw logs or manually orchestrate backend components.

## Journey 2: Daily monitoring

### Persona
Active user checking the system each day.

### Steps
1. User opens the dashboard.
2. User scans the latest trade outputs as the primary trade objects.
3. User scans recent runs as execution context.
4. User notices whether health or snapshot freshness is degraded.
5. User opens only problematic runs or recommendation plans for deeper inspection.

### Success outcome
The user can separate trade decisions from system diagnostics without confusion.

## Journey 3: Investigating a degraded trade output

### Persona
User sees that a recommendation plan came from a warning-heavy or partially degraded execution path.

### Steps
1. User opens the recommendation-plan browser or run detail redesign section first.
2. User reviews the trade-ready object and stored diagnostics.
3. User checks linked shared context objects first, then the supporting refresh snapshots when present.
4. User follows the link back to the source run.
5. User reviews structured diagnostics to determine whether the issue came from missing providers, poor news coverage, stale snapshots, summary failure, or data retrieval problems.
6. User decides whether the trade output is still usable.

### Success outcome
The user can judge whether a trade output is degraded-but-usable or should be ignored.

## Journey 4: Reviewing historical quality

### Persona
User wants to inspect archive quality and outcome quality over time.

### Steps
1. User opens recommendation plans.
2. User filters by ticker, action, run, setup family, or calibration slice.
3. User runs or reviews evaluation workflows so older plans settle into stored recommendation-plan outcomes.
4. User reviews setup-family cohort surfaces or sorts by confidence / timestamp through the available operator views.
5. User opens ticker pages or run detail for deeper review.

### Success outcome
The user can inspect recommendation-plan quality and outcome state without direct database access.

## Journey 5: Running the self-improvement loop

### Persona
Operator who wants evaluation and optimization to run on a cadence.

### Steps
1. User enables or schedules evaluation workflows.
2. The app evaluates older recommendation plans through the normal run system.
3. User enables or schedules optimization workflows.
4. The app updates `weights.json` using resolved recommendation-plan outcomes and stores backup metadata.
5. User reviews run outputs, failures, and resulting weight changes.

### Success outcome
The self-improvement loop runs entirely inside the product with auditable records.

## Journey 6: Managing shared market context

### Persona
Operator responsible for keeping macro and industry context fresh.

### Steps
1. User opens the Context snapshots page.
2. User reviews recent macro and industry context snapshots plus the supporting refresh history.
3. User notices freshness warnings or missing coverage.
4. User queues a refresh or uses the run-now action.
5. User opens context detail pages, support snapshot detail pages, or related runs when investigating quality problems.

### Success outcome
Shared context becomes an inspectable system artifact rather than hidden background state, while the transitional support-snapshot layer remains auditable.

## Journey 7: Operating the deployment

### Persona
Operator maintaining a real deployment.

### Steps
1. Operator deploys the app and configures `.env`.
2. Operator checks `/api/health` and `/api/health/preflight`.
3. Operator monitors API, worker, and scheduler behavior.
4. Operator investigates failures through runs, diagnostics, and logs.
5. Operator upgrades the app without changing the product model.

### Success outcome
The app remains understandable to operate even when background workflows are active.

## Journey 8: Using the in-app docs

### Persona
Operator or trader trying to understand setup, diagnostics, or methodology without leaving the product.

### Steps
1. User opens the docs page.
2. User searches for setup, raw details, roadmap, or methodology.
3. User opens the relevant document.
4. User jumps to the needed section.
5. User returns to the workflow page with enough context to proceed.

### Success outcome
The user can answer most product and operations questions from inside the app.

## Deferred journey: multi-user collaboration

This is intentionally not a current product journey. Multi-user collaboration, RBAC, and tenancy remain future expansion topics and should not shape present-day workflow decisions until the single-user operational model is fully hardened.

## See also

- `operator-page-field-guide.md` — page-by-page workflow guidance
- `features-and-capabilities.md` — what is available today
- `getting-started.md` — first-time setup and startup
