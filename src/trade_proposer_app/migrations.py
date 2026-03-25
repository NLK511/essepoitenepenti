from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from trade_proposer_app.config import settings

HEAD_REVISION = "0014_recommendation_outcomes"


def get_alembic_config() -> Config:
    return Config("alembic.ini")


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
            if version != "0003_recommendation_diagnostics_fields":
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
