# Migration Plan

## Goal

Move from the current sentiment-oriented implementation toward a saliency-first, context-driven, short-horizon recommendation engine without breaking the app all at once.

The migration should be steered by measurable recommendation quality, not just by architectural neatness. Near-term success is better operator decision support and better candidate ranking; stronger predictive claims should come only after stored outcomes and calibration support them.

## Guiding rule

Do not try to convert the whole system in one step.

Introduce the new architecture beside the current one, validate it, then gradually make it primary.

## Phase 1: Freeze new complexity in current macro/industry sentiment summaries

Objective:

- keep the current system stable
- stop extending the sentiment-first approach for macro and industry

Actions:

- avoid adding more complexity to macro/industry sentiment summary logic
- treat current macro and industry sentiment outputs as transitional
- preserve current diagnostics and observability behavior

## Phase 2: Add new context models beside current sentiment snapshots

Objective:

Introduce new context-oriented objects without immediately removing existing ones.

Add:

- macro context models
- industry context models
- event extraction outputs
- explicit status and warning fields

Result:

The app can begin storing and exposing saliency-first context while preserving backward compatibility.

## Phase 3: Build news-first ingestion for macro and industry

Objective:

Shift macro and industry inputs toward the new source hierarchy.

Actions:

- make macro ingestion primarily newswire/newspaper/official-source driven
- make industry ingestion primarily trade-press/sector-reporting driven
- keep social as secondary support
- expose source failures and degraded states explicitly

## Phase 4: Implement event extraction

Objective:

Create a reusable event layer between raw content and context summaries.

Actions:

- normalize raw items into macro, industry, and ticker events
- store saliency, novelty, confidence, and linked evidence
- use event extraction as the basis for summaries and context objects

## Phase 5: Build context synthesis

Objective:

Make macro and industry jobs produce context outputs rather than sentiment-first outputs.

Actions:

- create macro context snapshots from extracted macro events
- create industry context snapshots from extracted industry events plus macro spillover
- store summaries, active themes, warnings, and source breakdown

At this stage, macro and industry sentiment can remain as a secondary sub-signal if still useful.

## Phase 6: Add recommendation-plan outcome tracking and evaluation

Objective:

Create a feedback loop for improving recommendation quality before making strong predictive claims.

Status:

This phase is now materially underway. The app persists recommendation outcomes against `RecommendationPlan`, exposes them through the API, and can queue recommendation-plan evaluation runs from operator workflows.

Delivered actions:

- store recommendation outcomes against `RecommendationPlan`
- track TP/SL hits, fixed-horizon returns, and max favorable/adverse excursion
- record direction correctness, setup-family attribution, and confidence buckets

Remaining actions:

- analyze which signal combinations and setup families work best
- use stored outcomes for confidence calibration and recommendation-engine refinement

## Phase 7: Refactor ticker analysis around setup quality

Objective:

Use context as input to a real short-horizon ticker setup engine.

Actions:

- feed macro context into ticker scoring
- feed industry context into ticker scoring
- combine ticker catalysts, sentiment, and technical structure
- classify setup family
- expose decomposed confidence components
- output swing probability, direction, and tradeability

## Phase 8: Add deterministic trade construction

Objective:

Make the app produce practical recommendation plans.

Actions:

- add entry-zone generation
- add stop-loss construction from invalidation logic
- add take-profit construction from structure and expected move
- add risk/reward gating
- emit `watchlist` or `no_action` when trade construction is weak

## Phase 9: Make context primary and sentiment secondary

Objective:

Complete the conceptual transition.

Actions:

- move UI and APIs to emphasize context objects over macro/industry sentiment labels
- retain sentiment as a sub-signal where useful
- retire macro/industry sentiment as the main product concept

## Recommended implementation order

A practical order would be:

1. new redesign docs
2. target data model and status/warning model
3. database migration strategy toward PostgreSQL
4. event extraction prototype
5. macro context prototype
6. industry context prototype
7. outcome tracking and evaluation refinement
8. ticker setup refactor
9. recommendation construction

## Success criteria

The migration is successful when:

- macro output explains salient market-moving developments
- industry output reflects both macro transmission and industry-native drivers
- ticker output evaluates short-horizon setup quality
- final recommendation plans include entry, stop, take profit, confidence, setup-aware rationale, and warnings
- degraded inputs are always visible and never hidden behind silent fallbacks
