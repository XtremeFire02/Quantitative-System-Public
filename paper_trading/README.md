# Paper Trading System

Paper trading validation for quantitative strategies on BTCUSDT perpetual futures.
The objective: verify that live paper performance matches the research backtest.

Strategy parameters and entry rules are private and not included in this repository.
The signal evaluators are implemented in the private `app/signals/` modules.

---

## Quick start

### 1. Backend

```
cd paper_trading/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

### 2. Frontend

```
cd paper_trading/frontend
npm start
```

- Dashboard: http://localhost:3000

---

## How it works

The backend scheduler runs two jobs automatically once uvicorn is running:

| Job | Schedule | What it does |
|---|---|---|
| Daily signal job | 00:00 UTC | Fetch market data → evaluate strategies → open trade if signal fires |
| Exit check | Every 15 min | Close any open trade whose hold period has elapsed, calculate full PnL |

To trigger manually (for testing), use the **Run Signal Now** button on the Dashboard, or call:

```
POST http://localhost:8000/api/jobs/run-daily-signal
POST http://localhost:8000/api/jobs/check-exits
```

---

## Pages

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Live market data, signal status, open position, equity |
| Signals | `/signals` | Every daily evaluation with reason — proves the frozen rule was obeyed |
| Trades | `/trades` | Full PnL breakdown per trade: price return + funding − fees |
| Trade Detail | `/trades/:id` | Per-trade PnL attribution and entry signal context |
| Performance | `/performance` | Equity curve, drawdown, Sharpe, win rate, year-by-year |
| System Health | `/health` | Data freshness, scheduler status, error logs |

---

## PnL accounting

```
Net PnL = position × (price_return − funding_paid) − entry_cost − exit_cost
```

Where:
- `funding_paid` = sum of all 8h settlements during the hold period (positive = longs pay)
- `entry_cost` = maker fee + slippage = 0.03% per leg (`framework/costs.py`)
- `exit_cost` = same

---

## Database

SQLite at `backend/paper_trading.db`.

| Table | Contents |
|---|---|
| `market_data` | BTC price, mark price, funding rate, DVOL per fetch |
| `signals` | Every daily strategy evaluation with reason |
| `trades` | All paper trades with full PnL attribution |
| `equity_curve` | Running equity, realised PnL, drawdown |
| `system_logs` | INFO / WARNING / ERROR from all jobs |

---

## Stack

- **Backend**: Python · FastAPI · SQLAlchemy · APScheduler · SQLite
- **Frontend**: React · TypeScript · Recharts · React Router
- **Data**: Deribit DVOL API · Binance FAPI
