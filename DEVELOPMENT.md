# Developer & Setup Guide

This document describes how to set up the development environment, configure the APIs, run data sync tasks, and boot the web application.

---

## 1. Environment Setup

### Prerequisites
*   Python 3.10 or higher
*   Valid Upstox API credentials (API Key, Secret, Redirect URI)

### Local Installation
1.  Navigate to the project root and create a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    # (or install core dependencies manually: fastapi uvicorn polars duckdb httpx yfinance pydantic)
    ```

---

## 2. Configuration (`.env`)

Create a `.env` file in the root directory with the following keys:

```ini
UPSTOX_API_KEY=your_api_key_here
UPSTOX_API_SECRET=your_api_secret_here
UPSTOX_REDIRECT_URI=http://127.0.0.1:8000/auth/callback
```

### Upstox Authentication Flow
1.  When the application starts, it reads credentials from `.env`.
2.  Navigate to `http://127.0.0.1:8000/` and click **Login with Upstox**.
3.  You will be redirected to the Upstox Login portal. Enter your OTP/PIN.
4.  Upstox will redirect back to `/auth/callback` with an authorization code.
5.  AMT exchanges this code for a persistent token, which is stored locally in `token.json`. Subsequent starts will use this token automatically.

---

## 3. Running the Server

Start the FastAPI application in development mode:

```bash
.venv/bin/uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

The terminal will be accessible at [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## 4. Ingestion & Bulk Data Sync

To build the databases from scratch:
1.  **Macro Sync**: Go to the **Data Sync Engine** dashboard inside the web UI (`/historical_ui`) and select **Global Macro**. Alternatively, trigger it programmatically:
    ```bash
    curl -X POST http://127.0.0.1:8000/api/historical/sync_all -H "Content-Type: application/json" -d '{"targets": ["global"]}'
    ```
2.  **Equity Master Sync**: The master equity list (`data/equities_master.json`) is downloaded automatically on server startup.
3.  **Historical Bulk Ingestion**: Go to the **Data Sync Engine** dashboard inside the web UI (`/historical_ui`) and select **Full Pipeline Sync** or trigger it programmatically:
    ```bash
    curl -X POST http://127.0.0.1:8000/api/historical/sync_all -H "Content-Type: application/json" -d '{"targets": ["equities", "indices", "delivery", "mtf", "intraday_etfs"]}'
    ```

---

## 5. Coding Best Practices

*   **DuckDB Connections**: Never open persistent write-connections across modules. Always use `db_manager.get_market_conn(read_only=True/False)` inside a `with` statement.
*   **Vectorization**: Avoid iterating over Polars series/dataframes. Use Polars expression trees (e.g. `col("close").rolling_mean()`) for high performance.
*   **API Lookups**: When resolving symbols, map them in-memory first using dictionary lookups instead of running $O(N \times M)$ linear list searches.
