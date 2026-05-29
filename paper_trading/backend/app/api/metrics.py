"""
Runtime metrics endpoint.

GET /api/metrics

Returns scheduler job telemetry, data freshness, position state, and risk state
in a single machine-readable response. Complements /system/health (which is
optimised for human-readable status) with structured numeric metrics.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import DATA_STALE_MINUTES
from app.database import MarketData, Signal, SystemLog, Trade, get_db
from app.trading.kill_switch import get_state as get_kill_switch_state

router = APIRouter()

_JOB_COMPONENTS = {
    "daily_signal_job": "daily_job",
    "exit_trade_job": "exit_job",
}


def _job_metrics(db: Session, component: str, since: datetime) -> dict:
    last_entry = (
        db.query(SystemLog)
        .filter(SystemLog.component == component)
        .order_by(SystemLog.id.desc())
        .first()
    )
    errors_24h = (
        db.query(func.count(SystemLog.id))
        .filter(
            SystemLog.component == component,
            SystemLog.level == "ERROR",
            SystemLog.timestamp >= since,
        )
        .scalar() or 0
    )
    runs_24h = (
        db.query(func.count(SystemLog.id))
        .filter(
            SystemLog.component == component,
            SystemLog.level == "INFO",
            SystemLog.timestamp >= since,
        )
        .scalar() or 0
    )

    last_run = None
    last_outcome = None
    if last_entry:
        ts = last_entry.timestamp
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        last_run = ts.isoformat() if ts else None
        last_outcome = "error" if last_entry.level == "ERROR" else "ok"

    return {
        "last_run": last_run,
        "last_outcome": last_outcome,
        "runs_24h": runs_24h,
        "errors_24h": errors_24h,
    }


def _freshness_minutes(row, attr: str = "timestamp") -> float | None:
    if row is None:
        return None
    ts = getattr(row, attr, None)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    return round(delta, 1)


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # Scheduler job telemetry
    scheduler = {
        name: _job_metrics(db, component, since_24h)
        for name, component in _JOB_COMPONENTS.items()
    }

    # Data freshness
    last_market = db.query(MarketData).order_by(MarketData.id.desc()).first()
    last_signal = db.query(Signal).order_by(Signal.id.desc()).first()
    market_age = _freshness_minutes(last_market)
    signal_age = _freshness_minutes(last_signal)

    data_freshness = {
        "market_data_age_minutes": market_age,
        "signal_age_minutes": signal_age,
        "market_data_ok": market_age is not None and market_age <= DATA_STALE_MINUTES,
        "signal_ok": signal_age is not None and signal_age <= 1440,  # 24h
    }

    # Position state
    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    strategies_active = list({t.strategy_name for t in open_trades})

    positions = {
        "open_count": len(open_trades),
        "strategies_active": sorted(strategies_active),
    }

    # Risk state
    ks = get_kill_switch_state(db)
    daily_pnl_bp = (
        db.query(func.sum(Trade.net_pnl_bp))
        .filter(
            Trade.status == "closed",
            Trade.exit_timestamp >= now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        .scalar() or 0.0
    )

    risk = {
        "kill_switch_active": ks.get("active", False),
        "daily_pnl_bp": round(daily_pnl_bp, 2),
    }

    return {
        "scheduler": scheduler,
        "data_freshness": data_freshness,
        "positions": positions,
        "risk": risk,
        "checked_at": now.isoformat(),
    }
