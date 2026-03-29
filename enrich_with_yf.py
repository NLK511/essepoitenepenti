import json
import time
import yfinance as yf

TAXONOMY_PATH = "src/trade_proposer_app/data/taxonomy/tickers.json"

with open(TAXONOMY_PATH, "r") as f:
    tickers = json.load(f)

unknowns = [t for t, d in tickers.items() if d.get("sector") == "Unknown" or d.get("industry") == "Unknown"]
print(f"Found {len(unknowns)} tickers to enrich.")

if not unknowns:
    print("Nothing to do.")
    exit()

# We do batches of 50 to avoid rate limits
batch_size = 50
for i in range(0, len(unknowns), batch_size):
    batch = unknowns[i:i+batch_size]
    print(f"Processing batch {i//batch_size + 1}: {batch}")
    
    # Use yfinance.Tickers
    tickers_api = yf.Tickers(" ".join(batch))
    
    for ticker_sym in batch:
        try:
            info = tickers_api.tickers[ticker_sym].info
            if not info:
                continue
            
            sector = info.get("sector", "Unknown")
            industry = info.get("industry", "Unknown")
            name = info.get("longName") or info.get("shortName") or ticker_sym
            
            entry = tickers[ticker_sym]
            entry["company_name"] = name
            
            # YFinance returns "Technology" -> map to "Information Technology"
            # YFinance returns "Financial Services" -> map to "Financials"
            if sector == "Technology":
                sector = "Information Technology"
            elif sector == "Financial Services":
                sector = "Financials"
            elif sector == "Healthcare":
                sector = "Health Care"
            elif sector == "Consumer Defensive":
                sector = "Consumer Staples"
            elif sector == "Basic Materials":
                sector = "Materials"
            
            entry["sector"] = sector
            entry["industry"] = industry
            
            # Simple keyword extraction from sector/industry
            if sector != "Unknown":
                if sector.lower() not in entry["themes"]:
                    entry["themes"].append(sector.lower())
                entry["macro_sensitivity"] = ["rates", "gdp"]
                
                # Assign some default exposure channels based on sector
                if sector == "Information Technology":
                    entry["exposure_channels"] = ["tech_capex", "software_spend"]
                elif sector == "Financials":
                    entry["exposure_channels"] = ["yield_curve", "credit_quality"]
                elif sector == "Health Care":
                    entry["exposure_channels"] = ["drug_pricing", "hospital_volumes"]
                elif sector == "Consumer Staples":
                    entry["exposure_channels"] = ["consumer_spending", "input_costs"]
                elif sector == "Consumer Discretionary":
                    entry["exposure_channels"] = ["consumer_spending", "employment"]
                elif sector == "Energy":
                    entry["exposure_channels"] = ["commodity_prices", "geopolitics"]
                elif sector == "Industrials":
                    entry["exposure_channels"] = ["infrastructure_spend", "capex"]
                else:
                    entry["exposure_channels"] = ["general_macro"]
                    
            if industry != "Unknown":
                entry["industry_keywords"].append(industry.lower())
                
        except Exception as e:
            print(f"Failed to fetch {ticker_sym}: {e}")
            
    time.sleep(1) # Be nice to the API

with open(TAXONOMY_PATH, "w") as f:
    json.dump(tickers, f, indent=2)

print("Saved updated taxonomy.")
