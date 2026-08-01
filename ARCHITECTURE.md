# System Architecture & Technical Specifications

This document outlines the architectural blueprint, data flows, database schemas, and mathematical methodologies behind the **Advanced Momentum Terminal (AMT)**.

---

## 1. Directory Structure

```text
Daily-report/
├── database/               # Analytical DuckDB database storage
│   ├── market_data.duckdb  # Daily equity and index candles
│   ├── macro_data.duckdb   # Global macro indexes
│   └── intraday_data.duckdb # Intraday ETF data
├── data/                   # Cache directory
│   ├── equities_master.json # Filtered Upstox master instruments
│   ├── mcap_cache.json     # Market capitalization cache
│   └── universes/          # Predefined index constituent CSV files
├── scripts/                # Standalone data sync scripts
│   ├── sync_mtf_1y.py
│   ├── sync_delivery_1y.py
│   └── ...
├── src/
│   ├── api/                # FastAPI Application Shell
│   │   ├── routers/        # Modular API routes (auth, macro, rs, sync)
│   │   ├── templates/      # HTML5 dashboard templates
│   │   └── main.py         # App entry point and context initialization
│   ├── engines/            # Numerical and analytical computational cores
│   │   ├── search_engine.py      # O(1) in-memory stock metadata registry
│   │   ├── historical_engine.py  # Data sync & DB persistence layer
│   │   ├── macro_engine.py       # Sector Heatmaps & RRG calculations
│   │   ├── performance_engine.py # Vectorized Polars Performance & Breadth core
│   │   ├── mtf_engine.py         # MTF logic and processing
│   │   ├── trend_engine.py       # Volatility-adjusted trend calculations
│   └── managers/           # Database and resource managers (including auth)
```

---

## 2. Database Design & Schemas

AMT utilizes a split-database architecture in **DuckDB** to separate high-volume market price series from configuration and global macro data. Both databases use context-managed connections with built-in retry capabilities to prevent file locking issues during background syncs.

### A. `market_data.duckdb`
Contains time-series price data for NSE equities and indices.

*   **Table**: `daily_candles`
    *   `instrument_key` (VARCHAR, PK part 1): Ex. `NSE_EQ|INE002A01018`
    *   `timestamp` (TIMESTAMP, PK part 2): Candle date
    *   `open` (DOUBLE): Open price
    *   `high` (DOUBLE): High price
    *   `low` (DOUBLE): Low price
    *   `close` (DOUBLE): Close price
    *   `volume` (BIGINT): Trading volume
    *   `open_interest` (BIGINT): Derivative open interest (0 if not applicable)

### B. `macro_data.duckdb`
Contains global asset price feeds.

*   **Table**: `global_candles`
    *   `symbol` (VARCHAR, PK part 1): Yahoo Finance ticker (Ex. `SPY`, `^NSEI`)
    *   `timestamp` (TIMESTAMP, PK part 2): Date
    *   `close` (DOUBLE): Adjusted closing price


---

## 3. Mathematical Calculations

### A. Relative Strength (RS)
Calculated matching the TradingView PineScript engine logic over a specific length ($L$, default 123 days):

$$RS_t = \frac{Price_{Stock, t} / Price_{Stock, t-L}}{Price_{Index, t} / Price_{Index, t-L}} - 1$$

The engine also provides:
*   **RS SMA**: Simple Moving Average of $RS$ over a specified length (default 50 days).
*   **Price SMA**: Simple Moving Average of the stock price for basic trend confirmation.

### B. Historical Relative Strength Market Breadth
Breadth is defined as the percentage of index constituents outperforming the index over the specified period:

$$\text{Breadth } \%_t = \frac{\sum_{i=1}^{N} \mathbb{I}(RS_{i, t} > 0)}{N} \times 100$$

Where $\mathbb{I}$ is the indicator function. 
*Nuance: To ensure exact date alignment, the index close price is joined onto the stock price series before performing the historical window shift (LEAD/LAG).*

### C. Volatility-Adjusted Trend Indicator
The Trend Indicator provides a detrended, volatility-adjusted measure of price momentum:

1.  **Calculate Day-to-Day Percentage Change (`ccr`)**:
    $$ccr_t = \frac{Price_t - Price_{t-1}}{Price_{t-1}}$$
2.  **Calculate Absolute Change (`ccv`)**:
    $$ccv_t = |ccr_t|$$
3.  **Smooth with EMA**: Apply an Exponential Moving Average (default span 21).
    $$EMA_{ccr} = EMA(ccr_t, 21)$$
    $$EMA_{ccv} = EMA(ccv_t, 21)$$
4.  **Trend Ratio ($P$)**: 
    $$P_t = \frac{EMA_{ccr}}{EMA_{ccv}}$$
    This ratio normalizes between -1.0 and +1.0, identifying smooth uptrends versus choppy sideways action.

### D. Relative Rotation Graphs (RRG)
RRG values are computed weekly (resampled to Friday close) using a trailing rolling window of 52 weeks to calculate Z-scores:

1.  **Relative Strength Ratio (RS-Ratio)**:
    Let $RS = \frac{Price_{Asset}}{Price_{Benchmark}} \times 100$. Smooth $RS$ using an Exponential Moving Average (EMA, span=10):
    $$RS_{smooth} = \text{EMA}(RS, 10)$$
    Compute the Rolling Mean ($\mu$) and Rolling Standard Deviation ($\sigma$) of $RS_{smooth}$ over a 52-week window:
    $$\text{RS-Ratio} = 100 + \left(\frac{RS_{smooth} - \mu_{RS}}{\sigma_{RS}}\right) \times 2$$

2.  **Relative Strength Momentum (RS-Momentum)**:
    Compute the weekly difference of the RS-Ratio:
    $$RS_{diff} = \text{RS-Ratio}_t - \text{RS-Ratio}_{t-1}$$
    Smooth the difference:
    $$Mom_{smooth} = \text{EMA}(RS_{diff}, 5)$$
    Compute the Rolling Mean ($\mu_{Mom}$) and Standard Deviation ($\sigma_{Mom}$) over a 52-week window:
    $$\text{RS-Momentum} = 100 + \left(\frac{Mom_{smooth} - \mu_{Mom}}{\sigma_{Mom}}\right) \times 2$$
