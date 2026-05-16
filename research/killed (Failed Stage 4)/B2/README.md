# Phase 5 Research — Novel High-Frequency Signals

**Status: All signals killed (2026-05-15)**

Phase 5 searched for signals with higher trade frequency than the N3/P3 stack.
No standalone viable signal was found. The fundamental finding is that edge in
BTCUSDT perpetuals remains concentrated in high-DVOL fear events, which are
by nature infrequent.

---

## Scripts

| Script | Purpose | Result |
|--------|---------|--------|
| `27_phase5_ic_screen.py` | IC screen for S1a/S1b (realized skewness), S2a/S2b (pre-settlement flow), S3a/S3b (cross-exchange funding divergence) | S1a advances; all others killed |
| `28_s1a_deep_dive.py` | Full deep dive for S1a: CI, incremental IC vs N3z, standalone vs regime-conditioned backtest | S1a killed (CI lower bound -0.008, not significant after N3z control) |

## Data requirements

- 1-minute BTCUSDT klines: `data/raw/BTCUSDT_*.parquet` (existing)
- Bybit funding rates: `data/raw/BTCUSDT_bybit_funding.parquet` (download via `data/download_phase5.py --bybit`)
- OKX funding rates: `data/raw/BTCUSDT_okx_funding.parquet` (only ~90 days available; S3b untestable)

## Kill summary

| Signal | Kill reason |
|--------|------------|
| S1a Realized skewness (contrarian) | CI lower bound -0.008; incremental IC p=0.234; loses money outside N3 regime (Sharpe -2.26) |
| S1b Skewness velocity | Wrong direction (2/5 stability, p=0.754) |
| S2a Pre-settlement flow × funding | Near-zero IC (0.04x), p=0.484 |
| S2b Pre-settlement flow contrarian | Below threshold (0.47x); DVOL-filtered 0.02x |
| S3a Bybit−Binance divergence | Wrong direction (2/5, p=0.840) |
| S3b OKX−Binance divergence | OKX API retains ~90 days only; insufficient OOS data |

## Research report

See `results/reports/A4.tex` for the full Phase 5 research document.
