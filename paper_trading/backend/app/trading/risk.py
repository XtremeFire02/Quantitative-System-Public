"""Pre-trade risk checks for paper trading."""
from datetime import datetime, timezone, timedelta
from app.config import DATA_STALE_MINUTES, DVOL_LOOKBACK_DAYS


class RiskCheckFailed(Exception):
    pass


def check_can_trade(
    price: float | None,
    open_trade_count: int,
    dvol: float | None = None,
    n_dvol_bars: int | None = None,
    dvol_timestamp: datetime | None = None,
) -> None:
    """Raise RiskCheckFailed if any check fails. DVOL checks only run when dvol is provided."""
    if price is None or price <= 0:
        raise RiskCheckFailed("Price missing or invalid")

    if open_trade_count >= 1:
        raise RiskCheckFailed(
            f"Position limit: {open_trade_count} open trade(s) already exist for this market/strategy"
        )

    if dvol is not None:
        if dvol <= 0:
            raise RiskCheckFailed("DVOL missing or invalid")

        if n_dvol_bars is not None:
            min_bars = DVOL_LOOKBACK_DAYS * 24
            if n_dvol_bars < min_bars:
                raise RiskCheckFailed(
                    f"Insufficient DVOL history: {n_dvol_bars} bars, need {min_bars}"
                )

        if dvol_timestamp is not None:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=DATA_STALE_MINUTES)
            if dvol_timestamp < stale_cutoff:
                raise RiskCheckFailed(
                    f"DVOL data stale: last update {dvol_timestamp.isoformat()}"
                )
