"""
Canonical investor / recruiter view.

GET /api/report

A single structured document covering:
  - Strategy pipeline: lifecycle stage per strategy
  - Forward validation: live paper trade counts, Sharpe, win rate
  - Killed signals: strategy name + kill reason (from StrategyStatus notes)
  - Current risk state: kill switch, open positions, open notional
  - Recent alerts: last 5 system events
  - System description: methodology summary

No alpha-revealing parameters (entry thresholds, OOS IC values) are included.
Those live in the restricted experiment YAML files and research scripts.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import POSITION_NOTIONAL_USD
from app.database import Alert, Signal, StrategyStatus, Trade, get_db
from app.trading import kill_switch as ks_module

router = APIRouter()


def _sharpe(pnls: list[float]) -> float | None:
    n = len(pnls)
    if n < 2:
        return None
    mu = sum(pnls) / n
    std = math.sqrt(sum((x - mu) ** 2 for x in pnls) / (n - 1))
    return round(mu / std * math.sqrt(252), 3) if std > 0 else None


def _forward_stats(trades: list) -> dict:
    closed = [t for t in trades if t.status == "closed" and t.net_pnl_bp is not None]
    open_n = sum(1 for t in trades if t.status == "open")
    pnls = [t.net_pnl_bp for t in closed]
    n = len(pnls)
    return {
        "n_closed":     n,
        "n_open":       open_n,
        "sharpe":       _sharpe(pnls),
        "total_pnl_bp": round(sum(pnls), 1) if pnls else 0.0,
        "win_rate":     round(sum(1 for p in pnls if p > 0) / n, 3) if n > 0 else None,
    }


@router.get("/report")
def get_investor_report(db: Session = Depends(get_db)):
    """
    Canonical single-page system report.
    Designed for investors and technical reviewers assessing strategy maturity.
    """
    now = datetime.now(timezone.utc)

    # ── Strategy pipeline ─────────────────────────────────────────────────────
    statuses = db.query(StrategyStatus).order_by(StrategyStatus.strategy_name).all()

    validated = []
    shadow = []
    killed = []
    for s in statuses:
        entry = {
            "strategy":     s.strategy_name,
            "status":       s.status,
            "promoted_at":  s.promoted_at.isoformat() if s.promoted_at else None,
            "note":         s.note,
        }
        if s.status == "validated":
            validated.append(entry)
        elif s.status in ("shadow", "candidate"):
            shadow.append(entry)
        elif s.status == "killed":
            killed.append(entry)

    pipeline = {
        "validated":  validated,
        "shadow":     shadow,
        "killed":     killed,
        "summary":    f"{len(validated)} validated, {len(shadow)} shadow, {len(killed)} killed",
    }

    # ── Forward validation results ────────────────────────────────────────────
    n3_trades = db.query(Trade).filter(Trade.strategy_name == "N3_DVOL_LONG").all()
    p3_trades = db.query(Trade).filter(Trade.strategy_name.like("P3%")).all()

    forward_results = {
        "N3_DVOL_LONG": _forward_stats(n3_trades),
        "P3_OIPD_DD":   _forward_stats(p3_trades),
    }

    # ── Current market regime ─────────────────────────────────────────────────
    last_sig = (
        db.query(Signal)
        .filter(Signal.strategy_name == "N3_DVOL_LONG")
        .order_by(Signal.timestamp.desc())
        .first()
    )
    regime = {
        "dvol":             last_sig.dvol              if last_sig else None,
        "regime_active":    bool(last_sig.dvol_filter_pass) if last_sig else None,
        "signal_active":    bool(last_sig.entry_signal)     if last_sig else None,
        "last_evaluated":   last_sig.timestamp.isoformat()  if last_sig and last_sig.timestamp else None,
    }

    # ── Risk state ────────────────────────────────────────────────────────────
    try:
        ks_state = ks_module.get_state(db)
        kill_switch_active = ks_state["active"]
    except Exception:
        kill_switch_active = False

    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    open_notional = sum(t.notional_usd if t.notional_usd is not None else POSITION_NOTIONAL_USD for t in open_trades)

    risk_state = {
        "kill_switch_active": kill_switch_active,
        "open_positions":     len(open_trades),
        "open_notional_usd":  round(open_notional, 0),
        "blocked_trades":     db.query(Alert).filter(Alert.category == "risk_blocked").count(),
    }

    # ── Recent alerts ─────────────────────────────────────────────────────────
    recent_alerts = (
        db.query(Alert)
        .order_by(Alert.timestamp.desc())
        .limit(5)
        .all()
    )
    alerts = [
        {
            "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            "category":  a.category,
            "title":     a.title,
            "strategy":  a.strategy,
        }
        for a in recent_alerts
    ]

    # ── System metadata ───────────────────────────────────────────────────────
    system = {
        "name":               "N3 DVOL Fear Resolution — Quantitative Research & Paper Trading",
        "validation_method":  "7-stage pipeline: hypothesis → IC screen → OOS block bootstrap "
                              "→ stress test → regime conditioning → cost-adjusted backtest "
                              "→ live forward validation",
        "cost_model":         "Maker execution — 3 bp per leg (Binance VIP0 maker + 1 bp slippage)",
        "execution_model":    "Simulated maker/taker fill based on DVOL-conditioned fill probability; "
                              "separate slippage and fee attribution per trade",
        "data_sources":       ["Deribit DVOL (hourly)", "Binance FAPI price + funding + OI"],
        "observation_start":  "2026-05",
    }

    return {
        "generated_at":    now.isoformat(),
        "pipeline":        pipeline,
        "forward_results": forward_results,
        "current_regime":  regime,
        "risk_state":      risk_state,
        "recent_alerts":   alerts,
        "system":          system,
    }
