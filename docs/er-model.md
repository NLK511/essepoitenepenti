# ER Model

**Status:** current database entity-relationship reference

This document describes the current database shape reflected by the live SQLAlchemy persistence models in `src/trade_proposer_app/persistence/models.py`.

Notes:
- this is a practical ER view of the current app schema, not an aspirational redesign-only schema
- the legacy `recommendations` table was removed in migration `0015_drop_legacy_recommendations_table.py`
- several tables store structured payloads in `*_json` text columns, so not every business concept is normalized into its own table
- some foreign keys exist without explicit ORM back-populated relationship fields, but they are still part of the relational model

## Mermaid ER diagram

This diagram intentionally uses plain Mermaid ER syntax with unquoted entity identifiers so it stays compatible with the in-app renderer.

```mermaid
erDiagram
    WATCHLISTS {
        int id PK
        string name UK
        text description
        string region
        string exchange
        string timezone
        string default_horizon
        boolean allow_shorts
        boolean optimize_evaluation_timing
        text tickers_csv
        datetime created_at
        datetime updated_at
    }

    JOBS {
        int id PK
        string name UK
        string job_type
        text tickers_csv
        int watchlist_id FK
        string schedule
        boolean enabled
        datetime last_enqueued_at
        datetime created_at
        datetime updated_at
    }

    RUNS {
        int id PK
        int job_id FK
        string job_type
        string status
        text error_message
        datetime scheduled_for
        text summary_json
        text artifact_json
        datetime started_at
        datetime completed_at
        float duration_seconds
        text timing_json
        datetime created_at
        datetime updated_at
    }

    APP_SETTINGS {
        string key PK
        text value
        datetime created_at
        datetime updated_at
    }

    PROVIDER_CREDENTIALS {
        string provider PK
        text api_key
        text api_secret
        datetime created_at
        datetime updated_at
    }

    SENTIMENT_SNAPSHOTS {
        int id PK
        string scope
        string subject_key
        string subject_label
        string status
        float score
        string label
        datetime computed_at
        datetime expires_at
        int job_id FK
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    MACRO_CONTEXT_SNAPSHOTS {
        int id PK
        datetime computed_at
        string status
        text summary_text
        float saliency_score
        float confidence_percent
        int job_id FK
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    INDUSTRY_CONTEXT_SNAPSHOTS {
        int id PK
        string industry_key
        string industry_label
        datetime computed_at
        string status
        string direction
        float saliency_score
        float confidence_percent
        int job_id FK
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    TICKER_SIGNAL_SNAPSHOTS {
        int id PK
        string ticker
        string horizon
        datetime computed_at
        string status
        string direction
        float swing_probability_percent
        float confidence_percent
        float attention_score
        int job_id FK
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    RECOMMENDATION_PLANS {
        int id PK
        string ticker
        string horizon
        string action
        string status
        float confidence_percent
        float entry_price_low
        float entry_price_high
        float stop_loss
        float take_profit
        int holding_period_days
        float risk_reward_ratio
        text thesis_summary
        text rationale_summary
        datetime computed_at
        int watchlist_id FK
        int ticker_signal_snapshot_id FK
        int job_id FK
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    RECOMMENDATION_OUTCOMES {
        int id PK
        int recommendation_plan_id FK
        string outcome
        string status
        datetime evaluated_at
        boolean entry_touched
        boolean stop_loss_hit
        boolean take_profit_hit
        float horizon_return_1d
        float horizon_return_3d
        float horizon_return_5d
        float max_favorable_excursion
        float max_adverse_excursion
        float realized_holding_period_days
        boolean direction_correct
        string confidence_bucket
        string setup_family
        text notes
        int run_id FK
        datetime created_at
        datetime updated_at
    }

    WATCHLISTS ||--o{ JOBS : owns
    JOBS ||--o{ RUNS : schedules

    WATCHLISTS ||--o{ RECOMMENDATION_PLANS : scopes
    JOBS ||--o{ SENTIMENT_SNAPSHOTS : produces
    RUNS ||--o{ SENTIMENT_SNAPSHOTS : produces

    JOBS ||--o{ MACRO_CONTEXT_SNAPSHOTS : produces
    RUNS ||--o{ MACRO_CONTEXT_SNAPSHOTS : produces

    JOBS ||--o{ INDUSTRY_CONTEXT_SNAPSHOTS : produces
    RUNS ||--o{ INDUSTRY_CONTEXT_SNAPSHOTS : produces

    JOBS ||--o{ TICKER_SIGNAL_SNAPSHOTS : produces
    RUNS ||--o{ TICKER_SIGNAL_SNAPSHOTS : produces

    TICKER_SIGNAL_SNAPSHOTS ||--o{ RECOMMENDATION_PLANS : informs
    JOBS ||--o{ RECOMMENDATION_PLANS : produces
    RUNS ||--o{ RECOMMENDATION_PLANS : produces

    RECOMMENDATION_PLANS ||--o| RECOMMENDATION_OUTCOMES : resolves_to
    RUNS ||--o{ RECOMMENDATION_OUTCOMES : evaluates
```

## Relationship summary

Core execution chain:
- `watchlists -> jobs -> runs`
- `runs` act as the execution record for scheduled or manual work

Context and signal outputs:
- `sentiment_snapshots` attach to a `job` and/or `run`
- `macro_context_snapshots` attach to a `job` and/or `run`
- `industry_context_snapshots` attach to a `job` and/or `run`
- `ticker_signal_snapshots` attach to a `job` and/or `run`

Trade-planning outputs:
- `recommendation_plans` can attach to:
  - a `watchlist`
  - a `ticker_signal_snapshot`
  - a `job`
  - a `run`
- `recommendation_outcomes` attach to exactly one `recommendation_plan`
- `recommendation_outcomes` may also attach to the `run` that performed evaluation

Standalone tables:
- `app_settings`
- `provider_credentials`

## Source of truth

If this diagram drifts from the implementation, treat these as the authoritative sources in order:
1. `src/trade_proposer_app/persistence/models.py`
2. `alembic/versions/`
3. this document
