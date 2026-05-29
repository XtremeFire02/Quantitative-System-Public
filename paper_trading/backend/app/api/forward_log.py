"""
Forward validation logs — N3 primary and P3 shadow.

GET /forward-log/n3      — N3 DVOL Long: every daily evaluation + trade outcome
GET /forward-log/p3      — P3 OI-Price Divergence: shadow log + independence monitor
GET /forward-log/summary — Combined summary: live stats, blocked trades, regime

No-signal days are included in all logs: they prove the rule stayed frozen.

Independence monitor (P3 endpoint):
    `p3_exclusive` rows are P3 fires on days N3 did not fire. The summary
    block `exclusive_trades` aggregates only those rows — its Sharpe answers
    "does P3 add edge that N3 misses?". A high overall P3 Sharpe but a flat
    exclusive Sharpe means P3 is riding N3 days.

Sharpe annualization: sqrt(252), matching research convention. See
    app/api/performance.py module docstring for the full discussion.

Trade lookup keying: `trade_map` is keyed by entry date (UTC YYYY-MM-DD).
    Daily strategies fire ≤1 trade per market per day so collisions don't
    occur in practice; if a future strategy fires multiple times the latest
    trade wins in the lookup.
"""
import json
import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import Alert, Signal, Trade, get_db

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


# ── N3 forward log ────────────────────────────────────────────────────────────

@router.get("/forward-log/n3")
def get_n3_forward_log(
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
):
    """
    N3 DVOL Long — forward validation log.
    One row per daily evaluation at 00:00 UTC, newest first.
    Includes simulated fill details (signal_price vs entry_price, fill_type).
    """
    strategy = "N3_DVOL_LONG"
    signals = (
        db.query(Signal)
        .filter(Signal.strategy_name == strategy)
        .order_by(Signal.timestamp.desc())
        .limit(limit)
        .all()
    )

    _empty = {"n": 0, "sharpe": None, "total_pnl_bp": 0.0, "win_rate": None}
    if not signals:
        return {
            "strategy": strategy,
            "n_evaluations": 0,
            "n_trades": 0,
            "n_exclusive": 0,
            "n_overlap": 0,
            "summary": {
                "all_trades":       _empty,
                "exclusive_trades": _empty,
                "overlap_trades":   _empty,
            },
            "rows": [],
        }

    trade_map: dict[str, Trade] = {}
    for t in db.query(Trade).filter(Trade.strategy_name == strategy).all():
        if t.entry_timestamp:
            trade_map[_date_str(t.entry_timestamp)] = t

    rows = []
    for sig in signals:
        date = _date_str(sig.timestamp)
        trade = trade_map.get(date)
        slip_bp = _bp(trade.slippage) if trade else None
        row = {
            "date":              date,
            "evaluation_time":   _iso(sig.timestamp),
            "dvol":              sig.dvol,
            "n3_z":              sig.n3_z,
            "dvol_filter_pass":  sig.dvol_filter_pass,
            "signal_fired":      bool(sig.entry_signal),
            "reason":            sig.reason,
            # Execution detail
            "signal_price":      trade.signal_price      if trade else None,
            "entry_price":       trade.entry_price       if trade else None,
            "fill_type":         trade.fill_type         if trade else None,
            "entry_quality":     trade.entry_quality_score if trade else None,
            # Outcome
            "exit_price":        trade.exit_price        if trade else None,
            "funding_bp":        _bp(trade.funding_pnl)  if trade else None,
            "slippage_bp":       slip_bp,
            "fees_bp":           _bp(trade.fees)         if trade else None,
            "net_pnl_bp":        trade.net_pnl_bp        if trade else None,
            "trade_status":      trade.status            if trade else None,
        }
        rows.append(row)

    _empty = {"n": 0, "sharpe": None, "total_pnl_bp": 0, "win_rate": None}
    closed = [r for r in rows if r["net_pnl_bp"] is not None and r["trade_status"] == "closed"]
    return {
        "strategy":      strategy,
        "n_evaluations": len(rows),
        "n_trades":      sum(1 for r in rows if r["signal_fired"]),
        "n_exclusive":   0,
        "n_overlap":     0,
        "summary": {
            "all_trades":       _n3_stats([r["net_pnl_bp"] for r in closed]),
            "exclusive_trades": _empty,
            "overlap_trades":   _empty,
        },
        "rows": rows,
    }


def _n3_stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "sharpe": None, "total_pnl_bp": 0.0, "win_rate": None}
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


# ── Combined summary ──────────────────────────────────────────────────────────

@router.get("/forward-log/summary")
def get_forward_summary(db: Session = Depends(get_db)):
    """
    Combined N3 + P3 forward summary.

    Reports live paper stats per strategy, blocked-trade count (risk_blocked alerts),
    and current market regime from the most recent N3 evaluation.
    """
    # Per-strategy closed trade stats
    def strategy_stats(name_prefix: str) -> dict:
        trades = (
            db.query(Trade)
            .filter(Trade.strategy_name.like(f"{name_prefix}%"), Trade.status == "closed")
            .all()
        )
        pnls = [t.net_pnl_bp for t in trades if t.net_pnl_bp is not None]
        return _n3_stats(pnls)

    n3_stats = strategy_stats("N3_DVOL_LONG")
    p3_stats = strategy_stats("P3")

    n3_open = db.query(Trade).filter(
        Trade.strategy_name == "N3_DVOL_LONG", Trade.status == "open"
    ).count()
    p3_open = db.query(Trade).filter(
        Trade.strategy_name.like("P3%"), Trade.status == "open"
    ).count()

    # Blocked trades — signals that fired but were prevented by portfolio risk
    blocked_count = db.query(Alert).filter(Alert.category == "risk_blocked").count()

    # Current regime from latest N3 evaluation
    last_sig = (
        db.query(Signal)
        .filter(Signal.strategy_name == "N3_DVOL_LONG")
        .order_by(Signal.timestamp.desc())
        .first()
    )
    regime = {
        "dvol":             last_sig.dvol              if last_sig else None,
        "n3_z":             last_sig.n3_z              if last_sig else None,
        "dvol_filter_pass": last_sig.dvol_filter_pass  if last_sig else None,
        "signal_active":    bool(last_sig.entry_signal) if last_sig else None,
        "last_evaluated":   _iso(last_sig.timestamp)   if last_sig else None,
    }

    return {
        "n3": {**n3_stats, "open_positions": n3_open},
        "p3": {**p3_stats, "open_positions": p3_open},
        "blocked_trades": blocked_count,
        "current_regime": regime,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
