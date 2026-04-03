# User Journeys

**Status:** canonical workflow framing

These journeys describe how the product is meant to be used today.

They exist to keep UI and workflow decisions tied to real operator tasks.

## 1. First-time setup

**Persona:** solo trader or operator bringing up the app locally or on a VPS.

Steps:
1. start the app
2. log in
3. open Settings and verify health/preflight
4. configure providers and summary settings if needed
5. create a watchlist
6. create a proposal job
7. run the job
8. review the resulting plans and source run

**Success outcome:** the user gets a first recommendation or plan without needing raw logs or manual backend orchestration.

## 2. Daily monitoring

**Persona:** active user checking the system each day.

Steps:
1. open the dashboard
2. scan signals and plans first
3. scan recent runs as execution context
4. check health and context freshness
5. open only problematic runs or plans for deeper inspection

**Success outcome:** the user can separate trade decisions from system diagnostics.

## 3. Investigating a degraded output

**Persona:** user sees a warning-heavy or partially degraded recommendation.

Steps:
1. open recommendation plans or run detail
2. review the trade object and diagnostics
3. check linked shared context first
4. follow the link back to the source run
5. review warnings to determine whether the issue came from missing providers, stale context, summary failure, weak coverage, or data retrieval problems
6. decide whether the output is still usable

**Success outcome:** the user can judge whether a degraded output is still usable or should be ignored.

## 4. Reviewing historical quality

**Persona:** user wants to inspect quality and outcome behavior over time.

Steps:
1. open recommendation plans
2. filter by ticker, action, run, setup family, or calibration slice
3. run or review evaluation workflows so older plans gain outcomes
4. review setup-family and calibration surfaces
5. open ticker pages or run detail for deeper inspection

**Success outcome:** the user can review quality and outcome state without direct database access.

## 5. Running the self-improvement loop

**Persona:** operator who wants evaluation and optimization to run on a cadence.

Steps:
1. enable or schedule evaluation workflows
2. let the app evaluate older plans through the run system
3. enable or schedule optimization workflows
4. let the app update `weights.json` using resolved outcomes and store backups
5. review run outputs, failures, and resulting weight changes

**Success outcome:** the improvement loop runs inside the product with auditable records.

## 6. Managing shared context

**Persona:** operator responsible for keeping macro and industry context fresh.

Steps:
1. open Context review
2. review recent macro and industry context plus supporting refresh history
3. notice freshness warnings or missing coverage
4. queue a refresh
5. open context detail pages or related runs when investigating quality problems

**Success outcome:** shared context becomes an inspectable system artifact rather than hidden background state.

## 7. Operating the deployment

**Persona:** operator maintaining a real deployment.

Steps:
1. deploy the app and configure `.env`
2. check `/api/health` and `/api/health/preflight`
3. monitor API, worker, and scheduler behavior
4. investigate failures through runs, diagnostics, and logs
5. upgrade the app without changing the product model

**Success outcome:** the app remains understandable to operate while background workflows are active.

## 8. Using the in-app docs

**Persona:** operator or trader trying to understand setup, diagnostics, or methodology without leaving the product.

Steps:
1. open the docs page
2. search for the relevant document
3. open the document
4. jump to the needed section
5. return to the workflow page with enough context to proceed

**Success outcome:** the user can answer most product and operations questions from inside the app.

## Deferred: multi-user collaboration

This is intentionally not a current product journey. Multi-user collaboration, RBAC, and tenancy should not shape present-day workflow decisions until the single-user model is more mature.

## See also

- `operator-page-field-guide.md`
- `features-and-capabilities.md`
- `getting-started.md`
