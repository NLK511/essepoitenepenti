import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add the src directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from trade_proposer_app.config import settings
from trade_proposer_app.services.builders import (
    create_macro_context_refresh_service,
    create_macro_context_service,
    create_industry_context_refresh_service,
    create_industry_context_service,
    create_proposal_service
)
from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.persistence.models import JobRecord
from trade_proposer_app.services.job_execution import JobExecutionService
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository

def reconstruct_context():
    print(f"Connecting to database...")
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Define the range for reconstruction
    start_date = datetime(2026, 4, 6, tzinfo=timezone.utc)
    end_date = datetime(2026, 4, 10, tzinfo=timezone.utc)
    
    print(f"Reconstruction window: {start_date.isoformat()} to {end_date.isoformat()}")
    
    macro_refresh_service = create_macro_context_refresh_service(session)
    macro_context_service = create_macro_context_service(session)
    industry_refresh_service = create_industry_context_refresh_service(session)
    industry_context_service = create_industry_context_service(session)

    current_date = start_date
    while current_date <= end_date:
        snapshot_as_of = current_date.replace(hour=23, minute=59, second=59, microsecond=0)
        print(f"--- Reconstructing context for {snapshot_as_of.isoformat()} ---")
        
        # 1. Macro Context
        print("Refreshing Macro Context...")
        try:
            # Use end-of-day timestamps so each snapshot reflects the full simulated day.
            macro_refresh_result = macro_refresh_service.refresh(as_of=snapshot_as_of)
            macro_payload = macro_refresh_result.get("payload")
            macro_snapshot = macro_context_service.create_from_refresh_payload(macro_payload, request_mode="replay")
            print(f"  Macro Snapshot created: ID={macro_snapshot.id}, Score={macro_snapshot.saliency_score}")
        except Exception as e:
            print(f"  Error refreshing macro context: {e}")

        # 2. Industry Context
        print("Refreshing Industry Contexts...")
        try:
            industry_refresh_payloads = industry_refresh_service.refresh_all(as_of=snapshot_as_of)
            for payload in industry_refresh_payloads:
                industry_snapshot = industry_context_service.create_from_refresh_payload(payload, request_mode="replay")
                print(f"  Industry Snapshot created: {industry_snapshot.industry_label}, ID={industry_snapshot.id}")
        except Exception as e:
            print(f"  Error refreshing industry context: {e}")
        
        current_date += timedelta(days=1)
    
    session.commit()
    print("Context reconstruction complete.")

    # 3. Enqueue Proposal Generation jobs for the week
    print("Enqueuing Proposal Generation jobs...")
    job_repo = JobRepository(session)
    run_repo = RunRepository(session)
    job_service = JobExecutionService(jobs=job_repo, runs=run_repo)
    
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
            # Assuming schedule is 'MM HH * * *'
            parts = job.schedule.split()
            if len(parts) < 2: continue
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
    print(f"Enqueued {total_enqueued} proposal runs.")
    session.close()

if __name__ == "__main__":
    reconstruct_context()
