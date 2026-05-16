"""
Daily signal job — runs at 00:00 UTC.
Iterates all active BotConfig rows and evaluates each strategy/market pair.
"""
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import Signal, MarketData, SystemLog, BotConfig, SessionLocal
from app.data.binance_client import get_market_snapshot
from app.data.deribit_client import get_dvol_snapshot
from app.signals.dispatcher import get_evaluator
from app.trading.paper_broker import open_trade, count_open_trades
from app.trading.risk import check_can_trade, RiskCheckFailed
from app.trading.portfolio_risk import check_portfolio_risk, PortfolioRiskBlocked, get_portfolio_state
from app.trading.execution_sim import estimate_execution
from app.trading.kill_switch import check_kill_switch, KillSwitchActive
import app.alerts as alerts


async def run_daily_signal_job() -> dict:
    db: Session = SessionLocal()
    results = []

    try:
        _log(db, "INFO", "daily_job", "Starting daily signal evaluation")

        active_configs = (
            db.query(BotConfig)
            .filter(BotConfig.is_active == True)
            .all()
        )

        if not active_configs:
            _log(db, "WARNING", "daily_job", "No active bot configs — nothing to evaluate")
            db.close()
            return {"status": "no_configs", "results": []}

        # Cache DVOL once (shared across all strategies that need it)
        dvol_data = None
        dvol_error = None
        try:
            dvol_data = await get_dvol_snapshot()
        except Exception as e:
            dvol_error = str(e)
            _log(db, "WARNING", "daily_job", f"DVOL fetch failed: {e}")
            alerts.fire_data_failed("deribit_dvol", str(e), db)

        for cfg in active_configs:
            result = await _run_for_config(db, cfg.market, cfg.strategy_name, dvol_data)
            results.append(result)

        overall = "ok" if all(r["status"] not in ("error",) for r in results) else "partial_error"
        return {"status": overall, "results": results}

    except Exception as e:
        try:
            _log(db, "ERROR", "daily_job", f"Job failed: {e}")
        except Exception:
            pass
        return {"status": "error", "error": str(e), "results": results}

    finally:
        db.close()


async def _run_for_config(
    db: Session,
    market: str,
    strategy_name: str,
    dvol_data: dict | None,
) -> dict:
    result = {"market": market, "strategy": strategy_name, "status": "unknown",
              "signal": None, "trade_opened": False, "error": None}
    try:
        # Fetch current market snapshot for this market
        snapshot = await get_market_snapshot(market)

        # Save market data (only for BTCUSDT to avoid duplicate rows)
        if market == "BTCUSDT" and dvol_data:
            db.add(MarketData(
                timestamp=snapshot["timestamp"],
                btc_price=snapshot["price"],
                btc_mark_price=snapshot.get("mark_price"),
                funding_rate=snapshot["funding_rate"],
                dvol=dvol_data.get("dvol"),
            ))
            db.commit()

        # Evaluate signal
        evaluator = get_evaluator(strategy_name)
        sig = await evaluator.evaluate(market)

        # Persist signal row
        db.add(Signal(
            timestamp=datetime.now(timezone.utc),
            strategy_name=sig.strategy_name,
            market=market,
            dvol=sig.dvol,
            dvol_mean_30d=sig.dvol_mean_30d,
            dvol_std_30d=sig.dvol_std_30d,
            n3_z=sig.n3_z,
            dvol_filter_pass=sig.dvol_filter_pass,
            entry_signal=sig.entry_signal,
            reason=sig.reason,
            signal_metadata=json.dumps(sig.metadata) if sig.metadata else None,
        ))
        db.commit()

        result["signal"] = {"entry_signal": sig.entry_signal, "reason": sig.reason}
        _log(db, "INFO", "daily_job", f"[{market}/{strategy_name}] {sig.reason}")

        # P3-specific alert when signal fires
        if sig.entry_signal and strategy_name.startswith("P3_OIPD"):
            meta = sig.metadata or {}
            alerts.fire_p3_signal(
                market=market,
                dp=meta.get("dp", 0.0),
                doi=meta.get("doi", 0.0),
                dvol=sig.dvol or 0.0,
                db=db,
            )

        if sig.entry_signal:
            open_count = count_open_trades(db, market, strategy_name)
            try:
                # System-wide kill switch check
                check_kill_switch(db)
                # Per-strategy risk check
                check_can_trade(
                    price=snapshot["price"],
                    open_trade_count=open_count,
                    dvol=sig.dvol,
                    n_dvol_bars=dvol_data["n_bars_used"] if dvol_data and sig.dvol else None,
                    dvol_timestamp=dvol_data["timestamp"] if dvol_data and sig.dvol else None,
                )
                # Portfolio-level risk check
                portfolio_state = check_portfolio_risk(db, strategy_name, market)

                # Execution quality estimate (informational — recorded in reason)
                exec_est = estimate_execution(snapshot["price"], sig.dvol, sig.side)

                trade = open_trade(
                    db=db,
                    market=market,
                    strategy_name=strategy_name,
                    side=sig.side,
                    entry_price=snapshot["price"],
                    hold_hours=sig.hold_hours,
                    entry_reason=sig.reason,
                    entry_dvol=sig.dvol,
                    entry_n3_z=sig.n3_z,
                )
                result["trade_opened"] = True
                result["status"] = "trade_opened"
                result["execution_estimate"] = exec_est.to_dict()
                _log(db, "INFO", "daily_job",
                     f"[{market}/{strategy_name}] Trade #{trade.id} opened @ {snapshot['price']:.2f} "
                     f"| maker_prob={exec_est.maker_fill_probability:.0%} "
                     f"| quality={exec_est.execution_quality_score}/10")
            except KillSwitchActive as e:
                _log(db, "WARNING", "daily_job",
                     f"[{market}/{strategy_name}] Kill switch active — trade blocked")
                result["status"] = "kill_switch_active"
                result["error"] = str(e)
            except RiskCheckFailed as e:
                _log(db, "WARNING", "daily_job",
                     f"[{market}/{strategy_name}] Per-strategy risk blocked: {e}")
                result["status"] = "risk_blocked"
                result["error"] = str(e)
            except PortfolioRiskBlocked as e:
                _log(db, "WARNING", "daily_job",
                     f"[{market}/{strategy_name}] Portfolio risk blocked: {e}")
                alerts.fire_risk_blocked(strategy_name, market, str(e), db)
                result["status"] = "portfolio_risk_blocked"
                result["error"] = str(e)
        else:
            result["status"] = "no_signal"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        try:
            _log(db, "ERROR", "daily_job", f"[{market}/{strategy_name}] Error: {e}")
        except Exception:
            pass

    return result


def _log(db: Session, level: str, component: str, message: str) -> None:
    db.add(SystemLog(level=level, component=component, message=message))
    db.commit()
