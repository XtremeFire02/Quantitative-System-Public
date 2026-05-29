"""N3 DVOL signal evaluator — frozen rule, do not modify thresholds."""
import os

from app.data.deribit_client import get_dvol_snapshot
from app.signals.base import SignalResult

HOLD_HOURS = 24

# Entry thresholds are loaded from environment variables and are not published
# in this repository. See paper_trading/.env.example for variable names.
_N3Z_THRESHOLD  = float(os.getenv("N3Z_THRESHOLD",  "0"))
_DVOL_THRESHOLD = float(os.getenv("DVOL_THRESHOLD", "0"))


def evaluate_signal(
    dvol: float,
    dvol_mean_30d: float,
    dvol_std_30d: float,
    long_only: bool = True,
    n3z_threshold: float | None = None,
    dvol_threshold: float | None = None,
) -> SignalResult:
    """Pure synchronous computation — used by tests and the async evaluator.

    n3z_threshold / dvol_threshold override the frozen defaults only for
    shadow research variants. The official N3 strategies use the environment
    variable values loaded at startup.
    """
    n3z_th  = n3z_threshold  if n3z_threshold  is not None else _N3Z_THRESHOLD
    dvol_th = dvol_threshold if dvol_threshold is not None else _DVOL_THRESHOLD

    n3_z = (dvol - dvol_mean_30d) / dvol_std_30d if dvol_std_30d > 0 else 0.0
    dvol_filter_pass = dvol >= dvol_th
    long_signal  = dvol_filter_pass and n3_z > n3z_th
    short_signal = (not long_only) and dvol_filter_pass and n3_z < -n3z_th
    entry_signal = long_signal or short_signal
    side = "long" if long_signal else "short"

    if long_signal:
        reason = (
            f"LONG: N3z = {n3_z:.3f} > threshold "
            f"and DVOL = {dvol:.1f} >= regime filter"
        )
    elif short_signal:
        reason = (
            f"SHORT: N3z = {n3_z:.3f} < -threshold "
            f"and DVOL = {dvol:.1f} >= regime filter"
        )
    elif not dvol_filter_pass:
        reason = f"No trade: DVOL = {dvol:.1f} below regime filter"
    else:
        reason = f"No trade: N3z = {n3_z:.3f} within neutral band"

    return SignalResult(
        strategy_name="N3_DVOL_LONG" if long_only else "N3_DVOL_LONGSHORT",
        market="BTCUSDT",
        entry_signal=entry_signal,
        side=side,
        reason=reason,
        hold_hours=HOLD_HOURS,
        metadata={"n3_z": round(n3_z, 4), "dvol": round(dvol, 2)},
        dvol=dvol,
        dvol_mean_30d=dvol_mean_30d,
        dvol_std_30d=dvol_std_30d,
        n3_z=n3_z,
        dvol_filter_pass=dvol_filter_pass,
    )


class N3DvolEvaluator:
    """
    Evaluates the N3 DVOL z-score signal for BTCUSDT.

    The signal computes the 30-day rolling z-score of the Deribit BTCVOL
    (DVOL) index and fires a directional entry when the z-score exceeds a
    threshold and DVOL satisfies a volatility-regime filter.

    long_only=True  → long-only strategy (no short leg)
    long_only=False → both legs (z > threshold → long, z < -threshold → short)

    n3z_threshold / dvol_threshold: override for shadow research variants.
    Official strategies leave these as None to use env-var values.
    """

    def __init__(
        self,
        strategy_name: str,
        long_only: bool = True,
        n3z_threshold: float | None = None,
        dvol_threshold: float | None = None,
    ):
        self.strategy_name  = strategy_name
        self.long_only      = long_only
        self.n3z_threshold  = n3z_threshold
        self.dvol_threshold = dvol_threshold

    async def evaluate(self, market: str) -> SignalResult:
        dvol_data = await get_dvol_snapshot()
        sig = evaluate_signal(
            dvol=dvol_data["dvol"],
            dvol_mean_30d=dvol_data["dvol_mean_30d"],
            dvol_std_30d=dvol_data["dvol_std_30d"],
            long_only=self.long_only,
            n3z_threshold=self.n3z_threshold,
            dvol_threshold=self.dvol_threshold,
        )
        sig.strategy_name = self.strategy_name
        sig.market = market
        sig.metadata.update({
            "dvol_mean_30d":   round(dvol_data["dvol_mean_30d"], 2),
            "dvol_std_30d":    round(dvol_data["dvol_std_30d"],  4),
            "n_dvol_bars":     dvol_data["n_bars_used"],
            "dvol_timestamp":  dvol_data["timestamp"].isoformat(),
        })
        return sig
