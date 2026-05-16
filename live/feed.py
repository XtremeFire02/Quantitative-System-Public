"""
Async real-time data feed for Binance USDT-M perpetual futures.

Two modes
---------
warm_up()       - fetch last N closed 1m bars via CCXT REST (blocking async)
stream_bars()   - yield closed 1m bars via Binance WebSocket (async generator)

The Binance futures kline WebSocket sends a message every time a 1m bar
updates. The field k.x == True signals the bar is *closed* — we emit it only
then, so downstream code always sees complete bars.

Extended fields included (not in standard ccxt ohlcv):
  V  = taker buy base asset volume
  Q  = taker buy quote asset volume
  n  = trade count
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import AsyncGenerator, List

import ccxt.async_support as ccxt
import websockets
import pandas as pd

from strategies.base import Bar

log = logging.getLogger(__name__)

SYMBOL_CCXT = "BTC/USDT:USDT"      # CCXT perpetual notation
SYMBOL_WS   = "btcusdt"            # Binance WebSocket symbol
WS_URL      = f"wss://fstream.binance.com/ws/{SYMBOL_WS}@kline_1m"
RECONNECT_DELAY = 5                 # seconds between reconnection attempts


def _row_to_bar(row) -> Bar:
    """Convert a CCXT ohlcv row (list) to a Bar.
    CCXT returns: [ts_ms, open, high, low, close, volume]
    Extra fields from Binance fetch_ohlcv are not guaranteed.
    """
    return Bar(
        timestamp        = pd.Timestamp(row[0], unit="ms", tz="UTC"),
        open             = float(row[1]),
        high             = float(row[2]),
        low              = float(row[3]),
        close            = float(row[4]),
        volume           = float(row[5]),
        taker_buy_volume = float(row[5]) * 0.5,   # placeholder; corrected below
        trade_count      = 0,
    )


LOCAL_DATA = "data/processed/ofi.parquet"


async def warm_up(n_bars: int = 400, use_local: bool = False) -> List[Bar]:
    """
    Fetch the last `n_bars` closed 1m bars.

    use_local=True  : read from the saved historical parquet (no network).
    use_local=False : fetch live from Binance REST API.
    """
    if use_local:
        return _warm_up_local(n_bars)
    return await _warm_up_live(n_bars)


def _warm_up_local(n_bars: int) -> List[Bar]:
    """Load the most recent n_bars from the local historical dataset."""
    from pathlib import Path
    path = Path(LOCAL_DATA)
    if not path.exists():
        raise FileNotFoundError(f"Local data not found: {path}")
    df = pd.read_parquet(path)
    df = df.tail(n_bars)
    bars = []
    for ts, row in df.iterrows():
        bars.append(Bar(
            timestamp              = ts,
            open                   = float(row["open"]),
            high                   = float(row["high"]),
            low                    = float(row["low"]),
            close                  = float(row["close"]),
            volume                 = float(row["volume"]),
            quote_volume           = float(row.get("quote_volume", 0)),
            taker_buy_volume       = float(row.get("taker_buy_base_volume", 0)),
            taker_buy_quote_volume = float(row.get("taker_buy_quote_volume", 0)),
            trade_count            = int(row.get("trade_count", 0)),
        ))
    log.info("Warmed up from local data: %d bars (last: %s)",
             len(bars), bars[-1].timestamp if bars else "n/a")
    return bars


async def _warm_up_live(n_bars: int) -> List[Bar]:
    """Fetch the last n_bars from Binance FAPI REST."""
    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        resp = await exchange.fapiPublicGetKlines({
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": n_bars,
        })
        bars = []
        for k in resp:
            bars.append(Bar(
                timestamp            = pd.Timestamp(int(k[0]), unit="ms", tz="UTC"),
                open                 = float(k[1]),
                high                 = float(k[2]),
                low                  = float(k[3]),
                close                = float(k[4]),
                volume               = float(k[5]),
                quote_volume         = float(k[7]),
                taker_buy_volume     = float(k[9]),
                taker_buy_quote_volume = float(k[10]),
                trade_count          = int(k[8]),
            ))
        log.info("Warmed up with %d bars (last: %s)", len(bars),
                 bars[-1].timestamp if bars else "n/a")
        return bars
    finally:
        await exchange.close()


async def stream_bars() -> AsyncGenerator[Bar, None]:
    """
    Async generator that yields closed 1m bars from Binance WebSocket.
    Reconnects automatically on disconnection.
    """
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20,
                                          ping_timeout=10) as ws:
                log.info("WebSocket connected: %s", WS_URL)
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    k   = msg.get("k", {})
                    if not k.get("x", False):
                        continue   # bar not yet closed

                    bar = Bar(
                        timestamp              = pd.Timestamp(int(k["t"]),
                                                              unit="ms", tz="UTC"),
                        open                   = float(k["o"]),
                        high                   = float(k["h"]),
                        low                    = float(k["l"]),
                        close                  = float(k["c"]),
                        volume                 = float(k["v"]),
                        quote_volume           = float(k["q"]),
                        taker_buy_volume       = float(k["V"]),
                        taker_buy_quote_volume = float(k["Q"]),
                        trade_count            = int(k["n"]),
                    )
                    yield bar

        except (websockets.ConnectionClosed,
                websockets.InvalidHandshake,
                OSError) as exc:
            log.warning("WebSocket error: %s — reconnecting in %ds",
                        exc, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)
        except asyncio.CancelledError:
            log.info("stream_bars cancelled")
            return
