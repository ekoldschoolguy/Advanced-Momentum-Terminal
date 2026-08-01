from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import asyncio
import os

from src.api.dependencies import instrument_manager, search_engine, universe_manager
from src.api.routers import ui_routes, indices_etf_api, sync_api, auth_api, equity_api, rs_api

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run initialization in background so it doesn't block server startup
    async def init_equity():
        try:
            if not os.path.exists("data/equities_master.json"):
                await instrument_manager.download_instrument_file(file_type="complete")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, search_engine.load_data)
            
            # Load locally available universes
            await loop.run_in_executor(None, universe_manager.load_all)
            
            # Optionally trigger background download of universes if empty
            if not any(universe_manager.universe_symbols.values()):
                asyncio.create_task(universe_manager.download_all())
                
            # Check market cap cache age and update if older than 24h (86400s)
            import time as pytime
            import subprocess
            mcap_cache_path = 'data/mcap_cache.json'
            need_mcap_update = False
            
            if not os.path.exists(mcap_cache_path):
                need_mcap_update = True
            else:
                mtime = os.path.getmtime(mcap_cache_path)
                if pytime.time() - mtime > 86400:
                    need_mcap_update = True
                    
            if need_mcap_update:
                def run_mcap_script():
                    print("Starting background market cap update (daily sync)...")
                    try:
                        subprocess.run(["python3", "scripts/generate_mcap_cache.py"], check=True)
                        print("Finished background market cap update.")
                    except Exception as e:
                        print(f"Failed background market cap update: {e}")
                        
                # Run the update in a background thread so it doesn't block startup
                await loop.run_in_executor(None, run_mcap_script)
                
        except Exception as e:
            print(f"Error initializing equity engine: {e}")

    asyncio.create_task(init_equity())
    yield

app = FastAPI(title="Upstox Algo Trading Platform", lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files
app.mount("/static", StaticFiles(directory="src/api/static"), name="static")

# Include Modular Routers
app.include_router(ui_routes.router)
app.include_router(auth_api.router, prefix="/auth", tags=["Auth"])
app.include_router(equity_api.router, tags=["Equity"])
app.include_router(sync_api.router, prefix="/api/historical", tags=["Historical Sync"])
app.include_router(rs_api.router, prefix="/api/rs", tags=["Relative Strength"])
app.include_router(indices_etf_api.router, prefix="/api/macro", tags=["Macro & Sectors"])



@app.get("/callback")
async def root_callback(request: Request):
    query_string = request.url.query
    target_url = f"/auth/callback?{query_string}" if query_string else "/auth/callback"
    return RedirectResponse(url=target_url)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)
