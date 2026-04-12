import os
import sys
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the src directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from trade_proposer_app.config import settings
from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.persistence.models import (
    JobRecord, 
    WatchlistRecord, 
    MacroContextSnapshotRecord, 
    IndustryContextSnapshotRecord
)
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository

def simulate_week():
    print(f"Connecting to database...")
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # 1. Create Mock Context Snapshots for the week
    # This allows the proposal generation to proceed without actual historical news
    start_date = datetime(2026, 4, 6, tzinfo=timezone.utc)
    end_date = datetime(2026, 4, 10, tzinfo=timezone.utc)
    
    current_date = start_date
    while current_date <= end_date:
        print(f"Creating mock context for {current_date.date()}...")
        
        # Macro Snapshot
        macro = MacroContextSnapshotRecord(
            computed_at=current_date,
            expires_at=current_date + timedelta(days=1),
            status="ok",
            summary_text="Simulation: Neutral global macro regime.",
            saliency_score=50.0,
            confidence_percent=80.0,
            active_themes_json="[]",
            regime_tags_json='["neutral"]',
            warnings_json="[]",
            missing_inputs_json="[]",
            source_breakdown_json="{}",
            metadata_json='{"simulation": true}'
        )
        session.add(macro)
        
        # Industry Snapshots (Major sectors)
        industries = ["tech", "finance", "healthcare", "consumer", "industrials", "energy", "materials"]
        for ind in industries:
            industry = IndustryContextSnapshotRecord(
                industry_key=ind,
                industry_label=ind.capitalize(),
                computed_at=current_date,
                expires_at=current_date + timedelta(days=1),
                status="ok",
                summary_text=f"Simulation: Neutral {ind} industry outlook.",
                direction="neutral",
                saliency_score=50.0,
                confidence_percent=80.0,
                active_drivers_json="[]",
                linked_macro_themes_json="[]",
                linked_industry_themes_json="[]",
                warnings_json="[]",
                missing_inputs_json="[]",
                source_breakdown_json="{}",
                metadata_json='{"simulation": true}'
            )
            session.add(industry)
        
        current_date += timedelta(days=1)
    
    session.commit()
    print("Context snapshots created.")

    # 2. Enqueue Proposal Generation jobs
    job_repo = JobRepository(session)
    run_repo = RunRepository(session)
    job_service = JobExecutionService(jobs=job_repo, runs=run_repo)
    
    # Get all regular regional jobs
    # Use simpler names we just renamed to
    jobs = session.query(JobRecord).filter(
        JobRecord.job_type == JobType.PROPOSAL_GENERATION.value
    ).all()
    
    total_enqueued = 0
    current_date = start_date
    while current_date <= end_date:
        for job in jobs:
            if not job.schedule:
                continue
                
            # Calculate the specific time for this job on this day
            parts = job.schedule.split()
            minute = int(parts[0])
            hour = int(parts[1])
            
            scheduled_time = datetime.combine(
                current_date.date(), 
                datetime.min.time().replace(hour=hour, minute=minute),
                tzinfo=timezone.utc
            )
            
            print(f"Enqueuing {job.name} for {scheduled_time.isoformat()}...")
            job_service.enqueue_job(job.id, scheduled_for=scheduled_time)
            total_enqueued += 1
            
        current_date += timedelta(days=1)

    session.commit()
    print(f"Enqueued {total_enqueued} simulation runs.")
    session.close()

if __name__ == "__main__":
    simulate_week()
