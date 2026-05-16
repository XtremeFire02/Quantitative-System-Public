from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.database import get_db, Signal, Trade, EquityCurve, MarketData
from app.trading.pnl import calculate_unrealised_pnl

router = APIRouter()


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    latest_signal = db.query(Signal).order_by(Signal.id.desc()).first()
    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    latest_market = db.query(MarketData).order_by(MarketData.id.desc()).first()
    latest_equity = db.query(EquityCurve).order_by(EquityCurve.id.desc()).first()

    btc_price = latest_market.btc_price if latest_market else None
    funding_rate = latest_market.funding_rate if latest_market else None

    now = datetime.now(timezone.utc)
    total_unrealised_pnl = 0.0
    total_unrealised_pnl_bp = 0.0
    trade_summaries = []

    for t in open_trades:
        current_price = btc_price if (t.market or "BTCUSDT") == "BTCUSDT" else None
        unrealised = 0.0
        unrealised_bp = 0.0
        time_to_exit = None

        if current_price and t.entry_price:
            unrealised = calculate_unrealised_pnl(
                side=t.side,
                entry_price=t.entry_price,
                current_price=current_price,
            )
            unrealised_bp = unrealised * 10000
            total_unrealised_pnl += unrealised
            total_unrealised_pnl_bp += unrealised_bp

        if t.planned_exit_timestamp:
            planned = t.planned_exit_timestamp
            if planned.tzinfo is None:
                planned = planned.replace(tzinfo=timezone.utc)
            delta = (planned - now).total_seconds() / 3600
            time_to_exit = round(max(delta, 0), 1)

        trade_summaries.append(_trade_summary(t, unrealised_bp, time_to_exit))

    # Backward-compat single trade fields
    first_trade = open_trades[0] if open_trades else None

    return {
        "btc_price": btc_price,
        "funding_rate": funding_rate,
        "dvol": latest_signal.dvol if latest_signal else None,
        "n3_z": latest_signal.n3_z if latest_signal else None,
        "dvol_filter_pass": latest_signal.dvol_filter_pass if latest_signal else None,
        "entry_signal": latest_signal.entry_signal if latest_signal else None,
        "signal_reason": latest_signal.reason if latest_signal else None,
        "last_signal_time": latest_signal.timestamp.isoformat() if latest_signal else None,
        "open_position": len(open_trades) > 0,
        "open_trade": _trade_summary(first_trade, None, None) if first_trade else None,
        "open_trades": trade_summaries,
        "time_to_exit_hours": trade_summaries[0]["time_to_exit_hours"] if trade_summaries else None,
        "equity": latest_equity.equity if latest_equity else 10000.0,
        "realised_pnl": latest_equity.realised_pnl if latest_equity else 0.0,
        "unrealised_pnl": total_unrealised_pnl,
        "unrealised_pnl_bp": total_unrealised_pnl_bp,
        "drawdown": latest_equity.drawdown if latest_equity else 0.0,
        "last_market_update": latest_market.timestamp.isoformat() if latest_market else None,
    }


def _trade_summary(t: Trade | None, unrealised_bp: float | None, time_to_exit: float | None) -> dict:
    if t is None:
        return {}
    entry_ts = t.entry_timestamp
    if entry_ts and entry_ts.tzinfo is None:
        entry_ts = entry_ts.replace(tzinfo=timezone.utc)
    planned_ts = t.planned_exit_timestamp
    if planned_ts and planned_ts.tzinfo is None:
        planned_ts = planned_ts.replace(tzinfo=timezone.utc)
    return {
        "id": t.id,
        "market": t.market or "BTCUSDT",
        "strategy_name": t.strategy_name,
        "side": t.side,
        "entry_price": t.entry_price,
        "entry_dvol": t.entry_dvol,
        "entry_n3_z": t.entry_n3_z,
        "entry_timestamp": entry_ts.isoformat() if entry_ts else None,
        "planned_exit_timestamp": planned_ts.isoformat() if planned_ts else None,
        "unrealised_pnl_bp": unrealised_bp,
        "time_to_exit_hours": time_to_exit,
    }
