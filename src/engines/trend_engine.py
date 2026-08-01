import polars as pl
from typing import Optional
from src.engines.historical_engine import HistoricalEngine

class TrendEngine:
    """
    Calculates volatility-adjusted price-trend indicators.
    """
    def __init__(self, historical_engine: HistoricalEngine):
        self.historical_engine = historical_engine
        
    def calculate_trend(self, symbol: str, length: int = 21) -> Optional[pl.DataFrame]:
        """
        Calculates a volatility-adjusted trend indicator oscillating between -1 and +1.
        """
        # Fetch historical data
        df = self.historical_engine.get_data_from_db(symbol)
        if df.is_empty():
            return None
            
        df = df.select(["timestamp", "close"]).sort("timestamp")
        
        # 1. Day-to-day % changes (ccr) and absolute % changes (ccv)
        df = df.with_columns([
            ((pl.col("close") - pl.col("close").shift(1)) / pl.col("close").shift(1)).alias("ccr")
        ]).with_columns([
            pl.col("ccr").abs().alias("ccv")
        ])

        # 2. EMA of changes (ema_ccr) and EMA of absolute changes (ema_ccv)
        df = df.with_columns([
            pl.col("ccr").ewm_mean(span=length, adjust=False).alias("ema_ccr"),
            pl.col("ccv").ewm_mean(span=length, adjust=False).alias("ema_ccv")
        ])

        # 3. Volatility-Adjusted Trend Indicator (P)
        df = df.with_columns([
            (pl.col("ema_ccr") / pl.col("ema_ccv")).alias("trend_indicator")
        ])
        
        # Format timestamp and select necessary columns
        df = df.with_columns(pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("date"))
        
        # Drop rows with nulls (due to shifting/EMA start periods)
        df = df.drop_nulls(subset=["trend_indicator"])
        
        return df.select(["date", "trend_indicator"])
