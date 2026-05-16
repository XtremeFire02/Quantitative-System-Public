"""
P3 forward shadow log — per-day record of every evaluation.

Returns one row per day regardless of whether a trade fired.
No-trade days are included because they prove the rule stayed frozen.

Key column: n3_also_fired
  True  → P3 and N3 both active on that day (overlap day)
  False → P3 exclusive day (the independence monitor)

The Sharpe on P3-exclusive days is the single most important forward metric.
Research baseline: Sh=+5.18, p=0.007 on 57 OOS exclusive trades.
"""
import json
from datetime import timezone, datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db, Signal, Trade

router = APIRouter()


@router.get("/forward-log/p3")
def get_p3_forward_log(
    strategy: str = Query(default="P3_OIPD_DD"),
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
):
    """
    Full forward shadow log for P3_OIPD_DD (or specified variant).
    One row per daily evaluation at 00:00 UTC, newest first.
    """
    # All P3 signal evaluations
    signals = (
        db.query(Signal)
        .filter(Signal.strategy_name == strategy)
        .order_by(Signal.timestamp.desc())
        .limit(limit)
        .all()
    )

    _empty_stats = {"n": 0, "sharpe": None, "total_pnl_bp": 0, "win_rate": None}
    _empty_summary = {
        "all_trades": _empty_stats,
        "exclusive_trades": _empty_stats,
        "overlap_trades": _empty_stats,
    }
    if not signals:
        return {
            "strategy": strategy,
            "n_evaluations": 0,
            "n_trades": 0,
            "n_exclusive": 0,
            "n_overlap": 0,
            "summary": _empty_summary,
            "rows": [],
        }

    # Build date → N3 entry_signal lookup (one query)
    n3_dates: set[str] = set()
    n3_sigs = (
        db.query(Signal.timestamp, Signal.entry_signal)
        .filter(
            Signal.strategy_name == "N3_DVOL_LONG",
            Signal.entry_signal == True,
        )
        .all()
    )
    for s in n3_sigs:
        n3_dates.add(_date_str(s.timestamp))

    # Build date → Trade lookup for P3
    trade_map: dict[str, Trade] = {}
    p3_trades = (
        db.query(Trade)
        .filter(Trade.strategy_name == strategy)
        .all()
    )
    for t in p3_trades:
        if t.entry_timestamp:
            trade_map[_date_str(t.entry_timestamp)] = t

    rows = []
    for sig in signals:
        date = _date_str(sig.timestamp)
        meta = _parse_meta(sig.signal_metadata)
        trade = trade_map.get(date)
        n3_fired = date in n3_dates

        row = {
            "date":            date,
            "evaluation_time": _iso(sig.timestamp),
            # Signal inputs
            "dvol":            sig.dvol,
            "regime":          meta.get("regime"),
            "dp_pct":          _pct(meta.get("dp")),
            "doi_pct":         _pct(meta.get("doi")),
            # Signal output
            "signal_fired":    bool(sig.entry_signal),
            "reason":          sig.reason,
            # Independence monitor
            "n3_also_fired":   n3_fired,
            "p3_exclusive":    bool(sig.entry_signal) and not n3_fired,
            # Trade outcome (None if no trade)
            "entry_price":     trade.entry_price     if trade else None,
            "exit_price":      trade.exit_price      if trade else None,
            "funding_bp":      _bp(trade.funding_pnl) if trade else None,
            "fees_bp":         _bp(trade.fees)        if trade else None,
            "net_pnl_bp":      trade.net_pnl_bp      if trade else None,
            "trade_status":    trade.status           if trade else None,
        }
        rows.append(row)

    # Summary stats over completed trades
    summary = _compute_summary(rows)

    return {
        "strategy":       strategy,
        "n_evaluations":  len(rows),
        "n_trades":       sum(1 for r in rows if r["signal_fired"]),
        "n_exclusive":    sum(1 for r in rows if r["p3_exclusive"]),
        "n_overlap":      sum(1 for r in rows if r["signal_fired"] and r["n3_also_fired"]),
        "summary":        summary,
        "rows":           rows,
    }


def _compute_summary(rows: list[dict]) -> dict:
    import math

    def stats(pnls):
        if not pnls:
            return {"n": 0, "sharpe": None, "total_pnl_bp": 0, "win_rate": None}
        n = len(pnls)
        mu = sum(pnls) / n
        std = math.sqrt(sum((x - mu) ** 2 for x in pnls) / max(n - 1, 1))
        sh = round(mu / std * math.sqrt(252), 3) if std > 0 else None
        return {
            "n":            n,
            "sharpe":       sh,
            "total_pnl_bp": round(sum(pnls), 1),
            "win_rate":     round(sum(1 for p in pnls if p > 0) / n, 3),
        }

    closed = [r for r in rows if r["net_pnl_bp"] is not None and r["trade_status"] == "closed"]
    all_pnl       = [r["net_pnl_bp"] for r in closed]
    excl_pnl      = [r["net_pnl_bp"] for r in closed if r["p3_exclusive"]]
    overlap_pnl   = [r["net_pnl_bp"] for r in closed if r["n3_also_fired"] and r["signal_fired"]]

    return {
        "all_trades":      stats(all_pnl),
        "exclusive_trades": stats(excl_pnl),   # The independence monitor
        "overlap_trades":   stats(overlap_pnl),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_str(ts) -> str:
    if ts is None:
        return ""
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%Y-%m-%d")


def _iso(ts) -> str:
    if ts is None:
        return ""
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _pct(val) -> float | None:
    if val is None:
        return None
    return round(float(val) * 100, 3)


def _bp(val) -> float | None:
    if val is None:
        return None
    return round(float(val) * 10000, 1)
