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
    create_industry_context_service
)

def reconstruct_context():
    print(f"Connecting to database...")
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Define the range for reconstruction
    # Adjust these dates to the historical window you want to reconstruct
    # Defaulting to a few days ago to ensure data is available
    end_date = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0) - timedelta(days=2)
    start_date = end_date - timedelta(days=4)
    
    print(f"Reconstruction window: {start_date.isoformat()} to {end_date.isoformat()}")
    
    macro_refresh_service = create_macro_context_refresh_service(session)
    macro_context_service = create_macro_context_service(session)
    industry_refresh_service = create_industry_context_refresh_service(session)
    industry_context_service = create_industry_context_service(session)

    current_date = start_date
    while current_date <= end_date:
        print(f"--- Reconstructing context for {current_date.isoformat()} ---")
        
        # 1. Macro Context
        print("Refreshing Macro Context...")
        try:
            macro_refresh_result = macro_refresh_service.refresh(as_of=current_date)
            macro_payload = macro_refresh_result.get("payload")
            macro_snapshot = macro_context_service.create_from_refresh_payload(macro_payload)
            print(f"  Macro Snapshot created: ID={macro_snapshot.id}, Score={macro_snapshot.saliency_score}")
        except Exception as e:
            print(f"  Error refreshing macro context: {e}")

        # 2. Industry Context
        print("Refreshing Industry Contexts...")
        try:
            industry_refresh_payloads = industry_refresh_service.refresh_all(as_of=current_date)
            for payload in industry_refresh_payloads:
                industry_snapshot = industry_context_service.create_from_refresh_payload(payload)
                print(f"  Industry Snapshot created: {industry_snapshot.industry_label}, ID={industry_snapshot.id}")
        except Exception as e:
            print(f"  Error refreshing industry context: {e}")
        
        current_date += timedelta(days=1)
    
    session.commit()
    print("Reconstruction complete.")
    session.close()

if __name__ == "__main__":
    reconstruct_context()
