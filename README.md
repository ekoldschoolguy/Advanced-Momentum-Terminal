# Advanced Momentum Terminal (AMT)

Advanced Momentum Terminal is a high-performance quantitative research and trading intelligence dashboard designed for Indian markets. It implements advanced Relative Strength (RS) momentum screening, sector rotation analysis, relative rotation graphs (RRG), and market breadth metrics on top of NSE equities and global macro indexes.

## Core Features
*   **Relative Strength (RS) Engine**: Vectorized Polars-based engine calculating absolute and relative momentum.
*   **Volatility-Adjusted Trend Indicator**: Real-time detrended price oscillator to identify smooth breakouts vs choppy action.
*   **Real-time Momentum Screener**: Blazing-fast cross-sectional stock screening using O(1) in-memory metadata mappings.
*   **Systemic Market Breadth**: Historical tracking of the percentage of stocks outperforming a benchmark index over time.
*   **India Sectors & ETFs**: Interactive heatmaps, relative rotation graphs (RRG), and sectoral ETF scan tools.
*   **Global Macro Pulse**: Multi-asset class rotation trackers and US Sector SPDR heatmap feeds.
*   **Data Sync Engine**: Structured background pipeline leveraging Upstox API and yfinance to feed a dual-instance DuckDB database.

## System Architecture

For a detailed walkthrough of the technical design, database schemas, and mathematical calculations, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## Getting Started

To install dependencies and run the application locally, refer to [DEVELOPMENT.md](./DEVELOPMENT.md).
