"""
Multi-feed staleness checks with per-market thresholds.

Each market defines which feeds are required, their staleness thresholds,
and whether they are critical (block new entries) or advisory (warning only).

Usage:
    from app.data.staleness import check_all_feeds, StalenessResult

    results = check_all_feeds(db, market_id="BTCUSDT-PERP")
    critical_stale = [r for r in results.values() if r.critical and not r.ok]
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import MarketData, SystemLog
from app.markets import FeedConfig, get_market


@dataclass
class StalenessResult:
    feed: str
    last_update: datetime | None
    age_minutes: float | None     # None if no data at all
    threshold_minutes: int
    ok: bool                      # age <= threshold
    critical: bool                # from FeedConfig
    message: str


def _age_minutes(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0


def _last_log_ts(db: Session, component: str) -> datetime | None:
    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == component, SystemLog.level != "ERROR")
        .order_by(SystemLog.id.desc())
        .first()
    )
    if row is None:
        return None
    ts = row.timestamp
    return ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else ts


def _check_feed(db: Session, feed: FeedConfig, symbol: str) -> StalenessResult:
    """Route each feed name to its DB source and compute staleness."""
    last_update: datetime | None = None

    if feed.name == "price":
        row = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(MarketData.id.desc())
            .first()
        )
        if row is None:
            # Fall back to any market_data row (legacy: symbol column may not exist)
            row = db.query(MarketData).order_by(MarketData.id.desc()).first()
        if row is not None:
            ts = getattr(row, "price_event_time", None) or row.timestamp
            last_update = ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else ts

    elif feed.name == "dvol":
        row = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(MarketData.id.desc())
            .first()
        )
        if row is None:
            row = db.query(MarketData).filter(MarketData.dvol.isnot(None)).order_by(MarketData.id.desc()).first()
        if row is not None and row.dvol is not None:
            ts = getattr(row, "dvol_event_time", None) or row.timestamp
            last_update = ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else ts

    elif feed.name == "oi":
        # OI updates are logged by the data fetcher with component "oi_fetch"
        last_update = _last_log_ts(db, "oi_fetch")
        if last_update is None:
            # Fall back: check oi column on MarketData if it exists
            row = db.query(MarketData).filter(
                MarketData.open_interest.isnot(None)
            ).order_by(MarketData.id.desc()).first()
            if row is not None:
                ts = getattr(row, "oi_event_time", None) or row.timestamp
                last_update = ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else ts

    elif feed.name == "funding":
        last_update = _last_log_ts(db, "funding_fetch")

    age = _age_minutes(last_update)
    if age is None:
        ok = False
        msg = f"{feed.name}: no data in DB"
    elif age > feed.threshold_minutes:
        ok = False
        msg = f"{feed.name}: stale {age:.1f} min > {feed.threshold_minutes} min threshold"
    else:
        ok = True
        msg = f"{feed.name}: ok ({age:.1f} min old)"

    return StalenessResult(
        feed=feed.name,
        last_update=last_update,
        age_minutes=round(age, 1) if age is not None else None,
        threshold_minutes=feed.threshold_minutes,
        ok=ok,
        critical=feed.critical,
        message=msg,
    )


def check_all_feeds(db: Session, market_id: str) -> dict[str, StalenessResult]:
    """
    Check every feed defined for the given market.

    Returns a dict of feed_name → StalenessResult.
    Callers should check results where critical=True and ok=False to decide
    whether to block a new trade entry.
    """
    market = get_market(market_id)
    return {
        feed.name: _check_feed(db, feed, market.symbol)
        for feed in market.feeds
    }


def any_critical_stale(db: Session, market_id: str) -> list[StalenessResult]:
    """Return list of critical feeds that are currently stale. Empty = safe to trade."""
    results = check_all_feeds(db, market_id)
    return [r for r in results.values() if r.critical and not r.ok]
