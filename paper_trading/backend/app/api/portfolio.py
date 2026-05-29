"""
Portfolio attribution API.

GET /api/portfolio/attribution
    Per-strategy P&L contribution, Sharpe decomposition, open exposure,
    and N3↔P3 return correlation on overlapping trade dates.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import POSITION_NOTIONAL_USD
from app.database import Trade, get_db

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "sharpe": None, "total_pnl_bp": 0.0,
                "avg_pnl_bp": None, "win_rate": None, "max_dd_bp": None}
    n = len(pnls)
    mu = sum(pnls) / n
    var = sum((x - mu) ** 2 for x in pnls) / max(n - 1, 1)
    std = math.sqrt(var)
    sh = round(mu / std * math.sqrt(252), 3) if std > 0 else None

    # Running max-drawdown on cumulative P&L
    peak = cum = max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)

    return {
        "n":            n,
        "sharpe":       sh,
        "total_pnl_bp": round(sum(pnls), 1),
        "avg_pnl_bp":   round(mu, 2),
        "win_rate":     round(sum(1 for p in pnls if p > 0) / n, 3),
        "max_dd_bp":    round(max_dd, 1),
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / (n - 1))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / (n - 1))
    if sx == 0 or sy == 0:
        return None
    return round(cov / (sx * sy), 3)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/portfolio/attribution")
def get_portfolio_attribution(db: Session = Depends(get_db)):
    """
    Multi-strategy portfolio attribution.

    Returns per-strategy closed-trade statistics with portfolio contribution
    percentages, cross-strategy return correlation, and current open exposure.
    """
    closed = db.query(Trade).filter(Trade.status == "closed").all()
    open_trades = db.query(Trade).filter(Trade.status == "open").all()

    # Group by strategy
    by_strategy: dict[str, list[Trade]] = {}
    for t in closed:
        by_strategy.setdefault(t.strategy_name, []).append(t)

    # Portfolio total for contribution pct
    all_pnls = [t.net_pnl_bp for t in closed if t.net_pnl_bp is not None]
    portfolio_total_bp = sum(all_pnls)

    # Per-strategy attribution rows
    rows = []
    for name, trades in sorted(by_strategy.items()):
        pnls = [t.net_pnl_bp for t in trades if t.net_pnl_bp is not None]
        notionals = [t.notional_usd for t in trades if t.notional_usd]
        avg_notional = sum(notionals) / len(notionals) if notionals else POSITION_NOTIONAL_USD
        st = _stats(pnls)
        contribution_pct = (
            round(st["total_pnl_bp"] / portfolio_total_bp * 100, 1)
            if portfolio_total_bp != 0 else 0.0
        )
        rows.append({
            "strategy":          name,
            "avg_notional_usd":  round(avg_notional, 0),
            "contribution_pct":  contribution_pct,
            **st,
        })

    # N3 ↔ P3 correlation on overlapping trade dates
    n3_by_date: dict[str, float] = {}
    p3_by_date: dict[str, float] = {}
    for name, trades in by_strategy.items():
        for t in trades:
            if t.net_pnl_bp is None or not t.entry_timestamp:
                continue
            ts = t.entry_timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            date = ts.strftime("%Y-%m-%d")
            if name == "N3_DVOL_LONG":
                n3_by_date[date] = t.net_pnl_bp
            elif name.startswith("P3"):
                p3_by_date[date] = t.net_pnl_bp

    common = sorted(set(n3_by_date) & set(p3_by_date))
    correlation = _pearson(
        [n3_by_date[d] for d in common],
        [p3_by_date[d] for d in common],
    )

    def _iso(ts) -> str | None:
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()

    # Open exposure breakdown
    open_exposure = [
        {
            "strategy":        t.strategy_name,
            "market":          t.market,
            "side":            t.side,
            "notional_usd":    t.notional_usd or POSITION_NOTIONAL_USD,
            "entry_timestamp": _iso(t.entry_timestamp),
            "planned_exit":    _iso(t.planned_exit_timestamp),
        }
        for t in open_trades
    ]
    total_open_notional = sum(t.notional_usd or POSITION_NOTIONAL_USD for t in open_trades)

    port = _stats(all_pnls)
    return {
        "strategies":              rows,
        "portfolio_total_pnl_bp":  round(portfolio_total_bp, 1),
        "portfolio_stats": {
            "n_strategies":   len(by_strategy),
            "n_closed_trades": port["n"],
            "sharpe":         port["sharpe"],
        },
        "n3_p3_correlation":       correlation,
        "correlation_n_pairs":     len(common),
        "open_exposure":           open_exposure,
        "total_open_notional_usd": round(total_open_notional, 0),
        "generated_at":            datetime.now(timezone.utc).isoformat(),
    }
