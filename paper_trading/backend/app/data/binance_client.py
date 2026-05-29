"""
Binance FAPI data fetcher — price, mark price, funding, open interest.

All public functions are decorated with async_retry (3 attempts, 0.5 s base).
Responses include both event_time (exchange server timestamp) and receive_time
(local clock at response arrival) to support latency and drift analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.config import BINANCE_FAPI_BASE
from app.data.retry import async_retry
from app.data.ws_market_data import get_latest

# ── Internal helpers ──────────────────────────────────────────────────────────

def _utc(ts_ms: int | None) -> datetime | None:
    """Convert a Binance millisecond timestamp to UTC datetime."""
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Core fetchers ─────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_price(symbol: str) -> dict:
    """Last traded price for any USDT-M symbol.

    Returns: {"price": float, "event_time": datetime, "receive_time": datetime}
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/price",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        receive_time = _now()
        data = r.json()
        return {
            "price": float(data["price"]),
            "event_time": _utc(data.get("time")),
            "receive_time": receive_time,
        }


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_mark_price(symbol: str) -> dict:
    """Mark price and funding rate from premiumIndex.

    Returns event_time from the exchange field `time`, which is the
    server-side timestamp of the premium index snapshot.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        receive_time = _now()
        data = r.json()
        return {
            "mark_price": float(data["markPrice"]),
            "funding_rate": float(data["lastFundingRate"]),
            "next_funding_time": int(data["nextFundingTime"]),
            "event_time": _utc(data.get("time")),
            "receive_time": receive_time,
        }


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_funding_history(symbol: str, start_ms: int, limit: int = 1000) -> list[dict]:
    """Historical 8-hour funding rate settlements from startTime."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate",
            params={"symbol": symbol, "startTime": start_ms, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_oi_snapshot(symbol: str) -> dict:
    """Current open interest for a symbol.

    Returns: {"open_interest": float, "event_time": datetime, "receive_time": datetime}
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/openInterest",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        receive_time = _now()
        data = r.json()
        return {
            "open_interest": float(data["openInterest"]),
            "event_time": _utc(data.get("time")),
            "receive_time": receive_time,
        }


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_oi_history(symbol: str, period: str = "1d", limit: int = 3) -> list[dict]:
    """Daily open interest snapshots from Binance futures data API."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/futures/data/openInterestHist",
            params={"symbol": symbol, "period": period, "limit": limit},
        )
        r.raise_for_status()
        return [
            {
                "timestamp": int(row["timestamp"]),
                "open_interest": float(row["sumOpenInterest"]),
                "open_interest_value": float(row["sumOpenInterestValue"]),
                "event_time": _utc(int(row["timestamp"])),
            }
            for row in r.json()
        ]


# ── Composite snapshots ───────────────────────────────────────────────────────

async def get_market_snapshot(symbol: str = "BTCUSDT") -> dict:
    """
    Full market snapshot: price, mark price, funding rate, OI.

    Fetches price, mark price, and OI via REST (always needed for OI, volume,
    and as fallback). If the WebSocket cache has a fresh snapshot (< 30 s old)
    for the symbol, mark_price and funding_rate from the cache override the
    REST values, reducing latency for those fields.

    Returns a flat dict with generic keys (price, mark_price, funding_rate, etc.).
    """
    import asyncio
    price_data, mark_data, oi_data = await asyncio.gather(
        fetch_price(symbol),
        fetch_mark_price(symbol),
        fetch_oi_snapshot(symbol),
        return_exceptions=True,
    )

    # Price is critical — propagate exception
    if isinstance(price_data, Exception):
        raise price_data

    # Mark price is critical — propagate exception
    if isinstance(mark_data, Exception):
        raise mark_data

    # OI failure is non-critical — log and continue with None
    oi_result = None if isinstance(oi_data, Exception) else oi_data

    price = price_data["price"]
    mark = mark_data["mark_price"]
    funding = mark_data["funding_rate"]

    # Prefer WebSocket cache for mark price and funding rate when fresh (< 30 s)
    ws_snapshot = get_latest(symbol)
    if ws_snapshot is not None:
        age_s = (datetime.now(timezone.utc) - ws_snapshot["received_at"]).total_seconds()
        if age_s < 30:
            mark = ws_snapshot["mark_price"]
            funding = ws_snapshot["funding_rate"]

    return {
        # Generic keys
        "symbol": symbol,
        "price": price,
        "mark_price": mark,
        "funding_rate": funding,
        "next_funding_time": mark_data["next_funding_time"],
        "open_interest": oi_result["open_interest"] if oi_result else None,
        # Timestamps
        "timestamp": price_data["receive_time"],          # local receive time (legacy)
        "price_event_time": price_data["event_time"],    # exchange server time
        "dvol_event_time": mark_data["event_time"],      # proxy for general feed event time
        "oi_event_time": oi_result["event_time"] if oi_result else None,
    }


# ── Feed reconciliation ────────────────────────────────────────────────────────

def reconcile_snapshot(snapshot: dict) -> list[str]:
    """
    Sanity-check a market snapshot for internal consistency.
    Returns a list of warning strings; empty = clean.
    """
    warnings: list[str] = []
    price = snapshot.get("price")
    mark = snapshot.get("mark_price")

    if price and mark:
        basis_bp = abs(price - mark) / mark * 10_000
        if basis_bp > 200:
            warnings.append(
                f"Large price/mark divergence: {basis_bp:.1f} bp "
                f"(price={price}, mark={mark})"
            )

    funding = snapshot.get("funding_rate")
    if funding is not None and abs(funding) > 0.003:
        warnings.append(
            f"Extreme funding rate: {funding:.4%} — possible data anomaly"
        )

    price_et = snapshot.get("price_event_time")
    dvol_et = snapshot.get("dvol_event_time")
    if price_et and dvol_et:
        lag_s = abs((price_et - dvol_et).total_seconds())
        if lag_s > 300:
            warnings.append(
                f"Price and mark timestamps diverge by {lag_s:.0f}s — feed sync issue"
            )

    return warnings


async def fetch_klines_close(symbol: str = "BTCUSDT", limit: int = 2) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1d", "limit": limit},
        )
        r.raise_for_status()
        return [{"open_time": int(row[0]), "close": float(row[4])} for row in r.json()]
