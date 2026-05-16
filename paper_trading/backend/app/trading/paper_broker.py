"""Paper broker — open and close fake trades, update equity curve."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import Trade, EquityCurve, SystemLog
from app.trading.pnl import calculate_pnl


def open_trade(
    db: Session,
    market: str,
    strategy_name: str,
    side: str,
    entry_price: float,
    hold_hours: int,
    entry_reason: str = "",
    entry_dvol: float | None = None,
    entry_n3_z: float | None = None,
) -> Trade:
    entry_ts = datetime.now(timezone.utc)
    planned_exit_ts = entry_ts + timedelta(hours=hold_hours)

    trade = Trade(
        market=market,
        strategy_name=strategy_name,
        status="open",
        side=side,
        entry_timestamp=entry_ts,
        entry_price=entry_price,
        entry_dvol=entry_dvol,
        entry_n3_z=entry_n3_z,
        entry_reason=entry_reason,
        planned_exit_timestamp=planned_exit_ts,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)

    _log(db, "INFO", "paper_broker",
         f"Opened {side.upper()} trade #{trade.id} {market}/{strategy_name} @ {entry_price:.2f}")
    return trade


def close_trade(
    db: Session,
    trade: Trade,
    exit_price: float,
    funding_rates: list[float],
    exit_reason: str = "time_exit",
) -> Trade:
    pnl = calculate_pnl(
        side=trade.side,
        entry_price=trade.entry_price,
        exit_price=exit_price,
        funding_rates=funding_rates,
    )

    trade.status = "closed"
    trade.exit_timestamp = datetime.now(timezone.utc)
    trade.exit_price = exit_price
    trade.gross_price_return = pnl["gross_price_return"]
    trade.funding_pnl = pnl["funding_pnl"]
    trade.fees = pnl["fees"]
    trade.slippage = pnl["slippage"]
    trade.net_pnl = pnl["net_pnl"]
    trade.net_pnl_bp = pnl["net_pnl_bp"]
    trade.exit_reason = exit_reason
    trade.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(trade)

    _update_equity(db, pnl["net_pnl"])
    _log(db, "INFO", "paper_broker",
         f"Closed trade #{trade.id} @ {exit_price:.2f} | net PnL = {pnl['net_pnl_bp']:+.1f}bp")
    return trade


def get_open_trade(db: Session, market: str, strategy_name: str) -> Trade | None:
    return (
        db.query(Trade)
        .filter(Trade.status == "open", Trade.market == market, Trade.strategy_name == strategy_name)
        .first()
    )


def get_all_open_trades(db: Session) -> list[Trade]:
    return db.query(Trade).filter(Trade.status == "open").all()


def count_open_trades(db: Session, market: str, strategy_name: str) -> int:
    return (
        db.query(Trade)
        .filter(Trade.status == "open", Trade.market == market, Trade.strategy_name == strategy_name)
        .count()
    )


def _update_equity(db: Session, net_pnl: float) -> None:
    last = db.query(EquityCurve).order_by(EquityCurve.id.desc()).first()
    prev_equity = last.equity if last else 10000.0
    prev_realised = last.realised_pnl if last else 0.0

    new_equity = prev_equity * (1 + net_pnl)
    new_realised = prev_realised + net_pnl

    peak = db.query(func.max(EquityCurve.equity)).scalar() or new_equity
    peak = max(peak, new_equity)
    drawdown = (new_equity - peak) / peak if peak > 0 else 0.0

    db.add(EquityCurve(
        timestamp=datetime.now(timezone.utc),
        equity=new_equity,
        realised_pnl=new_realised,
        unrealised_pnl=0.0,
        drawdown=drawdown,
    ))
    db.commit()


def _log(db: Session, level: str, component: str, message: str) -> None:
    db.add(SystemLog(level=level, component=component, message=message))
    db.commit()
