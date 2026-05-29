"""
Liquidations feed — forced order events from Binance FAPI.
GET /api/market/liquidations?symbol=BTCUSDT&limit=100
GET /api/market/liquidations/summary
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.data.binance_market import fetch_liquidations

log = logging.getLogger(__name__)

router = APIRouter()

_MONITOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT"]


@router.get("/market/liquidations")
async def get_liquidations(
    symbol: str | None = Query(None, description="Filter to a specific symbol, e.g. BTCUSDT"),
    limit: int = Query(50, ge=1, le=500),
    min_usd: float = Query(0.0, description="Minimum notional USD threshold"),
):
    """Recent forced liquidations from Binance perpetuals."""
    try:
        data = await fetch_liquidations(symbol, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Binance error: {exc}")

    if min_usd > 0:
        data = [d for d in data if d["notional_usd"] >= min_usd]

    # Sort by most recent first
    data.sort(key=lambda x: x["timestamp"], reverse=True)

    total_long_liq = sum(d["notional_usd"] for d in data if d["side"] == "SELL")
    total_short_liq = sum(d["notional_usd"] for d in data if d["side"] == "BUY")

    return {
        "symbol": symbol or "all",
        "liquidations": data[:limit],
        "total_long_liquidated_usd":  round(total_long_liq, 0),
        "total_short_liquidated_usd": round(total_short_liq, 0),
        "total_usd": round(total_long_liq + total_short_liq, 0),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/market/liquidations/summary")
async def get_liquidations_summary():
    """
    Cross-asset liquidation summary for all monitored symbols.
    Returns aggregate long/short liquidations per asset.
    """
    tasks = [fetch_liquidations(sym, 200) for sym in _MONITOR_SYMBOLS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    summary = []
    for sym, result in zip(_MONITOR_SYMBOLS, results):
        if isinstance(result, Exception):
            log.warning("Liquidation fetch failed for %s: %s", sym, result)
            summary.append({"symbol": sym, "error": str(result)})
            continue
        long_liq  = sum(d["notional_usd"] for d in result if d["side"] == "SELL")
        short_liq = sum(d["notional_usd"] for d in result if d["side"] == "BUY")
        summary.append({
            "symbol":              sym,
            "long_liquidated_usd":  round(long_liq, 0),
            "short_liquidated_usd": round(short_liq, 0),
            "total_usd":            round(long_liq + short_liq, 0),
            "n_events":             len(result),
            "dominant_side": (
                "long" if long_liq > short_liq
                else "short" if short_liq > long_liq
                else "neutral"
            ),
        })

    return {
        "assets": summary,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
