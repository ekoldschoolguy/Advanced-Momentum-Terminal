from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from src.api.dependencies import auth_manager, search_engine

router = APIRouter()

def render_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@router.get("/", response_class=HTMLResponse)
async def index():
    is_authenticated = auth_manager.is_token_valid()
    
    eq_stats = search_engine.get_stats()
    eq_status = (
        f"<div class='status-pill ok'><span class='dot'></span> Equity Engine Ready ({eq_stats['nse_equities']} NSE Stocks)</div>" 
        if eq_stats["is_loaded"] 
        else "<div class='status-pill warn'><span class='dot no-pulse'></span> Loading Equity Engine...</div>"
    )
    
    auth_status = (
        "<div class='status-pill ok'><span class='dot'></span> Connected to Upstox</div>"
        if is_authenticated
        else "<div class='status-pill err'><span class='dot no-pulse'></span> Not Authenticated</div>"
    )
    
    auth_action = ""
    if not is_authenticated:
        auth_action = "<a href='/auth/login' class='auth-btn login'>Login with Upstox</a>"
    else:
        auth_action = "<a href='/auth/logout' class='auth-btn logout'>Force Re-Login / Clear Token</a>"
    
    locked_class = "" if is_authenticated else "locked"
    
    with open("src/api/templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    return html.replace("{auth_status}", auth_status).replace("{eq_status}", eq_status).replace("{auth_action}", auth_action).replace("{locked_class}", locked_class)

@router.get("/historical_ui", response_class=HTMLResponse)
async def historical_ui(): return render_file("src/api/templates/historical_ui.html")



@router.get("/search_ui", response_class=HTMLResponse)
async def search_ui(): return render_file("src/api/templates/search_ui.html")

@router.get("/download_ui", response_class=HTMLResponse)
async def download_ui(): return render_file("src/api/templates/download_ui.html")

@router.get("/rs_ui", response_class=HTMLResponse)
async def rs_ui(): return render_file("src/api/templates/rs_ui.html")

@router.get("/screener_ui", response_class=HTMLResponse)
async def screener_ui(): return render_file("src/api/templates/rs_screener.html")

@router.get("/mtf_screener_ui", response_class=HTMLResponse)
async def mtf_screener_ui(): return render_file("src/api/templates/mtf_screener.html")



@router.get("/india_sectors_ui", response_class=HTMLResponse)
async def india_sectors_ui(): return render_file("src/api/templates/india_sectors_ui.html")


