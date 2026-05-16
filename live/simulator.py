"""
Virtual Trading Simulator
=========================
Connects both strategies to a live Binance data feed and runs them
in a shared VirtualExchange (paper trading).

Modes
-----
  live  : Real-time WebSocket stream from Binance (runs indefinitely).
  replay: Replay the last N bars of historical data at full speed,
          then optionally continue live. Good for testing.

Usage
-----
  python live/simulator.py              # replay last 800 bars then go live
  python live/simulator.py --live-only  # skip replay, go straight to live feed
  python live/simulator.py --replay-only --bars 1000  # replay only

The simulator prints a status line after every closed bar and a detailed
P&L report every 60 bars (1 hour).
"""
from __future__ import annotations
import asyncio
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

from archive.strategies.cvd_strategy import CVDDivergenceStrategy
from archive.strategies.vpin_strategy import VPINRegimeStrategy
from strategies.base import Bar, Signal
from live.feed import warm_up, stream_bars
from live.exchange import VirtualExchange
from framework.costs import TAKER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _make_strategies():
    return [
        CVDDivergenceStrategy(entry_pct=0.80, hold_bars=60),
        VPINRegimeStrategy(vpin_regime_pct=0.40, cvd_entry_pct=0.80, hold_bars=60),
    ]


async def process_bar(bar: Bar,
                      strategies,
                      exchange: VirtualExchange,
                      bar_counter: list) -> None:
    """Core per-bar logic: update exchange, run strategies, execute signals."""
    exchange.on_bar(bar)

    for strat in strategies:
        sig: Signal = strat.on_bar(bar)
        if sig is not None:
            pos = exchange.execute(sig, bar)
            if pos:
                log.info(
                    "  SIGNAL  %-10s  %s  dir=%+d  price=%.2f  "
                    "hold=%dm  conf=%.2f",
                    sig.strategy_id,
                    bar.timestamp.strftime("%Y-%m-%d %H:%M"),
                    sig.direction, bar.close,
                    sig.hold_bars, sig.confidence,
                )

    bar_counter[0] += 1
    if bar_counter[0] % 60 == 0:
        print(exchange.status())


async def replay_mode(bars: List[Bar],
                      strategies,
                      exchange: VirtualExchange) -> None:
    """Feed historical bars as fast as possible."""
    bar_counter = [0]
    log.info("Replaying %d historical bars...", len(bars))
    for bar in bars:
        await process_bar(bar, strategies, exchange, bar_counter)
    log.info("Replay complete.  %s", exchange.status())


async def live_mode(strategies,
                    exchange: VirtualExchange) -> None:
    """Stream live 1m bars from Binance WebSocket indefinitely."""
    bar_counter = [0]
    log.info("Starting live stream from Binance USDT-M futures...")
    async for bar in stream_bars():
        await process_bar(bar, strategies, exchange, bar_counter)


async def run(replay_bars: int = 800,
              live_only: bool = False,
              replay_only: bool = False,
              use_local: bool = False) -> None:

    strategies = _make_strategies()
    exchange   = VirtualExchange(
        initial_capital    = 10_000.0,
        cost_model         = TAKER,
        position_size_pct  = 0.10,
    )

    print("=" * 72)
    print("VIRTUAL TRADING SIMULATOR")
    print("Strategies: CVDDivergenceStrategy | VPINRegimeStrategy")
    print(f"Capital: $10,000   Cost: {TAKER}")
    print("=" * 72)

    if not live_only:
        log.info("Fetching last %d bars for warm-up / replay...", replay_bars)
        hist_bars = await warm_up(n_bars=replay_bars, use_local=use_local)
        await replay_mode(hist_bars, strategies, exchange)

    if not replay_only:
        await live_mode(strategies, exchange)

    # ── Final report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("SESSION SUMMARY")
    print("=" * 72)
    print(exchange.status())

    fills = exchange.fills_df()
    if not fills.empty:
        print(f"\nAll fills ({len(fills)} trades):")
        print(fills[["strategy_id", "direction", "entry_price", "exit_price",
                      "gross_pct", "net_pct", "hold_bars"]].to_string(index=False))
        print(f"\nBy strategy:")
        print(fills.groupby("strategy_id")["net_pct"].agg(
            ["count", "mean", "sum",
             lambda x: (x > 0).mean()]).rename(
            columns={"count": "n", "mean": "avg_net%",
                     "sum": "total_net%", "<lambda_0>": "hit_rate"}))

        # save results
        fills.to_csv("results/simulation/simulation_fills.csv", index=False)
        exchange.equity_df().to_csv("results/simulation/simulation_equity.csv")
        print("\nSaved: results/simulation/simulation_fills.csv  results/simulation/simulation_equity.csv")


def main():
    parser = argparse.ArgumentParser(description="Virtual Trading Simulator")
    parser.add_argument("--live-only",    action="store_true")
    parser.add_argument("--replay-only",  action="store_true")
    parser.add_argument("--bars",   type=int, default=800,
                        help="Number of historical bars to replay (default: 800)")
    parser.add_argument("--use-local", action="store_true",
                        help="Read historical bars from local parquet (no internet)")
    args = parser.parse_args()

    # Windows asyncio fix
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run(
        replay_bars  = args.bars,
        live_only    = args.live_only,
        replay_only  = args.replay_only,
        use_local    = args.use_local,
    ))


if __name__ == "__main__":
    main()
