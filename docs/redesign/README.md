# Redesign

**Status:** active redesign reference

This directory contains the redesign docs that are still part of the active technical reference.

Historical redesign planning and convergence material has been moved to `../archive/redesign/` so this folder stays focused on current design guidance.

## Active redesign docs

### Principles
- `principles.md`
- Core product principles: observability, trust, explicit degraded states, and no hidden fallbacks.

### Target architecture
- `target-architecture.md`
- High-level design across context, exposure, ticker setup, and trade-plan construction.

### Data model and persistence
- `data-model-and-persistence.md`
- Redesign persistence direction, entity framing, and schema-oriented reference.

### Transmission modeling spec
- `transmission-modeling-spec.md`
- Rules for mapping macro and industry context into ticker-level exposure, transmission bias, conflicts, and timing windows.

### Calibration governance spec
- `calibration-governance-spec.md`
- Rules for sample-aware, operator-visible use of outcome history in confidence and action gating.

### Setup family playbook
- `setup-family-playbook.md`
- Setup-family-specific expectations for entry, invalidation, target, context interaction, and evaluation.

### Full combined reference
- `short-horizon-recommendation-architecture.md`
- Consolidated design reference containing the broader redesign shape in one file.

## Archived redesign docs

The following redesign docs were moved to archive because they are now mainly historical or migration-oriented:
- `../archive/redesign/migration-plan.md`
- `../archive/redesign/implementation-charter.md`
- `../archive/redesign/legacy-convergence-plan.md`
- `../archive/redesign/measured-success-criteria.md`

## Operating rules

Across all redesign work, preserve these rules:
- no hidden fallbacks
- explicit degraded states
- structured warnings
- clear source provenance
- no false confidence

## See also

- `principles.md` — redesign rules
- `target-architecture.md` — overall redesign shape
- `../roadmap.md` — current priorities
- `../archive/redesign/` — historical redesign planning and convergence docs
