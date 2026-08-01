import asyncio
import logging
from src.engines.mtf_engine import MTFEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def main():
    print("Initializing MTF Engine...")
    mtf_engine = MTFEngine()
    
    print("Starting historical MTF sync for the past 1 year (365 days)...")
    await mtf_engine.sync_mtf_history(days_lookback=365)
    
    from src.managers.database_manager import db_manager
    with db_manager.get_market_conn(read_only=True) as conn:
        summary_count = conn.execute("SELECT count(*) FROM mtf_summary").fetchone()[0]
        candles_count = conn.execute("SELECT count(*) FROM mtf_candles").fetchone()[0]
        uniq_symbols = conn.execute("SELECT count(distinct symbol) FROM mtf_candles").fetchone()[0]
        
    print(f"MTF Sync Complete!")
    print(f"Total summary records: {summary_count}")
    print(f"Total candle records: {candles_count} across {uniq_symbols} distinct symbols.")

if __name__ == "__main__":
    asyncio.run(main())
