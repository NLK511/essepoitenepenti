# Nitter Social Sentiment Implementation Checklist

## Completed in this first pass
- [x] Add generalized `SignalItem` and `SignalBundle` models
- [x] Add social/Nitter app settings
- [x] Add `POST /api/settings/social`
- [x] Add `NitterProvider` scaffold
- [x] Add `SocialIngestionService`
- [x] Add `SignalIngestionService`
- [x] Wire signal ingestion into `ProposalService`
- [x] Persist `analysis_json.signals` and `analysis_json.social`
- [x] Add Nitter reachability to preflight
- [x] Add design doc and taxonomy placeholder

## Next coding pass
- [ ] improve Nitter parsing robustness and add fixture-based tests
- [ ] add ticker taxonomy loading service
- [ ] build macro / industry / ticker query profiles
- [ ] classify signal items by scope
- [ ] compute social sentiment scores with recency / engagement / author weighting
- [ ] fuse news + social into ticker sentiment
- [ ] expose social settings in the frontend
- [ ] surface social diagnostics in run detail pages

## Later phases
- [ ] hierarchical macro / industry / ticker sentiment fusion
- [ ] divergence metrics between news and social
- [ ] feature-vector integration and weight tuning
- [ ] social author allowlist / blocklist
- [ ] industry and macro trend visualizations in the UI
