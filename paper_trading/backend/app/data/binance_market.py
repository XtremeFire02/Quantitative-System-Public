"""
Extended Binance FAPI fetchers — OHLCV, order book, multi-asset stats, term structure.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import BINANCE_FAPI_BASE
from app.data.retry import async_retry


def _utc(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── OHLCV ─────────────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_klines(symbol: str, interval: str = "1h", limit: int = 500) -> list[dict]:
    """OHLCV klines for any USDT-M perp symbol and candlestick interval."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": min(limit, 1500)},
        )
        r.raise_for_status()
        return [
            {
                "t": int(row[0]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
                "v": float(row[5]),
            }
            for row in r.json()
        ]


# ── Order book ────────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_orderbook(symbol: str, depth: int = 20) -> dict:
    """Best bid/ask depth snapshot for a symbol."""
    valid_depths = (5, 10, 20, 50, 100, 500, 1000)
    depth = min(valid_depths, key=lambda d: abs(d - depth))
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/depth",
            params={"symbol": symbol, "limit": depth},
        )
        r.raise_for_status()
        data = r.json()
        return {
            "symbol": symbol,
            "last_update_id": data.get("lastUpdateId"),
            "bids": [[float(p), float(q)] for p, q in data["bids"]],
            "asks": [[float(p), float(q)] for p, q in data["asks"]],
        }


# ── Multi-asset 24h stats ─────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_24h_stats_multi(symbols: list[str]) -> list[dict]:
    """24h ticker stats for a list of symbols in one batch call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr")
        r.raise_for_status()
        sym_set = set(symbols)
        return [
            {
                "symbol": d["symbol"],
                "price": float(d["lastPrice"]),
                "price_change_pct": float(d["priceChangePercent"]),
                "high_24h": float(d["highPrice"]),
                "low_24h": float(d["lowPrice"]),
                "volume": float(d["volume"]),
                "quote_volume": float(d["quoteVolume"]),
                "count": int(d["count"]),
            }
            for d in r.json()
            if d["symbol"] in sym_set
        ]


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_premium_index_multi(symbols: list[str]) -> list[dict]:
    """Mark price and current funding rate for multiple symbols."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex")
        r.raise_for_status()
        sym_set = set(symbols)
        return [
            {
                "symbol": d["symbol"],
                "mark_price": float(d["markPrice"]),
                "index_price": float(d.get("indexPrice", d["markPrice"])),
                "funding_rate": float(d["lastFundingRate"]),
                "next_funding_time": int(d["nextFundingTime"]),
            }
            for d in r.json()
            if d["symbol"] in sym_set
        ]


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_open_interest_multi(symbols: list[str]) -> list[dict]:
    """Open interest for multiple symbols via parallel fetches."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = [
            client.get(f"{BINANCE_FAPI_BASE}/fapi/v1/openInterest", params={"symbol": sym})
            for sym in symbols
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
    result = []
    for sym, resp in zip(symbols, responses):
        if isinstance(resp, Exception):
            result.append({"symbol": sym, "open_interest": None})
        else:
            try:
                resp.raise_for_status()
                data = resp.json()
                result.append({"symbol": sym, "open_interest": float(data["openInterest"])})
            except Exception:
                result.append({"symbol": sym, "open_interest": None})
    return result


# ── Term structure ─────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def _fetch_all_premium_index() -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex")
        r.raise_for_status()
        return r.json()


@async_retry(max_attempts=3, base_delay=1.0)
async def _fetch_exchange_info() -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo")
        r.raise_for_status()
        return r.json()


async def fetch_term_structure(base: str = "BTC") -> list[dict]:
    """
    Futures term structure for a base asset: perpetual + quarterly contracts.
    Basis pct is computed relative to the perpetual mark price.
    """
    info, premium_resp = await asyncio.gather(
        _fetch_exchange_info(),
        _fetch_all_premium_index(),
    )

    sym_info = {
        s["symbol"]: s
        for s in info["symbols"]
        if s.get("baseAsset") == base
        and s.get("contractType") in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")
        and s.get("status") == "TRADING"
    }

    price_map = {d["symbol"]: d for d in premium_resp if d["symbol"] in sym_info}

    result = []
    for sym, si in sym_info.items():
        d = price_map.get(sym)
        if not d:
            continue
        delivery_ms = si.get("deliveryDate", 0)
        result.append({
            "symbol": sym,
            "contract_type": si["contractType"],
            "mark_price": float(d["markPrice"]),
            "index_price": float(d.get("indexPrice", d["markPrice"])),
            "funding_rate": float(d.get("lastFundingRate", 0)),
            "delivery_date": _utc(delivery_ms).isoformat() if delivery_ms else None,
            "basis_pct": 0.0,
        })

    perp = next((r for r in result if r["contract_type"] == "PERPETUAL"), None)
    if perp and perp["mark_price"]:
        for r in result:
            if r["contract_type"] != "PERPETUAL":
                r["basis_pct"] = (r["mark_price"] - perp["mark_price"]) / perp["mark_price"] * 100

    result.sort(key=lambda x: (x["contract_type"] != "PERPETUAL", x.get("delivery_date") or ""))
    return result


# ── Liquidations ──────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_liquidations(symbol: str | None = None, limit: int = 100) -> list[dict]:
    """
    Recent forced liquidation orders from Binance FAPI.
    Returns large liquidations sorted by timestamp descending.
    """
    params: dict = {"limit": min(limit, 1000)}
    if symbol:
        params["symbol"] = symbol
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{BINANCE_FAPI_BASE}/fapi/v1/allForceOrders",
            params=params,
        )
        r.raise_for_status()
        return [
            {
                "symbol": d["symbol"],
                "side": d["side"],
                "price": float(d["price"]),
                "qty": float(d["origQty"]),
                "notional_usd": float(d["price"]) * float(d["origQty"]),
                "timestamp": int(d["time"]),
                "time_utc": _utc(int(d["time"])).isoformat(),
            }
            for d in r.json()
        ]
