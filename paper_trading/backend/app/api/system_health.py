from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from app.database import get_db, MarketData, Signal, Trade, SystemLog
from app.config import DATA_STALE_MINUTES

router = APIRouter()


@router.get("/system/health")
def get_system_health(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=DATA_STALE_MINUTES)

    last_market = db.query(MarketData).order_by(MarketData.id.desc()).first()
    last_signal = db.query(Signal).order_by(Signal.id.desc()).first()
    open_trade = db.query(Trade).filter(Trade.status == "open").first()
    open_count = db.query(Trade).filter(Trade.status == "open").count()

    def _ts(row):
        if row is None:
            return None
        ts = row.timestamp if hasattr(row, "timestamp") else row.created_at
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat() if ts else None

    def _stale(row):
        if row is None:
            return True
        ts = row.timestamp if hasattr(row, "timestamp") else row.created_at
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts < stale_threshold if ts else True

    market_stale = _stale(last_market)
    signal_stale = _stale(last_signal)

    # Next scheduled exit: planned_exit_timestamp of open trade (if any)
    next_scheduled_exit = None
    hours_to_exit = None
    if open_trade and open_trade.planned_exit_timestamp:
        planned = open_trade.planned_exit_timestamp
        if planned.tzinfo is None:
            planned = planned.replace(tzinfo=timezone.utc)
        next_scheduled_exit = planned.isoformat()
        delta = (planned - now).total_seconds() / 3600
        hours_to_exit = round(max(delta, 0), 1)

    # Next daily signal job: next 00:00 UTC
    next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_midnight <= now:
        next_midnight = next_midnight + timedelta(days=1)

    return {
        "status": "degraded" if (market_stale or signal_stale) else "healthy",
        "last_binance_update": _ts(last_market),
        "market_data_stale": market_stale,
        "last_signal_calculation": _ts(last_signal),
        "signal_data_stale": signal_stale,
        "open_position_count": open_count,
        "next_scheduled_exit": next_scheduled_exit,
        "hours_to_exit": hours_to_exit,
        "next_daily_job_utc": next_midnight.isoformat(),
        "stale_threshold_minutes": DATA_STALE_MINUTES,
        "database_status": "ok",
        "checked_at": now.isoformat(),
    }


@router.get("/system/logs")
def get_system_logs(
    limit: int = Query(default=50, le=500),
    level: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(SystemLog).order_by(SystemLog.id.desc())
    if level:
        q = q.filter(SystemLog.level == level.upper())
    logs = q.limit(limit).all()
    return [
        {
            "id": log.id,
            "timestamp": (log.timestamp.replace(tzinfo=timezone.utc)
                          if log.timestamp and log.timestamp.tzinfo is None
                          else log.timestamp).isoformat() if log.timestamp else None,
            "level": log.level,
            "component": log.component,
            "message": log.message,
        }
        for log in reversed(logs)
    ]
