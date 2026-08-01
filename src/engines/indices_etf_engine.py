import os
import polars as pl
import duckdb
import datetime
from typing import List, Dict, Any

from src.engines.historical_engine import HistoricalEngine
from src.engines.search_engine import SearchEngine

from src.managers.database_manager import db_manager

class IndicesEtfEngine:
    def __init__(self, historical_engine: HistoricalEngine, search_engine: SearchEngine, base_dir: str = "database"):
        self.historical_engine = historical_engine
        self.search_engine = search_engine

    def get_india_data(self, instrument_keys: List[str]) -> pl.DataFrame:
        """Fetch cached india data from market_data duckdb"""
        placeholders = ','.join(['?'] * len(instrument_keys))
        query = f"SELECT instrument_key as symbol, timestamp, close, volume FROM daily_candles WHERE instrument_key IN ({placeholders}) ORDER BY timestamp"
        with db_manager.get_market_conn(read_only=True) as conn:
            return conn.execute(query, instrument_keys).pl()

    # ==========================================
    # LAYER 2: INDIA SECTORS
    # ==========================================

    def get_india_sectoral_heatmap(self) -> List[Dict[str, Any]]:
        """Nifty sectoral indices returns."""
        # Mapping index names to upstox instrument keys if possible
        # Or if we don't have them hardcoded, we can search search_engine
        sector_names = [
            "Nifty Auto", "Nifty Bank", "Nifty Cement", "Nifty Chemicals",
            "Nifty Fin Service", "Nifty FinSrv25 50", "Nifty FinSerExBnk",
            "Nifty FMCG", "NIFTY HEALTHCARE", "Nifty IT", "Nifty Media",
            "Nifty Metal", "Nifty Pharma", "Nifty Pvt Bank", "Nifty PSU Bank",
            "Nifty Realty", "Nifty REITs Realty", "NIFTY CONSR DURBL",
            "NIFTY OIL AND GAS", "Nifty500 Health", "Nifty MS Fin Serv",
            "Nifty MidSml Hlth", "Nifty MS IT Telcm", "Nifty PSE", "Nifty Energy"
        ]
        
        instrument_keys = []
        key_to_name = {}
        for name in sector_names:
            results = self.search_engine.search_by_name(name)
            if results:
                # Filter to indices
                indices = [r for r in results if r.get('instrument_type') == 'INDEX']
                if indices:
                    key = indices[0]['instrument_key']
                    instrument_keys.append(key)
                    key_to_name[key] = name
                    
        if not instrument_keys:
            return []
            
        df = self.get_india_data(instrument_keys)
        if df.is_empty():
            return []
            
        results = []
        for key in instrument_keys:
            sym_df = df.filter(pl.col('symbol') == key).sort('timestamp')
            if len(sym_df) < 252:
                continue
                
            closes = sym_df['close'].to_list()
            latest = closes[-1]
            ret_1d = (latest / closes[-2] - 1) * 100 if len(closes) > 1 else 0
            ret_1w = (latest / closes[-6] - 1) * 100 if len(closes) > 5 else 0
            ret_1m = (latest / closes[-22] - 1) * 100 if len(closes) > 21 else 0
            ret_3m = (latest / closes[-64] - 1) * 100 if len(closes) > 63 else 0
            ret_6m = (latest / closes[-126] - 1) * 100 if len(closes) > 125 else 0
            ret_1y = (latest / closes[-252] - 1) * 100 if len(closes) > 251 else 0
            
            results.append({
                'name': key_to_name[key],
                '1D': round(ret_1d, 2),
                '1W': round(ret_1w, 2),
                '1M': round(ret_1m, 2),
                '3M': round(ret_3m, 2),
                '6M': round(ret_6m, 2),
                '1Y': round(ret_1y, 2),
            })
            
        return results

    def get_india_rrg(self, timeframe: int = 14, benchmark: str = 'Nifty 50') -> Dict[str, Any]:
        """
        Calculates Relative Rotation Graph (RRG) data for Indian Sectors.
        benchmark: Default Nifty 50
        timeframe: Number of weeks for the trailing path
        """
        sector_names = [
            "Nifty Auto", "Nifty Bank", "Nifty Cement", "Nifty Chemicals",
            "Nifty Fin Service", "Nifty FinSrv25 50", "Nifty FinSerExBnk",
            "Nifty FMCG", "NIFTY HEALTHCARE", "Nifty IT", "Nifty Media",
            "Nifty Metal", "Nifty Pharma", "Nifty Pvt Bank", "Nifty PSU Bank",
            "Nifty Realty", "Nifty REITs Realty", "NIFTY CONSR DURBL",
            "NIFTY OIL AND GAS", "Nifty500 Health", "Nifty MS Fin Serv",
            "Nifty MidSml Hlth", "Nifty MS IT Telcm", "Nifty PSE", "Nifty Energy"
        ]
        
        benchmark_term = benchmark
        
        # 1. Resolve instrument keys
        instrument_keys = []
        key_to_name = {}
        bench_key = None
        
        # Resolve benchmark
        b_res = self.search_engine.search_by_name(benchmark_term)
        if b_res:
            b_valid = [r for r in b_res if r.get('instrument_type') == 'INDEX']
            if b_valid:
                bench_key = b_valid[0]['instrument_key']
                instrument_keys.append(bench_key)
                
        if not bench_key:
            return {}
            
        for name in sector_names:
            results = self.search_engine.search_by_name(name)
            if results:
                valid = [r for r in results if r.get('instrument_type') == 'INDEX']
                if valid:
                    key = valid[0]['instrument_key']
                    instrument_keys.append(key)
                    key_to_name[key] = name
                    
        if len(instrument_keys) < 2:
            return {}
            
        df = self.get_india_data(instrument_keys)
        if df.is_empty():
            return {}

        # Pivot to have symbols as columns, timestamp as rows
        pivot_df = df.pivot(values="close", index="timestamp", columns="symbol").sort("timestamp")
        
        if bench_key not in pivot_df.columns:
            return {}

        # Fill forward missing values (daily)
        pivot_df = pivot_df.fill_null(strategy="forward").fill_null(strategy="backward")

        # Resample to Weekly (Friday close)
        pivot_df = pivot_df.group_by_dynamic(
            "timestamp", every="1w", closed="right", label="right"
        ).agg([pl.col(col).last() for col in pivot_df.columns if col != "timestamp"])

        results = {}
        for key, name in key_to_name.items():
            if key not in pivot_df.columns:
                continue
            
            # 1. Compute RS: Asset / Benchmark
            rs = pivot_df[key] / pivot_df[bench_key] * 100
            
            # 2. Smooth RS (span=10)
            rs_smoothed = rs.ewm_mean(span=10, adjust=False)
            
            # 3. RS-Ratio = 100 + Z-Score of RS (window=52) * 2
            rs_mean = rs_smoothed.rolling_mean(window_size=52, min_periods=20)
            rs_std = rs_smoothed.rolling_std(window_size=52, min_periods=20)
            rs_ratio = 100 + ((rs_smoothed - rs_mean) / (rs_std + 1e-9)) * 2
            
            # 4. RS-Momentum
            rs_momentum_raw = rs_ratio.diff(1)
            mom_smoothed = rs_momentum_raw.ewm_mean(span=5, adjust=False)
            mom_mean = mom_smoothed.rolling_mean(window_size=52, min_periods=20)
            mom_std = mom_smoothed.rolling_std(window_size=52, min_periods=20)
            rs_momentum = 100 + ((mom_smoothed - mom_mean) / (mom_std + 1e-9)) * 2
            
            temp_df = pl.DataFrame({
                "date": pivot_df["timestamp"],
                "rs_ratio": rs_ratio,
                "rs_momentum": rs_momentum
            })
            
            valid_df = temp_df.filter(pl.col("rs_ratio").is_not_null() & pl.col("rs_momentum").is_not_null())
            if valid_df.is_empty():
                continue
                
            tail_df = valid_df.tail(timeframe)
            
            dates = tail_df["date"].dt.strftime("%Y-%m-%d").to_list()
            ratios = tail_df["rs_ratio"].to_list()
            momentums = tail_df["rs_momentum"].to_list()
            
            results[name] = {
                "symbol": name,
                "dates": dates,
                "rs_ratio": [round(x, 2) for x in ratios],
                "rs_momentum": [round(x, 2) for x in momentums]
            }
            
        return results
    def get_india_etf_screener(self) -> List[Dict[str, Any]]:
        """Filterable table of Indian ETFs"""
        etfs = [
            "NIFTYBEES", "BANKBEES", "ITBEES", "PHARMABEES", "CPSEETF", "GOLDBEES", 
            "SILVERBEES", "LIQUIDBEES", "MON100", "MID150BEES", "MOM30IETF", "ALPHAETF",
            "LOWVOLIETF", "MAKEINDIA", "HDFCSML250", "ICICIB250"
        ]
        
        instrument_keys = []
        key_to_symbol = {}
        for symbol in etfs:
            results = self.search_engine.search_by_symbol(symbol, exact_match=True)
            if results:
                key = results[0]['instrument_key']
                instrument_keys.append(key)
                key_to_symbol[key] = symbol
                
        if not instrument_keys:
            return []
            
        df = self.get_india_data(instrument_keys)
        if df.is_empty():
            return []
            
        results = []
        for key in instrument_keys:
            sym_df = df.filter(pl.col('symbol') == key).sort('timestamp')
            if len(sym_df) < 252:
                # need at least 1 year for 52W range
                continue
                
            closes = sym_df['close'].to_list()
            latest = closes[-1]
            
            # 52w high / low
            last_1y_df = sym_df.tail(252)
            high_52 = last_1y_df['close'].max()
            low_52 = last_1y_df['close'].min()
            avg_vol = last_1y_df['volume'].mean()
            
            ret_1d = (latest / closes[-2] - 1) * 100 if len(closes) > 1 else 0
            ret_1m = (latest / closes[-22] - 1) * 100 if len(closes) > 21 else 0
            ret_1y = (latest / closes[-252] - 1) * 100 if len(closes) > 251 else 0
            
            results.append({
                'symbol': key_to_symbol[key],
                'price': round(latest, 2),
                '1D': round(ret_1d, 2),
                '1M': round(ret_1m, 2),
                '1Y': round(ret_1y, 2),
                '52w_high': round(high_52, 2),
                '52w_low': round(low_52, 2),
                'avg_volume': int(avg_vol) if avg_vol else 0
            })
            
        return results
