# Redesign

**Status:** active redesign reference

This directory contains the redesign docs that still matter as active technical reference.

Historical redesign planning and convergence material lives in `../archive/redesign/` so this folder can stay focused on current guidance.

## Start here

If you only need the main redesign reading path, use:
- `principles.md` — redesign rules and guardrails
- `target-architecture.md` — high-level system shape
- `short-horizon-recommendation-architecture.md` — fuller combined reference

## Active redesign docs

- `principles.md` — observability, trust, explicit degraded states, and no hidden fallbacks
- `target-architecture.md` — context, exposure, ticker setup, and trade-plan construction
- `data-model-and-persistence.md` — persistence direction and entity framing
- `transmission-modeling-spec.md` — context-to-ticker transmission rules
- `calibration-governance-spec.md` — sample-aware confidence and action-gating rules
- `setup-family-playbook.md` — setup-family expectations for planning and evaluation
- `short-horizon-recommendation-architecture.md` — combined redesign reference

## Archived redesign docs

These are mainly historical or migration-oriented:
- `../archive/redesign/migration-plan.md`
- `../archive/redesign/implementation-charter.md`
- `../archive/redesign/legacy-convergence-plan.md`
- `../archive/redesign/measured-success-criteria.md`

## Shared redesign rules

Across redesign work, preserve these rules:
- no hidden fallbacks
- explicit degraded states
- structured warnings
- clear provenance
- no false confidence

## See also

- `principles.md`
- `target-architecture.md`
- `../roadmap.md`
- `../archive/redesign/`
