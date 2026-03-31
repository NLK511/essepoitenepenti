# Nitter Social Relevance Scoring

## Status

Implemented in the app-native Nitter social ingestion pipeline.

## Goal

Nitter search results can be noisy. The relevance scoring layer is designed to rank the most informative posts first so macro, industry, and ticker refreshes keep the strongest available items instead of filling the snapshot with low-value chatter.

This does **not** invent social coverage. If Nitter returns nothing meaningful, the snapshot still records zero coverage explicitly.

## Where it applies

The ranking is applied inside `NitterProvider` before the provider returns a `SignalBundle`.

That means the same scoring path is used for:
- ticker refreshes
- industry refreshes
- macro refreshes

## Scoring strategy

Each candidate post gets a relevance score built from these components:

### 1. Subject match strength
Posts are compared against the active subject query profile.

The scorer counts:
- exact query-term hits in the post body/title
- query-term hits in the title specifically
- multi-word phrase hits

These are the strongest signals in the ranking.

### 2. Recency
Recent posts are preferred over older ones inside the configured query window.

The score decays as the post ages, but it never falls below a floor so one older, highly relevant post can still survive if the rest of the feed is weak.

### 3. Engagement
Likes, retweets, and replies provide a small boost.

This is intentionally secondary to topical relevance so high-engagement off-topic chatter does not dominate the feed.

### 4. Source quality and credibility
The provider’s existing quality and credibility estimates are reused as ranking inputs.

This helps informative, account-like posts outrank low-signal fragments.

### 5. Length / information density
Very short posts are penalized.

The goal is to reduce:
- reaction posts
- meme replies
- one-word commentary
- generic “agree / interesting / wow” style posts

### 6. Generic noise penalties
A small penalty is applied to obviously low-value wording such as:
- `great`
- `interesting`
- `wow`
- `agreed`
- `lol`
- `watch this`
- `thoughts`

Short question-like macro posts also receive a small penalty.

## Ranking behavior

After scoring:
1. duplicate items are removed using the existing dedupe key logic
2. items are sorted by relevance score descending
3. the provider keeps the top `max_items_per_query` items in the returned bundle

## Diagnostics

Each query now records:
- `raw_item_count`
- `parsed_item_count`
- `filtered_item_count`

The subject diagnostics also include:
- `ranked_item_count`
- the executed query list

This makes it easier to distinguish between:
- Nitter returned nothing
- Nitter returned items but the parser rejected them
- items were parsed but filtered by window / exclude keywords
- items were parsed and ranked, but only the strongest ones were kept

## Operational note

Relevance ranking improves signal quality, but it does not guarantee high-quality macro coverage if the underlying query set is too broad or the Nitter instance is sparse.

For macro support/context refreshes, the strongest results usually come from more specific phrasing such as:
- `ECB rates`
- `European Central Bank`
- `rate cut`
- `war escalation`
- `military tensions`
- `geopolitical risk`

The app still preserves signal integrity: low coverage stays explicit instead of being silently padded with fallback content.
