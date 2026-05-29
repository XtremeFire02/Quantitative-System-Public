"""
Exit trade job — runs every 15 minutes.
Closes every open trade whose planned_exit_timestamp has passed.

Exit execution model:
  The raw market price is fetched first (exit_signal_price).
  A simulated exit fill is then computed from the market registry half-spread
  (long exits sell at bid; short exits buy at ask).
  Both prices are recorded on the trade so P&L attribution is fully traceable.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import app.alerts as alerts
from app.data.binance_client import fetch_funding_history, fetch_price
from app.database import SessionLocal, SystemLog, Trade
from app.markets import symbol_to_market_id
from app.trading.execution_sim import estimate_exit_execution
from app.trading.paper_broker import close_trade, get_all_open_trades


async def _close_one_trade(
    db: Session,
    trade: Trade,
    exit_reason: str = "time_exit",
) -> dict:
    """Fetch market price and close a single open trade.

    Returns a summary dict with trade_id, market, strategy, net_pnl_bp.
    Raises on fetch or close failure (caller handles logging).
    """
    now = datetime.now(timezone.utc)
    market = trade.market or "BTCUSDT"

    exit_data = await fetch_price(market)
    exit_market_price = exit_data["price"]

    exit_exec_estimate = None
    try:
        market_id = symbol_to_market_id(market)
        exit_exec_estimate = estimate_exit_execution(
            market_id=market_id,
            signal_price=exit_market_price,
            dvol=trade.entry_dvol,
            side=trade.side,
            notional_usd=trade.notional_usd or 10_000.0,
        )
        exit_fill_price = (
            exit_exec_estimate.estimated_maker_price
            if exit_exec_estimate.maker_fill_probability >= 0.5
            else exit_exec_estimate.estimated_taker_price
        )
        exit_signal_price = exit_market_price
    except Exception:
        exit_fill_price = exit_market_price
        exit_signal_price = None

    if trade.entry_timestamp is None:
        raise ValueError(f"Trade #{trade.id} has no entry_timestamp")
    entry_ms = (
        int(trade.entry_timestamp.replace(tzinfo=timezone.utc).timestamp() * 1000)
        if trade.entry_timestamp.tzinfo is None
        else int(trade.entry_timestamp.timestamp() * 1000)
    )
    funding_records = await fetch_funding_history(market, start_ms=entry_ms)
    funding_rates = [
        float(f["fundingRate"]) for f in funding_records
        if int(f["fundingTime"]) <= int(now.timestamp() * 1000)
    ]

    reason = exit_reason if exit_reason != "time_exit" else f"time_exit_{trade.strategy_name}"
    closed = close_trade(
        db=db,
        trade=trade,
        exit_price=exit_fill_price,
        funding_rates=funding_rates,
        exit_reason=reason,
        exit_signal_price=exit_signal_price,
        exit_exec_estimate=exit_exec_estimate,
    )
    return {
        "trade_id": closed.id,
        "market": market,
        "strategy": trade.strategy_name,
        "net_pnl_bp": closed.net_pnl_bp,
    }


async def run_exit_trade_job() -> dict:
    db: Session = SessionLocal()
    closed_trades = []
    result = {"status": "ok", "closed": 0, "error": None}

    try:
        open_trades = get_all_open_trades(db)
        if not open_trades:
            result["status"] = "no_open_trades"
            db.close()
            return result

        now = datetime.now(timezone.utc)

        for trade in open_trades:
            if trade.planned_exit_timestamp is None:
                continue
            planned = (
                trade.planned_exit_timestamp.replace(tzinfo=timezone.utc)
                if trade.planned_exit_timestamp.tzinfo is None
                else trade.planned_exit_timestamp
            )
            if now < planned:
                continue

            try:
                summary = await _close_one_trade(db, trade)
                closed_trades.append(summary)
                if trade.strategy_name.startswith("P3_OIPD"):
                    closed_trade = db.query(Trade).filter(Trade.id == summary["trade_id"]).first()
                    if closed_trade:
                        alerts.fire_trade_closed(
                            trade_id=closed_trade.id,
                            strategy=trade.strategy_name,
                            net_pnl_bp=closed_trade.net_pnl_bp or 0.0,
                            db=db,
                        )
            except Exception as e:
                try:
                    db.add(SystemLog(
                        level="ERROR", component="exit_job",
                        message=f"Failed to close trade #{trade.id}: {e}",
                    ))
                    db.commit()
                except Exception:
                    pass

        result["closed"] = len(closed_trades)
        result["trades"] = closed_trades
        if not closed_trades and open_trades:
            result["status"] = "holding"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        try:
            db.add(SystemLog(level="ERROR", component="exit_job",
                             message=f"Exit job failed: {e}"))
            db.commit()
        except Exception:
            pass

    finally:
        db.close()

    return result
