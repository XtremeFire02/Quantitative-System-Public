"""
Daily signal job — runs at 00:00 UTC.
Iterates all active BotConfig rows and evaluates each strategy/market pair.

Pre-flight: before any data is fetched or trades are evaluated, both
exchange feeds (Binance FAPI and Deribit) are probed. If any critical
feed is unreachable the job aborts immediately and fires a data_failed alert.
This upgrades connectivity monitoring from advisory to enforced.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import app.alerts as alerts
from app.data.binance_client import get_market_snapshot
from app.data.deribit_client import get_dvol_snapshot
from app.data.exchange_probe import probe_all
from app.database import BotConfig, EquityCurve, MarketData, SessionLocal, Signal, SystemLog
from app.markets import get_market, symbol_to_market_id
from app.signals.dispatcher import get_evaluator
from app.trading.broker_adapter import OrderRequest, get_paper_adapter
from app.trading.execution_sim import estimate_execution
from app.trading.kill_switch import KillSwitchActive, check_kill_switch
from app.trading.paper_broker import count_open_trades
from app.trading.portfolio_risk import PortfolioRiskBlocked, check_portfolio_risk
from app.trading.position_sizer import SizingInput, compute_size
from app.config import LOG_RETENTION_DAYS
from app.trading.risk import RiskCheckFailed, check_can_trade, check_feed_staleness


def _prune_logs(db: Session) -> int:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
    deleted = db.query(SystemLog).filter(SystemLog.timestamp < cutoff).delete()
    db.commit()
    return deleted


async def run_daily_signal_job() -> dict:
    db: Session = SessionLocal()
    results = []

    try:
        pruned = _prune_logs(db)
        _log(db, "INFO", "daily_job", f"Starting daily signal evaluation (pruned {pruned} old log rows)")

        # ── Connectivity pre-flight ───────────────────────────────────────────
        # Abort the entire job if any critical exchange feed is unreachable.
        # This is enforcement, not just monitoring — we do not proceed to data
        # fetching or trade evaluation when feeds are known-down at job start.
        probes, overall_level = await probe_all()
        failed_probes = [p for p in probes if not p.ok]
        if overall_level == "critical":
            msg = "Connectivity pre-flight failed: " + "; ".join(
                f"{p.name} ({p.error or f'HTTP {p.status_code}'})"
                for p in failed_probes
            )
            _log(db, "ERROR", "daily_job", msg)
            alerts.fire_data_failed("connectivity_preflight", msg, db)
            db.close()
            return {"status": "connectivity_failed", "error": msg, "results": []}

        if overall_level == "warn":
            warn_msg = "Connectivity degraded (warn): " + "; ".join(
                f"{p.name} {p.latency_ms:.0f}ms" for p in probes if p.level == "warn"
            )
            _log(db, "WARNING", "daily_job", warn_msg)

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
        try:
            dvol_data = await get_dvol_snapshot()
        except Exception as e:
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
        # Resolve canonical market ID from the exchange symbol
        market_id = symbol_to_market_id(market)

        # Fetch current market snapshot for this market
        snapshot = await get_market_snapshot(market)

        # Log OI and funding fetch events so staleness.py can track them
        if snapshot.get("open_interest") is not None:
            _log(db, "INFO", "oi_fetch", f"[{market}] OI={snapshot['open_interest']:.0f}")
        _log(db, "INFO", "funding_fetch",
             f"[{market}] funding={snapshot.get('funding_rate', 0):.6f}")

        # Persist market data row (one row per symbol per run)
        db.add(MarketData(
            symbol=market,
            timestamp=snapshot["timestamp"],
            price=snapshot["price"],
            mark_price=snapshot.get("mark_price"),
            funding_rate=snapshot["funding_rate"],
            dvol=dvol_data.get("dvol") if dvol_data else None,
            price_event_time=snapshot.get("price_event_time"),
            dvol_event_time=dvol_data.get("event_time") if dvol_data else None,
            oi_event_time=snapshot.get("oi_event_time"),
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

                # Multi-feed staleness gate (blocks on any critical stale feed)
                check_feed_staleness(db, market_id)

                # Per-strategy risk check
                check_can_trade(
                    price=snapshot["price"],
                    open_trade_count=open_count,
                    dvol=sig.dvol,
                    n_dvol_bars=dvol_data["n_bars_used"] if dvol_data and sig.dvol else None,
                    dvol_timestamp=dvol_data.get("event_time") if dvol_data and sig.dvol else None,
                )

                # Portfolio-level risk check
                check_portfolio_risk(db, strategy_name, market)

                # Position sizing — fixed mode by default; vol_target mode via env var
                last_equity = db.query(EquityCurve).order_by(EquityCurve.id.desc()).first()
                current_equity = last_equity.equity if last_equity else 10_000.0
                signal_strength = min(1.0, max(0.0, sig.n3_z)) if sig.n3_z is not None else 1.0
                _market_vol_fallback = get_market(symbol_to_market_id(market)).typical_annual_vol
                asset_vol_ann = (sig.dvol / 100.0) if sig.dvol is not None else _market_vol_fallback
                sizing = compute_size(SizingInput(
                    signal_strength=signal_strength,
                    asset_vol_ann=asset_vol_ann,
                    available_capital=current_equity,
                    strategy_name=strategy_name,
                ))

                # Execution quality estimate (market-aware, includes slippage for P&L attribution)
                exec_est = estimate_execution(
                    market_id=market_id,
                    signal_price=snapshot["price"],
                    dvol=sig.dvol,
                    side=sig.side,
                    notional_usd=sizing.notional_usd,
                )

                # Submit order through the broker adapter (OMS → paper_broker)
                adapter = get_paper_adapter()
                fill = await adapter.submit(
                    db=db,
                    request=OrderRequest(
                        market=market,
                        strategy_name=strategy_name,
                        side=sig.side,
                        notional_usd=sizing.notional_usd,
                        signal_price=snapshot["price"],
                        entry_reason=sig.reason,
                        hold_hours=sig.hold_hours,
                        exec_estimate=exec_est,
                        entry_dvol=sig.dvol,
                        entry_n3_z=sig.n3_z,
                    ),
                )
                result["trade_opened"] = fill.status == "filled"
                result["status"] = "trade_opened" if fill.status == "filled" else f"fill_{fill.status}"
                result["order_id"] = fill.order_id
                result["trade_id"] = fill.trade_id
                result["execution_estimate"] = exec_est.to_dict()
                result["sizing"] = {
                    "notional_usd": sizing.notional_usd,
                    "sizing_mode": sizing.sizing_mode,
                    "signal_weight": sizing.signal_weight,
                }
                _log(db, "INFO", "daily_job",
                     f"[{market}/{strategy_name}] Order #{fill.order_id} → "
                     f"Trade #{fill.trade_id} {fill.status} @ {fill.fill_price or snapshot['price']:.2f} "
                     f"[{fill.fill_type or 'n/a'}] notional=${sizing.notional_usd:,.0f} "
                     f"[{sizing.sizing_mode}] quality={exec_est.execution_quality_score}/10")
            except KillSwitchActive as e:
                _log(db, "WARNING", "daily_job",
                     f"[{market}/{strategy_name}] Kill switch active — trade blocked")
                result["status"] = "kill_switch_active"
                result["error"] = str(e)
            except RiskCheckFailed as e:
                _log(db, "WARNING", "daily_job",
                     f"[{market}/{strategy_name}] Risk blocked: {e}")
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
