"""
Core data structures shared by all strategies and the backtest/live engines.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union
import numpy as np

try:
    from pandas import Timestamp as _PdTimestamp
    _BarTimestamp = Union[_PdTimestamp, int]
except ImportError:
    _BarTimestamp = int  # type: ignore[assignment]


@dataclass
class Bar:
    """One closed 1-minute OHLCV bar with order-flow fields."""
    timestamp:              _BarTimestamp   # pd.Timestamp (backtest/live replay) or int ms (WebSocket)
    open:                   float
    high:                   float
    low:                    float
    close:                  float
    volume:                 float    # base asset (BTC)
    taker_buy_volume:       float    # taker-initiated buy volume (base)
    trade_count:            int
    quote_volume:           float = 0.0
    taker_buy_quote_volume: float = 0.0

    @property
    def taker_sell_volume(self) -> float:
        return self.volume - self.taker_buy_volume

    @property
    def ofi_centered(self) -> float:
        if self.volume == 0:
            return 0.0
        return self.taker_buy_volume / self.volume - 0.5


@dataclass
class Signal:
    direction:     int     # +1 long, -1 short
    confidence:    float   # 0-1, used for position sizing
    hold_bars:     int     # planned hold period in bars
    strategy_id:   str     = ""
    feature_values: dict   = field(default_factory=dict)


class Strategy:
    """Base class. Subclasses override on_bar."""

    strategy_id: str = "base"
    warmup_bars: int = 300   # bars needed before first signal

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        raise NotImplementedError

    def reset(self) -> None:
        """Called when replaying data from scratch."""
        pass
