"""
Signal C: CVD Divergence Strategy
==================================
cvd_divergence = (net_buy_volume_60m / total_volume_60m) - log_price_return_60m

Thesis: when cumulative buying pressure over the past hour fails to produce
price gains (positive divergence), sellers are absorbing the flow and price
will fall. The reverse for negative divergence.

Signal: percentile rank of cvd_divergence within a rolling 300-bar window.
  - pct_rank > entry_pct  → SHORT  (high positive divergence = bearish)
  - pct_rank < 1-entry_pct → LONG  (high negative divergence = bullish)
Hold for hold_bars minutes, then exit.
"""
from __future__ import annotations
from collections import deque
from typing import Optional
import bisect
import numpy as np

from strategies.base import Bar, Signal, Strategy


class CVDDivergenceStrategy(Strategy):

    strategy_id = "CVD"
    warmup_bars = 360      # 60 (window) + 300 (percentile history)

    def __init__(
        self,
        cvd_window:  int   = 60,     # bars for CVD accumulation
        hist_window: int   = 300,    # bars for percentile estimation
        entry_pct:   float = 0.80,   # 80th percentile threshold to enter
        hold_bars:   int   = 60,     # hold for 60 minutes
    ):
        self.cvd_window  = cvd_window
        self.hist_window = hist_window
        self.entry_pct   = entry_pct
        self.hold_bars   = hold_bars
        self.reset()

    def reset(self) -> None:
        # Scalar deques — much faster than deque-of-Bar + array creation
        self._buy_buf    = deque(maxlen=self.cvd_window + 1)
        self._sell_buf   = deque(maxlen=self.cvd_window + 1)
        self._vol_buf    = deque(maxlen=self.cvd_window + 1)
        self._close_buf  = deque(maxlen=self.cvd_window + 1)
        self._hist       = deque(maxlen=self.hist_window)
        self._hist_sorted: list = []   # sorted mirror for O(log n) rank
        # Running sums for O(1) window computation
        self._buy_sum   = 0.0
        self._sell_sum  = 0.0
        self._vol_sum   = 0.0

    def _compute_divergence(self) -> Optional[float]:
        n = len(self._buy_buf)
        if n < self.cvd_window + 1:
            return None
        if self._vol_sum == 0:
            return None
        cvd_norm  = (self._buy_sum - self._sell_sum) / self._vol_sum
        c0        = self._close_buf[0]
        c1        = self._close_buf[-1]
        if c0 <= 0:
            return None
        return cvd_norm - np.log(c1 / c0)

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        tbv  = bar.taker_buy_volume
        tsv  = bar.taker_sell_volume
        vol  = bar.volume

        # Update running sums before appending (maxlen handles eviction)
        if len(self._buy_buf) == self._buy_buf.maxlen:
            # oldest value about to be evicted — subtract it first
            self._buy_sum  -= self._buy_buf[0]
            self._sell_sum -= self._sell_buf[0]
            self._vol_sum  -= self._vol_buf[0]

        self._buy_buf.append(tbv)
        self._sell_buf.append(tsv)
        self._vol_buf.append(vol)
        self._close_buf.append(bar.close)
        self._buy_sum  += tbv
        self._sell_sum += tsv
        self._vol_sum  += vol

        div = self._compute_divergence()
        if div is None:
            return None

        # Evict oldest from sorted mirror before appending to deque
        if len(self._hist) == self._hist.maxlen:
            old = self._hist[0]
            del self._hist_sorted[bisect.bisect_left(self._hist_sorted, old)]
        self._hist.append(div)
        bisect.insort(self._hist_sorted, div)

        n = len(self._hist_sorted)
        if n < 60:
            return None

        # O(log n) percentile rank via binary search
        pct_rank = bisect.bisect_left(self._hist_sorted, div) / n

        fv = {"cvd_div": div, "pct_rank": pct_rank}

        if pct_rank >= self.entry_pct:
            return Signal(direction=-1, confidence=pct_rank,
                          hold_bars=self.hold_bars, strategy_id=self.strategy_id,
                          feature_values=fv)
        if pct_rank <= (1.0 - self.entry_pct):
            return Signal(direction=+1, confidence=1.0 - pct_rank,
                          hold_bars=self.hold_bars, strategy_id=self.strategy_id,
                          feature_values=fv)
        return None
