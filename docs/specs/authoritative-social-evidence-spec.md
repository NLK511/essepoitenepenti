# Authoritative social evidence spec

**Status:** current behavior

## Problem

The app currently treats social evidence as secondary support. That is correct for generic market chatter, but too blunt when the social item comes from an authoritative account through Nitter.

Nitter is a transport layer. The evidence quality should depend on both:
- the transport/source channel, for example news provider vs Nitter
- the origin authority, for example official regulator account, central bank account, company IR account, or known primary newsroom account

A Federal Reserve post fetched through Nitter should not be scored like a random social post. At the same time, it should not silently become equivalent to a press release or filing unless provenance is explicit and auditable.

## Goal

Blend authoritative social evidence into the existing context-confidence model without creating false confidence.

The improvement should:
- preserve the current conservative treatment for generic social evidence
- recognize allowlisted official or primary-author social accounts as stronger evidence
- make the distinction visible in diagnostics and UI payloads
- avoid large refactors to news ingestion, Nitter ingestion, or event extraction
- keep primary-news provider eligibility semantics unchanged

## Non-goals

- Do not make all Nitter items count as primary news.
- Do not treat engagement, virality, or follower count as authority.
- Do not trust an account as authoritative without an explicit allowlist or curated rule.
- Do not use authoritative social as a positive confidence booster for live trading until outcomes show benefit. Initial behavior should mainly remove inappropriate social-only penalties and improve saliency ordering.

## Evidence tiers

Introduce an evidence-tier concept independent from transport channel.

Recommended tiers:

| Tier | Meaning | Examples | Confidence role |
| --- | --- | --- | --- |
| `primary_official` | Official source through primary/news channel | SEC, FDA, Fed site, company IR release | strongest |
| `primary_major` | Major or trade publisher through news channel | Reuters, Bloomberg, WSJ, industry trade press | strong |
| `authoritative_social` | Allowlisted authoritative account through social/Nitter | @federalreserve, @ecb, company IR/official account, regulator account, newsroom account posting its own story | strong support, not generic social |
| `social` | Non-allowlisted social item | analysts, traders, commentators, generic accounts | weak support |
| `other` | Unclassified/low provenance | unknown publisher/account | weak/neutral |

This can initially be represented as an extension of existing `source_priority` values, for example:
- `official`
- `major`
- `trade`
- `authoritative_social`
- `social`
- `other`

A later refactor can split `transport_channel` and `evidence_tier` cleanly, but the first implementation should minimize surface area.

## Authority allowlist

Authoritative social classification must be deterministic and auditable.

Add a small curated allowlist with categories:

- `official_policy`: central banks, treasury departments, regulators, government agencies
- `company_official`: company main account, investor relations, verified executive account only when the company identity matters
- `primary_newsroom`: primary publisher/newsroom accounts that post their own reporting
- `industry_authority`: exchange, standards body, OPEC/IEA/IAEA-like institution, major data agency

Each allowlist entry should include:
- `handle`
- `display_name` or expected author label when available
- `category`
- `source_priority` result, normally `authoritative_social`
- optional `topics` or `ticker_scope`
- optional `notes`

The first version can live in code as a compact constant near social/event extraction utilities. If it grows, move it to taxonomy/config.

## Classification rules

When extracting source priority for a social item:

1. Normalize `author_handle` from the Nitter item.
2. If the handle matches the allowlist, classify as `authoritative_social`.
3. Otherwise classify as `social`.
4. Never infer authority from engagement metrics alone.
5. Never infer authority from display name alone unless handle is missing and the provider has a reliable account URL. Prefer `social` when uncertain.

For primary/news items, keep current rules:
- official publisher hints -> `official`
- trade publisher hints -> `trade`
- major publisher hints -> `major`
- else `other`

## Confidence behavior

Authoritative social should reduce inappropriate confidence cliffs without creating uncontrolled boosts.

Recommended first-pass behavior:

### Macro context

Current confidence heavily penalizes:
- zero primary news items
- no official or major primary source counts

Update the penalty logic so authoritative social can partially mitigate these penalties:

- If `news_item_count == 0` but `authoritative_social_count > 0`, apply a smaller missing-primary penalty instead of the full penalty.
- If official/major primary counts are zero but authoritative social exists, reduce the no-official/major penalty.
- Keep generic social contribution small.
- Keep warnings explicit: “primary news missing; authoritative social evidence present”.

Suggested initial bounds:
- authoritative social may recover at most 8-12 confidence points from missing-primary penalties
- it should not lift confidence above the level reached by real primary official/major coverage
- contradictory social evidence still subtracts confidence

### Industry context

Use the same treatment as macro context, but allow industry-specific authoritative accounts such as regulators, exchanges, standards bodies, or company/industry institutions.

### Ticker/deep analysis

For ticker-specific runs, company official/IR social evidence can support catalyst detection, but should be capped unless confirmed by news/filings/price-volume evidence.

## Saliency behavior

Authoritative social should rank above generic social in event extraction.

Suggested source-priority weight order:

1. `official`
2. `authoritative_social`
3. `trade`
4. `major`
5. `other`
6. `social`

Rationale:
- an official account may be more direct than a major-news article
- trade/major coverage is still important because it adds independent interpretation and distribution
- generic social remains weak

If this ordering feels too aggressive for first release, place `authoritative_social` between `trade` and `major` and evaluate.

## Diagnostics and UI

Every context snapshot should expose:
- `authoritative_social_item_count`
- `authoritative_social_handles`
- `generic_social_item_count`
- `primary_news_item_count`
- `primary_news_coverage_quality`
- a warning when authoritative social is used without primary news confirmation

Operator wording should be explicit:

- “Official/social evidence present via Nitter: @federalreserve”
- “Primary news confirmation missing; confidence remains capped”
- “Generic social only; confidence reduced”

This keeps the operator from confusing Nitter transport with primary-news confirmation.

## Elegant integration path

The smallest clean change is to extend the existing source-priority pipeline instead of creating a parallel evidence system immediately.

### Existing useful seams

- `NitterProvider` already returns social items with `author` and `author_handle`.
- `event_extraction.classify_source_priority(...)` already centralizes source-priority classification.
- Macro and industry context already compute `source_priority_counts(...)` and use those counts in confidence math.
- Context payloads already include `source_breakdown` diagnostics.

### Proposed implementation shape

1. Add `authoritative_social` as a recognized source priority.
2. Add a helper such as `classify_social_authority(author_handle, author_name)`.
3. Update social item classification to inspect `author_handle` when `source_type == "social"`.
4. Update `source_priority_counts(...)` to count `authoritative_social`.
5. Thread `authoritative_social_count` into macro/industry confidence calculations.
6. Add diagnostics to `source_breakdown`.
7. Add tests before behavior changes.

This avoids changing news provider eligibility. `primary_only=true` should still mean primary-news providers only. Authoritative social is a stronger supporting tier, not a primary-news provider.

## Test requirements

Unit tests should prove:

- generic Nitter items remain `social`
- allowlisted handles classify as `authoritative_social`
- authoritative social is counted separately from primary news
- primary-only news provider selection does not include Nitter/social providers
- macro confidence with no news and generic social remains low
- macro confidence with no news but authoritative social is higher than generic-social-only but still capped below primary-news coverage
- warnings explicitly mention missing primary news when authoritative social is the best evidence
- event saliency ranks authoritative social above generic social
- unknown or malformed handles do not become authoritative

## Open questions

- Should primary newsroom social accounts count as `authoritative_social`, or only official institutions/company accounts?
- Should company executive accounts be accepted, or only company/IR accounts?
- Should allowlists be global, taxonomy-managed, or editable from settings?
- What confidence cap should apply when authoritative social is the only evidence?
- Should authoritative social be replay-safe only when historical capture has point-in-time availability metadata?

## Implemented first release

The first release implements a curated `authoritative_social` source priority inside the existing event-extraction/source-priority pipeline.

Included account classes:

- official policy/regulator/central-bank/institution accounts
- primary newsroom / journal accounts
- a small curated set of respected, source-driven financial journalists and analysts

Implemented behavior:

- generic social remains `social`
- allowlisted handles classify as `authoritative_social`
- authoritative social is counted separately from primary news
- macro and industry confidence partially mitigate missing-primary/source-quality penalties when authoritative social is present
- context source breakdowns expose authoritative social counts, handles, generic social counts, and social source-priority summaries
- primary-news provider eligibility is unchanged; Nitter/social does not become a primary-news provider

Authoritative social can mitigate penalties but does not create standalone high-confidence context, and diagnostics still show that primary news is missing when applicable.
