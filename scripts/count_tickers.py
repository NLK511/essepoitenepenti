import os
import sys
from sqlalchemy import create_engine, text

# Add the src directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from trade_proposer_app.config import settings

def count_tickers():
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        tickers = list(set([
            t.strip().upper() 
            for r in conn.execute(text('SELECT tickers_csv FROM watchlists')) 
            for t in r[0].split(',') if t.strip()
        ]))
        print(f"Total unique tickers: {len(tickers)}")

if __name__ == "__main__":
    count_tickers()
