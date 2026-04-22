# News Provider Reliability Spec

**Status:** canonical current behavior for ticker-news provider failure handling

This document answers one question:
> how should ticker-news fetching behave when one provider degrades or fails?

It is the source of truth for provider retry and fallback diagnostics in ticker-news flows.

## Goal

Ticker-news fetching should stay usable when a single provider becomes noisy or temporarily unavailable.

The system should:
- retry bounded transient-looking provider failures
- preserve successful fallback coverage from other eligible providers
- keep provider failures visible to the operator
- make it obvious when fallback providers still supplied enough ticker-news evidence

## Scope

This spec covers:
- `NewsIngestionService.fetch` ticker-news flows
- Finnhub ticker-news retry behavior
- ticker-news diagnostics stored in `NewsBundle` and downstream detail payloads

This spec does not cover:
- topic-query retry behavior
- social-provider retry behavior
- summary-model retry behavior

## Current implemented behavior

### Eligible provider set
For ticker-news requests, the provider set is still determined by request semantics and provider capabilities.

Typical live ticker-news flows may include:
- Finnhub
- Google News
- Yahoo Finance

Typical replay ticker-news flows may include only replay-safe ticker providers, which currently makes Finnhub much more important.

## Finnhub retry policy

### When retry applies
- Finnhub ticker-news requests use bounded retry.
- Retry applies only to ticker-news fetches handled by `FinnhubProvider.fetch`.

### Attempt cap and backoff
- Maximum attempts: `3` total.
- Small bounded backoff is allowed between attempts.

### Retriable conditions
The implementation must retry when Finnhub returns a transient-looking HTTP status, including:
- `429`
- `500`
- `502`
- `503`
- `504`

A `403` response is treated as an unsupported-market signal for Finnhub company-news and must not be retried or surfaced as an operator warning.

Non-retriable statuses may fail immediately.

### Final failure behavior
- If Finnhub still fails after the retry cap, the provider contributes a feed error.
- A Finnhub unsupported-market `403` must be recorded in diagnostics as a non-warning outcome, not as a feed error.
- A Finnhub failure must not abort the whole ticker-news fetch if other eligible providers can still run.

## Bundle diagnostics

`NewsBundle` must include `query_diagnostics` for ticker-news fetches.

At minimum, ticker-news diagnostics must make visible:
- which providers were selected
- per-provider outcome summaries
- which providers succeeded
- which providers failed
- whether fallback providers still supplied articles despite provider failures

### Required provider outcome fields
Per-provider diagnostics must include at least:
- `provider`
- `status`
- `article_count`
- `attempt_count`
- `error`

### Required fallback summary fields
Ticker-news diagnostics must include at least:
- `fallback_used`
- `fallback_succeeded`
- `successful_provider_count`
- `failed_provider_count`
- `unsupported_provider_count`
- `article_count`

## Operator-facing error semantics

When one or more providers fail but ticker-news articles were still supplied by other providers, the operator-facing diagnostics must say so explicitly.

The current operator-visible path may use a feed-error-style note such as:
- `news: fallback coverage preserved despite provider errors; successful providers=GoogleNews,YahooFinance article_count=4`

This note is additive. It does not replace the underlying provider-specific errors.

## Downstream detail payloads
Ticker proposal/deep-analysis payloads must preserve the ticker-news diagnostics so operators can distinguish:
- complete news failure
- partial provider failure with adequate fallback coverage
- healthy multi-provider coverage

## Tests required by this spec

The automated tests must cover at least:
- Finnhub ticker-news records unsupported-market `403` responses without surfacing them as warnings
- exhausted Finnhub retries still preserve Google/Yahoo fallback articles in live ticker-news flows
- ticker-news diagnostics expose per-provider outcomes and fallback summary fields
- operator-visible feed errors include an explicit fallback-preserved note when other providers still supplied articles

## Current limitations

- Retry classification is still heuristic and based on status codes rather than richer provider semantics.
- Topic-query providers do not yet use the same retry policy.
- UI rendering may still compress diagnostics, so some details are most visible in raw payloads.
