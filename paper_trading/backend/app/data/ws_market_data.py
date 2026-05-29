"""
Real-time Binance FAPI WebSocket client — mark price and funding rate cache.

Connects to the combined mark-price stream for the configured symbols and
keeps an in-memory snapshot per symbol. The cache is updated every second
(1s stream) with no DB writes; callers read via get_latest().

Thread-safety note: CPython dict assignment is atomic for simple key writes,
and the asyncio event loop runs the WebSocket callbacks on a single thread,
so a plain dict is sufficient here without an explicit lock.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets
import websockets.exceptions

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_STREAM_URL = (
    "wss://fstream.binance.com/stream?streams="
    "btcusdt@markPrice@1s"
    "/ethusdt@markPrice@1s"
    "/solusdt@markPrice@1s"
    "/bnbusdt@markPrice@1s"
    "/xrpusdt@markPrice@1s"
    "/avaxusdt@markPrice@1s"
)

# ── In-memory cache ───────────────────────────────────────────────────────────

# symbol (uppercase) -> latest snapshot dict
# Keys: mark_price (float), funding_rate (float), event_time_ms (int), received_at (datetime)
_CACHE: dict[str, dict] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def get_latest(symbol: str) -> dict | None:
    """Return the latest cached snapshot for *symbol* (e.g. 'BTCUSDT'), or None."""
    return _CACHE.get(symbol.upper())


# ── Internal helpers ──────────────────────────────────────────────────────────

def _process_message(msg: dict) -> None:
    """Parse a combined-stream envelope and update _CACHE."""
    data = msg.get("data")
    if not data:
        return
    symbol = data.get("s", "").upper()
    if not symbol:
        return
    _CACHE[symbol] = {
        "mark_price":    float(data["p"]),
        "funding_rate":  float(data["r"]),
        "event_time_ms": int(data["E"]),
        "received_at":   datetime.now(timezone.utc),
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_ws_feed() -> None:
    """
    Connect to the Binance mark-price combined stream and update _CACHE forever.

    Reconnects automatically after any disconnection or error (5 s back-off).
    This coroutine never exits under normal operation; cancel it to stop.
    """
    while True:
        try:
            logger.info("WebSocket: connecting to Binance mark-price stream")
            async with websockets.connect(_STREAM_URL) as ws:
                logger.info("WebSocket: connected — receiving mark-price updates")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        _process_message(msg)
                    except Exception as parse_exc:
                        logger.warning("WebSocket: failed to parse message: %s", parse_exc)
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("WebSocket: connection closed (%s) — reconnecting in 5 s", exc)
            await asyncio.sleep(5)
        except Exception as exc:
            logger.warning("WebSocket: unexpected error (%s) — reconnecting in 5 s", exc)
            await asyncio.sleep(5)
