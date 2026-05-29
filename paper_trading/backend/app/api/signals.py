from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import Signal, get_db

router = APIRouter()


def _fmt(s: Signal) -> dict:
    ts = s.timestamp
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "id": s.id,
        "timestamp": ts.isoformat() if ts else None,
        "strategy_name": s.strategy_name,
        "dvol": s.dvol,
        "dvol_mean_30d": s.dvol_mean_30d,
        "dvol_std_30d": s.dvol_std_30d,
        "n3_z": s.n3_z,
        "dvol_filter_pass": s.dvol_filter_pass,
        "entry_signal": s.entry_signal,
        "reason": s.reason,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/signals/latest")
def get_latest_signal(db: Session = Depends(get_db)):
    s = db.query(Signal).order_by(Signal.id.desc()).first()
    if not s:
        return {"error": "No signals recorded yet"}
    return _fmt(s)


@router.get("/signals/history")
def get_signal_history(
    limit: int = Query(default=90, le=500),
    db: Session = Depends(get_db),
):
    signals = db.query(Signal).order_by(Signal.id.desc()).limit(limit).all()
    return [_fmt(s) for s in reversed(signals)]
