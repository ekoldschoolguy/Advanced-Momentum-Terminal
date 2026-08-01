import asyncio
import os
import logging
from datetime import datetime, timedelta
from src.auth.auth_manager import AuthManager
from src.engines.historical_engine import HistoricalEngine
from src.managers.universe_manager import UniverseManager
from src.managers.database_manager import db_manager

# Set up logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def main():
    print("Initializing Engines...")
    auth_manager = AuthManager(env_file=".env", token_file="token.json")
    
    # Initialize HistoricalEngine (which handles DB operations)
    historical_engine = HistoricalEngine(auth_manager=auth_manager)
    
    print("Loading universes...")
    universe_manager = UniverseManager()
    universe_manager.load_all()
    
    # Collect unique symbols
    unique_symbols = set()
    for _, symbols in universe_manager.universe_symbols.items():
        unique_symbols.update(symbols)
    
    symbols_list = sorted(list(unique_symbols))
    print(f"Found {len(symbols_list)} unique symbols across all universes.")
    
    # Past 1 year dates
    to_date = datetime.now().strftime("%d-%m-%Y")
    from_date = (datetime.now() - timedelta(days=365)).strftime("%d-%m-%Y")
    print(f"Syncing delivery data from {from_date} to {to_date}...")
    
    # Run the sync
    await historical_engine.sync_delivery_data(
        symbols=symbols_list,
        from_date=from_date,
        to_date=to_date
    )
    
    # Report results
    with db_manager.get_market_conn(read_only=True) as conn:
        count = conn.execute("SELECT count(*) FROM delivery_candles").fetchone()[0]
        distinct_syms = conn.execute("SELECT count(distinct symbol) FROM delivery_candles").fetchone()[0]
    print(f"Delivery sync complete! Total records in DB: {count} across {distinct_syms} symbols.")

if __name__ == "__main__":
    asyncio.run(main())
