# Terminology

Canonical terminology for the app.

## Job types

| Canonical key | Deprecated compatibility key | Meaning |
|---|---|---|
| `macro_context_refresh` | `macro_context_refresh` | Refresh the shared macro context snapshot |
| `industry_context_refresh` | `industry_context_refresh` | Refresh shared industry context snapshots |

Rules:
- The app writes only canonical job type keys.
- Deprecated compatibility keys are accepted only during the local migration window.
- UI, docs, scripts, and tests should use the canonical keys.

## Context data

| Canonical term | Retired term | Notes |
|---|---|---|
| `ContextSnapshot` | `SupportSnapshot` | `SupportSnapshot` was a transitional internal model and is retired. |
| context refresh | support refresh | Context refresh is the canonical workflow name. |
| context score / context label | support score / support label | New code should prefer context wording. |

## Archive material

Archive docs may still contain historical prototype/support terminology. Active docs should not.
