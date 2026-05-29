# Quantitative Research & Paper Trading System

A personal research project applying systematic signal validation to BTC perpetual futures. Built from scratch over several months — every component, from the backtest engine to the live paper trading dashboard, was written without external backtesting or trading frameworks (FastAPI, React, and standard scientific Python libraries are used for infrastructure).

The goal was not to build a black-box strategy optimizer. It was to build a system rigorous enough that I could trust a rejection.

> **Disclaimer:** This is a research and paper trading system. It is not financial advice and does not claim guaranteed profitability. All results are from backtesting and live paper trading with no real capital at risk. Signal parameters for validated strategies are kept private.

---

## What I Built

| Layer | Stack | What it does |
|---|---|---|
| Research pipeline | Python, pandas, SciPy | 7-stage signal validation with pre-specified kill criteria |
| Backtest engine | Python (event-driven) | Position-level simulation with realistic costs and funding |
| Paper trading backend | FastAPI, APScheduler, SQLite | Runs daily signal jobs at 00:00 UTC, tracks PnL and equity |
| Live data feeds | Binance FAPI, Deribit API | Price, funding rate, open interest, implied volatility |
| Risk system | Python | Pre-trade and portfolio-level gates; DB-persisted kill switch |
| Dashboard | React 19, TypeScript, Recharts | 12-page SPA with real-time signal, trade, and performance views |
| Infrastructure | Docker, GitHub Actions CI | Containerised deploy; pytest + tsc on every push |

---

## Pipeline Status (May 2026)

Every hypothesis is tracked from formation to a binary verdict. Nothing is abandoned without a formal kill or promotion decision.

| Phase | Signals Tested | Verdict | Stage Reached | Report |
|---|---|---|---|---|
| B1 | Q5c — Mark-Index Basis / Cross-Asset IV / Liquidation Exhaustion | Killed | Stage 4 | [`B1.tex`](results/reports/killed%20reports/B1.tex) |
| B2 | S1a — Realized Skewness | Killed | Stage 4 | [`B2.tex`](results/reports/killed%20reports/B2.tex) |
| B2 | S1b — Pre-Settlement Flow | Killed | Stage 2 | [`B2.tex`](results/reports/killed%20reports/B2.tex) |
| B2 | S1c — Cross-Exchange Funding Divergence | Killed | Stage 2 | [`B2.tex`](results/reports/killed%20reports/B2.tex) |
| Archive | CVD Divergence, VPIN Regime | Killed | Early stages | — |
| A1 | N3 — DVOL Z-Score signal | **Validated** | Stage 7 — live paper trading | [`A1.tex`](results/reports/validated%20reports/A1.tex) |
| A2 | P1 (VRP), P2 (TAR), P3 (OI-Price Divergence) | P3 Validated; P1/P2 Killed | Stage 7 (P3) | [`A2.tex`](results/reports/validated%20reports/A2.tex) |

The kill reports for B1 and B2 are full LaTeX documents with IC results, bootstrap confidence intervals, regime breakdowns, and cost-adjusted PnL tables. The validated signal reports (A1, A2) include the full statistical methodology and out-of-sample results; specific entry thresholds are withheld.

---

## Research Pipeline

Every signal passes through this 7-stage pipeline. A signal is killed the moment it fails a pre-specified threshold at any stage. No stage is skipped.

```
Stage 1 — Generate Hypothesis
         Form a hypothesis about why a signal should predict returns.
         State the proposed mechanism, the expected direction, and the
         holding period. No data is touched at this stage.

Stage 2 — Initial Statistical Screen
         Apply a fast, low-cost quantitative filter on in-sample data.
         Signals that fail here are killed immediately.
         (Spearman IC vs. breakeven IC threshold, hit rate vs. random baseline)

Stage 3 — Out-of-Sample Validation
         Test the signal on data it has never seen, controlling for serial
         dependence, non-normality, and multiple comparisons.
         (non-overlapping daily returns, one-sided block bootstrap p ≤ 0.05)

Stage 4 — Stress Testing
         Deliberately attempt to invalidate the signal. Extended evaluation
         window, regime splits, most unfavourable cost assumptions.

Stage 5 — Regime Conditioning
         Identify structural conditions where the signal has edge and those
         where it does not.

Stage 6 — Cost-Adjusted Backtest
         Simulate at the position level with realistic transaction costs,
         market impact, and carry.

Stage 7 — Forward Validation
         Deploy the frozen, unmodified rule to paper trading. No parameter
         changes permitted during this stage. Minimum 3-month observation
         window before promotion.
```

---

## Repository Structure

```
Quantitative-Framework/
├── data/
│   ├── raw/                    # Parquet files — NOT in GitHub (see Data section)
│   ├── processed/              # Derived features — NOT in GitHub
│   └── download*.py            # Download scripts for Binance + Deribit public APIs
├── framework/                  # Shared infrastructure
│   ├── costs.py                # CostModel — single source of truth for fees
│   ├── splits.py               # Train / val / test date ranges
│   └── registry.py             # Experiment metadata loader
├── experiments/                # YAML metadata per research experiment
│   ├── B1.yaml                 # Phase 4 — killed at stage 4
│   └── B2.yaml                 # Phase 5 — killed at stage 4
├── scripts/
│   └── check_sync.py           # Detects hardcoded split-date drift
├── backtest/
│   └── engine.py               # Generic event-driven backtest engine
├── strategies/
│   └── base.py                 # Bar, Signal, Strategy base classes
├── archive/strategies/         # Retired implementations (CVD, VPIN — killed)
├── live/                       # Real-time 1m-bar simulator (WebSocket feed)
├── research/
│   ├── README.md               # 7-stage pipeline and directory map
│   ├── validated/              # Research trails for validated strategies (scripts private)
│   ├── killed (Failed Stage 2)/  # Killed at IC screen
│   └── killed (Failed Stage 4)/  # Killed at stress testing
├── paper_trading/
│   ├── backend/                # FastAPI + APScheduler + SQLite
│   └── frontend/               # React + TypeScript dashboard
├── results/
│   └── reports/
│       ├── killed reports/     # Full LaTeX reports for killed phases (B1, B2)
│       └── validated reports/  # Reports for validated phases (private)
├── tests/                      # Unit tests
├── docs/
│   ├── architecture.md         # System architecture
│   └── runbook.md              # Operational runbook
└── pyproject.toml
```

---

## Framework Components

### Cost Model (`framework/costs.py`)

Single source of truth for all transaction costs. All research scripts, the backtest engine, and the paper trading backend import from here.

```python
from framework.costs import MAKER, TAKER

MAKER.round_trip_cost()   # 6 bp (entry + exit, maker fills)
TAKER.round_trip_cost()   # 10 bp (entry + exit, taker fills)
```

### Data Splits (`framework/splits.py`)

Canonical train/val/test boundaries shared across all layers:

```
Train : 2023-01-01 → 2023-12-31  (~60%)
Val   : 2024-01-01 → 2024-06-30  (~20%)
Test  : 2024-07-01 → 2024-12-31  (~20%)
```

```python
from framework.splits import TRAIN_END, VAL_END, split, get_split
train, val, test = split(df)
```

### Experiment Registry (`framework/registry.py`)

Loads YAML metadata files from `experiments/` and provides a structured query interface.

```python
from framework.registry import load_all, killed, summary
summary()    # print status of every registered experiment
killed()     # list of killed-experiment dicts
```

---

## Backend Architecture

```
Deribit API ────► Signal Engine ────► Paper Broker ────► SQLite DB
                       │                                       │
Binance FAPI ──────────┘ (price + funding)                    │
                                                               ▼
                                                     FastAPI REST API
                                                               │
                                                               ▼
                                                  React Dashboard (port 3000)
```

| Component | File | Purpose |
|---|---|---|
| Data fetchers | `app/data/` | DVOL from Deribit, price + funding + OI from Binance FAPI |
| Signal engine | `app/signals/` | Strategy evaluators + dispatcher |
| Risk checks | `app/trading/risk.py` | Data staleness, per-strategy position limits |
| Portfolio risk | `app/trading/portfolio_risk.py` | Max positions, daily loss, strategy drawdown, consecutive losses |
| Kill switch | `app/trading/kill_switch.py` | System-wide trade halt (DB-persisted) |
| Paper broker | `app/trading/paper_broker.py` | Open/close paper positions, update equity |
| OMS | `app/trading/oms.py` | Order management — pre-trade risk gate before broker submit |
| Position sizer | `app/trading/position_sizer.py` | Fixed and volatility-scaled sizing modes |
| Broker adapter | `app/trading/broker_adapter.py` | Abstract broker interface; live adapter for future exchange integration |
| PnL calculator | `app/trading/pnl.py` | Price return + funding − fees |
| Scheduler | `app/main.py` | APScheduler: daily signal job + 15-min exit check + fwd validation report |
| API | `app/api/` | FastAPI routers (dashboard, signals, trades, risk, analytics, market monitor, options, …) |
| Database | `app/database.py` | SQLAlchemy ORM — 13 tables |

**Scheduled jobs:**

| Job | Schedule | Action |
|---|---|---|
| Daily signal | 00:00 UTC | Fetch market data → evaluate strategies → open trades if signal fires |
| Exit check | Every 15 min | Close any position whose hold period has elapsed |

---

## Frontend Architecture

**Stack:** React 19 · TypeScript 4.9 · Recharts 3 · React Router v7

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | Live market data, signal status, open position, equity |
| `/chart` | Chart | Interactive OHLCV price chart with signal overlays |
| `/monitor` | MarketMonitor | Real-time BTC market snapshot (price, OI, funding, DVOL) |
| `/options` | Options | Deribit options chain and IV surface overview |
| `/vol-surface` | VolSurface | Implied volatility surface visualisation |
| `/news` | News | Crypto news feed with sentiment tagging |
| `/analytics` | Analytics | Signal analytics: regime breakdown, IC series, return distributions |
| `/signals` | Signals | Every daily evaluation with reason string |
| `/trades` | Trades | Full trade log: price return + funding − fees per trade |
| `/trades/:id` | Trade Detail | Per-trade PnL attribution and entry signal context |
| `/performance` | Performance | Equity curve, drawdown, Sharpe, yearly breakdown |
| `/replay` | Replay | Historical signal replay — step through past evaluations |
| `/forward-log` | ForwardLog | Shadow strategy log + N3/P3 independence monitor |
| `/forward-validation` | ForwardValidation | Automated 3-month forward validation report |
| `/portfolio` | Portfolio | Multi-strategy portfolio exposure and correlation view |
| `/risk` | RiskDashboard | Portfolio exposure, limit gauges, kill switch |
| `/pipeline` | StrategyPipeline | Strategy lifecycle status editor |
| `/alerts` | Alerts | Alert inbox with category filter |
| `/data-quality` | DataQuality | Feed completeness and freshness checks |
| `/experiments` | Experiments | Research run log with metrics drilldown |
| `/health` | SystemHealth | Data freshness, scheduler status, error logs |

---

## How to Run Locally

### Prerequisites

- Python 3.11+
- Node.js 18+

### Backend

```bash
cd paper_trading/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd paper_trading/frontend
npm install
npm start
```

Dashboard: http://localhost:3000

### Docker

```bash
cd paper_trading
cp .env.example .env   # fill in ALERT_* if email alerts wanted
docker compose up --build
```

---

## Sync Checker

Detects split-date drift between `framework/splits.py` and active research scripts:

```bash
python scripts/check_sync.py
```

---

## Data

**Excluded from GitHub** (large binary files):

| File | Contents |
|---|---|
| `data/raw/BTCUSDT_1m_klines.parquet` | BTC/USDT 1m OHLCV, 2023–2026 |
| `data/raw/BTC_deribit_dvol_1h.parquet` | Deribit DVOL hourly |
| `data/raw/BTCUSDT_funding.parquet` | Binance 8h funding rates |
| `data/raw/BTCUSDT_oi_5m.parquet` | Open interest 5m |
| `data/processed/` | Derived signals |

To download fresh data:

```bash
python data/download.py          # 1m klines + funding
python data/download_phase2.py   # DVOL + OI
```

---

## PnL Accounting

```
Net PnL = direction × (log(exit_price / entry_price) − Σ funding_8h) − 2 × maker_fee
```

- Funding: sum of all 8h settlements during the hold period (positive rate = long pays)
- Maker fee: 0.03% per leg (`framework/costs.py` — `MAKER.one_way_cost()`)

---

## Portfolio Risk Gates

All four checks run before any trade opens. A failure fires an alert.

| Gate | Limit |
|---|---|
| Total open positions | ≤ 3 |
| Same-market positions | ≤ 2 |
| Daily loss | ≥ −500 bp |
| Strategy trailing drawdown | ≥ −20% |

---

## License

Research and educational use only. Not a trading system for live capital.
