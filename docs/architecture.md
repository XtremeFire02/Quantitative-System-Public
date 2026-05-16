# Architecture — Quantitative Trading Platform

_Last updated: 2026-05-15_

---

## Repository Layout

```
Quantitative-Framework/
│
├── framework/           Shared cost model and data splits (used by all layers)
│   ├── costs.py         CostModel dataclass — TAKER and MAKER convenience instances
│   ├── splits.py        Train/val/test date ranges
│   └── registry.py      Experiment metadata loader
│
├── experiments/         YAML metadata per research experiment
│   ├── B1.yaml          Phase 4 signals — killed at stage 4
│   └── B2.yaml          Phase 5 signals — killed at stage 4
│
├── scripts/
│   └── check_sync.py    Detects hardcoded split-date drift in active code
│
├── strategies/          Validated and shadow strategy implementations
│   └── base.py          Bar, Signal, Strategy base class (shared primitives)
│
├── archive/             Retired / experimental implementations (not in production)
│   └── strategies/
│       ├── cvd_strategy.py   CVD Divergence (killed)
│       └── vpin_strategy.py  VPIN Regime (killed)
│
├── backtest/            Event-driven backtest engine (used during research)
│   └── engine.py        BacktestEngine, Trade, compute_metrics
│
├── live/                Real-time 1m-bar simulator (WebSocket feed)
│   ├── simulator.py     Entry point — replay + live modes
│   ├── feed.py          Binance WebSocket bar stream
│   └── exchange.py      VirtualExchange (paper execution)
│
├── research/            Numbered hypothesis scripts, split by outcome
│   ├── README.md        7-stage pipeline and directory map
│   ├── validated/       Scripts for strategies in production (private)
│   └── killed*/         Scripts for hypotheses that failed validation
│
├── data/                Data download and processing scripts
│   ├── download*.py     Binance FAPI + Deribit public API downloaders
│   ├── raw/             Parquet files (excluded from git)
│   └── processed/       Derived features (excluded from git)
│
├── results/             Organised by origin
│   └── reports/
│       ├── killed reports/    LaTeX reports for killed phases (B1, B2)
│       └── validated reports/ LaTeX reports for validated phases (private)
│
├── paper_trading/       Production paper trading system
│   ├── backend/         FastAPI + SQLite backend (see below)
│   ├── frontend/        React + TypeScript dashboard
│   ├── docker-compose.yml
│   └── .env.example     Environment variable template
│
├── tests/               Cross-layer test suite
│
├── docs/
│   ├── architecture.md     This file
│   ├── runbook.md          Operational runbook (startup, kill switch, incident response)
│   └── frontend_report.tex Frontend architecture report
├── pyproject.toml       Root package config
└── .github/workflows/ci.yml  CI: pytest + tsc + build on every push
```

---

## Strategy Lifecycle

New research follows this progression. A script never stays permanently at the root of `research/` — it moves to `validated/` or `killed*/` once a verdict is reached.

```
New Hypothesis
    │
    ▼  research/NN_*.py  (numbered, at root during development)
Stage 2 IC screen → Stage 3 OOS → Stage 4 stress-test → Stage 5 regime →
Stage 6 backtest → Stage 7 forward validation
    │
    ├── FAIL (p > 0.05 OR Sharpe below threshold)
    │       ▼
    │   research/killed*/  +  experiment registry entry
    │   archive/strategies/  (if an implementation was written)
    │
    └── PASS
            ▼
        research/validated/<strategy>/  (scripts moved here)
        strategies/<strategy>.py        (frozen standalone implementation)
        paper_trading/backend/app/signals/<evaluator>.py  (live evaluator)
            ▼
        paper_trading/  shadow deployment ≥ 3 months forward log
            ▼
        status → validated / real capital
```

---

## Canonical Cost Model

**Single source of truth: `framework/costs.py`**

| Constant | Value | Location |
|---|---|---|
| Maker fee | 2 bp | `MAKER.maker_fee` |
| Slippage (est.) | 1 bp | `MAKER.slippage` |
| One-way cost | 3 bp | `MAKER.one_way_cost()` |
| Round-trip | 6 bp | `MAKER.round_trip_cost()` |

Paper trading mirrors this via `app/config.py`. Tests enforce this equivalence on every CI run.

---

## Experiment Registry

Every experiment is recorded as a YAML file in `experiments/`. This is the canonical source of metadata — hypothesis, status, stage reached, key metrics, and file pointers.

```python
from framework.registry import load_all, killed, summary
summary()    # print one-line status per experiment
```

**Required fields:**

| Field | Description |
|---|---|
| `id` | Matches the filename (B1, B2, …) |
| `status` | `validated` \| `killed` \| `in_progress` |
| `stage_reached` | Last pipeline stage completed (1–7) |
| `dataset.splits` | Must be `framework.splits` — never hardcode dates |
| `report` | Path to `.tex` report |
| `scripts` | Ordered list of `.py` files that produced the results |

---

## Paper Trading Backend (`paper_trading/backend/`)

```
app/
├── main.py              FastAPI app — registers all routers, APScheduler
├── config_registry.py   Available markets + strategies catalogue
├── database.py          SQLAlchemy ORM — 9 tables
├── alerts.py            Alert system (DB + optional SMTP email)
│
├── data/
│   ├── binance_client.py  Binance FAPI: price, mark price, funding, OI history
│   └── deribit_client.py  Deribit API: DVOL hourly bars, rolling mean/std
│
├── signals/
│   └── base.py           SignalResult dataclass, SignalEvaluator protocol
│
├── trading/
│   ├── pnl.py            calculate_pnl() — verified against framework/costs.py
│   ├── risk.py           Per-strategy pre-trade checks (data staleness, position limit)
│   ├── portfolio_risk.py Portfolio-level checks (max positions, daily loss, drawdown)
│   ├── execution_sim.py  Execution quality estimator
│   ├── kill_switch.py    System-wide trade halt (DB-persisted, survives restart)
│   └── paper_broker.py   open_trade(), close_trade(), equity curve update
│
├── jobs/
│   ├── daily_signal_job.py  00:00 UTC: kill switch → risk → evaluate → open trades
│   └── exit_trade_job.py    Every 15 min: close expired positions
│
└── api/
    ├── dashboard.py         GET /api/dashboard
    ├── signals.py           GET /api/signals/{latest,history}
    ├── trades.py            GET /api/trades
    ├── performance.py       GET /api/performance
    ├── replay.py            GET /api/replay
    ├── forward_log.py       GET /api/forward-log
    ├── system_health.py     GET /api/system/{health,logs}
    ├── data_quality.py      GET /api/system/data-quality
    ├── portfolio_risk.py    GET /api/risk/{state,limits}
    ├── kill_switch.py       GET/POST /api/risk/kill-switch
    ├── strategy_pipeline.py GET/POST /api/strategies
    ├── alerts.py            GET /api/alerts
    ├── experiments.py       GET/POST/PATCH /api/experiments
    ├── audit.py             GET /api/audit
    └── config.py            GET/POST/DELETE /api/config/{available,active}
```

---

## Database Schema (9 tables)

| Table | Purpose |
|---|---|
| `market_data` | Daily price + funding + volatility snapshot |
| `signals` | One row per strategy evaluation (entry/no-entry + reason) |
| `trades` | Full trade journal (entry, exit, PnL attribution) |
| `equity_curve` | Running equity, drawdown, realised PnL |
| `system_logs` | Structured logs (INFO/WARNING/ERROR per component) |
| `bot_configs` | Active market/strategy pairs (drives daily job) |
| `alerts` | Signal events, trade closes, data failures, risk blocks |
| `strategy_status` | Formal lifecycle stage per strategy |
| `experiment_runs` | Research run metadata (script, params, metrics, verdict) |

---

## Portfolio Risk Gates

All four checks run before any trade opens. A failure fires a `risk_blocked` alert.

| Gate | Limit | Config key |
|---|---|---|
| Total open positions | ≤ 3 | `PORTFOLIO_MAX_OPEN_POSITIONS` |
| Same-market positions | ≤ 2 | `PORTFOLIO_MAX_SAME_MARKET` |
| Daily loss | ≥ −500 bp | `PORTFOLIO_MAX_DAILY_LOSS_BP` |
| Strategy trailing drawdown | ≥ −20% | `PORTFOLIO_MAX_STRATEGY_DD_PCT` |

---

## Data Flow: Daily Signal Evaluation

```
00:00 UTC CronTrigger fires
    │
    ├─► check_kill_switch()      → abort if armed
    ├─► Fetch volatility index hourly bars → compute rolling z-score
    ├─► Fetch BTC price + funding rate
    ├─► Save MarketData row
    │
    └─► For each active BotConfig:
            evaluator = dispatcher[strategy_name]
            sig = await evaluator.evaluate(market)
            Save Signal row
            │
            └─► if sig.entry_signal:
                    check_kill_switch()
                    check_can_trade()
                    check_portfolio_risk()
                    estimate_execution()
                    open_trade()
                    fire_alert()
```

---

## Frontend (`paper_trading/frontend/`)

React + TypeScript SPA running on port 3000.

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | Live market data, signal status, open position, equity |
| `/signals` | Signals | Daily evaluation log with reasons |
| `/trades` | Trades | Full trade journal |
| `/trades/:id` | TradeDetail | Per-trade PnL attribution |
| `/performance` | Performance | Equity curve, Sharpe, yearly breakdown |
| `/replay` | Replay | Historical backtest verification |
| `/forward-log` | ForwardLog | Shadow strategy log |
| `/risk` | RiskDashboard | Portfolio exposure, limit gauges, kill switch |
| `/pipeline` | StrategyPipeline | Strategy lifecycle status editor |
| `/alerts` | Alerts | Alert inbox |
| `/data-quality` | DataQuality | Feed completeness and freshness |
| `/experiments` | Experiments | Research run log with metrics drilldown |
| `/health` | SystemHealth | Data freshness, scheduler, error logs |

---

## Running Locally

```bash
# Backend (port 8000)
cd paper_trading/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# Frontend (port 3000)
cd paper_trading/frontend
npm install && npm start

# Root-package tests
pip install -e .
python -m pytest tests/
```

## Running with Docker

```bash
cd paper_trading
cp .env.example .env
docker compose up --build
```
