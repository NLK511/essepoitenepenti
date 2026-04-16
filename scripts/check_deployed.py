import re

def check_tickers():
    with open('scripts/deploy_watchlists.py', 'r') as f:
        content = f.read()
    
    # Find all ticker lists
    ticker_lists = re.findall(r'"tickers": \[\s*([^\]]+)\]', content, re.DOTALL)
    
    total = 0
    all_tickers = []
    for i, t_list in enumerate(ticker_lists):
        tickers = [t.strip().strip('"') for t in t_list.split(',') if t.strip()]
        print(f"List {i}: {len(tickers)} tickers")
        total += len(tickers)
        all_tickers.extend(tickers)
    
    print(f"Total tickers: {total}")
    
    # Check for duplicates
    seen = set()
    dupes = []
    for t in all_tickers:
        if t in seen:
            dupes.append(t)
        seen.add(t)
    
    if dupes:
        print(f"Duplicates: {dupes}")

if __name__ == "__main__":
    check_tickers()
