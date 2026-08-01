import os
import httpx
import logging
import urllib.parse
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

import polars as pl
import duckdb

from src.managers.auth_manager import AuthManager
from src.engines.search_engine import SearchEngine

logger = logging.getLogger(__name__)

from src.managers.database_manager import db_manager

class HistoricalEngine:
    """
    Engine to download and manage historical OHLCV data using Upstox V3 API.
    Utilizes Polars and DuckDB, with strict rate-limiting for bulk downloads.
    """
    
    def __init__(self, auth_manager: AuthManager, base_dir: str = "database"):
        self.auth_manager = auth_manager
        self.base_url = "https://api.upstox.com/v3"
        self.base_dir = base_dir
        
        # State variables for background tasks
        self.is_syncing = False
        self.progress = {}
        
        self._setup_db()

    def _setup_db(self):
        """Initializes the database tables if they don't exist."""
        with db_manager.get_market_conn(read_only=False) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_candles (
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delivery_candles (
                    symbol VARCHAR,
                    timestamp TIMESTAMP,
                    series VARCHAR,
                    traded_qty BIGINT,
                    deliverable_qty BIGINT,
                    delivery_pct DOUBLE,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
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

    def get_nse_session(self):
        if not hasattr(self, '_nse_session') or self._nse_session is None:
            import requests
            session = requests.Session()
            default_header = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            }
            try:
                logger.info("Establishing fresh NSE session/cookies...")
                session.get("https://www.nseindia.com/", headers=default_header, timeout=10)
                self._nse_session = session
            except Exception as e:
                logger.error(f"Error establishing NSE session: {e}")
                return None
        return self._nse_session

    def fetch_delivery_data(self, symbol: str, from_date: str, to_date: str):
        """
        Fetch historical delivery data using requests session from NSE India.
        from_date and to_date should be in dd-mm-yyyy format.
        """
        import pandas as pd
        from io import BytesIO
        
        url = "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData"
        session = self.get_nse_session()
        if not session:
            logger.error("No NSE session available.")
            return None
            
        header = {
            "referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        }
        
        try:
            params = {
                "from": from_date,
                "to": to_date,
                "symbol": symbol,
                "type": "deliverable",
                "series": "ALL",
                "csv": "true"
            }
            res = session.get(url, headers=header, params=params, timeout=15)
            if res.status_code == 200:
                df = pd.read_csv(BytesIO(res.content))
                return df
            elif res.status_code in [401, 403]:
                logger.warning(f"NSE Session expired or rate limited (status {res.status_code}). Resetting session...")
                self._nse_session = None
                session = self.get_nse_session()
                if session:
                    res = session.get(url, headers=header, params=params, timeout=15)
                    if res.status_code == 200:
                        return pd.read_csv(BytesIO(res.content))
                logger.error(f"Failed to fetch delivery data for {symbol} after session reset: {res.status_code}")
                return None
            else:
                logger.error(f"Failed to fetch delivery data for {symbol}: {res.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching delivery data for {symbol}: {e}")
            return None

    def store_delivery_data(self, df):
        """Inserts a pandas DataFrame of delivery data into DuckDB using Upsert."""
        if df is None or df.empty:
            return
        import pandas as pd
        try:
            df_clean = df.copy()
            df_clean.columns = [c.replace('\ufeff', '').strip() for c in df_clean.columns]
            
            rename_map = {
                'Symbol': 'symbol',
                'Series': 'series',
                'Date': 'date_str',
                'Traded Qty': 'traded_qty_str',
                'Deliverable Qty': 'deliverable_qty_str',
                '% Dly Qt to Traded Qty': 'delivery_pct'
            }
            for raw_col in list(df_clean.columns):
                clean_c = raw_col.strip()
                for k, v in rename_map.items():
                    if clean_c == k:
                        df_clean.rename(columns={raw_col: v}, inplace=True)
            
            df_clean['timestamp'] = pd.to_datetime(df_clean['date_str'], format='mixed')
            
            for col in ['traded_qty_str', 'deliverable_qty_str']:
                if col in df_clean.columns:
                    df_clean[col] = df_clean[col].astype(str).str.replace(',', '', regex=False)
                    df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0).astype('int64')
            
            df_clean.rename(columns={'traded_qty_str': 'traded_qty', 'deliverable_qty_str': 'deliverable_qty'}, inplace=True)
            
            if 'delivery_pct' in df_clean.columns:
                df_clean['delivery_pct'] = pd.to_numeric(df_clean['delivery_pct'], errors='coerce').fillna(0.0)
            
            final_cols = ['symbol', 'timestamp', 'series', 'traded_qty', 'deliverable_qty', 'delivery_pct']
            df_clean = df_clean[final_cols]
            
            with db_manager.get_market_conn(read_only=False) as conn:
                conn.execute("""
                    INSERT INTO delivery_candles (symbol, timestamp, series, traded_qty, deliverable_qty, delivery_pct)
                    SELECT symbol, timestamp, series, traded_qty, deliverable_qty, delivery_pct FROM df_clean 
                    ON CONFLICT (symbol, timestamp) 
                    DO UPDATE SET 
                        series = EXCLUDED.series,
                        traded_qty = EXCLUDED.traded_qty,
                        deliverable_qty = EXCLUDED.deliverable_qty,
                        delivery_pct = EXCLUDED.delivery_pct
                """)
        except Exception as e:
            logger.error(f"Error storing delivery data: {e}")

    def get_delivery_data_from_db(self, symbol: str) -> pl.DataFrame:
        """Query DuckDB and return a Polars DataFrame of delivery data."""
        with db_manager.get_market_conn(read_only=True) as conn:
            table_exists = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'delivery_candles'"
            ).fetchone()[0] > 0
            if not table_exists:
                return pl.DataFrame()
            return conn.execute(
                "SELECT * FROM delivery_candles WHERE symbol = ? ORDER BY timestamp", 
                [symbol]
            ).pl()

    def get_latest_delivery_pcts(self) -> Dict[str, float]:
        """Returns a dict of symbol -> latest delivery percentage."""
        with db_manager.get_market_conn(read_only=True) as conn:
            table_exists = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'delivery_candles'"
            ).fetchone()[0] > 0
            if not table_exists:
                return {}
            
            res = conn.execute("""
                SELECT symbol, delivery_pct 
                FROM delivery_candles 
                QUALIFY ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY timestamp DESC) = 1
            """).fetchall()
            return {row[0]: row[1] for row in res}

    async def sync_delivery_data(self, symbols: List[str], from_date: str = None, to_date: str = None):
        """
        Background task to sync delivery data for a list of symbols.
        Uses incremental sync to avoid fetching duplicate historical data.
        """
        if self.is_syncing and "delivery" in self.progress:
            return
            
        self.is_syncing = True
        self.progress["delivery"] = {"total": len(symbols), "completed": 0, "errors": 0, "symbol": ""}
        
        if not to_date:
            to_date = datetime.now().strftime("%d-%m-%Y")
        if not from_date:
            from_date = (datetime.now() - timedelta(days=365)).strftime("%d-%m-%Y")
            
        logger.info(f"Starting delivery sync for {len(symbols)} symbols...")
        
        latest_dates = {}
        try:
            with db_manager.get_market_conn(read_only=True) as conn:
                table_exists = conn.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name = 'delivery_candles'"
                ).fetchone()[0] > 0
                if table_exists:
                    latest_df = conn.execute(
                        "SELECT symbol, MAX(timestamp) as last_date FROM delivery_candles GROUP BY symbol"
                    ).pl()
                    latest_dates = dict(zip(latest_df['symbol'], latest_df['last_date']))
        except Exception as e:
            logger.error(f"Error checking latest delivery dates: {e}")
            
        import pandas as pd
        import asyncio
        
        try:
            loop = asyncio.get_event_loop()
            sem = asyncio.Semaphore(1)
            
            async def process_delivery(symbol):
                async with sem:
                    if not self.is_syncing:
                        return
                        
                    self.progress["delivery"]["symbol"] = f"Delivery: {symbol}"
                    
                    symbol_from_date = from_date
                    if symbol in latest_dates and latest_dates[symbol]:
                        last_date = latest_dates[symbol]
                        if isinstance(last_date, str):
                            last_dt = pd.to_datetime(last_date)
                        else:
                            last_dt = last_date
                        
                        if (datetime.now() - last_dt).days <= 1:
                            self.progress["delivery"]["completed"] += 1
                            return
                        
                        symbol_from_date = (last_dt + timedelta(days=1)).strftime("%d-%m-%Y")
                    
                    df = await loop.run_in_executor(
                        None, 
                        self.fetch_delivery_data, 
                        symbol, 
                        symbol_from_date, 
                        to_date
                    )
                    
                    if df is not None and not df.empty:
                        async with db_manager.market_write_lock:
                            await loop.run_in_executor(None, self.store_delivery_data, df)
                    else:
                        self.progress["delivery"]["errors"] += 1
                        
                    self.progress["delivery"]["completed"] += 1
                    await asyncio.sleep(1.0)

            tasks = [asyncio.create_task(process_delivery(sym)) for sym in symbols]
            await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Delivery sync encountered error: {e}")
        finally:
            self.is_syncing = False
            logger.info("Delivery sync finished.")

    async def fetch_historical_data(
        self, 
        instrument_key: str, 
        from_date: str, 
        to_date: str, 
        interval: str = "days", 
        interval_value: int = 1
    ) -> Optional[pl.DataFrame]:
        """
        Fetches historical data for an instrument and returns a Polars DataFrame.
        Automatically chunks requests if the date range exceeds 10 years to prevent UDAPI1148 errors.
        """
        if not self.auth_manager.is_token_valid():
            logger.error("Not authenticated. Cannot fetch historical data.")
            return None

        start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
        
        if start_date > end_date:
            logger.error("from_date cannot be greater than to_date")
            return None

        # Upstox strictly limits date ranges per request. 
        # Using 3650 days (10 years) as the maximum safe chunk size.
        MAX_DAYS = 3650
        
        all_dfs = []
        current_start = start_date
        
        encoded_key = urllib.parse.quote(instrument_key)
        headers = self.auth_manager.get_headers()
        
        has_error = False
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=MAX_DAYS), end_date)
                
                url = f"{self.base_url}/historical-candle/{encoded_key}/{interval}/{interval_value}/{current_end.strftime('%Y-%m-%d')}/{current_start.strftime('%Y-%m-%d')}"
                
                try:
                    response = await client.get(url, headers=headers)
                    
                    if response.status_code == 200:
                        data = response.json()
                        candles = data.get("data", {}).get("candles", [])
                        
                        if candles:
                            schema = {
                                "timestamp": pl.String,
                                "open": pl.Float64,
                                "high": pl.Float64,
                                "low": pl.Float64,
                                "close": pl.Float64,
                                "volume": pl.Int64,
                                "open_interest": pl.Int64
                            }
                            df = pl.DataFrame(candles, schema=schema, orient="row")
                            all_dfs.append(df)
                    else:
                        logger.error(f"Failed to fetch {instrument_key}: {response.status_code} - {response.text}")
                        has_error = True
                        break
                except Exception as e:
                    logger.error(f"Network error while fetching {instrument_key}: {e}")
                    has_error = True
                    break
                
                current_start = current_end + timedelta(days=1)
                
                # Rate limit safety between chunks
                if current_start <= end_date:
                    await asyncio.sleep(1.0)
                    
        if not all_dfs:
            return None if has_error else pl.DataFrame()
            
        final_df = pl.concat(all_dfs)
        final_df = final_df.with_columns(
            pl.col("timestamp").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").dt.convert_time_zone("Asia/Kolkata").dt.replace_time_zone(None)
        )
        final_df = final_df.with_columns(
            pl.lit(instrument_key).alias("instrument_key")
        )
        
        return final_df

    def store_data_to_db(self, df: pl.DataFrame):
        """Inserts a Polars DataFrame directly into DuckDB using Upsert."""
        if df is None or df.is_empty():
            return
        try:
            with db_manager.get_market_conn(read_only=False) as conn:
                conn.execute("""
                    INSERT INTO daily_candles (instrument_key, timestamp, open, high, low, close, volume, open_interest)
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
        except Exception as e:
            logger.error(f"Error storing data to DB: {e}")

    def get_data_from_db(self, instrument_key: str) -> pl.DataFrame:
        """Query DuckDB and return a Polars DataFrame."""
        with db_manager.get_market_conn(read_only=True) as conn:
            return conn.execute(
                "SELECT * FROM daily_candles WHERE instrument_key = ? ORDER BY timestamp", 
                [instrument_key]
            ).pl()
        
    def get_batch_data_from_db(self, instrument_keys: List[str]) -> pl.DataFrame:
        """Query DuckDB for multiple instrument keys and return a Polars DataFrame."""
        if not instrument_keys:
            return pl.DataFrame()
        placeholders = ",".join(["?"] * len(instrument_keys))
        with db_manager.get_market_conn(read_only=True) as conn:
            return conn.execute(
                f"SELECT * FROM daily_candles WHERE instrument_key IN ({placeholders}) ORDER BY timestamp",
                instrument_keys
            ).pl()
        

    async def sync_all_data(self, search_engine: SearchEngine, from_date: str, to_date: str, target: str = "equities"):
        """
        Background task to sync all NSE equities or indices.
        Strictly adheres to rate limits: 2000 req / 30 mins (approx 1.11 req/sec).
        We will limit to 1 request every 1.0 seconds to be extremely safe.
        """
        if self.is_syncing and target in self.progress:
            return
            
        if not search_engine.is_loaded:
            logger.error("Equity engine not loaded. Cannot sync.")
            return

        # Filter based on target
        if target == "indices":
            items_to_sync = [eq for eq in search_engine.equities if eq.get('segment') == 'NSE_INDEX']
        else:
            items_to_sync = [eq for eq in search_engine.equities if eq.get('exchange') == 'NSE' and eq.get('instrument_type') == 'EQ']

        
        self.is_syncing = True
        self.progress[target] = {"total": len(items_to_sync), "completed": 0, "errors": 0, "symbol": ""}
        
        logger.info(f"Starting bulk sync of {len(items_to_sync)} {target}...")
        
        # --- Smart Resume Logic ---
        # Get the latest timestamp for all stored instruments
        try:
            with db_manager.get_market_conn() as conn:
                latest_dates_df = conn.execute(
                    "SELECT instrument_key, MAX(timestamp) as last_date FROM daily_candles GROUP BY instrument_key"
                ).pl()
            latest_dates = dict(zip(latest_dates_df['instrument_key'], latest_dates_df['last_date']))
        except Exception as e:
            logger.error(f"Error fetching latest dates for smart resume: {e}")
            latest_dates = {}
            
        target_to_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        try:
            for eq in items_to_sync:
                if not self.is_syncing:
                    break # Cancelled
                    
                instrument_key = eq.get('instrument_key')
                # Check if we already have the data up to the requested to_date
                last_synced_datetime = latest_dates.get(instrument_key)
                
                if last_synced_datetime and last_synced_datetime.date() >= target_to_date:
                    # Smart Resume: Skip this stock as it's already fully synced
                    self.progress[target]["completed"] += 1
                    continue
                
                # If we have some data but need newer data, optimize the from_date
                actual_from_date = from_date
                if last_synced_datetime:
                    actual_from_date = (last_synced_datetime.date() + timedelta(days=1)).strftime("%Y-%m-%d")
                    self.progress[target]["symbol"] = f"{eq.get('trading_symbol', instrument_key)} (Updating from {actual_from_date} to {to_date})"
                else:
                    self.progress[target]["symbol"] = f"{eq.get('trading_symbol', instrument_key)} (Full Sync)"

                    
                df = await self.fetch_historical_data(
                    instrument_key=instrument_key,
                    from_date=actual_from_date,
                    to_date=to_date,
                    interval="days",
                    interval_value=1
                )
                
                if df is not None and not df.is_empty():
                    async with db_manager.market_write_lock:
                        await asyncio.get_event_loop().run_in_executor(None, self.store_data_to_db, df)
                else:
                    self.progress[target]["errors"] += 1
                
                self.progress[target]["completed"] += 1
                
                # Rate Limiting: 1 second sleep ensures max ~1800 requests per 30 mins, 
                # staying well under the 2000 req/30min Upstox limit.
                await asyncio.sleep(1.0)
                
        except Exception as e:
            logger.error(f"Bulk sync encountered an error: {e}")
        finally:
            self.is_syncing = False
            logger.info("Bulk sync finished.")

    def get_sync_progress(self) -> Dict[str, Any]:
        """Returns the aggregated progress of all running bulk downloads"""
        total = sum(p["total"] for p in self.progress.values())
        completed = sum(p["completed"] for p in self.progress.values())
        errors = sum(p["errors"] for p in self.progress.values())
        
        symbols = [p["symbol"] for p in self.progress.values() if p["symbol"]]
        current_symbol = " | ".join(symbols) if symbols else ""
        
        percentage = 0
        if total > 0:
            percentage = round((completed / total) * 100, 2)
            
        return {
            "is_syncing": self.is_syncing,
            "total": total,
            "completed": completed,
            "errors": errors,
            "current_symbol": current_symbol,
            "percentage": percentage
        }

    async def sync_intraday_etfs(self):
        """Background task to sync 1-minute intraday data for ETFs."""
        if self.is_syncing:
            return
            
        self.is_syncing = True
        self.sync_completed = 0
        self.sync_errors = 0
        
        try:
            import json
            with open("data/equities_master.json", "r") as f:
                data = json.load(f)
                
            etfs = []
            case_etfs = ["LIQUIDCASE", "GOLDCASE", "SILVERCASE", "MID150CASE", "TOP100CASE", "NIFTYCASE", "LTGILTCASE", "SML100CASE"]
            for x in data:
                name = x.get("name", "").upper()
                symbol = x.get("trading_symbol", "").upper()
                if "ETF" in name or "ETF" in symbol or x.get("instrument_type") == "ETF" or symbol in case_etfs:
                    if x not in etfs:
                        etfs.append(x)
                        
            self.sync_total = len(etfs)
            logger.info(f"Starting intraday sync for {self.sync_total} ETFs...")
            
            headers = self.auth_manager.get_headers()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                for eq in etfs:
                    if not self.is_syncing:
                        break # user cancelled
                        
                    instrument_key = eq["instrument_key"]
                    symbol = eq["trading_symbol"]
                    
                    # Get DB bounds
                    with db_manager.get_intraday_conn(read_only=True) as conn:
                        res = conn.execute(
                            "SELECT MIN(timestamp), MAX(timestamp) FROM minute_candles WHERE instrument_key = ?",
                            [instrument_key]
                        ).fetchone()
                        min_dt, max_dt = res[0], res[1]
                        
                    now = datetime.now()
                    
                    # Forward Fill
                    if max_dt and (now - max_dt).days > 0:
                        self.sync_current_symbol = f"{symbol} (Forward Fill)"
                        current_start = max_dt
                        while current_start < now and self.is_syncing:
                            current_end = min(current_start + timedelta(days=25), now)
                            df = await self._fetch_minute_chunk(client, headers, instrument_key, current_start, current_end)
                            if df is not None and not df.is_empty():
                                self._store_minute_candles(df)
                            await asyncio.sleep(1.0)
                            current_start = current_end + timedelta(days=1)
                            
                    # Backward Fill
                    current_end = min_dt if min_dt else now
                    self.sync_current_symbol = f"{symbol} (Backward Fill)"
                    
                    while self.is_syncing:
                        current_start = current_end - timedelta(days=25)
                        
                        df = await self._fetch_minute_chunk(client, headers, instrument_key, current_start, current_end)
                        if df is None:
                            self.sync_errors += 1
                            break # Error
                        if df.is_empty():
                            break # Reached start of history
                            
                        self._store_minute_candles(df)
                        current_end = current_start - timedelta(days=1)
                        await asyncio.sleep(1.0)
                        
                    self.sync_completed += 1
                    
        except Exception as e:
            logger.error(f"Intraday ETF sync encountered an error: {e}")
        finally:
            self.is_syncing = False
            self.sync_current_symbol = "Intraday ETF Sync Complete!"

    async def _fetch_minute_chunk(self, client, headers, instrument_key, start_dt, end_dt):
        encoded_key = urllib.parse.quote(instrument_key)
        url = f"{self.base_url}/historical-candle/{encoded_key}/minutes/1/{end_dt.strftime('%Y-%m-%d')}/{start_dt.strftime('%Y-%m-%d')}"
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json().get("data", {}).get("candles", [])
                if not data:
                    return pl.DataFrame()
                schema = {
                    "timestamp": pl.String, "open": pl.Float64, "high": pl.Float64,
                    "low": pl.Float64, "close": pl.Float64, "volume": pl.Int64, "open_interest": pl.Int64
                }
                df = pl.DataFrame(data, schema=schema, orient="row")
                df = df.with_columns(
                    pl.col("timestamp").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").dt.convert_time_zone("Asia/Kolkata").dt.replace_time_zone(None),
                    pl.lit(instrument_key).alias("instrument_key")
                )
                return df
            return None
        except Exception as e:
            return None

    def _store_minute_candles(self, df):
        if df is None or df.is_empty(): return
        with db_manager.get_intraday_conn(read_only=False) as conn:
            conn.execute("""
                INSERT INTO minute_candles (instrument_key, timestamp, open, high, low, close, volume, open_interest)
                SELECT instrument_key, timestamp, open, high, low, close, volume, open_interest FROM df 
                ON CONFLICT (instrument_key, timestamp) 
                DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume, open_interest=EXCLUDED.open_interest
            """)
