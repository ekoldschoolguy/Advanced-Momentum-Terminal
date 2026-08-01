from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import date
from typing import List
from src.api.dependencies import historical_engine, search_engine, mtf_engine
import asyncio
import io
import pandas as pd
router = APIRouter()

_bulk_sync_running = False  # Module-level lock for the multi-phase pipeline

async def run_selected_sync(targets: list[str]):
    global _bulk_sync_running
    if _bulk_sync_running:
        return  # Prevent concurrent multi-phase runs
    _bulk_sync_running = True

    historical_engine.progress = {}
    mtf_engine.is_syncing = False
    mtf_engine.sync_total = 0
    mtf_engine.sync_completed = 0
    
    total_phases = len(targets)
    current_phase = 0
    
    try:
            
        tasks = []

        if "indices" in targets and _bulk_sync_running:
            today_str = date.today().strftime("%Y-%m-%d")
            tasks.append(historical_engine.sync_all_data(
                search_engine=search_engine,
                from_date="2000-01-01",
                to_date=today_str,
                target="indices"
            ))

        if "equities" in targets and _bulk_sync_running:
            today_str = date.today().strftime("%Y-%m-%d")
            tasks.append(historical_engine.sync_all_data(
                search_engine=search_engine,
                from_date="2000-01-01",
                to_date=today_str,
                target="equities"
            ))

        if "delivery" in targets and _bulk_sync_running:
            from src.api.dependencies import universe_manager
            universe_manager.load_all()
            unique_symbols = set()
            for universe_name, symbols in universe_manager.universe_symbols.items():
                unique_symbols.update(symbols)
            tasks.append(historical_engine.sync_delivery_data(symbols=list(unique_symbols)))

        if "mtf" in targets and _bulk_sync_running:
            tasks.append(mtf_engine.sync_mtf_history(days_lookback=1800))
            
        if tasks:
            await asyncio.gather(*tasks)
            

    except Exception as e:
        historical_engine.is_syncing = False
        mtf_engine.is_syncing = False
    finally:
        historical_engine.is_syncing = False
        mtf_engine.is_syncing = False
        _bulk_sync_running = False

class SyncRequest(BaseModel):
    targets: list[str]

@router.post("/sync_all")
async def start_bulk_sync(req: SyncRequest, background_tasks: BackgroundTasks):
    targets = req.targets
    if not targets:
        raise HTTPException(status_code=400, detail="No sync targets provided")
        
    valid_targets = {"equities", "indices", "delivery", "mtf"}
    if any(t not in valid_targets for t in targets):
        raise HTTPException(status_code=400, detail="Invalid sync target in list")
        
    if historical_engine.is_syncing:
        return {"status": "error", "message": "Bulk sync is already running."}
        
    background_tasks.add_task(run_selected_sync, targets)
    return {"status": "success", "message": f"Bulk sync started for {len(targets)} targets."}

@router.post("/cancel_sync")
async def cancel_bulk_sync():
    if not historical_engine.is_syncing and not mtf_engine.is_syncing:
        return {"status": "error", "message": "No sync is currently running."}
    historical_engine.is_syncing = False
    mtf_engine.is_syncing = False
    return {"status": "success", "message": "Bulk sync cancellation requested."}

@router.get("/progress")
async def get_sync_progress():
    he_prog = historical_engine.get_sync_progress()
    mtf_prog = mtf_engine.get_sync_progress()
    
    is_syncing = he_prog["is_syncing"] or mtf_prog["is_syncing"]
    total = he_prog["total"] + mtf_prog["total"]
    completed = he_prog["completed"] + mtf_prog["completed"]
    errors = he_prog["errors"] + mtf_prog["errors"]
    
    symbols = []
    if he_prog["current_symbol"]: symbols.append(he_prog["current_symbol"])
    if mtf_prog["current_symbol"]: symbols.append(mtf_prog["current_symbol"])
    current_symbol = " | ".join(symbols) if symbols else "Syncing..."
    
    percentage = 0
    if total > 0:
        percentage = round((completed / total) * 100, 2)
        
    return {
        "is_syncing": is_syncing,
        "total": total,
        "completed": completed,
        "errors": errors,
        "current_symbol": current_symbol,
        "percentage": percentage
    }

@router.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    await websocket.accept()
    try:
        last_progress = None
        while True:
            progress = historical_engine.get_sync_progress()
            if progress != last_progress:
                await websocket.send_json(progress)
                last_progress = progress
            
            # If not syncing and we already sent the completed state, we can just sleep longer
            # or break. We'll just sleep.
            await asyncio.sleep(0.25)
    except Exception as e:
        pass # Client disconnected


@router.get("/download")
async def download_historical(instrument_key: str, interval: str = "days"):
    if historical_engine.is_syncing:
        return {"status": "error", "message": "Sync is running, database is locked."}
        
    engine_interval = "days" if interval in ["day", "days"] else interval
    df = await historical_engine.fetch_historical_data(
        instrument_key=instrument_key,
        from_date="2000-01-01",
        to_date="2026-12-31",
        interval=engine_interval
    )
    if df is not None and not df.is_empty():
        historical_engine.store_data_to_db(df)
        return {"status": "success", "rows_fetched": len(df)}
    else:
        return {"status": "error", "message": "Failed to fetch data."}

@router.get("/query")
async def query_local_data(instrument_key: str):
    df = historical_engine.get_data_from_db(instrument_key)
    if df.is_empty():
        return {"status": "error", "message": "No data found locally."}
    
    # Convert dates to strings for JSON
    data = df.with_columns(
        df["timestamp"].dt.strftime("%Y-%m-%d").alias("date")
    ).to_dicts()
    
    return {"status": "success", "data": data}

class ExportExcelRequest(BaseModel):
    instrument_keys: List[str]

@router.post("/export_excel")
async def export_excel(req: ExportExcelRequest):
    if not req.instrument_keys:
        raise HTTPException(status_code=400, detail="No instrument keys provided.")
    
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for key in req.instrument_keys:
            # Get OHLC data
            df_ohlc_pl = historical_engine.get_data_from_db(key)
            df_ohlc = df_ohlc_pl.to_pandas() if not df_ohlc_pl.is_empty() else pd.DataFrame()
            
            # Find trading_symbol
            eq_info = next((eq for eq in search_engine.equities if eq.get('instrument_key') == key), None)
            symbol = eq_info.get("trading_symbol", "") if eq_info else ""
            
            # Get MTF data
            df_mtf = None
            if symbol:
                mtf_pl = mtf_engine.get_mtf_candles(symbol)
                if not mtf_pl.is_empty():
                    df_mtf = mtf_pl.to_pandas()
            
            # Merge and process
            if df_ohlc.empty:
                # create empty sheet
                pd.DataFrame({"Message": ["No data found"]}).to_excel(writer, sheet_name=(symbol or key)[:31].replace('/', '_'), index=False)
                continue
                
            if df_mtf is not None and not df_mtf.empty:
                # Merge on normalized dates to ignore time component
                df_ohlc['date_join'] = pd.to_datetime(df_ohlc['timestamp']).dt.normalize()
                df_mtf['date_join'] = pd.to_datetime(df_mtf['timestamp']).dt.normalize()
                
                df_merged = pd.merge(df_ohlc, df_mtf, on='date_join', how='left', suffixes=('', '_mtf'))
                
                # Calculate Net Add and Liquidated
                df_merged['overall_outstanding_qty'] = df_merged['qty_financed'].fillna(0)
                df_merged['amt_financed'] = df_merged['amt_financed'].fillna(0)
                
                # Calculate diffs
                qty_diff = df_merged['overall_outstanding_qty'].diff().fillna(0)
                df_merged['net_add'] = qty_diff.clip(lower=0)
                df_merged['liquidated'] = (-qty_diff).clip(lower=0)
                
                # Format columns
                df_final = df_merged[[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'open_interest', 
                    'overall_outstanding_qty', 'net_add', 'liquidated', 'amt_financed'
                ]].copy()
            else:
                df_final = df_ohlc.copy()
                df_final['overall_outstanding_qty'] = 0
                df_final['net_add'] = 0
                df_final['liquidated'] = 0
                df_final['amt_financed'] = 0
                df_final = df_final[[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'open_interest', 
                    'overall_outstanding_qty', 'net_add', 'liquidated', 'amt_financed'
                ]]
                
            df_final.rename(columns={
                'timestamp': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'open_interest': 'Open Interest',
                'overall_outstanding_qty': 'Overall Outstanding (Qty)',
                'net_add': 'Net Add',
                'liquidated': 'Liquidated',
                'amt_financed': 'Amt Financed'
            }, inplace=True)
            
            # Sort descending by Date so the most recent data is at the top
            df_final.sort_values('Date', ascending=False, inplace=True)
            df_final['Date'] = df_final['Date'].dt.strftime('%Y-%m-%d')
            
            safe_sheet_name = (symbol or key).replace('/', '_')[:31]
            df_final.to_excel(writer, sheet_name=safe_sheet_name, index=False)
            
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Export.xlsx"}
    )
