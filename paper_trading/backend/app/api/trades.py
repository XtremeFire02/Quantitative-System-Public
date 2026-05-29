from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import Trade, get_db
from app.middleware.auth import require_api_key

router = APIRouter()


def _fmt(t: Trade) -> dict:
    def _ts(v):
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    def _bp(v):
        return round(v * 10000, 1) if v is not None else None

    return {
        "id": t.id,
        "market": t.market,
        "strategy_name": t.strategy_name,
        "status": t.status,
        "side": t.side,
        "notional_usd": t.notional_usd,
        "entry_timestamp": _ts(t.entry_timestamp),
        "entry_price": t.entry_price,
        "entry_dvol": t.entry_dvol,
        "entry_n3_z": t.entry_n3_z,
        "entry_reason": t.entry_reason,
        # Execution quality
        "signal_price": t.signal_price,
        "fill_type": t.fill_type,
        "entry_half_spread_bp": t.entry_half_spread_bp,
        "entry_impact_bp": t.entry_impact_bp,
        "entry_maker_prob": t.entry_maker_prob,
        "entry_quality_score": t.entry_quality_score,
        "planned_exit_timestamp": _ts(t.planned_exit_timestamp),
        "exit_timestamp": _ts(t.exit_timestamp),
        "exit_price": t.exit_price,
        "exit_signal_price": t.exit_signal_price,
        "exit_half_spread_bp": t.exit_half_spread_bp,
        "exit_impact_bp": t.exit_impact_bp,
        "exit_quality_score": t.exit_quality_score,
        "gross_price_return": t.gross_price_return,
        "gross_price_return_bp": _bp(t.gross_price_return),
        "funding_pnl": t.funding_pnl,
        "funding_pnl_bp": _bp(t.funding_pnl),
        "slippage": t.slippage,
        "slippage_bp": _bp(t.slippage),
        "fees": t.fees,
        "fees_bp": _bp(t.fees),
        "net_pnl": t.net_pnl,
        "net_pnl_bp": t.net_pnl_bp,
        "exit_reason": t.exit_reason,
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


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_api_key)])
async def manual_close_trade(trade_id: int, db: Session = Depends(get_db)):
    """Manually close an open trade at the current market price.

    Fetches the latest market price for the trade's market, runs the
    same close logic as the scheduled exit job, and records exit_reason
    as "manual".  Requires API key authentication.
    """
    from app.jobs.exit_trade_job import _close_one_trade

    t = db.query(Trade).filter(Trade.id == trade_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    if t.status != "open":
        raise HTTPException(status_code=409, detail=f"Trade #{trade_id} is already {t.status}")

    try:
        result = await _close_one_trade(db, t, exit_reason="manual")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"status": "closed", "trade_id": trade_id, **result}
