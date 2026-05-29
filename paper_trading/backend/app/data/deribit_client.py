"""
Deribit DVOL fetcher — implied volatility index for BTC and ETH.

All public functions are decorated with async_retry (3 attempts, 0.5 s base).
Responses include event_time (exchange server timestamp derived from the data
array) and receive_time (local clock) for latency tracking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.config import DERIBIT_BASE, DVOL_LOOKBACK_DAYS
from app.data.retry import async_retry


def _utc(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@async_retry(max_attempts=3, base_delay=0.5)
async def fetch_current_dvol(currency: str = "BTC") -> dict:
    """Current Deribit DVOL index for the given currency.

    Returns: {"dvol": float, "event_time": None, "receive_time": datetime}
    (event_time is None — the get_index_price endpoint has no server timestamp.)
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{DERIBIT_BASE}/get_index_price",
            params={"index_name": f"dvol_{currency.lower()}"},
        )
        r.raise_for_status()
        receive_time = _now()
        return {
            "dvol": float(r.json()["result"]["index_price"]),
            "event_time": None,
            "receive_time": receive_time,
        }


@async_retry(max_attempts=3, base_delay=1.0)
async def fetch_dvol_history(
    days: int = DVOL_LOOKBACK_DAYS + 2,
    currency: str = "BTC",
) -> list[dict]:
    """
    Historical hourly DVOL bars for the last `days` days.

    Each bar includes:
        timestamp_ms : Exchange bar open timestamp (milliseconds)
        dvol         : Closing DVOL value for the bar
        event_time   : Exchange timestamp as UTC datetime
    """
    now_ms   = int(_now().timestamp() * 1000)
    start_ms = int((_now() - timedelta(days=days)).timestamp() * 1000)

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{DERIBIT_BASE}/get_volatility_index_data",
            params={
                "currency":        currency,
                "start_timestamp": start_ms,
                "end_timestamp":   now_ms,
                "resolution":      "3600",
            },
        )
        r.raise_for_status()
        data = r.json()["result"]["data"]
        # data: list of [timestamp_ms, open, high, low, close]
        return [
            {
                "timestamp_ms": int(row[0]),
                "dvol": float(row[4]),
                "event_time": _utc(int(row[0])),
            }
            for row in data
        ]


def _compute_zscore(
    dvol_values: list[float], lookback: int
) -> tuple[float, float, float, float]:
    """Compute (current_dvol, mean_30d, std_30d, z_score) from a history list."""
    if len(dvol_values) < lookback:
        raise RuntimeError(
            f"Insufficient DVOL history: {len(dvol_values)} bars, need {lookback}"
        )
    window   = dvol_values[-lookback:]
    mean_30d = sum(window) / len(window)
    variance = sum((x - mean_30d) ** 2 for x in window) / len(window)
    std_30d  = variance ** 0.5
    current  = dvol_values[-1]
    z_score  = (current - mean_30d) / std_30d if std_30d > 0 else 0.0
    return current, mean_30d, std_30d, z_score


async def get_dvol_snapshot(currency: str = "BTC") -> dict:
    """
    Current DVOL and 30-day rolling statistics for any Deribit-covered currency.

    Parameters
    ----------
    currency : "BTC" or "ETH"

    Returns event_time from the most recent hourly bar in the history.
    """
    history = await fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency=currency)
    if not history:
        raise RuntimeError(f"Empty {currency} DVOL history from Deribit")

    lookback = DVOL_LOOKBACK_DAYS * 24
    dvol_values = [h["dvol"] for h in history]
    current_dvol, mean_30d, std_30d, z_score = _compute_zscore(dvol_values, lookback)

    # Use the most recent bar's exchange timestamp as event_time
    last_event_time = history[-1].get("event_time")
    receive_time = _now()

    return {
        "dvol":          current_dvol,
        "dvol_mean_30d": mean_30d,
        "dvol_std_30d":  std_30d,
        "n3_z":          z_score,
        "n_bars_used":   lookback,
        "currency":      currency,
        "event_time":    last_event_time,
        "receive_time":  receive_time,
        "timestamp":     receive_time,    # legacy key
    }


async def get_cross_dvol_snapshot() -> dict:
    """
    BTC and ETH DVOL snapshots for cross-asset implied-vol signals.

    q5c = btc_z - eth_z  (BTC-excess implied vol relative to ETH).
    Both z-scores use the same 30-day rolling window (720 hourly bars).
    """
    import asyncio
    lookback = DVOL_LOOKBACK_DAYS * 24

    btc_hist, eth_hist = await asyncio.gather(
        fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency="BTC"),
        fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency="ETH"),
    )

    if not btc_hist:
        raise RuntimeError("Empty BTC DVOL history from Deribit")
    if not eth_hist:
        raise RuntimeError("Empty ETH DVOL history from Deribit")

    btc_dvol, btc_mean, btc_std, btc_z = _compute_zscore(
        [h["dvol"] for h in btc_hist], lookback
    )
    eth_dvol, eth_mean, eth_std, eth_z = _compute_zscore(
        [h["dvol"] for h in eth_hist], lookback
    )

    return {
        "btc_dvol":     btc_dvol,
        "btc_n3z":      btc_z,
        "btc_mean_30d": btc_mean,
        "eth_dvol":     eth_dvol,
        "eth_n3z":      eth_z,
        "eth_mean_30d": eth_mean,
        "q5c":          btc_z - eth_z,
        "event_time":   btc_hist[-1].get("event_time"),
        "timestamp":    _now(),
    }


def reconcile_dvol(dvol: float, currency: str = "BTC") -> list[str]:
    """
    Sanity-check a DVOL value for implausible readings.
    Returns warning strings; empty = clean.
    """
    warnings: list[str] = []
    bounds = {"BTC": (10.0, 300.0), "ETH": (10.0, 400.0)}
    lo, hi = bounds.get(currency, (5.0, 500.0))
    if not (lo <= dvol <= hi):
        warnings.append(
            f"{currency} DVOL={dvol:.1f} outside plausible range [{lo}, {hi}]"
        )
    return warnings
