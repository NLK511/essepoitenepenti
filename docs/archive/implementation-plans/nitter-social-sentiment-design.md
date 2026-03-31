# Nitter Social Sentiment Design

## Status

Conceptual only. This is not part of the current near-term roadmap.

## Intended role

If resumed later, Nitter-backed social ingestion should be treated as an optional extension to the existing signal stack, not as a replacement for the current news/snapshot architecture.

The design constraints should remain:
- normalize social items into the same operator-auditable shape as other signals
- preserve the signal integrity policy by making missing social coverage explicit
- avoid increasing provider and credential complexity until the current platform is operationally stronger

## Current recommendation

Do not prioritize this work ahead of:
1. scheduler and worker hardening
2. observability
3. credential lifecycle improvements
4. measurement of the current sentiment stack's effectiveness

If development resumes later, produce a fresh design note based on the live schema and live roadmap rather than relying on older implementation assumptions.
