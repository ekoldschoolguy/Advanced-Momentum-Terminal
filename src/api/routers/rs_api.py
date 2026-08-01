from fastapi import APIRouter, Query
from src.api.dependencies import performance_engine, search_engine
import polars as pl
import pandas as pd
import io
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.get("/calculate")
async def calculate_relative_strength(
    target: str = Query(..., description="Target instrument key or symbol (e.g., RELIANCE)"),
    index: str = Query("NSE_INDEX|Nifty 50", description="Index instrument key"),
    length: int = Query(123, description="Period for return calculation"),
    ema_length: int = Query(50, description="Period for RS EMA"),
    price_sma_length: int = Query(50, description="Period for Price SMA")
):
    try:
        resolved_symbol = target
        if "|" not in target:
            if not search_engine.is_loaded:
                return {"status": "error", "message": "Equity engine is not loaded. Cannot resolve symbol."}
            results = search_engine.search_by_symbol(target)
            if not results:
                return {"status": "error", "message": f"Could not find any instrument matching: {target}"}
            exact_matches = [r for r in results if r.get("trading_symbol", "").upper() == target.upper()]
            if exact_matches:
                resolved_symbol = exact_matches[0].get("trading_symbol")
                target = exact_matches[0].get("instrument_key")
            else:
                resolved_symbol = results[0].get("trading_symbol")
                target = results[0].get("instrument_key")
        else:
            # If target has | we find it in equities map
            if search_engine.is_loaded:
                matches = [eq for eq in search_engine.equities if eq.get("instrument_key") == target]
                if matches:
                    resolved_symbol = matches[0].get("trading_symbol")
                else:
                    resolved_symbol = target.split("|")[-1]

        df = performance_engine.calculate_rs(
            target_instrument=target,
            index_instrument=index,
            length=length,
            ema_length=ema_length,
            price_sma_length=price_sma_length
        )
        if df is None or df.is_empty():
            return {"status": "error", "message": "Could not calculate RS. Ensure both target and index data are downloaded."}
            
        df = df.with_columns(pl.col("timestamp").dt.to_string("%Y-%m-%d %H:%M:%S"))
        return {"status": "success", "count": len(df), "symbol": resolved_symbol, "data": df.tail(300).to_dicts()}
    except Exception as e:
        return {"error": str(e)}

@router.get("/screener")
async def get_rs_screener(index: str = Query("NSE_INDEX|Nifty 50", description="Index instrument key")):
    try:
        from src.api.dependencies import historical_engine
        df = performance_engine.get_rs_screener_data(index_instrument=index)
        if df is None or df.is_empty():
             return {"status": "error", "message": "No data returned from DB."}
        
        data_dicts = df.to_dicts()
        final_data = []
        
        # Build O(1) metadata lookup map
        metadata_map = {}
        if search_engine.is_loaded:
            for eq in search_engine.equities:
                key = eq.get("instrument_key")
                if key:
                    metadata_map[key] = {
                        "symbol": eq.get("trading_symbol", key.split("|")[-1]),
                        "name": eq.get("name", "")
                    }
        
        # Fetch latest delivery percentages
        delivery_map = historical_engine.get_latest_delivery_pcts()
        
        # Fetch symbol to sector mapping
        from src.api.dependencies import universe_manager, mtf_engine
        sector_map = universe_manager.get_symbol_sectors()
        
        # Fetch latest MTF status mapping
        mtf_map = mtf_engine.get_latest_mtf_status()
        
        import json
        import os
        mcap_cache = {}
        cache_path = os.path.join(os.getcwd(), 'data/mcap_cache.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                try:
                    mcap_cache = json.load(f)
                except:
                    pass
        
        for row in data_dicts:
            key = row["instrument_key"]
            meta = metadata_map.get(key)
            if meta:
                row["symbol"] = meta["symbol"]
                row["name"] = meta["name"]
            else:
                row["symbol"] = key.split("|")[-1]
                row["name"] = ""
            
            # Map sector/industry classification
            row["sector"] = sector_map.get(row["symbol"], "—")
            
            # Add delivery percentage
            row["delivery_pct"] = delivery_map.get(row["symbol"], 0.0)
            
            # Add MTF details
            mtf_info = mtf_map.get(row["symbol"])
            shares = mcap_cache.get(row["symbol"], 0)
            mcap_cr = (shares * row.get("price", 0)) / 10000000
            
            if mtf_info:
                row["mtf_eligible"] = True
                row["mtf_qty"] = mtf_info["qty"]
                mtf_amt_cr = mtf_info["amt"] / 100.0
                row["mtf_amt"] = round(mtf_amt_cr, 2) # in Crores
                row["mtf_pct_mcap"] = round((mtf_amt_cr / mcap_cr * 100), 2) if mcap_cr > 0 else 0
            else:
                row["mtf_eligible"] = False
                row["mtf_qty"] = 0
                row["mtf_amt"] = 0.0
                row["mtf_pct_mcap"] = 0.0
                
            row["mcap_cr"] = round(mcap_cr, 2)
                
            final_data.append(row)

        return {"status": "success", "count": len(final_data), "data": final_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/trend")
async def get_trend_data(symbol: str = Query(..., description="Stock symbol")):
    try:
        from src.api.dependencies import trend_engine, search_engine
        
        instrument_key = symbol
        if "|" not in symbol:
            if search_engine.is_loaded:
                results = search_engine.search_by_symbol(symbol)
                exact_matches = [r for r in results if r.get("trading_symbol", "").upper() == symbol.upper()]
                if exact_matches:
                    instrument_key = exact_matches[0].get("instrument_key")
                elif results:
                    instrument_key = results[0].get("instrument_key")

        df = trend_engine.calculate_trend(instrument_key)
        if df is None or df.is_empty():
            return {"status": "error", "message": f"No trend data found for symbol: {symbol}"}
            
        return {"status": "success", "count": len(df), "data": df.to_dicts()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mtf")
async def get_mtf_data(symbol: str = Query(..., description="Stock symbol (e.g. SBIN)")):
    try:
        from src.api.dependencies import mtf_engine
        df = mtf_engine.get_mtf_candles(symbol)
        if df.is_empty():
            return {"status": "error", "message": f"No MTF data found for symbol: {symbol}"}
        
        df_rich = df.with_columns([
            pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("date"),
            (pl.col("amt_financed") / 100.0).round(2).alias("amt_crores")
        ])
        return {"status": "success", "count": len(df_rich), "data": df_rich.to_dicts()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mtf/summary")
async def get_mtf_summary():
    try:
        from src.managers.database_manager import db_manager
        with db_manager.get_market_conn(read_only=True) as conn:
            df = conn.execute("""
                SELECT timestamp, fresh_exposure, exposure_liquidated, total_outstanding 
                FROM mtf_summary 
                WHERE total_outstanding IS NOT NULL AND total_outstanding > 0
                ORDER BY timestamp
            """).pl()
            
        if df.is_empty():
            return {"status": "error", "message": "No MTF summary data found."}
            
        df_rich = df.with_columns([
            pl.col("timestamp").dt.strftime("%Y-%m-%d").alias("date"),
            (pl.col("fresh_exposure") / 100.0).round(2).alias("added_crores"),
            (pl.col("exposure_liquidated") / 100.0).round(2).alias("liquidated_crores"),
            (pl.col("total_outstanding") / 100.0).round(2).alias("outstanding_crores")
        ])
        return {"status": "success", "count": len(df_rich), "data": df_rich.to_dicts()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mtf_screener_data")
async def get_mtf_screener_data():
    try:
        from src.managers.database_manager import db_manager
        from src.api.dependencies import search_engine, performance_engine, universe_manager, historical_engine
        
        # 1. Get RS data (has price, chg_pct)
        rs_df = performance_engine.get_rs_screener_data()
        if rs_df is None or rs_df.is_empty():
            return {"status": "error", "message": "No base market data available. Run sync first."}
        rs_data = rs_df.to_dicts()
        
        # 2. Get MTF historical data using window functions
        mtf_query = """
        WITH ranked_mtf AS (
            SELECT 
                symbol,
                timestamp,
                qty_financed,
                amt_financed,
                LEAD(amt_financed, 5) OVER w as amt_1w_ago,
                LEAD(amt_financed, 21) OVER w as amt_1m_ago,
                LEAD(amt_financed, 63) OVER w as amt_3m_ago,
                LEAD(amt_financed, 126) OVER w as amt_6m_ago,
                ROW_NUMBER() OVER w as rn
            FROM mtf_candles
            WINDOW w AS (PARTITION BY symbol ORDER BY timestamp DESC)
        ),
        latest_mtf AS (
            SELECT * FROM ranked_mtf WHERE rn = 1
        )
        SELECT * FROM latest_mtf WHERE amt_financed > 0
        """
        with db_manager.get_market_conn(read_only=True) as conn:
            mtf_df = conn.execute(mtf_query).pl()
            
        mtf_dict = {row['symbol']: row for row in mtf_df.to_dicts()}
        
        # 3. Sector map
        sector_map = universe_manager.get_symbol_sectors()
        
        # 4. Load MCAP Cache
        import json
        import os
        mcap_cache = {}
        cache_path = os.path.join(os.getcwd(), 'data/mcap_cache.json')
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                try:
                    mcap_cache = json.load(f)
                except:
                    pass
        
        final_data = []
        for row in rs_data:
            key = row['instrument_key']
            
            # Need symbol
            sym = key.split('|')[-1]
            name = ""
            if search_engine.is_loaded:
                matches = [eq for eq in search_engine.equities if eq.get('instrument_key') == key]
                if matches:
                    sym = matches[0].get('trading_symbol')
                    name = matches[0].get('name')
            
            mtf_info = mtf_dict.get(sym)
            if not mtf_info:
                continue
                
            latest_amt = mtf_info['amt_financed'] or 0
            amt_1w = mtf_info['amt_1w_ago'] or latest_amt
            amt_1m = mtf_info['amt_1m_ago'] or latest_amt
            amt_3m = mtf_info['amt_3m_ago'] or latest_amt
            amt_6m = mtf_info['amt_6m_ago'] or latest_amt
            
            shares = mcap_cache.get(sym, 0)
            mcap_cr = (shares * row['price']) / 10000000
            mtf_amt_cr = latest_amt / 100.0
            
            mtf_pct_mcap = (mtf_amt_cr / mcap_cr * 100) if mcap_cr > 0 else 0
            
            final_data.append({
                'symbol': sym,
                'name': name,
                'sector': sector_map.get(sym, '—'),
                'price': row['price'],
                'mtf_amt_cr': round(mtf_amt_cr, 2),
                'mtf_pct_mcap': round(mtf_pct_mcap, 2),
                'mtf_1w_cr': round(amt_1w / 100.0, 2),
                'mtf_1m_cr': round(amt_1m / 100.0, 2),
                'mtf_3m_cr': round(amt_3m / 100.0, 2),
                'mtf_6m_cr': round(amt_6m / 100.0, 2),
                'mtf_net_1w_cr': round((latest_amt - amt_1w) / 100.0, 2),
                'mtf_net_1m_cr': round((latest_amt - amt_1m) / 100.0, 2),
                'mtf_net_3m_cr': round((latest_amt - amt_3m) / 100.0, 2),
                'mtf_net_6m_cr': round((latest_amt - amt_6m) / 100.0, 2),
                'cms': row.get('cms', 0)
            })
            
        return {"status": "success", "count": len(final_data), "data": final_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


