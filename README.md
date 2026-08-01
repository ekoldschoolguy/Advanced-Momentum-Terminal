# Advanced Momentum Terminal (AMT)

Advanced Momentum Terminal is a high-performance quantitative research and trading intelligence dashboard designed for Indian markets. It implements advanced Relative Strength (RS) momentum screening, sector rotation analysis, relative rotation graphs (RRG), and market breadth metrics on top of NSE equities and global macro indexes.

## Application Interface

### RS Screener
![RS Screener](assets/rs_screener.png)
The **RS Screener** provides a blazing-fast, cross-sectional view of the stock universe. It allows you to scan and rank stocks based on custom momentum scores (CMS Score), margin funding (MTF) data, and timeframe performance relative to a base index. The screener uses optimized in-memory lookups for near-instant filtering across thousands of instruments.
<img width="1907" height="948" alt="image" src="https://github.com/user-attachments/assets/2cfded8a-8327-4f69-8786-9f5242f8dc08" />

### RS Engine
![RS Engine](assets/rs_engine.png)
The **RS Engine** provides an advanced charting interface for deep-dive single-stock analysis. It overlays absolute price action with a proprietary Relative Strength oscillator, a Volatility-Adjusted Trend Indicator, and historical Margin Trading Facility (MTF) exposure to identify high-conviction breakout setups with institutional backing.
<img width="1907" height="948" alt="image" src="https://github.com/user-attachments/assets/52f77f27-528c-49a1-9cdd-0533dde2b556" />

### Sector Rotation Map
![Sector Rotation](assets/india_sectors.png)
The **India Sector Rotation Map** leverages Relative Rotation Graphs (RRG) to visualize capital flow and momentum shifts across NSE Sector Indices. By plotting RS-Ratio vs RS-Momentum, it helps traders quickly identify which sectors are entering the "Leading" or "Improving" quadrants to stay ahead of market rotation cycles.
<img width="1907" height="948" alt="image" src="https://github.com/user-attachments/assets/ee5dafbf-4abd-4e91-8390-ccb1ff02d1fa" />

## Core Features
*   **Relative Strength (RS) Engine**: Vectorized Polars-based engine calculating absolute and relative momentum.
*   **Volatility-Adjusted Trend Indicator**: Real-time detrended price oscillator to identify smooth breakouts vs choppy action.
*   **Real-time Momentum Screener**: Blazing-fast cross-sectional stock screening using O(1) in-memory metadata mappings.
*   **Systemic Market Breadth**: Historical tracking of the percentage of stocks outperforming a benchmark index over time.
*   **India Sectors & ETFs**: Interactive heatmaps, relative rotation graphs (RRG), and sectoral ETF scan tools.
*   **Data Sync Engine**: Structured background pipeline leveraging Upstox API and yfinance to feed a dual-instance DuckDB database.

## System Architecture

For a detailed walkthrough of the technical design, database schemas, and mathematical calculations, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## Getting Started

To install dependencies and run the application locally, refer to [DEVELOPMENT.md](./DEVELOPMENT.md).
