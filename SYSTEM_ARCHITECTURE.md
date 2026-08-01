# System Architecture & Data Flow Documentation

This document provides a comprehensive audit and technical breakdown of the Quantitative Relative Strength (RS) platform. It covers data downloading, database stitching, calculations, and frontend rendering, with a focus on memory efficiency, nuances, and performance tuning.

---

## 1. Data Ingestion & Downloading Architecture

The platform aggregates data from multiple disparate sources simultaneously. The download architecture is built to be asynchronous, strictly rate-limited, and fault-tolerant.

### Sources
1. **Upstox API**: Provides daily OHLCV (Open, High, Low, Close, Volume) data for all NSE Equities and Indices.
2. **NSE India**: Provides daily Deliverable Volume and Delivery Percentage via historical HTML/CSV endpoints.
3. **NSE MTF (Margin Trading Facility)**: Provides daily zipped CSV reports of margin exposure per stock.
4. **Yahoo Finance (yfinance)**: Downloads global macro data (e.g., S&P 500, Dollar Index, Gold) for inter-market analysis.

### The "Stitching" Mechanism
Different sources provide different identifiers (e.g., Upstox uses `NSE_EQ|INE...`, NSE uses `RELIANCE`, Yahoo uses `RELIANCE.NS`). 
The stitching relies on a central `equities_master` map (fetched dynamically) that acts as the source of truth.
* All data is mapped to a universal `symbol` (e.g., `RELIANCE`) and a primary `timestamp` representing the trading day.
* Using SQL `ON CONFLICT` constraints and `timestamp` as the primary key, we achieve an **Upsert** (Update or Insert) pattern. This prevents duplicate data entries across partial syncs.

### Efficiency & Nuances
* **Rate-Limit Safeguards**: Upstox allows ~2000 requests per 30 minutes. `HistoricalEngine` enforces a strict `asyncio.sleep(1.0)` between requests.
* **Smart Resuming**: Before downloading, the engine queries `SELECT instrument_key, MAX(timestamp) FROM daily_candles`. It only downloads new data from `MAX(timestamp) + 1 day`, vastly reducing network I/O and API exhaustion.
* **Chunking**: Upstox errors out on horizons larger than 10 years (UDAPI1148). The engine recursively chunks requests in 3650-day windows.

---

## 2. Storage & Memory Efficiency (DuckDB)

We utilize **DuckDB** as our local data warehouse, split into three files:
* `market_data.duckdb` (Equities, Indices, Delivery, MTF)
* `macro_data.duckdb` (Global Macro Economic Data)
* `intraday_data.duckdb` (Intraday ETF Data)

### Efficiency Highlights
1. **Columnar Storage**: DuckDB is a columnar OLAP database. Unlike SQLite (row-based), DuckDB only loads the exact columns requested into RAM. If the frontend requests only `timestamp` and `close` to calculate Relative Strength, memory usage drops by 70%.
2. **Connection Polling & Concurrency**: Since background sync scripts (like `scripts/sync_mtf_1y.py`) run concurrently with the FastAPI server, DuckDB file-locking can cause `duckdb.IOException`. We've built `DatabaseManager` utilizing a robust retry mechanism (5 retries, 50ms intervals) to queue locks, preventing app crashes during simultaneous reads/writes.
3. **No Double Storage**: We avoid storing redundant merged tables. Instead, historical OHLCV, Delivery, and MTF data live in separate tables and are merged on-the-fly using highly optimized `JOIN` operations.

---

## 3. Calculation Engine (Polars)

The backend calculation engines (e.g., `PerformanceEngine`, `TrendEngine`) rely on **Polars**, a multi-threaded DataFrame library written in Rust.

### The Calculation Flow
1. **Fetch**: Query DuckDB for target stock OHLCV and Base Index OHLCV. 
2. **Merge**: `target_df.join(index_df, on="timestamp", how="left")`.
3. **Calculate**:
   * Stock Return over $N$ periods: $Price_{t} / Price_{t-N}$
   * Index Return over $N$ periods: $Index_{t} / Index_{t-N}$
   * **Relative Strength (RS)**: $(Stock Return / Index Return) - 1$
   * **RS EMA**: We use Polars `ewm_mean(span=length, adjust=False)` to natively calculate the Exponential Moving Average of RS in sub-milliseconds without Python `for` loops.

### Preventing Double Calculation & RAM Waste
* **Vectorization**: We avoid iterating over rows (`iterrows` or list comprehensions). By using `pl.col().shift()` and `pl.col().ewm_mean()`, all mathematics occur in contiguous memory blocks natively in Rust.
* **Lazy Evaluation**: While currently using Eager dataframes due to small single-stock query sizes, the Screener calculation across 5000+ stocks uses DuckDB window functions to push calculations directly to the C++ database engine. The data never enters Python RAM until the final sorted Screener table is produced.

---

## 4. Frontend Ploting & Rendering (Lightweight Charts)

The UI leverages **TradingView Lightweight Charts** running on standard Canvas/WebGL. 

### Rendering Flow & Deduplication
1. FastAPI returns a combined JSON payload of OHLCV, Delivery, MTF, and RS calculations.
2. The JS frontend maps this data into individual series: `lineSeries`, `rsSeries`, `totalVolumeSeries`, etc.
3. **Strict Deduplication (`uniqueByTime`)**: TradingView charts crash violently if two data points share the exact same UNIX timestamp. We run a strict deduplication pass based on the `Set()` data structure before invoking `.setData()`.

### Visual Nuances
* **Last Value Visibility**: To reduce Y-axis label clutter, we enforce `lastValueVisible: false` on secondary studies (like Traded Volume, Delivery %, and MTF changes). Only the Price and RS exact values are pinned to the axes.
* **Canvas Resizing**: Charts dynamically call `.timeScale().fitContent()` to optimize screen real-estate automatically based on the browser window size, preventing CPU overhead from constant redrawing.
* **Crosshair Synchronization**: Subscribing to `crosshairMove` on any single pane broadcasts the `param.time` event to all other panes (RS, Delivery, MTF) and dynamically updates a centralized HTML legend for O/H/L/C and indicator values. This prevents the charts from feeling disjointed.
