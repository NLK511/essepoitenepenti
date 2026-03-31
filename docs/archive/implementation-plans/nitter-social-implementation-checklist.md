# Nitter Social Sentiment Checklist

## Status

Exploratory and lower priority.

This work should not be treated as part of the current critical path. The product's near-term priorities are scheduler reliability, observability, credential lifecycle, and evidence that the existing sentiment stack improves outcomes.

## Why this is deferred

The app already has a coherent sentiment architecture:
- native news ingestion
- shared macro snapshots
- shared industry snapshots
- live ticker sentiment
- optional LLM-enhanced narrative metadata

Before adding more source complexity, the team should validate the quality of the current stack and improve the operational foundation around it.

## If this work resumes later

Use the following sequence:
1. improve parser robustness and add fixture-based tests
2. classify macro, industry, and ticker social signals explicitly
3. make missing social coverage transparent under the existing signal-integrity policy
4. evaluate whether social data improves recommendation quality before fusing it into scoring weights
