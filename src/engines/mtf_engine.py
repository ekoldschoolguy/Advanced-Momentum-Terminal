import os
import logging
import requests
import zipfile
import io
import pandas as pd
import polars as pl
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from src.managers.database_manager import db_manager

logger = logging.getLogger(__name__)

class MTFEngine:
    def __init__(self):
        self.data_dir = "data"
        self.is_syncing = False
        self.sync_total = 0
        self.sync_completed = 0
        self.sync_errors = 0
        self.sync_current_date = ""
        self._nse_session = None
        self.init_db()

    def init_db(self):
        """Creates the DuckDB tables if they do not exist."""
        with db_manager.get_market_conn(read_only=False) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mtf_summary (
                    timestamp TIMESTAMP PRIMARY KEY,
                    fresh_exposure DOUBLE,
                    exposure_liquidated DOUBLE,
                    total_outstanding DOUBLE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mtf_candles (
                    symbol VARCHAR,
                    timestamp TIMESTAMP,
                    qty_financed BIGINT,
                    amt_financed DOUBLE,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)

    def get_nse_session(self):
        if self._nse_session is None:
            session = requests.Session()
            default_header = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            }
            try:
                logger.info("MTFEngine: Establishing NSE session/cookies...")
                session.get("https://www.nseindia.com/", headers=default_header, timeout=10)
                self._nse_session = session
            except Exception as e:
                logger.error(f"MTFEngine: Error establishing NSE session: {e}")
                return None
        return self._nse_session

    def fetch_mtf_data_for_date(self, date_dt: datetime) -> Optional[Dict]:
        """
        Downloads the MTF ZIP file for a given datetime and parses both the summary and details.
        """
        session = self.get_nse_session()
        if not session:
            return None

        date_url = date_dt.strftime("%d%m%y")
        date_display = date_dt.strftime("%d-%b-%Y")
        url = f"https://nsearchives.nseindia.com/content/equities/mrg_trading_{date_url}.zip"
        
        header = {
            "referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        }

        try:
            res = session.get(url, headers=header, timeout=15)
            if res.status_code == 404:
                return None
            if res.status_code in [401, 403]:
                logger.warning(f"MTFEngine: Session expired (status {res.status_code}). Resetting session...")
                self._nse_session = None
                session = self.get_nse_session()
                if session:
                    res = session.get(url, headers=header, timeout=15)
                    if res.status_code == 404:
                        return None
            
            res.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                csv_filenames = [f for f in z.namelist() if f.lower().endswith('.csv')]
                if not csv_filenames:
                    return None
                csv_filename = csv_filenames[0]
                with z.open(csv_filename) as f:
                    content = f.read()

                    # Part 1: Summary parsing
                    df_summary = pd.read_csv(io.BytesIO(content), header=None, nrows=20)
                    df_summary[1] = df_summary[1].astype(str).str.strip()

                    def get_val(keyword):
                        row = df_summary[df_summary[1].str.contains(keyword, na=False, case=False)]
                        if not row.empty:
                            val_str = str(row.iloc[0, 2]).replace(',', '').strip()
                            try:
                                return float(val_str)
                            except ValueError:
                                return 0.0
                        return 0.0

                    summary_data = {
                        'fresh_exposure': get_val("Fresh Exposure"),
                        'exposure_liquidated': get_val("Exposure liquidated"),
                        'total_outstanding': get_val("Net scripwise outstanding")
                    }

                    # Part 2: Scripwise Details parsing
                    csv_text = content.decode('utf-8', errors='ignore').splitlines()
                    header_idx = -1
                    for idx, line in enumerate(csv_text):
                        if "Symbol" in line and "Qty" in line:
                            header_idx = idx
                            break
                    
                    scrip_rows = []
                    if header_idx != -1:
                        df_details = pd.read_csv(io.BytesIO(content), skiprows=header_idx)
                        df_details.columns = [c.strip() for c in df_details.columns]
                        col_symbol = next((c for c in df_details.columns if "Symbol" in c), None)
                        col_amt = next((c for c in df_details.columns if "Amt" in c and "Fin" in c), None)
                        col_qty = next((c for c in df_details.columns if "Qty" in c and "Fin" in c), None)

                        if col_symbol and col_amt and col_qty:
                            df_details[col_symbol] = df_details[col_symbol].astype(str).str.strip()
                            for col in [col_amt, col_qty]:
                                df_details[col] = df_details[col].astype(str).str.replace(',', '', regex=False)
                                df_details[col] = pd.to_numeric(df_details[col], errors='coerce').fillna(0)

                            for _, row in df_details.iterrows():
                                sym = row[col_symbol]
                                if sym and not pd.isna(sym) and sym != "nan":
                                    scrip_rows.append({
                                        'symbol': sym,
                                        'qty_financed': int(row[col_qty]),
                                        'amt_financed': float(row[col_amt]) # in Rs. Lakhs
                                    })

                    return {
                        'summary': summary_data,
                        'details': scrip_rows
                    }
        except zipfile.BadZipFile:
            logger.warning(f"MTFEngine: MTF data not available for {date_display} (BadZipFile, maybe WAF block)")
            return None
        except requests.exceptions.HTTPError as e:
            logger.warning(f"MTFEngine: HTTP Error for {date_display}: {e}")
            return None
        except Exception as e:
            logger.error(f"MTFEngine: Error parsing MTF data for date {date_display}: {e}")
            return None

    def store_mtf_data(self, date_dt: datetime, data: Dict):
        """Stores the parsed MTF summary and details inside DuckDB using Upsert."""
        if not data:
            return

        ts_str = date_dt.strftime("%Y-%m-%d 00:00:00")
        
        # 1. Store Summary
        summary = data['summary']
        df_summary = pd.DataFrame([{
            'timestamp': ts_str,
            'fresh_exposure': summary['fresh_exposure'],
            'exposure_liquidated': summary['exposure_liquidated'],
            'total_outstanding': summary['total_outstanding']
        }])
        df_summary['timestamp'] = pd.to_datetime(df_summary['timestamp'])

        # 2. Store Details
        details = data['details']
        if details:
            df_details = pd.DataFrame(details)
            df_details['timestamp'] = pd.to_datetime(ts_str)
            df_details = df_details[['symbol', 'timestamp', 'qty_financed', 'amt_financed']]
        else:
            df_details = pd.DataFrame(columns=['symbol', 'timestamp', 'qty_financed', 'amt_financed'])

        # Write transactionally
        with db_manager.get_market_conn(read_only=False) as conn:
            # Upsert Summary
            conn.execute("""
                INSERT INTO mtf_summary (timestamp, fresh_exposure, exposure_liquidated, total_outstanding)
                SELECT timestamp, fresh_exposure, exposure_liquidated, total_outstanding FROM df_summary
                ON CONFLICT (timestamp) 
                DO UPDATE SET 
                    fresh_exposure = EXCLUDED.fresh_exposure,
                    exposure_liquidated = EXCLUDED.exposure_liquidated,
                    total_outstanding = EXCLUDED.total_outstanding
            """)
            
            # Upsert Details
            if not df_details.empty:
                conn.execute("""
                    INSERT INTO mtf_candles (symbol, timestamp, qty_financed, amt_financed)
                    SELECT symbol, timestamp, qty_financed, amt_financed FROM df_details
                    ON CONFLICT (symbol, timestamp) 
                    DO UPDATE SET 
                        qty_financed = EXCLUDED.qty_financed,
                        amt_financed = EXCLUDED.amt_financed
                """)

    async def sync_mtf_history(self, days_lookback: int = 365):
        """Runs historical MTF sync for the past days_lookback days in the background."""
        if self.is_syncing:
            logger.info("MTFEngine: Sync already in progress.")
            return

        self.is_syncing = True
        self.sync_completed = 0
        self.sync_errors = 0
        
        # Work out dates to check
        dates_to_sync = []
        today = datetime.now()
        for i in range(days_lookback):
            check_date = today - timedelta(days=i)
            if check_date.weekday() < 5 and check_date.date() < today.date():
                dates_to_sync.append(check_date)
        
        self.sync_total = len(dates_to_sync)
        logger.info(f"MTFEngine: Starting historical sync for {self.sync_total} dates...")

        import asyncio

        # Check existing dates in DB to avoid duplicate fetching
        existing_dates = set()
        try:
            with db_manager.get_market_conn(read_only=True) as conn:
                dates_df = conn.execute("SELECT DISTINCT timestamp FROM mtf_summary").pl()
                if not dates_df.is_empty():
                    existing_dates = {t.date() for t in dates_df['timestamp']}
        except Exception as e:
            logger.error(f"MTFEngine: Error fetching existing mtf dates: {e}")

        try:
            loop = asyncio.get_event_loop()
            sem = asyncio.Semaphore(1)

            async def process_date(date_dt):
                async with sem:
                    if not self.is_syncing:
                        return
                    self.sync_current_date = date_dt.strftime("%d-%b-%Y")
                    if date_dt.date() in existing_dates:
                        self.sync_completed += 1
                        return

                    logger.info(f"MTFEngine: Syncing MTF for {self.sync_current_date}...")
                    
                    data = await loop.run_in_executor(None, self.fetch_mtf_data_for_date, date_dt)
                    if data:
                        async with db_manager.market_write_lock:
                            await loop.run_in_executor(None, self.store_mtf_data, date_dt, data)
                    
                    self.sync_completed += 1
                    await asyncio.sleep(1.0)

            tasks = [asyncio.create_task(process_date(dt)) for dt in dates_to_sync]
            await asyncio.gather(*tasks)
            
        except Exception as e:
            logger.error(f"MTFEngine: Sync encountered critical error: {e}")
        finally:
            self.is_syncing = False
            logger.info("MTFEngine: Historical sync finished.")

    def get_mtf_candles(self, symbol: str) -> pl.DataFrame:
        """Retrieves historical MTF time-series data for a specific stock."""
        with db_manager.get_market_conn(read_only=True) as conn:
            table_exists = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'mtf_candles'"
            ).fetchone()[0] > 0
            if not table_exists:
                return pl.DataFrame()
            
            return conn.execute("""
                SELECT timestamp, qty_financed, amt_financed 
                FROM mtf_candles 
                WHERE symbol = ? 
                ORDER BY timestamp
            """, [symbol]).pl()

    def get_latest_mtf_status(self) -> Dict[str, Dict]:
        """Returns symbol -> latest MTF details (amt_financed, qty_financed) for active screener lookup."""
        with db_manager.get_market_conn(read_only=True) as conn:
            table_exists = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'mtf_candles'"
            ).fetchone()[0] > 0
            if not table_exists:
                return {}
            
            res = conn.execute("""
                SELECT symbol, qty_financed, amt_financed
                FROM mtf_candles
                QUALIFY ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY timestamp DESC) = 1
            """).fetchall()
            return {row[0]: {'qty': row[1], 'amt': row[2]} for row in res}

    def get_sync_progress(self) -> Dict:
        percentage = 0
        if self.sync_total > 0:
            percentage = round((self.sync_completed / self.sync_total) * 100, 2)
            
        return {
            "is_syncing": self.is_syncing,
            "total": self.sync_total,
            "completed": self.sync_completed,
            "errors": self.sync_errors,
            "current_symbol": "MTF: " + self.sync_current_date if self.sync_current_date else "",
            "percentage": percentage
        }
