"""
Chart API — OHLCV candlestick data with technical indicators, order book depth.
GET /api/chart/ohlcv?symbol=BTCUSDT&interval=1h&limit=500
GET /api/chart/orderbook?symbol=BTCUSDT&depth=20
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data.binance_market import fetch_klines, fetch_orderbook

router = APIRouter()


# ── Technical indicator helpers ───────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    k = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        val = values[i] * k + prev * (1.0 - k)
        result[i] = val
        prev = val
    return result


def _wilder_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(closes)):
        idx = i - 1
        avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
        avg_loss = (avg_loss * (period - 1) + losses[idx]) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        result[i] = 100.0 - 100.0 / (1.0 + rs)

    return result


def _macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    macd_line: list[float | None] = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]

    # EMA of MACD values for the signal line
    valid_vals = [v for v in macd_line if v is not None]
    sig_raw = _ema(valid_vals, signal)

    sig_line: list[float | None] = [None] * len(macd_line)
    j = 0
    for i, v in enumerate(macd_line):
        if v is not None:
            sig_line[i] = sig_raw[j]
            j += 1

    hist: list[float | None] = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, sig_line)
    ]

    return macd_line, sig_line, hist


def _bollinger(
    closes: list[float], period: int = 20, std_mult: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    upper: list[float | None] = [None] * len(closes)
    middle: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = variance ** 0.5
        middle[i] = sma
        upper[i] = sma + std_mult * std
        lower[i] = sma - std_mult * std
    return upper, middle, lower


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/chart/ohlcv")
async def get_chart_ohlcv(
    symbol: str = Query("BTCUSDT", description="Binance FAPI symbol"),
    interval: str = Query("1h", description="Kline interval: 1m,5m,15m,1h,4h,1d,1w"),
    limit: int = Query(500, ge=10, le=1500),
):
    """
    OHLCV bars with pre-computed RSI, MACD, Bollinger Bands, EMA-20, EMA-50.
    """
    valid_intervals = {
        "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
        "12h", "1d", "3d", "1w", "1M",
    }
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Valid: {sorted(valid_intervals)}")

    try:
        bars = await fetch_klines(symbol.upper(), interval, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Binance error: {exc}")

    closes = [b["c"] for b in bars]
    rsi = _wilder_rsi(closes, 14)
    macd_line, sig_line, hist = _macd(closes)
    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    enriched = [
        {
            **bar,
            "rsi": rsi[i],
            "macd": macd_line[i],
            "macd_signal": sig_line[i],
            "macd_hist": hist[i],
            "bb_upper": bb_upper[i],
            "bb_mid": bb_mid[i],
            "bb_lower": bb_lower[i],
            "ema20": ema20[i],
            "ema50": ema50[i],
        }
        for i, bar in enumerate(bars)
    ]

    return {"symbol": symbol.upper(), "interval": interval, "bars": enriched}


@router.get("/chart/orderbook")
async def get_orderbook(
    symbol: str = Query("BTCUSDT"),
    depth: int = Query(20, ge=5, le=100),
):
    """Order book snapshot with bids and asks."""
    try:
        book = await fetch_orderbook(symbol.upper(), depth)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Binance error: {exc}")

    # Compute mid price and spread stats
    if book["bids"] and book["asks"]:
        best_bid = book["bids"][0][0]
        best_ask = book["asks"][0][0]
        mid = (best_bid + best_ask) / 2.0
        spread_bp = (best_ask - best_bid) / mid * 10_000
    else:
        mid = None
        spread_bp = None

    return {
        **book,
        "mid_price": mid,
        "spread_bp": spread_bp,
    }
