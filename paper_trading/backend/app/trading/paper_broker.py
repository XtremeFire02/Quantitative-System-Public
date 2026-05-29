"""Paper broker — open and close simulated trades, update equity curve."""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import POSITION_NOTIONAL_USD
from app.database import EquityCurve, SystemLog, Trade
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
    notional_usd: float | None = None,
    exec_estimate=None,     # ExecutionEstimate dataclass from execution_sim
) -> Trade:
    entry_ts = datetime.now(timezone.utc)
    planned_exit_ts = entry_ts + timedelta(hours=hold_hours)
    notional = notional_usd if notional_usd is not None else POSITION_NOTIONAL_USD

    # Determine simulated fill price based on execution estimate
    if exec_estimate is not None:
        fill_type = "maker" if random.random() < exec_estimate.maker_fill_probability else "taker"
        actual_fill = (
            exec_estimate.estimated_maker_price
            if fill_type == "maker"
            else exec_estimate.estimated_taker_price
        )
    else:
        fill_type = None
        actual_fill = entry_price

    trade = Trade(
        market=market,
        strategy_name=strategy_name,
        status="open",
        side=side,
        notional_usd=notional,
        entry_timestamp=entry_ts,
        signal_price=entry_price,        # evaluation price
        entry_price=actual_fill,         # simulated fill price
        fill_type=fill_type,
        entry_dvol=entry_dvol,
        entry_n3_z=entry_n3_z,
        entry_reason=entry_reason,
        planned_exit_timestamp=planned_exit_ts,
        entry_half_spread_bp=exec_estimate.half_spread_bp if exec_estimate else None,
        entry_impact_bp=exec_estimate.impact_bp if exec_estimate else None,
        entry_maker_prob=exec_estimate.maker_fill_probability if exec_estimate else None,
        entry_quality_score=exec_estimate.execution_quality_score if exec_estimate else None,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)

    fill_note = (
        f" | fill={fill_type} @ {actual_fill:.2f} (signal={entry_price:.2f})"
        f" | quality={exec_estimate.execution_quality_score:.1f}/10"
        if exec_estimate else ""
    )
    _log(db, "INFO", "paper_broker",
         f"Opened {side.upper()} trade #{trade.id} {market}/{strategy_name} "
         f"@ signal={entry_price:.2f}{fill_note} | notional=${notional:,.0f}")
    return trade


def close_trade(
    db: Session,
    trade: Trade,
    exit_price: float,
    funding_rates: list[float],
    exit_reason: str = "time_exit",
    exit_signal_price: float | None = None,
    exit_exec_estimate=None,    # ExecutionEstimate from estimate_exit_execution
) -> Trade:
    """
    Close a trade and compute P&L.

    exit_price        : the price at which the position is closed.
                        When exit_signal_price is also provided, this should
                        be the simulated fill (bid for long exits, ask for shorts).
    exit_signal_price : raw market price at exit (for audit trail).
                        When provided, signals that both entry and exit fills are
                        simulated — slippage is already in the fill prices and
                        is not charged separately in pnl.calculate_pnl().
    exit_exec_estimate: ExecutionEstimate from estimate_exit_execution (optional).
                        When provided, exit execution quality fields are recorded.
    """
    pnl = calculate_pnl(
        side=trade.side,
        entry_price=trade.entry_price,
        exit_price=exit_price,
        funding_rates=funding_rates,
        notional_usd=trade.notional_usd or POSITION_NOTIONAL_USD,
        entry_half_spread_bp=trade.entry_half_spread_bp,
        entry_impact_bp=trade.entry_impact_bp,
        signal_price=trade.signal_price,
        exit_signal_price=exit_signal_price,
    )

    trade.status = "closed"
    trade.exit_timestamp = datetime.now(timezone.utc)
    trade.exit_price = exit_price
    trade.exit_signal_price = exit_signal_price
    trade.gross_price_return = pnl["gross_price_return"]
    trade.funding_pnl = pnl["funding_pnl"]
    trade.fees = pnl["fees"]
    trade.slippage = pnl["slippage"]
    trade.net_pnl = pnl["net_pnl"]
    trade.net_pnl_bp = pnl["net_pnl_bp"]
    trade.exit_reason = exit_reason
    if exit_exec_estimate is not None:
        trade.exit_half_spread_bp = exit_exec_estimate.half_spread_bp
        trade.exit_impact_bp = exit_exec_estimate.impact_bp
        trade.exit_quality_score = exit_exec_estimate.execution_quality_score
    trade.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(trade)

    _update_equity(db, pnl["net_pnl"])
    quality_note = (
        f" | exit_quality={exit_exec_estimate.execution_quality_score:.1f}/10"
        if exit_exec_estimate else ""
    )
    _log(db, "INFO", "paper_broker",
         f"Closed trade #{trade.id} @ {exit_price:.2f} | "
         f"gross={pnl['gross_price_return']*10000:+.1f}bp "
         f"slippage={pnl['slippage']*10000:+.1f}bp "
         f"fees={pnl['fees']*10000:+.1f}bp "
         f"net={pnl['net_pnl_bp']:+.1f}bp{quality_note}")
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
