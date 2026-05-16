"""
Signal E: VPIN Regime-Filtered CVD Strategy
=============================================
VPIN (approximated) = 50-bar rolling mean of |taker_buy - taker_sell| / volume.
High VPIN  → calm, trending market → low expected volatility → skip trades.
Low  VPIN  → chaotic, two-sided market → high vol → CVD signal is stronger.

Strategy:
  1. Compute VPIN from rolling 50 bars.
  2. Compute CVD divergence (same as CVDDivergenceStrategy).
  3. Only enter a trade when VPIN is in the bottom `vpin_regime_pct` of recent
     VPIN values (chaotic regime).
  4. Position size scales with (1 - vpin_pct_rank): bigger size in more
     chaotic markets where the CVD signal is historically stronger.

This directly exploits both findings:
  - CVD divergence predicts returns (Signal C)
  - Low VPIN marks the regime where this prediction is strongest (Signal E)
"""
from __future__ import annotations
from collections import deque
from typing import Optional
import bisect
import numpy as np

from strategies.base import Bar, Signal, Strategy


class VPINRegimeStrategy(Strategy):

    strategy_id = "VPIN_CVD"
    warmup_bars = 410

    def __init__(
        self,
        vpin_window:      int   = 50,    # VPIN rolling window
        vpin_hist_window: int   = 300,   # VPIN percentile history
        vpin_regime_pct:  float = 0.40,  # only trade in bottom 40% VPIN
        cvd_window:       int   = 60,
        cvd_hist_window:  int   = 300,
        cvd_entry_pct:    float = 0.80,
        hold_bars:        int   = 60,
    ):
        self.vpin_window      = vpin_window
        self.vpin_hist_window = vpin_hist_window
        self.vpin_regime_pct  = vpin_regime_pct
        self.cvd_window       = cvd_window
        self.cvd_hist_window  = cvd_hist_window
        self.cvd_entry_pct    = cvd_entry_pct
        self.hold_bars        = hold_bars
        self.reset()

    def reset(self) -> None:
        w = max(self.vpin_window, self.cvd_window) + 1
        # Scalar deques for speed
        self._buy_buf    = deque(maxlen=w)
        self._sell_buf   = deque(maxlen=w)
        self._vol_buf    = deque(maxlen=w)
        self._close_buf  = deque(maxlen=w)
        self._imb_buf    = deque(maxlen=self.vpin_window)  # |buy-sell|/vol per bar
        self._vpin_hist        = deque(maxlen=self.vpin_hist_window)
        self._vpin_hist_sorted: list = []
        self._cvd_hist         = deque(maxlen=self.cvd_hist_window)
        self._cvd_hist_sorted:  list = []
        # Running sums for CVD window
        self._buy_sum    = 0.0
        self._sell_sum   = 0.0
        self._vol_sum    = 0.0
        # Running sum for VPIN window
        self._imb_sum    = 0.0

    def _compute_vpin(self) -> Optional[float]:
        if len(self._imb_buf) < self.vpin_window:
            return None
        return self._imb_sum / self.vpin_window

    def _compute_divergence(self) -> Optional[float]:
        if len(self._buy_buf) < self.cvd_window + 1:
            return None
        if self._vol_sum == 0:
            return None
        cvd_norm = (self._buy_sum - self._sell_sum) / self._vol_sum
        c0 = self._close_buf[-(self.cvd_window + 1)]
        c1 = self._close_buf[-1]
        if c0 <= 0:
            return None
        return cvd_norm - np.log(c1 / c0)

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        tbv = bar.taker_buy_volume
        tsv = bar.taker_sell_volume
        vol = bar.volume

        # CVD running sums — maintain for the cvd_window+1 oldest bar
        if len(self._buy_buf) == self._buy_buf.maxlen:
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

        # VPIN running sum
        imb = abs(tbv - tsv) / vol if vol > 0 else 0.0
        if len(self._imb_buf) == self._imb_buf.maxlen:
            self._imb_sum -= self._imb_buf[0]
        self._imb_buf.append(imb)
        self._imb_sum += imb

        vpin = self._compute_vpin()
        div  = self._compute_divergence()
        if vpin is None or div is None:
            return None

        # VPIN history with sorted mirror for O(log n) rank
        if len(self._vpin_hist) == self._vpin_hist.maxlen:
            old_v = self._vpin_hist[0]
            del self._vpin_hist_sorted[bisect.bisect_left(self._vpin_hist_sorted, old_v)]
        self._vpin_hist.append(vpin)
        bisect.insort(self._vpin_hist_sorted, vpin)

        # CVD history with sorted mirror
        if len(self._cvd_hist) == self._cvd_hist.maxlen:
            old_c = self._cvd_hist[0]
            del self._cvd_hist_sorted[bisect.bisect_left(self._cvd_hist_sorted, old_c)]
        self._cvd_hist.append(div)
        bisect.insort(self._cvd_hist_sorted, div)

        nv = len(self._vpin_hist_sorted)
        nc = len(self._cvd_hist_sorted)
        if nv < 60 or nc < 60:
            return None

        vpin_pct = bisect.bisect_left(self._vpin_hist_sorted, vpin) / nv
        cvd_pct  = bisect.bisect_left(self._cvd_hist_sorted,  div)  / nc

        # Gate: only trade in low-VPIN (chaotic) regime
        if vpin_pct >= self.vpin_regime_pct:
            return None

        fv = {"vpin": vpin, "vpin_pct": vpin_pct,
              "cvd_div": div, "cvd_pct": cvd_pct}

        regime_boost = 1.0 - vpin_pct

        if cvd_pct >= self.cvd_entry_pct:
            return Signal(direction=-1,
                          confidence=cvd_pct * regime_boost,
                          hold_bars=self.hold_bars,
                          strategy_id=self.strategy_id,
                          feature_values=fv)
        if cvd_pct <= (1.0 - self.cvd_entry_pct):
            return Signal(direction=+1,
                          confidence=(1.0 - cvd_pct) * regime_boost,
                          hold_bars=self.hold_bars,
                          strategy_id=self.strategy_id,
                          feature_values=fv)
        return None
