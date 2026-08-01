from fastapi import APIRouter, Query
from src.api.dependencies import indices_etf_engine, universe_manager, search_engine
import polars as pl

router = APIRouter()



@router.get("/india_heatmap")
async def get_india_heatmap():
    try:
        return {"status": "success", "data": indices_etf_engine.get_india_sectoral_heatmap()}
    except Exception as e:
        return {"error": str(e)}

@router.get("/india_rrg")
async def get_india_rrg(timeframe: int = 8, benchmark: str = "Nifty 50"):
    try:
        return {"status": "success", "data": indices_etf_engine.get_india_rrg(timeframe, benchmark), "benchmark": benchmark}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/india_etf_screener")
async def get_india_etf_screener():
    try:
        return {"status": "success", "data": indices_etf_engine.get_india_etf_screener()}
    except Exception as e:
        return {"error": str(e)}

@router.get("/sector_constituents")
async def get_sector_constituents(sector: str = Query(..., description="Exact sector name e.g. 'Nifty IT'")):
    try:
        symbols = universe_manager.get_symbols(sector)
        if not symbols:
            return {"status": "error", "message": f"No constituents found for {sector}. Ensure universes are synced."}
        
        instrument_keys = []
        key_to_symbol = {}
        for sym in symbols:
            res = search_engine.search_by_symbol(sym, exact_match=True)
            if res:
                nse_eq = [r for r in res if r.get("exchange") == "NSE"]
                if nse_eq:
                    key = nse_eq[0]['instrument_key']
                    instrument_keys.append(key)
                    key_to_symbol[key] = sym
        
        if not instrument_keys:
            return {"status": "error", "message": "Could not map constituents to known Upstox instruments."}
            
        df = indices_etf_engine.get_india_data(instrument_keys)
        if df.is_empty():
            return {"status": "success", "data": []}
            
        results = []
        for key in instrument_keys:
            sym_df = df.filter(pl.col('symbol') == key).sort('timestamp')
            if len(sym_df) < 2:
                continue
            
            closes = sym_df['close'].to_list()
            latest = closes[-1]
            ret_1d = (latest / closes[-2] - 1) * 100
            
            results.append({
                "symbol": key_to_symbol[key],
                "price": round(latest, 2),
                "1D": round(ret_1d, 2)
            })
            
        results.sort(key=lambda x: x["1D"], reverse=True)
        return {"status": "success", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}
