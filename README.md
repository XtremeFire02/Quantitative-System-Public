# Quantitative Research & Paper Trading System — BTCUSDT Perpetual

A rigorous quantitative research project investigating return predictability in BTC perpetual futures, built on a formal 7-stage signal validation pipeline.

> **Disclaimer:** This is a research and paper trading system. It is not financial advice and does not claim guaranteed profitability. All results are from backtesting and live paper trading with no real capital at risk.

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
| Data fetchers | `app/data/` | DVOL from Deribit, price + funding from Binance FAPI |
| Signal engine | `app/signals/` | Strategy evaluators + dispatcher |
| Risk checks | `app/trading/risk.py` | Data staleness, per-strategy position limits |
| Portfolio risk | `app/trading/portfolio_risk.py` | Max positions, daily loss, strategy drawdown |
| Kill switch | `app/trading/kill_switch.py` | System-wide trade halt (DB-persisted) |
| Paper broker | `app/trading/paper_broker.py` | Open/close paper positions, update equity |
| PnL calculator | `app/trading/pnl.py` | Price return + funding − fees |
| Scheduler | `app/main.py` | APScheduler: daily signal job + 15-min exit check |
| API | `app/api/` | FastAPI routers (dashboard, signals, trades, risk, pipeline, …) |
| Database | `app/database.py` | SQLAlchemy ORM — 9 tables |

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
| `/signals` | Signals | Every daily evaluation with reason string |
| `/trades` | Trades | Full trade log: price return + funding − fees per trade |
| `/trades/:id` | Trade Detail | Per-trade PnL attribution and entry signal context |
| `/performance` | Performance | Equity curve, drawdown, Sharpe, yearly breakdown |
| `/forward-log` | ForwardLog | Shadow strategy log + independence monitor |
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
