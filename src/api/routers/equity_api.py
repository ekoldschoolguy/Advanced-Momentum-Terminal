from fastapi import APIRouter, Query
from src.api.dependencies import search_engine, instrument_manager, universe_manager
import asyncio

router = APIRouter()

@router.get("/api/equity/search")
async def search_equity_local(
    query: str = Query(..., description="The string to search for"),
    search_type: str = Query("symbol", description="Type of search: symbol, name, or isin"),
    exact_match: bool = Query(False, description="Require exact match (for symbol search)")
):
    if not search_engine.is_loaded:
        return {"error": "Data not loaded. Please download the complete master file first and reload."}
    if search_type == "symbol":
        results = search_engine.search_by_symbol(query, exact_match=exact_match)
    elif search_type == "name":
        results = search_engine.search_by_name(query)
    elif search_type == "isin":
        results = search_engine.get_by_isin(query)
    elif search_type == "all":
        sym_res = search_engine.search_by_symbol(query, exact_match=exact_match)
        name_res = search_engine.search_by_name(query)
        seen = {r.get('instrument_key') for r in sym_res}
        results = sym_res + [r for r in name_res if r.get('instrument_key') not in seen]
    else:
        return {"error": "Invalid search_type. Use symbol, name, isin, or all."}
    return {"status": "success", "count": len(results), "data": results}

@router.post("/api/equity/reload")
async def reload_search_engine():
    success = search_engine.load_data()
    if success:
        universe_manager.load_all()
        return {"status": "success", "message": "Successfully reloaded equity and universe data.", "stats": search_engine.get_stats()}
    return {"error": "Failed to load equity data. Is the data/equities_master.json file downloaded?"}

@router.get("/api/instruments/search")
async def search_instruments_live(
    query: str, expiry: str = None, atm_offset: int = None, page: int = 1
):
    try:
        return await instrument_manager.search_instruments(query=query, expiry=expiry, atm_offset=atm_offset, page_number=page)
    except Exception as e:
        return {"error": str(e)}

@router.get("/api/instruments/download")
async def download_instruments(file_type: str = "complete"):
    try:
        path = await instrument_manager.download_instrument_file(file_type=file_type)
        if file_type == "complete":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, search_engine.load_data)
        return {"status": "success", "message": f"Successfully downloaded and decompressed to {path}"}
    except Exception as e:
        return {"error": str(e)}

@router.get("/api/universes")
async def get_universes():
    try:
        return {"status": "success", "data": universe_manager.universe_symbols}
    except Exception as e:
        return {"error": str(e)}
