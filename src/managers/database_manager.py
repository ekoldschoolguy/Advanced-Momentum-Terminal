import duckdb
import os
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Centralized connection manager for DuckDB to prevent file lock crashes.
    """
    def __init__(self, base_dir: str = "database"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.market_db_path = os.path.join(self.base_dir, "market_data.duckdb")
        self.macro_db_path = os.path.join(self.base_dir, "macro_data.duckdb")
        self.intraday_db_path = os.path.join(self.base_dir, "intraday_data.duckdb")
        self._market_write_lock = None

    @property
    def market_write_lock(self):
        import asyncio
        if self._market_write_lock is None:
            self._market_write_lock = asyncio.Lock()
        return self._market_write_lock
        
    @contextmanager
    def get_market_conn(self, read_only=True):
        """Yields a connection to the market data DB with retry logic for locks."""
        import time
        conn = None
        retries = 5
        delay = 0.05
        for i in range(retries):
            try:
                conn = duckdb.connect(self.market_db_path, read_only=read_only)
                break
            except (duckdb.IOException, duckdb.OperationalError) as e:
                if i == retries - 1:
                    logger.error(f"Failed to connect to market DB after {retries} attempts: {e}")
                    raise e
                time.sleep(delay * (2 ** i)) # Exponential backoff
        try:
            yield conn
        finally:
            if conn:
                conn.close()
                
    @contextmanager
    def get_macro_conn(self, read_only=True):
        """Yields a connection to the macro data DB with retry logic for locks."""
        import time
        conn = None
        retries = 5
        delay = 0.05
        for i in range(retries):
            try:
                conn = duckdb.connect(self.macro_db_path, read_only=read_only)
                break
            except (duckdb.IOException, duckdb.OperationalError) as e:
                if i == retries - 1:
                    logger.error(f"Failed to connect to macro DB after {retries} attempts: {e}")
                    raise e
                time.sleep(delay * (2 ** i)) # Exponential backoff
        try:
            yield conn
        finally:
            if conn:
                conn.close()

    @contextmanager
    def get_intraday_conn(self, read_only=True):
        """Yields a connection to the intraday data DB with retry logic for locks."""
        import time
        conn = None
        retries = 5
        delay = 0.05
        for i in range(retries):
            try:
                conn = duckdb.connect(self.intraday_db_path, read_only=read_only)
                break
            except (duckdb.IOException, duckdb.OperationalError) as e:
                if i == retries - 1:
                    logger.error(f"Failed to connect to intraday DB after {retries} attempts: {e}")
                    raise e
                time.sleep(delay * (2 ** i)) # Exponential backoff
        try:
            yield conn
        finally:
            if conn:
                conn.close()
# Initialize a global singleton manager
db_manager = DatabaseManager()
