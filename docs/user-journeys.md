# User Journeys

## Journey 1: First-time setup

### Persona
Solo trader running the app on a VPS.

### Steps
1. User opens the app.
2. User configures provider credentials.
3. User verifies service health.
4. User creates one or more watchlists.
5. User creates a scheduled analysis job.
6. User lands on the dashboard and waits for the first run.
7. User reviews the recommendations produced by that run.

### Success outcome
The user gets the first trade recommendation without reading logs or running shell commands.

## Journey 2: Daily monitoring

### Persona
Active user checking recommendations each morning.

### Steps
1. User opens dashboard.
2. User scans latest recommendations as the primary trade objects.
3. User uses latest runs as execution context, not as the trade record itself.
4. User opens only the problematic runs that need investigation.
5. User reviews the recommendation archive if needed.

### Success outcome
The user can triage execution issues quickly without confusing runs with recommendations.

## Journey 3: Investigating a problematic run behind a recommendation

### Persona
User sees that a recommendation came from a degraded or failed execution path.

### Steps
1. User opens the recommendation first to review the trade-ready output.
2. User follows the link back to the source run, debugger, or run detail.
3. User reviews structured diagnostics.
4. User sees if the issue came from:
   - missing provider credentials
   - provider timeout
   - summary failure
   - partial feed ingestion failure
5. User decides whether the recommendation is still usable.

### Success outcome
The user understands whether the source run was degraded but acceptable, or truly failed, without losing the distinction between trade output and execution record.

## Journey 4: Recommendation archive and evaluation review

### Persona
User wants to inspect low-confidence archived recommendations and see which ones eventually won or lost.

### Steps
1. User opens recommendation history.
2. User filters by ticker, direction, recommendation state, or warning state.
3. User runs evaluation when needed so older `PENDING` recommendations can settle into `WIN` or `LOSS`.
4. User sorts by confidence or timestamp.
5. User opens individual ticker pages or recommendation pages for deeper review.

### Success outcome
The user can inspect historical recommendation quality and outcome state without direct DB access.

## Journey 5: Scheduled self-improvement

### Persona
User or operator who wants the strategy to learn from outcomes on a regular cadence.

### Steps
1. User creates or enables a scheduled evaluation workflow.
2. The app runs evaluation automatically and settles older recommendations when due.
3. User creates or enables a scheduled optimization workflow.
4. The app runs optimization automatically when its schedule and guardrails allow it, using the run history stored in the app to adjust the tracked `weights.json` plus backups.
5. User reviews evaluation and optimization run history, outputs, failures, and any resulting weight changes.

### Success outcome
The self-improvement loop operates entirely inside the product—no prototype scripts or manual shell actions are required—while providing audit-ready summaries of every optimization batch.

## Journey 6: System operation

### Persona
Operator maintaining the deployment.

### Steps
1. Operator deploys app via Docker Compose.
2. Operator provides `.env` configuration.
3. Operator checks API health and the internal pipeline preflight endpoint.
4. Operator monitors worker process status, logs, and queue behavior.
5. Operator upgrades the app without changing the product model.

### Success outcome
The app remains easy to run and debug.

## Journey 7: In-app documentation use

### Persona
Operator or trader trying to understand setup, diagnostics, or recommendation logic without leaving the app.

### Steps
1. User opens the docs page.
2. User searches for a topic such as setup, raw details, or recommendation methodology.
3. User selects a document from the sidebar.
4. User jumps directly to an inner section within the selected document.
5. User returns to settings, debugger, or history with the needed context.

### Success outcome
The user can answer most operational or methodology questions from inside the product UI.

## Journey 8: Future evolution to multi-user product

### Persona
Small team using the app collaboratively.

### Steps
1. Each user logs in.
2. Users create workspace-scoped watchlists and jobs.
3. Access is controlled by role.
4. Alerts and recommendations become workspace-aware.

### Success outcome
The product grows into a team tool without requiring core architectural replacement.
