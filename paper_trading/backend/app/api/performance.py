"""
Performance API — closed-trade statistics, equity curve, drawdown.

Statistical conventions
-----------------------
Sharpe annualization factor: sqrt(252).

This matches the convention used throughout the research code
(research/validated/A1/21_strategy_backtest.py, A2/23_phase3_eda.py, etc.)
so that live Sharpe is directly comparable to research baselines stored in
ExperimentRun.metrics. It is the "daily-bar" convention.

CAVEAT: N3_DVOL_LONG and P3_OIPD_DD are fixed-24h-hold strategies that fire
on a subset of daily evaluations (~80 trades/year for N3 in research). For
trade-based returns, the mathematically correct annualization is
sqrt(trades_per_year) — using sqrt(252) inflates the absolute Sharpe by
roughly sqrt(252/80) ≈ 1.77x. Internal-consistency with research is preserved
because both use the same factor, so drift detection (ratio of live/research
Sharpe in fwd_validation_report_job.py) remains valid.

Yearly breakdown Sharpe is highly noisy with ~10-20 trades/year (SE(SR)
under Lo 2002 is ~0.3-0.5 at that sample size). Per-year Sharpe is suppressed
to None when fewer than 10 closed trades fall in that calendar year.
"""
import math
from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import EquityCurve, Trade, get_db

_MIN_TRADES_FOR_YEARLY_SHARPE = 10  # below this, per-year Sharpe is too noisy to publish

router = APIRouter()


@router.get("/performance")
def get_performance(db: Session = Depends(get_db)):
    closed = db.query(Trade).filter(Trade.status == "closed").all()
    n = len(closed)

    if n == 0:
        return {
            "total_trades": 0,
            "total_pnl": 0.0,
            "total_pnl_bp": 0.0,
            "sharpe": None,
            "max_drawdown": 0.0,
            "win_rate": None,
            "average_win": None,
            "average_win_bp": None,
            "average_loss": None,
            "average_loss_bp": None,
            "profit_factor": None,
            "equity_history": [],
            "yearly_breakdown": [],
            "message": "No closed trades yet",
        }

    net_pnls = [t.net_pnl for t in closed if t.net_pnl is not None]
    net_pnls_bp = [t.net_pnl_bp for t in closed if t.net_pnl_bp is not None]

    winners = [p for p in net_pnls if p > 0]
    losers = [p for p in net_pnls if p < 0]

    total_pnl = sum(net_pnls)
    mean_pnl = total_pnl / len(net_pnls) if net_pnls else 0
    std_pnl = _std(net_pnls)
    sharpe = (mean_pnl / std_pnl * math.sqrt(252)) if std_pnl > 0 else None
    win_rate = len(winners) / n if n > 0 else 0
    avg_win = sum(winners) / len(winners) if winners else 0
    avg_loss = sum(losers) / len(losers) if losers else 0
    profit_factor = (sum(winners) / abs(sum(losers))) if losers else None

    # Equity curve for drawdown
    eq_rows = db.query(EquityCurve).order_by(EquityCurve.id.asc()).all()
    equities = [r.equity for r in eq_rows]
    max_dd = _max_drawdown(equities) if equities else 0

    equity_history = [
        {
            "timestamp": (
                (r.timestamp.replace(tzinfo=timezone.utc)
                 if r.timestamp.tzinfo is None else r.timestamp).isoformat()
                if r.timestamp else None
            ),
            "equity": r.equity,
            "drawdown": r.drawdown,
            "realised_pnl": r.realised_pnl,
        }
        for r in eq_rows
        if r.timestamp is not None
    ]

    # Per-year breakdown
    yearly = _yearly_breakdown(closed)

    return {
        "total_trades": n,
        "total_pnl": total_pnl,
        "total_pnl_bp": round(sum(net_pnls_bp), 1),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "average_win": round(avg_win, 6) if avg_win != 0 else 0.0,
        "average_win_bp": round(avg_win * 10000, 1),
        "average_loss": round(avg_loss, 6) if avg_loss != 0 else 0.0,
        "average_loss_bp": round(avg_loss * 10000, 1),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "equity_history": equity_history,
        "yearly_breakdown": yearly,
    }


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))


def _max_drawdown(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        dd = (e - peak) / peak if peak > 0 else 0.0
        max_dd = min(max_dd, dd)
    return max_dd


@router.get("/performance/by-strategy")
def get_performance_by_strategy(
    strategy: str | None = Query(default=None, description="Filter to one strategy"),
    db: Session = Depends(get_db),
):
    """Per-strategy performance breakdown.

    Returns separate stats for N3_DVOL_LONG, P3_OIPD_DD, and all
    relevant combinations so each signal can be evaluated independently.
    The key rows are:
      N3 only        — N3_DVOL_LONG trades on days P3 did not fire
      P3 only        — P3_OIPD_DD trades on days N3 did not fire
      N3 + P3        — all trades from either signal
      P3 excl N3     — P3 trades on days with no N3 trade (independence test)
    """
    closed = db.query(Trade).filter(Trade.status == "closed").all()
    if not closed:
        return {"strategies": [], "combinations": [], "message": "No closed trades yet"}

    # Group by strategy
    by_strat: dict[str, list[Trade]] = {}
    for t in closed:
        by_strat.setdefault(t.strategy_name, []).append(t)

    # Per-strategy stats
    strategies = []
    for sname, trades in sorted(by_strat.items()):
        if strategy and sname != strategy:
            continue
        stats = _trade_stats(trades)
        stats["strategy_name"] = sname
        strategies.append(stats)

    # Cross-strategy combination rows (only when both N3 and P3 present)
    n3_trades = by_strat.get("N3_DVOL_LONG", [])
    p3_trades = by_strat.get("P3_OIPD_DD", [])
    combinations = []

    if n3_trades and p3_trades:
        n3_dates = {_trade_date(t) for t in n3_trades}

        # P3 trades on days with no N3 trade (independence test)
        p3_excl = [t for t in p3_trades if _trade_date(t) not in n3_dates]
        # All trades combined (union)
        all_combined = n3_trades + p3_trades

        combinations = [
            {**_trade_stats(n3_trades),     "label": "N3 only"},
            {**_trade_stats(p3_trades),     "label": "P3 only (all)"},
            {**_trade_stats(p3_excl),       "label": "P3 excl N3 days"},
            {**_trade_stats(all_combined),  "label": "N3 + P3 combined"},
        ]

    return {
        "strategies":   strategies,
        "combinations": combinations,
    }


def _trade_date(t: Trade) -> str:
    ts = t.entry_timestamp
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%Y-%m-%d")


def _trade_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n_trades": 0, "sharpe": None, "total_pnl_bp": 0,
                "max_dd_bp": None, "win_rate": None, "avg_win_bp": None,
                "avg_loss_bp": None, "yearly": []}

    net_pnls    = [t.net_pnl    for t in trades if t.net_pnl    is not None]
    net_pnls_bp = [t.net_pnl_bp for t in trades if t.net_pnl_bp is not None]
    n           = len(net_pnls)
    if n == 0:
        return {"n_trades": len(trades), "sharpe": None, "total_pnl_bp": 0,
                "max_dd_bp": None, "win_rate": None, "avg_win_bp": None,
                "avg_loss_bp": None, "yearly": []}

    winners = [p for p in net_pnls if p > 0]
    losers  = [p for p in net_pnls if p < 0]
    total   = sum(net_pnls)
    mean    = total / n
    std     = _std(net_pnls)
    sharpe  = round(mean / std * math.sqrt(252), 3) if std > 0 else None

    # Running max drawdown (trade-by-trade)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in net_pnls:
        cum  += p
        peak  = max(peak, cum)
        dd    = (cum - peak) / peak if peak > 0 else 0.0
        max_dd = min(max_dd, dd)

    return {
        "n_trades":      n,
        "sharpe":        sharpe,
        "total_pnl_bp":  round(sum(net_pnls_bp), 1),
        "max_dd_bp":     round(max_dd * 10000, 1),
        "win_rate":      round(len(winners) / n, 4),
        "avg_win_bp":    round(sum(winners) / len(winners) * 10000, 1) if winners else None,
        "avg_loss_bp":   round(sum(losers)  / len(losers)  * 10000, 1) if losers  else None,
        "yearly":        _yearly_breakdown(trades),
    }


def _yearly_breakdown(trades: list[Trade]) -> list[dict]:
    years: dict[int, list[float]] = {}
    for t in trades:
        if t.exit_timestamp and t.net_pnl is not None:
            ts = t.exit_timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            yr = ts.year
            years.setdefault(yr, []).append(t.net_pnl)

    result = []
    for yr in sorted(years.keys()):
        pnls = years[yr]
        mean = sum(pnls) / len(pnls)
        std = _std(pnls)
        # Suppress Sharpe when sample is too small to be meaningful (see module docstring).
        if std > 0 and len(pnls) >= _MIN_TRADES_FOR_YEARLY_SHARPE:
            sharpe = mean / std * math.sqrt(252)
        else:
            sharpe = None
        result.append({
            "year": yr,
            "n_trades": len(pnls),
            "total_pnl_bp": round(sum(pnls) * 10000, 1),
            "sharpe": round(sharpe, 3) if sharpe else None,
            "win_rate": round(len([p for p in pnls if p > 0]) / len(pnls), 3),
        })
    return result
