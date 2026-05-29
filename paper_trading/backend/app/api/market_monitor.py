"""
Market Monitor API — multi-asset snapshot, term structure, correlation matrix.
GET /api/market/monitor
GET /api/market/term-structure?base=BTC
GET /api/market/correlations?period=30
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.data.binance_market import (
    fetch_24h_stats_multi,
    fetch_klines,
    fetch_open_interest_multi,
    fetch_premium_index_multi,
    fetch_term_structure,
)
from app.data.deribit_client import fetch_current_dvol

router = APIRouter()

# Assets tracked by the market monitor
MONITOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT"]
MONITOR_BASES = ["BTC", "ETH", "SOL", "BNB", "XRP", "AVAX"]


# ── Correlation helpers ───────────────────────────────────────────────────────

def _log_returns(closes: list[float]) -> list[float]:
    result = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            result.append(math.log(closes[i] / closes[i - 1]))
    return result


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    xs, ys = xs[:n], ys[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n)
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)
    if std_x == 0 or std_y == 0:
        return None
    return round(cov / (std_x * std_y), 4)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/market/monitor")
async def get_market_monitor():
    """
    Multi-asset snapshot: price, 24h change, mark price, funding rate, open interest.
    Also fetches BTC and ETH DVOL from Deribit.
    """
    stats_task = fetch_24h_stats_multi(MONITOR_SYMBOLS)
    premium_task = fetch_premium_index_multi(MONITOR_SYMBOLS)
    oi_task = fetch_open_interest_multi(MONITOR_SYMBOLS)
    dvol_btc_task = fetch_current_dvol("BTC")
    dvol_eth_task = fetch_current_dvol("ETH")

    results = await asyncio.gather(
        stats_task, premium_task, oi_task, dvol_btc_task, dvol_eth_task,
        return_exceptions=True,
    )

    stats_list, premium_list, oi_list, dvol_btc, dvol_eth = results

    # Build lookup dicts
    stats_map: dict[str, dict] = {}
    if not isinstance(stats_list, Exception):
        stats_map = {d["symbol"]: d for d in stats_list}

    premium_map: dict[str, dict] = {}
    if not isinstance(premium_list, Exception):
        premium_map = {d["symbol"]: d for d in premium_list}

    oi_map: dict[str, dict | None] = {}
    if not isinstance(oi_list, Exception):
        oi_map = {d["symbol"]: d for d in oi_list}

    dvol_map: dict[str, float | None] = {
        "BTC": dvol_btc["dvol"] if not isinstance(dvol_btc, Exception) else None,
        "ETH": dvol_eth["dvol"] if not isinstance(dvol_eth, Exception) else None,
    }

    assets = []
    for sym, base in zip(MONITOR_SYMBOLS, MONITOR_BASES):
        s = stats_map.get(sym, {})
        p = premium_map.get(sym, {})
        o = oi_map.get(sym, {}) or {}
        assets.append({
            "symbol": sym,
            "base": base,
            "price": s.get("price") or p.get("mark_price"),
            "price_change_pct": s.get("price_change_pct"),
            "high_24h": s.get("high_24h"),
            "low_24h": s.get("low_24h"),
            "volume": s.get("volume"),
            "quote_volume": s.get("quote_volume"),
            "mark_price": p.get("mark_price"),
            "index_price": p.get("index_price"),
            "funding_rate": p.get("funding_rate"),
            "next_funding_time": p.get("next_funding_time"),
            "open_interest": o.get("open_interest"),
            "dvol": dvol_map.get(base),
        })

    return {
        "assets": assets,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/market/term-structure")
async def get_term_structure(
    base: str = Query("BTC", description="Base asset: BTC, ETH, SOL, BNB"),
):
    """Futures term structure — perpetual and quarterly contracts with basis."""
    valid = {"BTC", "ETH", "SOL", "BNB", "XRP", "AVAX"}
    if base.upper() not in valid:
        raise HTTPException(status_code=400, detail=f"Valid bases: {sorted(valid)}")
    try:
        structure = await fetch_term_structure(base.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Binance error: {exc}")
    return {"base": base.upper(), "contracts": structure}


@router.get("/market/correlations")
async def get_correlations(
    period: int = Query(30, ge=7, le=90, description="Lookback period in days"),
):
    """
    Pearson correlation matrix of daily log returns for the 6 monitor assets.
    Returns a symmetric NxN matrix with row/column labels.
    """
    limit = period + 2  # fetch a couple extra to ensure enough for log returns

    tasks = [fetch_klines(sym, "1d", limit) for sym in MONITOR_SYMBOLS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    labels = MONITOR_BASES[:]
    returns_by_asset: list[list[float] | None] = []

    for i, res in enumerate(results):
        if isinstance(res, Exception) or not res:
            returns_by_asset.append(None)
        else:
            closes = [bar["c"] for bar in res]
            returns_by_asset.append(_log_returns(closes))

    n = len(MONITOR_SYMBOLS)
    matrix: list[list[float | None]] = [
        [None] * n for _ in range(n)
    ]

    for i in range(n):
        for j in range(n):
            ri = returns_by_asset[i]
            rj = returns_by_asset[j]
            if ri is None or rj is None:
                matrix[i][j] = None
            elif i == j:
                matrix[i][j] = 1.0
            else:
                matrix[i][j] = _pearson(ri, rj)

    return {
        "labels": labels,
        "matrix": matrix,
        "period_days": period,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
