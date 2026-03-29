from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from trade_proposer_app.config import settings

HEAD_REVISION = "0017_historical_replay_batches"
LEGACY_REVISION_MAP = {
    "0003_recommendation_diagnostics_fields": "0003_rec_diag_fields",
    "0004_jobs_watchlists_and_run_errors": "0004_jobs_watchlists_run_errs",
    "0006_recommendation_states_and_summary": "0006_rec_states_summary",
    "0007_scheduled_runs_idempotency": "0007_sched_runs_idempotency",
    "0008_job_types_and_run_metadata": "0008_job_types_run_metadata",
    "0009_recommendation_feature_vectors": "0009_rec_feature_vectors",
    "0011_sentiment_snapshot_summaries": "0011_snapshot_summaries",
    "0013_context_and_recommendation_models": "0013_context_rec_models",
    "0015_drop_legacy_recommendations_table": "0015_drop_legacy_recs",
}


def get_alembic_config() -> Config:
    return Config("alembic.ini")


def normalize_alembic_revision_ids() -> bool:
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            if "alembic_version" not in set(inspector.get_table_names()):
                return False
            version = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
            normalized = LEGACY_REVISION_MAP.get(str(version), str(version))
            if not version or normalized == version:
                return False
            connection.execute(text("UPDATE alembic_version SET version_num = :version_num"), {"version_num": normalized})
            return True
    finally:
        engine.dispose()


def try_repair_partial_sqlite_schema() -> bool:
    if not settings.database_url.startswith("sqlite"):
        return False

    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            if "alembic_version" not in table_names or "jobs" not in table_names or "runs" not in table_names:
                return False

            version = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
            if version not in {"0003_rec_diag_fields", "0003_recommendation_diagnostics_fields"}:
                return False

            job_columns = {column["name"] for column in inspector.get_columns("jobs")}
            run_columns = {column["name"] for column in inspector.get_columns("runs")}

            if "watchlist_id" not in job_columns:
                return False

            if "job_type" not in job_columns:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN job_type VARCHAR(64) NOT NULL DEFAULT 'proposal_generation'"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_job_type ON jobs (job_type)"))

            if "error_message" not in run_columns:
                connection.execute(text("ALTER TABLE runs ADD COLUMN error_message TEXT NOT NULL DEFAULT ''"))
            if "scheduled_for" not in run_columns:
                connection.execute(text("ALTER TABLE runs ADD COLUMN scheduled_for DATETIME"))
            if "job_type" not in run_columns:
                connection.execute(text("ALTER TABLE runs ADD COLUMN job_type VARCHAR(64) NOT NULL DEFAULT 'proposal_generation'"))
            if "summary_json" not in run_columns:
                connection.execute(text("ALTER TABLE runs ADD COLUMN summary_json TEXT NOT NULL DEFAULT ''"))
            if "artifact_json" not in run_columns:
                connection.execute(text("ALTER TABLE runs ADD COLUMN artifact_json TEXT NOT NULL DEFAULT ''"))
            connection.execute(text("UPDATE runs SET job_type = 'proposal_generation' WHERE job_type IS NULL OR job_type = ''"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_runs_scheduled_for ON runs (scheduled_for)"
                )
            )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_runs_job_type ON runs (job_type)"))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_job_id_scheduled_for ON runs (job_id, scheduled_for)"
                )
            )

            connection.execute(text("UPDATE alembic_version SET version_num = :version_num"), {"version_num": HEAD_REVISION})
            return True
    finally:
        engine.dispose()


def main() -> None:
    normalize_alembic_revision_ids()
    try:
        command.upgrade(get_alembic_config(), "head")
    except OperationalError as exc:
        message = str(exc)
        if (
            "duplicate column name: watchlist_id" in message
            or "duplicate column name: error_message" in message
        ) and try_repair_partial_sqlite_schema():
            return
        raise


if __name__ == "__main__":
    main()
