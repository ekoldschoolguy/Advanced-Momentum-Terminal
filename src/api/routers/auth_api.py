from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from src.api.dependencies import auth_manager

router = APIRouter()

@router.get("/login")
async def login():
    login_url = auth_manager.get_authorization_url()
    return RedirectResponse(url=login_url)

@router.get("/logout")
async def logout():
    auth_manager.clear_tokens()
    return RedirectResponse(url="/")

@router.get("/callback", response_class=HTMLResponse)
async def callback(code: str):
    success = await auth_manager.exchange_code_for_token(code)
    if success:
        return """
        <html>
            <body>
                <h2>Authentication Successful!</h2>
                <p>Redirecting back to dashboard...</p>
                <script>
                    setTimeout(function() {
                        window.location.href = "/";
                    }, 2000);
                </script>
            </body>
        </html>
        """
    else:
        return "Authentication failed. Check server logs."

