"""
Strategy promotion pipeline API.

Tracks the formal lifecycle status of every strategy:
  research → candidate → shadow → validated → paused → killed

GET  /api/strategies              — all strategies with current status
GET  /api/strategies/{name}       — single strategy detail
POST /api/strategies/{name}/status — promote / change status
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import Signal, StrategyStatus, Trade, get_db
from app.middleware.auth import require_api_key

router = APIRouter()

VALID_STATUSES = {"research", "candidate", "shadow", "validated", "paused", "killed"}

STATUS_RULES = {
    "research":  "Initial idea; no forward data yet.",
    "candidate": "Backtest passed initial screen; preparing shadow deployment.",
    "shadow":    "Running live evaluations; trades paper-executed but not counted for capital.",
    "validated": "≥3 months forward shadow with acceptable metrics; ready for real capital.",
    "paused":    "Suspended due to drawdown or data quality issue; not entering new trades.",
    "killed":    "Hypothesis rejected by evidence; permanently inactive.",
}

PROMOTION_CRITERIA = {
    "candidate → shadow":    "Pass unit tests; p≤0.05 OOS backtest; no replay mismatch.",
    "shadow → validated":    "≥90 forward evaluations; Sharpe≥1.5 exclusive trades; no data failures; ≤1 replay mismatch.",
    "validated → paused":    "Portfolio drawdown limit hit, or data quality degraded.",
    "paused → shadow":       "Root cause resolved; data quality restored.",
    "any → killed":          "Null hypothesis not rejected (p≥0.05) in forward data, or persistent data failure.",
}


class StatusUpdate(BaseModel):
    status: str
    note: str = ""
    promoted_by: str = "manual"


@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db)):
    rows = db.query(StrategyStatus).order_by(StrategyStatus.strategy_name).all()
    return [_serialize(r, db) for r in rows]


@router.get("/strategies/{name}")
def get_strategy(name: str, db: Session = Depends(get_db)):
    row = db.query(StrategyStatus).filter(StrategyStatus.strategy_name == name).first()
    if not row:
        raise HTTPException(404, f"Strategy '{name}' not found in pipeline")
    return _serialize(row, db)


@router.post("/strategies/{name}/status", dependencies=[Depends(require_api_key)])
def update_status(name: str, body: StatusUpdate, db: Session = Depends(get_db)):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status '{body.status}'. Valid: {sorted(VALID_STATUSES)}")

    row = db.query(StrategyStatus).filter(StrategyStatus.strategy_name == name).first()
    if not row:
        row = StrategyStatus(strategy_name=name)
        db.add(row)

    row.status = body.status
    row.promoted_at = datetime.now(timezone.utc)
    row.promoted_by = body.promoted_by
    row.note = body.note
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize(row, db)


@router.get("/strategies/meta/rules")
def promotion_rules():
    return {
        "statuses": STATUS_RULES,
        "promotion_criteria": PROMOTION_CRITERIA,
    }


def _serialize(row: StrategyStatus, db: Session) -> dict:
    n_signals = db.query(Signal).filter(Signal.strategy_name == row.strategy_name).count()
    n_trades = db.query(Trade).filter(Trade.strategy_name == row.strategy_name).count()
    n_open = db.query(Trade).filter(
        Trade.strategy_name == row.strategy_name, Trade.status == "open"
    ).count()

    def _iso(ts):
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()

    return {
        "strategy_name": row.strategy_name,
        "status": row.status,
        "status_description": STATUS_RULES.get(row.status, ""),
        "promoted_at": _iso(row.promoted_at),
        "promoted_by": row.promoted_by,
        "note": row.note,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "live_stats": {
            "n_evaluations": n_signals,
            "n_trades": n_trades,
            "n_open": n_open,
        },
    }
