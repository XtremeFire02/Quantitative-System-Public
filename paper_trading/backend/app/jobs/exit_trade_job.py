"""
Exit trade job — runs every 15 minutes.
Closes every open trade whose planned_exit_timestamp has passed.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import Trade, SystemLog, SessionLocal
from app.data.binance_client import fetch_price, fetch_funding_history
from app.trading.paper_broker import get_all_open_trades, close_trade
import app.alerts as alerts


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
            planned = (
                trade.planned_exit_timestamp.replace(tzinfo=timezone.utc)
                if trade.planned_exit_timestamp.tzinfo is None
                else trade.planned_exit_timestamp
            )
            if now < planned:
                continue

            try:
                market = trade.market or "BTCUSDT"
                exit_price = await fetch_price(market)

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

                closed = close_trade(
                    db=db,
                    trade=trade,
                    exit_price=exit_price,
                    funding_rates=funding_rates,
                    exit_reason=f"time_exit_{trade.strategy_name}",
                )
                closed_trades.append({
                    "trade_id": closed.id,
                    "market": market,
                    "strategy": trade.strategy_name,
                    "net_pnl_bp": closed.net_pnl_bp,
                })
                if trade.strategy_name.startswith("P3_OIPD"):
                    alerts.fire_trade_closed(
                        trade_id=closed.id,
                        strategy=trade.strategy_name,
                        net_pnl_bp=closed.net_pnl_bp or 0.0,
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
