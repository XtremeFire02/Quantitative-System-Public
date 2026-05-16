"""
Virtual Exchange — paper trading engine for live simulation.

Accepts signals from strategies, simulates order execution at the
current bar's close price, tracks open positions, and marks to market
on every bar. No real orders are sent to any exchange.

Thread-safety: single asyncio event loop — no locking needed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import numpy as np
import pandas as pd

from strategies.base import Bar, Signal
from framework.costs import CostModel, TAKER


@dataclass
class Position:
    strategy_id:  str
    direction:    int         # +1 long, -1 short
    entry_price:  float
    entry_time:   object      # pd.Timestamp
    hold_bars:    int
    bars_held:    int   = 0
    size_usd:     float = 1000.0   # notional
    pnl_log:      float = 0.0      # running mark-to-market log return
    closed:       bool  = False
    exit_price:   float = 0.0
    exit_time:    object = None
    net_log_ret:  float = 0.0


@dataclass
class Fill:
    strategy_id:  str
    direction:    int
    entry_price:  float
    exit_price:   float
    entry_time:   object
    exit_time:    object
    gross_pct:    float    # gross % return
    net_pct:      float    # net % return (after costs)
    hold_bars:    int
    cost_bps:     float


class VirtualExchange:
    """
    Paper trading virtual exchange.

    Usage (from simulator):
        vex = VirtualExchange(initial_capital=10_000)
        vex.on_bar(bar)   # updates positions, marks to market
        vex.execute(signal, bar)   # opens new position
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        cost_model:      CostModel = TAKER,
        position_size_pct: float = 0.10,   # 10% of capital per trade
    ):
        self.initial_capital   = initial_capital
        self.capital           = initial_capital
        self.cost_model        = cost_model
        self.position_size_pct = position_size_pct

        self._positions:  List[Position] = []
        self._fills:      List[Fill]     = []
        self._equity_log: List[dict]     = []
        self._bar_count   = 0

    # ── called on every bar ────────────────────────────────────────────────────
    def on_bar(self, bar: Bar) -> None:
        """Update all open positions and record equity."""
        closed_this_bar = []
        for pos in self._positions:
            pos.pnl_log  = pos.direction * np.log(bar.close / pos.entry_price)
            pos.bars_held += 1
            if pos.bars_held >= pos.hold_bars:
                self._close_position(pos, bar)
                closed_this_bar.append(pos)

        for pos in closed_this_bar:
            self._positions.remove(pos)

        # record equity snapshot
        open_mtm = sum(
            pos.size_usd * (np.exp(pos.pnl_log) - 1)
            for pos in self._positions
        )
        realised_pnl = sum(
            f.net_pct / 100 * (self.initial_capital * self.position_size_pct)
            for f in self._fills
        )
        equity = self.initial_capital + realised_pnl + open_mtm
        self._equity_log.append({
            "time":   bar.timestamp,
            "price":  bar.close,
            "equity": equity,
            "n_open": len(self._positions),
        })
        self._bar_count += 1

    def _close_position(self, pos: Position, bar: Bar) -> None:
        gross_log = pos.direction * np.log(bar.close / pos.entry_price)
        net_log   = gross_log - self.cost_model.round_trip_cost()
        gross_pct = (np.exp(gross_log) - 1) * 100
        net_pct   = (np.exp(net_log)   - 1) * 100

        pos.exit_price  = bar.close
        pos.exit_time   = bar.timestamp
        pos.net_log_ret = net_log
        pos.closed      = True

        self._fills.append(Fill(
            strategy_id  = pos.strategy_id,
            direction    = pos.direction,
            entry_price  = pos.entry_price,
            exit_price   = bar.close,
            entry_time   = pos.entry_time,
            exit_time    = bar.timestamp,
            gross_pct    = gross_pct,
            net_pct      = net_pct,
            hold_bars    = pos.hold_bars,
            cost_bps     = self.cost_model.round_trip_cost() * 1e4,
        ))

    # ── signal execution ──────────────────────────────────────────────────────
    def execute(self, signal: Signal, bar: Bar) -> Optional[Position]:
        """Open a new position for the given signal, if not already full."""
        open_strats = {p.strategy_id for p in self._positions}
        if signal.strategy_id in open_strats:
            return None   # already in a position for this strategy

        size_usd = self.capital * self.position_size_pct * signal.confidence
        pos = Position(
            strategy_id = signal.strategy_id,
            direction   = signal.direction,
            entry_price = bar.close,
            entry_time  = bar.timestamp,
            hold_bars   = signal.hold_bars,
            size_usd    = size_usd,
        )
        self._positions.append(pos)
        return pos

    # ── status reporting ──────────────────────────────────────────────────────
    def status(self) -> str:
        fills = self._fills
        n     = len(fills)
        if n == 0:
            return (f"[{self._bar_count:>6} bars]  "
                    f"Capital: ${self.initial_capital:,.2f}  "
                    f"No trades yet  "
                    f"Open: {len(self._positions)}")
        net_pnl  = sum(f.net_pct for f in fills)
        win_rate = sum(1 for f in fills if f.net_pct > 0) / n
        cur_eq   = self._equity_log[-1]["equity"] if self._equity_log else self.initial_capital
        return (
            f"[{self._bar_count:>6} bars]  "
            f"Equity: ${cur_eq:>10,.2f}  "
            f"Trades: {n:>4}  "
            f"Win: {win_rate*100:.0f}%  "
            f"Sum net PnL: {net_pnl:+.2f}%  "
            f"Open: {len(self._positions)}"
        )

    def equity_df(self) -> pd.DataFrame:
        return pd.DataFrame(self._equity_log).set_index("time") \
            if self._equity_log else pd.DataFrame()

    def fills_df(self) -> pd.DataFrame:
        return pd.DataFrame([vars(f) for f in self._fills]) \
            if self._fills else pd.DataFrame()
