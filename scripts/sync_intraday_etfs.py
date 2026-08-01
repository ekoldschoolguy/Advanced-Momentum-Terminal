import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from datetime import datetime, timedelta
import urllib.parse
import json
import logging
import httpx
import polars as pl
from src.auth.auth_manager import AuthManager
from src.managers.database_manager import db_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def setup_db():
    with db_manager.get_intraday_conn(read_only=False) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS minute_candles (
                instrument_key VARCHAR,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                open_interest BIGINT,
                PRIMARY KEY (instrument_key, timestamp)
            )
        """)

def store_candles(df: pl.DataFrame):
    if df is None or df.is_empty():
        return
    with db_manager.get_intraday_conn(read_only=False) as conn:
        conn.execute("""
            INSERT INTO minute_candles (instrument_key, timestamp, open, high, low, close, volume, open_interest)
            SELECT instrument_key, timestamp, open, high, low, close, volume, open_interest FROM df 
            ON CONFLICT (instrument_key, timestamp) 
            DO UPDATE SET 
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                open_interest = EXCLUDED.open_interest
        """)

def get_db_bounds(instrument_key: str):
    with db_manager.get_intraday_conn(read_only=True) as conn:
        res = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM minute_candles WHERE instrument_key = ?",
            [instrument_key]
        ).fetchone()
        return res[0], res[1]

async def fetch_chunk(client: httpx.AsyncClient, headers: dict, instrument_key: str, start_dt: datetime, end_dt: datetime) -> pl.DataFrame:
    encoded_key = urllib.parse.quote(instrument_key)
    # Upstox V3 historical minute candles endpoint
    url = f"https://api.upstox.com/v3/historical-candle/{encoded_key}/minutes/1/{end_dt.strftime('%Y-%m-%d')}/{start_dt.strftime('%Y-%m-%d')}"
    
    try:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json().get("data", {}).get("candles", [])
            if not data:
                return pl.DataFrame()
                
            schema = {
                "timestamp": pl.String,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "open_interest": pl.Int64
            }
            df = pl.DataFrame(data, schema=schema, orient="row")
            df = df.with_columns(
                pl.col("timestamp").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").dt.convert_time_zone("Asia/Kolkata").dt.replace_time_zone(None)
            )
            df = df.with_columns(pl.lit(instrument_key).alias("instrument_key"))
            return df
        elif res.status_code == 400 and "Invalid date range" in res.text:
            logger.error(f"Invalid date range error for {instrument_key}. Chunk too large?")
            return None
        else:
            logger.error(f"API Error {res.status_code} for {instrument_key}: {res.text}")
            return None
    except Exception as e:
        logger.error(f"Network error: {e}")
        return None

async def sync_etf(client, headers, instrument_key, symbol):
    logger.info(f"--- Starting sync for {symbol} ({instrument_key}) ---")
    min_dt, max_dt = get_db_bounds(instrument_key)
    
    now = datetime.now()
    
    # 1. Forward Fill (if we have data, fetch from max_dt to now)
    if max_dt:
        if (now - max_dt).days > 0:
            logger.info(f"[{symbol}] Forward filling from {max_dt.date()} to {now.date()}")
            current_start = max_dt
            while current_start < now:
                current_end = min(current_start + timedelta(days=25), now)
                df = await fetch_chunk(client, headers, instrument_key, current_start, current_end)
                if df is not None and not df.is_empty():
                    store_candles(df)
                    logger.info(f"[{symbol}] Saved {len(df)} forward candles ({current_start.date()} to {current_end.date()})")
                await asyncio.sleep(1.0)
                current_start = current_end + timedelta(days=1)
    
    # 2. Backward Fill (fetch from min_dt backwards)
    current_end = min_dt if min_dt else now
    
    while True:
        current_start = current_end - timedelta(days=25)
        logger.info(f"[{symbol}] Fetching backwards: {current_start.date()} to {current_end.date()}")
        
        df = await fetch_chunk(client, headers, instrument_key, current_start, current_end)
        
        if df is None:
            # Error occurred (rate limit, etc.), sleep a bit longer and retry or break
            logger.warning(f"[{symbol}] Error fetching chunk. Stopping backward fill for now.")
            break
            
        if df.is_empty():
            logger.info(f"[{symbol}] No data returned for {current_start.date()} to {current_end.date()}. Assuming start of history.")
            break
            
        store_candles(df)
        logger.info(f"[{symbol}] Saved {len(df)} candles.")
        
        current_end = current_start - timedelta(days=1)
        await asyncio.sleep(1.0) # Strict rate limiting (Max 2000 per 30m)

async def main():
    setup_db()
    
    auth = AuthManager()
    if not auth.is_token_valid():
        logger.error("Upstox auth token is invalid or expired. Please login via UI.")
        return
        
    headers = auth.get_headers()
    
    # Load ETFs
    try:
        with open("data/equities_master.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("equities_master.json not found. Please sync master data first.")
        return
        
    etfs = []
    for x in data:
        name = x.get("name", "").upper()
        symbol = x.get("trading_symbol", "").upper()
        if "ETF" in name or "ETF" in symbol or x.get("instrument_type") == "ETF":
            etfs.append(x)
            
    # Also add Zerodha CASE ETFs specifically if they don't have ETF in name
    case_etfs = ["LIQUIDCASE", "GOLDCASE", "SILVERCASE", "MID150CASE", "TOP100CASE", "NIFTYCASE", "LTGILTCASE", "SML100CASE"]
    for x in data:
        symbol = x.get("trading_symbol", "").upper()
        if symbol in case_etfs and x not in etfs:
            etfs.append(x)
            
    logger.info(f"Found {len(etfs)} ETFs to sync.")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for idx, etf in enumerate(etfs, 1):
            logger.info(f"Processing {idx}/{len(etfs)}")
            await sync_etf(client, headers, etf["instrument_key"], etf["trading_symbol"])
            
    logger.info("Intraday ETF sync complete!")

if __name__ == "__main__":
    asyncio.run(main())
