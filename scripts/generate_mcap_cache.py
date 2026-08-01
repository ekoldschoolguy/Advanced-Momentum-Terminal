import yfinance as yf
import json
import os
import sys
import time
import random
import concurrent.futures

# Add project root to PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engines.mtf_engine import MTFEngine

def generate():
    engine = MTFEngine()
    mtf_status = engine.get_latest_mtf_status()
    symbols = list(mtf_status.keys())
    
    cache_path = 'data/mcap_cache.json'
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}
            
    print(f"Total MTF Symbols: {len(symbols)}")
    # Treat 0 as missing so we retry fetching them
    missing = [s for s in symbols if s not in cache or cache[s] == 0]
    print(f"Missing or zero in cache: {len(missing)}")
    
    def fetch_mcap(sym):
        max_retries = 3
        base_delay = 1.0
        for attempt in range(max_retries):
            try:
                # Sleep to spread out requests and avoid rate limits
                time.sleep(random.uniform(0.5, 1.5) + (base_delay * attempt))
                tk = yf.Ticker(f"{sym}.NS")
                info = tk.info
                shares = info.get('sharesOutstanding') or info.get('floatShares') or 0
                
                # Fallback to BSE if NSE fails or returns 0
                if shares == 0:
                    tk_bse = yf.Ticker(f"{sym}.BO")
                    info_bse = tk_bse.info
                    shares = info_bse.get('sharesOutstanding') or info_bse.get('floatShares') or 0
                    
                return sym, shares
            except Exception as e:
                print(f"Error fetching {sym} (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return sym, 0
                # Exponential backoff on error
                time.sleep((2 ** attempt) + random.uniform(0, 1))
        
        return sym, 0
            
    if missing:
        # Use lower concurrency to avoid rate limits
        max_threads = 2
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(fetch_mcap, sym): sym for sym in missing}
            
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                sym, shares = future.result()
                
                # Only update if we got a valid number or it wasn't in the cache at all
                if shares > 0 or sym not in cache:
                    cache[sym] = shares
                    
                completed += 1
                
                # Periodically save to avoid losing data if script is killed
                if completed % 20 == 0:
                    print(f"Fetched {completed}/{len(missing)}")
                    with open(cache_path, 'w') as f:
                        json.dump(cache, f)
                        
        # Final save
        with open(cache_path, 'w') as f:
            json.dump(cache, f)
            
    print("Cache generated/updated successfully.")

if __name__ == '__main__':
    generate()
