"""
Pre-trade risk checks for paper trading.

check_can_trade()    — per-strategy checks (price validity, position count, DVOL history)
check_feed_staleness() — multi-feed staleness gate using the market registry

All checks raise RiskCheckFailed on failure. The caller catches this,
logs the reason, fires an alert, and skips the trade without aborting
the overall daily job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import DATA_STALE_MINUTES, DVOL_LOOKBACK_DAYS

log = logging.getLogger(__name__)


class RiskCheckFailed(Exception):
    pass


def check_can_trade(
    price: float | None,
    open_trade_count: int,
    dvol: float | None = None,
    n_dvol_bars: int | None = None,
    dvol_timestamp: datetime | None = None,
) -> None:
    """
    Per-strategy pre-trade checks.

    Parameters
    ----------
    price            : Current mark price (required; must be positive).
    open_trade_count : Number of open trades for this market/strategy pair.
    dvol             : Current DVOL reading (checked only if provided).
    n_dvol_bars      : Number of hourly DVOL bars available (min = 30d × 24h).
    dvol_timestamp   : Exchange event_time of the most recent DVOL bar.

    Raises RiskCheckFailed with a descriptive message on the first failure.
    """
    if price is None or price <= 0:
        raise RiskCheckFailed("Price missing or invalid")

    if open_trade_count >= 1:
        raise RiskCheckFailed(
            f"Position limit: {open_trade_count} open trade(s) already exist "
            "for this market/strategy"
        )

    if dvol is not None:
        if dvol <= 0:
            raise RiskCheckFailed("DVOL value missing or invalid")

        if n_dvol_bars is not None:
            min_bars = DVOL_LOOKBACK_DAYS * 24
            if n_dvol_bars < min_bars:
                raise RiskCheckFailed(
                    f"Insufficient DVOL history: {n_dvol_bars} bars, "
                    f"need {min_bars} (30d × 24h)"
                )

        if dvol_timestamp is not None:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=DATA_STALE_MINUTES)
            if dvol_timestamp < stale_cutoff:
                raise RiskCheckFailed(
                    f"DVOL data stale: last exchange event at "
                    f"{dvol_timestamp.isoformat()} (threshold: {DATA_STALE_MINUTES} min)"
                )


def check_feed_staleness(db, market_id: str) -> None:
    """
    Block entry if any critical feed for this market is stale.

    Uses the market registry to determine which feeds are required and their
    per-feed staleness thresholds. Non-critical feeds log a warning but do
    not block the trade.

    Raises RiskCheckFailed listing all stale critical feeds.
    """
    from app.data.staleness import check_all_feeds

    results = check_all_feeds(db, market_id)
    critical_stale = [r for r in results.values() if r.critical and not r.ok]
    advisory_stale = [r for r in results.values() if not r.critical and not r.ok]

    for r in advisory_stale:
        log.warning("Feed advisory stale [%s] %s", market_id, r.message)

    if critical_stale:
        msgs = "; ".join(r.message for r in critical_stale)
        raise RiskCheckFailed(f"Critical feed(s) stale for {market_id}: {msgs}")
