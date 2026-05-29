"""P3 OI-Price Divergence signal — DD-regime long (shadow research variant).

Rule: LONG when the prior completed 24h bar saw simultaneous price decline
and OI contraction (DD regime), filtered by a DVOL volatility-regime gate.

The DD regime (price down, OI down) identifies long-liquidation exhaustion:
forced sellers are bounded, so once the over-levered longs are cleared the
market recoils. The DVOL filter restricts entries to elevated-fear environments
where the mechanism is empirically strongest.

Statistical validation details are in the research report (A2). Entry thresholds
are not published in this repository.
"""
import os

from app.data.binance_client import fetch_klines_close, fetch_oi_history
from app.data.deribit_client import get_dvol_snapshot
from app.signals.base import SignalResult

HOLD_HOURS = 24

# DVOL entry threshold — loaded from env; not published in this repository.
_DVOL_THRESHOLD = float(os.getenv("DVOL_THRESHOLD", "0"))


def _classify(dp: float, doi: float) -> str:
    if dp >= 0 and doi >= 0:
        return "UU"
    if dp >= 0 and doi < 0:
        return "UD"
    if dp < 0 and doi >= 0:
        return "DU"
    return "DD"


class P3OIPDEvaluator:
    """
    Evaluates the P3 OI-Price Divergence signal for BTCUSDT.

    Uses the last two *completed* daily bars:
      dp  = (price_yesterday - price_day_before) / price_day_before
      doi = (oi_yesterday   - oi_day_before)    / oi_day_before

    Regime DD (dp < 0 AND doi < 0) → long exhaustion-bounce signal.
    Entry fires only when DVOL is above the volatility-regime threshold.

    dvol_threshold: override for sensitivity variants; defaults to env var.
    """

    def __init__(
        self,
        strategy_name: str = "P3_OIPD_DD",
        dvol_threshold: float | None = None,
    ):
        self.strategy_name  = strategy_name
        self.dvol_threshold = dvol_threshold if dvol_threshold is not None else _DVOL_THRESHOLD

    async def evaluate(self, market: str) -> SignalResult:
        dvol_data = await get_dvol_snapshot()
        dvol = dvol_data["dvol"]

        # Fetch last 3 daily klines; use rows[0] and rows[1] (both complete).
        # Row[2] is the bar that just started at 00:00 UTC — intentionally skipped.
        klines = await fetch_klines_close(symbol=market, limit=3)
        if len(klines) < 3:
            return self._error(market, dvol, f"Need 3 klines, got {len(klines)}")

        price_prev = klines[0]["close"]   # close 48h ago
        price_yest = klines[1]["close"]   # close 24h ago (yesterday)

        oi_hist = await fetch_oi_history(symbol=market, period="1d", limit=3)
        if len(oi_hist) < 3:
            return self._error(market, dvol, f"Need 3 OI bars, got {len(oi_hist)}")

        oi_prev = oi_hist[0]["open_interest"]   # OI snapshot 48h ago
        oi_yest = oi_hist[1]["open_interest"]   # OI snapshot 24h ago

        if price_prev <= 0 or oi_prev <= 0:
            return self._error(
                market, dvol,
                f"Invalid base values: price_prev={price_prev}, oi_prev={oi_prev}"
            )

        dp     = (price_yest - price_prev) / price_prev
        doi    = (oi_yest   - oi_prev)    / oi_prev
        regime = _classify(dp, doi)
        is_dd  = regime == "DD"
        dvol_ok = dvol >= self.dvol_threshold

        entry_signal = is_dd and dvol_ok

        if entry_signal:
            reason = (
                f"LONG: DD regime (dp={dp:+.2%}, doi={doi:+.2%}) "
                f"and DVOL={dvol:.1f} above regime filter "
                f"[long-exhaustion bounce signal]"
            )
        elif not is_dd:
            reason = (
                f"No trade: regime={regime} (dp={dp:+.2%}, doi={doi:+.2%}), "
                f"DVOL={dvol:.1f}"
            )
        else:
            reason = (
                f"No trade: DD regime but DVOL={dvol:.1f} below regime filter"
            )

        return SignalResult(
            strategy_name=self.strategy_name,
            market=market,
            entry_signal=entry_signal,
            side="long",
            reason=reason,
            hold_hours=HOLD_HOURS,
            metadata={
                "regime":       regime,
                "dp":           round(dp,  6),
                "doi":          round(doi, 6),
                "price_prev":   round(price_prev, 2),
                "price_yest":   round(price_yest, 2),
                "oi_prev":      round(oi_prev, 2),
                "oi_yest":      round(oi_yest, 2),
                "dvol":         round(dvol, 2),
                "dvol_mean_30d": round(dvol_data["dvol_mean_30d"], 2),
            },
            dvol=dvol,
            dvol_filter_pass=dvol_ok,
        )

    def _error(self, market: str, dvol: float, msg: str) -> SignalResult:
        return SignalResult(
            strategy_name=self.strategy_name,
            market=market,
            entry_signal=False,
            side="long",
            reason=f"No trade: {msg}",
            hold_hours=HOLD_HOURS,
            metadata={"dvol": round(dvol, 2) if dvol else None, "error": msg},
            dvol=dvol,
        )
