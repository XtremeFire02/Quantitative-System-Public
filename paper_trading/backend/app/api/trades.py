from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import timezone
from app.database import get_db, Trade

router = APIRouter()


def _fmt(t: Trade) -> dict:
    def _ts(v):
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    return {
        "id": t.id,
        "market": t.market,
        "strategy_name": t.strategy_name,
        "status": t.status,
        "side": t.side,
        "entry_timestamp": _ts(t.entry_timestamp),
        "entry_price": t.entry_price,
        "entry_dvol": t.entry_dvol,
        "entry_n3_z": t.entry_n3_z,
        "planned_exit_timestamp": _ts(t.planned_exit_timestamp),
        "exit_timestamp": _ts(t.exit_timestamp),
        "exit_price": t.exit_price,
        "gross_price_return": t.gross_price_return,
        "gross_price_return_bp": round(t.gross_price_return * 10000, 1) if t.gross_price_return else None,
        "funding_pnl": t.funding_pnl,
        "funding_pnl_bp": round(t.funding_pnl * 10000, 1) if t.funding_pnl else None,
        "fees": t.fees,
        "fees_bp": round(t.fees * 10000, 1) if t.fees else None,
        "net_pnl": t.net_pnl,
        "net_pnl_bp": t.net_pnl_bp,
        "exit_reason": t.exit_reason,
        "entry_reason": t.entry_reason,
        "created_at": _ts(t.created_at),
        "updated_at": _ts(t.updated_at),
    }


@router.get("/trades")
def get_all_trades(
    status: str | None = Query(default=None, description="open|closed"),
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(Trade).order_by(Trade.id.desc())
    if status:
        q = q.filter(Trade.status == status)
    return [_fmt(t) for t in q.limit(limit).all()]


@router.get("/trades/open")
def get_open_trades(db: Session = Depends(get_db)):
    trades = db.query(Trade).filter(Trade.status == "open").all()
    return [_fmt(t) for t in trades]


@router.get("/trades/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    t = db.query(Trade).filter(Trade.id == trade_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    return _fmt(t)
