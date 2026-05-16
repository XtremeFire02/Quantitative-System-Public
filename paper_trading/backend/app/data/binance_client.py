"""Binance FAPI data fetcher — price, mark price, funding rate."""
import httpx
from datetime import datetime, timezone
from typing import Optional
from app.config import BINANCE_FAPI_BASE


async def fetch_price(symbol: str) -> float:
    """Current perpetual last traded price for any USDT-M symbol."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/price",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        return float(r.json()["price"])


async def fetch_mark_price(symbol: str) -> dict:
    """Mark price + funding rate from premiumIndex endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
        )
        r.raise_for_status()
        data = r.json()
        return {
            "mark_price": float(data["markPrice"]),
            "funding_rate": float(data["lastFundingRate"]),
            "next_funding_time": int(data["nextFundingTime"]),
        }


async def fetch_funding_history(symbol: str, start_ms: int, limit: int = 1000) -> list[dict]:
    """Historical funding rates from startTime for any symbol."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate",
            params={"symbol": symbol, "startTime": start_ms, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


async def get_market_snapshot(symbol: str = "BTCUSDT") -> dict:
    """Price, mark price, and funding rate for any symbol."""
    price = await fetch_price(symbol)
    mark_data = await fetch_mark_price(symbol)
    return {
        "symbol": symbol,
        "price": price,
        "btc_price": price,           # legacy key — kept for existing callers
        "btc_mark_price": mark_data["mark_price"],
        "mark_price": mark_data["mark_price"],
        "funding_rate": mark_data["funding_rate"],
        "timestamp": datetime.now(timezone.utc),
    }


# ── Backward-compat aliases ───────────────────────────────────────────────────

async def fetch_btc_price() -> Optional[float]:
    return await fetch_price("BTCUSDT")


async def fetch_klines_close(symbol: str = "BTCUSDT", limit: int = 2) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1d", "limit": limit},
        )
        r.raise_for_status()
        return [{"open_time": int(row[0]), "close": float(row[4])} for row in r.json()]


async def fetch_oi_history(symbol: str = "BTCUSDT", period: str = "1d", limit: int = 3) -> list[dict]:
    """Daily open interest snapshots from Binance futures data API.

    With period='1d' and limit=3, returns the last 3 end-of-day OI readings.
    Use rows[0] and rows[1] for a completed 24h comparison; rows[2] is the
    in-progress bar at the time of the request.
    """
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
            }
            for row in r.json()
        ]
