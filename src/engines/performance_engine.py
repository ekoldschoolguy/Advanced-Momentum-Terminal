import polars as pl
from typing import Optional
from src.engines.historical_engine import HistoricalEngine
from src.managers.database_manager import db_manager

class PerformanceEngine:
    """
    Blazing-fast Polars engine for calculating Relative Strength (RS).
    Matches TradingView PineScript logic:
    res = (baseSymbol / baseSymbol[length]) / (comparativeSymbol / comparativeSymbol[length]) - 1
    """
    
    def __init__(self, historical_engine: HistoricalEngine):
        self.historical_engine = historical_engine
        
    def calculate_rs(
        self,
        target_instrument: str,
        index_instrument: str = "NSE_INDEX|Nifty 50",
        length: int = 123,
        ema_length: int = 50,
        price_sma_length: int = 50
    ) -> Optional[pl.DataFrame]:
        """
        Calculates the Relative Strength of a target stock against an index.
        Uses vectorized operations in Polars for instant calculation.
        """
        # 1. Fetch data for both instruments using the shared DB connection
        # This safely reuses the DuckDB connection from HistoricalEngine
        target_df = self.historical_engine.get_data_from_db(target_instrument)
        index_df = self.historical_engine.get_data_from_db(index_instrument)
        
        if target_df.is_empty() or index_df.is_empty():
            return None
            
        # Select only needed columns and ensure chronological order
        target_df = target_df.select(["timestamp", "open", "high", "low", "close", "volume"]).sort("timestamp")
        index_df = index_df.select(["timestamp", "close"]).sort("timestamp")
        
        # 2. Calculate the Index Return over the 'length' period
        index_df = index_df.with_columns(
            index_return=(pl.col("close") / pl.col("close").shift(length))
        ).select(["timestamp", "index_return"])
        
        # 3. Join the Index return to the target stock data
        df = target_df.join(index_df, on="timestamp", how="left")
        
        # 4. Calculate RS, RS SMA, and Price SMA (Confirmation)
        df = df.with_columns([
            # baseSymbol / baseSymbol[length]
            (pl.col("close") / pl.col("close").shift(length)).alias("stock_return")
        ]).with_columns([
            # RS = (stock_return / (index_return)) - 1
            (pl.col("stock_return") / pl.col("index_return") - 1).alias("rs")
        ]).with_columns([
            # Exponential Moving Average of RS
            pl.col("rs").ewm_mean(span=ema_length, adjust=False).alias("ema_res"),
            # Simple Moving Average of Price (for trend confirmation)
            pl.col("close").rolling_mean(window_size=price_sma_length).alias("sma_price")
        ])
        
        # Clean up intermediary calculation columns and drop nulls from the initial shift window
        df = df.drop(["stock_return", "index_return"]).drop_nulls(subset=["rs"])
        
        return df

    def get_rs_screener_data(self, index_instrument: str = "NSE_INDEX|Nifty 50") -> pl.DataFrame:
        """
        Calculates cross-sectional Relative Strength for all stored instruments
        using DuckDB window functions for maximum performance.
        Returns 1W, 1M, 3M, 6M relative strength metrics.
        """
        query = """
        WITH max_date_cte AS (
            SELECT MAX(timestamp) as max_t FROM daily_candles
        ),
        filtered_candles AS (
            SELECT c.* 
            FROM daily_candles c, max_date_cte m
            WHERE c.timestamp >= m.max_t - INTERVAL 500 DAY
        ),
        ranked_data AS (
            SELECT 
                instrument_key,
                timestamp,
                close,
                LEAD(close, 1) OVER w as close_1d_ago,
                LEAD(close, 5) OVER w as close_1w_ago,
                LEAD(close, 21) OVER w as close_1m_ago,
                LEAD(close, 63) OVER w as close_3m_ago,
                LEAD(close, 126) OVER w as close_6m_ago,
                LEAD(close, 252) OVER w as close_1y_ago,
                FIRST_VALUE(close) OVER (PARTITION BY instrument_key, EXTRACT(year FROM timestamp) ORDER BY timestamp ASC) as close_ytd,
                ROW_NUMBER() OVER w as rn
            FROM filtered_candles
            WINDOW w AS (PARTITION BY instrument_key ORDER BY timestamp DESC)
        ),
        latest_data AS (
            SELECT * FROM ranked_data WHERE rn = 1
        ),
        index_data AS (
            SELECT * FROM latest_data WHERE instrument_key = ?
        )
        SELECT 
            l.instrument_key,
            l.close as price,
            (l.close - l.close_1d_ago) / NULLIF(l.close_1d_ago, 0) * 100 as chg_pct,
            ((l.close / NULLIF(l.close_1w_ago, 0)) - 1) * 100 as rs_1w,
            ((l.close / NULLIF(l.close_1m_ago, 0)) - 1) * 100 as rs_1m,
            ((l.close / NULLIF(l.close_3m_ago, 0)) - 1) * 100 as rs_3m,
            ((l.close / NULLIF(l.close_6m_ago, 0)) - 1) * 100 as rs_6m,
            ((l.close / NULLIF(l.close_1y_ago, 0)) - 1) * 100 as rs_1y,
            ((l.close / NULLIF(l.close_ytd, 0)) - 1) * 100 as rs_ytd,
            (
                COALESCE(((l.close / NULLIF(l.close_3m_ago, 0)) - 1) * 100 * 0.3, 0) +
                COALESCE(((l.close / NULLIF(l.close_6m_ago, 0)) - 1) * 100 * 0.3, 0) +
                COALESCE(((l.close / NULLIF(l.close_1y_ago, 0)) - 1) * 100 * 0.4, 0)
            ) / NULLIF(
                (CASE WHEN l.close_3m_ago IS NOT NULL THEN 0.3 ELSE 0 END) +
                (CASE WHEN l.close_6m_ago IS NOT NULL THEN 0.3 ELSE 0 END) +
                (CASE WHEN l.close_1y_ago IS NOT NULL THEN 0.4 ELSE 0 END), 
            0) as cms
        FROM latest_data l

        CROSS JOIN index_data i
        WHERE l.instrument_key != ?
        """
        with db_manager.get_market_conn(read_only=True) as conn:
            df = conn.execute(query, [index_instrument, index_instrument]).pl()
        return df

