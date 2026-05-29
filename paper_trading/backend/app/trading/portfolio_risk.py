"""
Portfolio-level risk manager.

Checks run before any new trade is opened, across all active strategies.
Raises PortfolioRiskBlocked on any violation — caller logs the reason.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import (
    PORTFOLIO_MAX_CONSECUTIVE_LOSSES,
    PORTFOLIO_MAX_DAILY_LOSS_BP,
    PORTFOLIO_MAX_GROSS_NOTIONAL_USD,
    PORTFOLIO_MAX_OPEN_POSITIONS,
    PORTFOLIO_MAX_SAME_MARKET,
    PORTFOLIO_MAX_STRATEGY_DD_PCT,
    POSITION_NOTIONAL_USD,
)
from app.database import Trade


class PortfolioRiskBlocked(Exception):
    pass


def check_portfolio_risk(db: Session, strategy_name: str, market: str) -> dict:
    """
    Raise PortfolioRiskBlocked if any portfolio-level limit is breached.
    Returns a state snapshot on success.

    Checks (in priority order):
      1. Total open position count
      2. Same-market concentration
      3. Gross notional exposure across all open positions
      4. Daily P&L loss limit
      5. Per-strategy trailing drawdown
      6. Circuit breaker: consecutive closing losers for this strategy
    """
    total_open = db.query(Trade).filter(Trade.status == "open").count()
    if total_open >= PORTFOLIO_MAX_OPEN_POSITIONS:
        raise PortfolioRiskBlocked(
            f"Max total open positions: {total_open}/{PORTFOLIO_MAX_OPEN_POSITIONS}"
        )

    market_open = (
        db.query(Trade)
        .filter(Trade.status == "open", Trade.market == market)
        .count()
    )
    if market_open >= PORTFOLIO_MAX_SAME_MARKET:
        raise PortfolioRiskBlocked(
            f"Max {market} positions: {market_open}/{PORTFOLIO_MAX_SAME_MARKET}"
        )

    # Gross notional exposure: sum of all open position sizes
    if PORTFOLIO_MAX_GROSS_NOTIONAL_USD > 0:
        open_trades = db.query(Trade).filter(Trade.status == "open").all()
        gross_notional = sum(
            (t.notional_usd or POSITION_NOTIONAL_USD) for t in open_trades
        )
        if gross_notional >= PORTFOLIO_MAX_GROSS_NOTIONAL_USD:
            raise PortfolioRiskBlocked(
                f"Gross notional exposure ${gross_notional:,.0f} >= "
                f"limit ${PORTFOLIO_MAX_GROSS_NOTIONAL_USD:,.0f}"
            )

    daily_pnl_bp = _daily_pnl_bp(db)
    if daily_pnl_bp <= PORTFOLIO_MAX_DAILY_LOSS_BP:
        raise PortfolioRiskBlocked(
            f"Daily loss limit hit: {daily_pnl_bp:.1f}bp (limit {PORTFOLIO_MAX_DAILY_LOSS_BP:.0f}bp)"
        )

    strategy_dd_pct = _strategy_trailing_dd_pct(db, strategy_name)
    if strategy_dd_pct is not None and strategy_dd_pct <= PORTFOLIO_MAX_STRATEGY_DD_PCT:
        raise PortfolioRiskBlocked(
            f"Strategy {strategy_name} drawdown {strategy_dd_pct:.1%} "
            f"exceeds limit {PORTFOLIO_MAX_STRATEGY_DD_PCT:.0%}"
        )

    # Circuit breaker: N consecutive closing losers for this strategy
    if PORTFOLIO_MAX_CONSECUTIVE_LOSSES > 0:
        consecutive = _consecutive_losses(db, strategy_name)
        if consecutive >= PORTFOLIO_MAX_CONSECUTIVE_LOSSES:
            raise PortfolioRiskBlocked(
                f"Circuit breaker: {consecutive} consecutive losing trades for "
                f"{strategy_name} (limit {PORTFOLIO_MAX_CONSECUTIVE_LOSSES})"
            )

    return {
        "allowed": True,
        "total_open": total_open,
        "market_open": market_open,
        "daily_pnl_bp": daily_pnl_bp,
        "strategy_dd_pct": strategy_dd_pct,
    }


def get_portfolio_state(db: Session) -> dict:
    """Full portfolio state snapshot for the risk dashboard."""
    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    daily_pnl_bp = _daily_pnl_bp(db)

    by_strategy: dict[str, list] = {}
    by_market: dict[str, int] = {}
    gross_notional = 0.0
    for t in open_trades:
        by_strategy.setdefault(t.strategy_name, []).append(t)
        by_market[t.market] = by_market.get(t.market, 0) + 1
        gross_notional += t.notional_usd or POSITION_NOTIONAL_USD

    # Per-strategy drawdown and circuit breaker state
    strategy_dds: dict[str, float | None] = {}
    strategy_consecutive_losses: dict[str, int] = {}
    all_strategy_names = list({t.strategy_name for t in open_trades})
    for name in all_strategy_names:
        strategy_dds[name] = _strategy_trailing_dd_pct(db, name)
        strategy_consecutive_losses[name] = _consecutive_losses(db, name)

    daily_limit_used_pct = 0.0
    if daily_pnl_bp < 0 and PORTFOLIO_MAX_DAILY_LOSS_BP != 0:
        daily_limit_used_pct = round(daily_pnl_bp / PORTFOLIO_MAX_DAILY_LOSS_BP * 100, 1)

    notional_limit_used_pct = 0.0
    if PORTFOLIO_MAX_GROSS_NOTIONAL_USD > 0:
        notional_limit_used_pct = round(gross_notional / PORTFOLIO_MAX_GROSS_NOTIONAL_USD * 100, 1)

    return {
        "total_open": len(open_trades),
        "max_total_open": PORTFOLIO_MAX_OPEN_POSITIONS,
        "max_same_market": PORTFOLIO_MAX_SAME_MARKET,
        "gross_notional_usd": round(gross_notional, 2),
        "daily_pnl_bp": round(daily_pnl_bp, 1),
        "daily_loss_limit_bp": PORTFOLIO_MAX_DAILY_LOSS_BP,
        "daily_limit_used_pct": daily_limit_used_pct,
        "notional_limit_used_pct": notional_limit_used_pct,
        "open_by_strategy": {k: len(v) for k, v in by_strategy.items()},
        "open_by_market": by_market,
        "strategy_drawdowns": strategy_dds,
        "strategy_consecutive_losses": strategy_consecutive_losses,
        "limits": {
            "max_open_positions": PORTFOLIO_MAX_OPEN_POSITIONS,
            "max_same_market_positions": PORTFOLIO_MAX_SAME_MARKET,
            "max_daily_loss_bp": PORTFOLIO_MAX_DAILY_LOSS_BP,
            "max_strategy_drawdown_pct": PORTFOLIO_MAX_STRATEGY_DD_PCT,
            "max_consecutive_losses": PORTFOLIO_MAX_CONSECUTIVE_LOSSES,
            "max_gross_notional_usd": PORTFOLIO_MAX_GROSS_NOTIONAL_USD,
        },
        "positions": [
            {
                "trade_id": t.id,
                "strategy": t.strategy_name,
                "market": t.market,
                "side": t.side,
                "notional_usd": t.notional_usd,
                "entry_price": t.entry_price,
                "entry_dvol": t.entry_dvol,
                "entry_quality_score": t.entry_quality_score,
                "entry_timestamp": _isoformat_utc(t.entry_timestamp),
                "planned_exit": _isoformat_utc(t.planned_exit_timestamp),
            }
            for t in open_trades
        ],
    }


def _isoformat_utc(ts) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _daily_pnl_bp(db: Session) -> float:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_closed = (
        db.query(Trade)
        .filter(Trade.status == "closed", Trade.exit_timestamp >= today_start)
        .all()
    )
    return sum(t.net_pnl_bp or 0.0 for t in today_closed)


def _consecutive_losses(db: Session, strategy_name: str) -> int:
    """Count consecutive closing losers for a strategy (most recent first). Resets on a winner."""
    trades = (
        db.query(Trade)
        .filter(Trade.strategy_name == strategy_name, Trade.status == "closed")
        .order_by(Trade.exit_timestamp.desc())
        .limit(PORTFOLIO_MAX_CONSECUTIVE_LOSSES + 5)
        .all()
    )
    count = 0
    for t in trades:
        if (t.net_pnl_bp or 0.0) < 0:
            count += 1
        else:
            break  # streak broken
    return count


def _strategy_trailing_dd_pct(db: Session, strategy_name: str) -> float | None:
    """Max drawdown (as pct) over last 20 closed trades for the strategy. None if < 5 trades."""
    trades = (
        db.query(Trade)
        .filter(Trade.strategy_name == strategy_name, Trade.status == "closed")
        .order_by(Trade.exit_timestamp.desc())
        .limit(20)
        .all()
    )
    if len(trades) < 5:
        return None

    pnls = [t.net_pnl_bp or 0.0 for t in reversed(trades)]
    peak = 0.0
    cum = 0.0
    max_dd_bp = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = cum - peak
        max_dd_bp = min(max_dd_bp, dd)

    return round(max_dd_bp / 10000, 4)  # bp → fraction
