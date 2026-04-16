import yfinance as yf
from datetime import datetime, timedelta, timezone

end_date = datetime.now(timezone.utc)
start_date = end_date - timedelta(days=6)
start_str = start_date.strftime("%Y-%m-%d")
end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"Testing AAPL from {start_str} to {end_str}")
df = yf.download("AAPL", start=start_str, end=end_str, interval="1m")
print(f"DataFrame shape: {df.shape}")
if not df.empty:
    print(f"Columns: {df.columns}")
    print(df.head())
else:
    print("DataFrame is empty")
