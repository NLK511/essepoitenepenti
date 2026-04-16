import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the src directory to sys.path to allow importing from trade_proposer_app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from trade_proposer_app.config import settings

def reset_database():
    print(f"Connecting to database: {settings.database_url}")
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Tables to truncate in order of dependency
    tables_to_clear = [
        "recommendation_outcomes",
        "recommendation_decision_samples",
        "recommendation_plans",
        "ticker_signal_snapshots",
        "macro_context_snapshots",
        "industry_context_snapshots",
        "historical_replay_slices",
        "historical_replay_batches",
        "plan_generation_tuning_events",
        "plan_generation_tuning_candidates",
        "plan_generation_tuning_runs",
        "plan_generation_tuning_config_versions",
        "signal_gating_tuning_runs",
        "runs",
        "worker_heartbeats",
        "historical_market_bars",
    ]

    try:
        print("Starting data reset...")
        # Use TRUNCATE with CASCADE for Postgres, or individual DELETE for SQLite
        if "postgresql" in settings.database_url:
            for table in tables_to_clear:
                print(f"Truncating {table}...")
                session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;"))
        else:
            # Fallback for SQLite (development)
            for table in reversed(tables_to_clear):
                print(f"Deleting from {table}...")
                session.execute(text(f"DELETE FROM {table};"))
                session.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}';"))

        session.commit()
        print("Successfully cleared historical data and signals.")
        print("Note: Watchlists, Jobs, App Settings, and Credentials have been PRESERVED.")
    except Exception as e:
        session.rollback()
        print(f"Error resetting database: {e}")
        sys.exit(1)
    finally:
        session.close()

if __name__ == "__main__":
    confirm = input("This will PERMANENTLY DELETE all ticker signals, plans, outcomes, and market data. Continue? (y/N): ")
    if confirm.lower() == 'y':
        reset_database()
    else:
        print("Aborted.")
