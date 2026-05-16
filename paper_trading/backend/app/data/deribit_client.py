"""Deribit DVOL fetcher — current and historical 30d IV for BTC and ETH."""
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.config import DERIBIT_BASE, DVOL_LOOKBACK_DAYS


async def fetch_current_dvol() -> Optional[float]:
    """Current Deribit BTC DVOL (30d implied vol index)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{DERIBIT_BASE}/get_index_price",
                              params={"index_name": "dvol_btc"})
        r.raise_for_status()
        return float(r.json()["result"]["index_price"])


async def fetch_dvol_history(
    days: int = DVOL_LOOKBACK_DAYS + 2,
    currency: str = "BTC",
) -> list[dict]:
    """Historical hourly DVOL for the last `days` days. currency: 'BTC' or 'ETH'."""
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{DERIBIT_BASE}/get_volatility_index_data",
                              params={
                                  "currency":        currency,
                                  "start_timestamp": start_ms,
                                  "end_timestamp":   now_ms,
                                  "resolution":      "3600",
                              })
        r.raise_for_status()
        data = r.json()["result"]["data"]
        # data is list of [timestamp_ms, open, high, low, close]
        return [{"timestamp_ms": row[0], "dvol": float(row[4])} for row in data]


def _compute_n3z(dvol_values: list[float], lookback: int) -> tuple[float, float, float]:
    """Compute (current_dvol, mean_30d, n3z) from a DVOL history list."""
    if len(dvol_values) < lookback:
        raise RuntimeError(
            f"Insufficient DVOL history: {len(dvol_values)} bars, need {lookback}"
        )
    window   = dvol_values[-lookback:]
    mean_30d = sum(window) / len(window)
    variance = sum((x - mean_30d) ** 2 for x in window) / len(window)
    std_30d  = variance ** 0.5
    current  = dvol_values[-1]
    n3z      = (current - mean_30d) / std_30d if std_30d > 0 else 0.0
    return current, mean_30d, n3z


async def get_dvol_snapshot() -> dict:
    """Returns current BTC DVOL and 30d rolling stats (used by N3 and P3 signals)."""
    history = await fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency="BTC")
    if not history:
        raise RuntimeError("Empty BTC DVOL history from Deribit")

    lookback = DVOL_LOOKBACK_DAYS * 24  # hours
    dvol_values = [h["dvol"] for h in history]
    current_dvol, mean_30d, n3_z = _compute_n3z(dvol_values, lookback)
    window  = dvol_values[-lookback:]
    std_30d = (sum((x - mean_30d) ** 2 for x in window) / len(window)) ** 0.5

    return {
        "dvol":        current_dvol,
        "dvol_mean_30d": mean_30d,
        "dvol_std_30d":  std_30d,
        "n3_z":        n3_z,
        "n_bars_used": len(window),
        "timestamp":   datetime.now(timezone.utc),
    }


async def get_cross_dvol_snapshot() -> dict:
    """
    Returns BTC and ETH DVOL snapshots for the Q5c signal.

    q5c = btc_n3z - eth_n3z  (BTC-excess implied vol relative to ETH).
    Both z-scores use the same 30d rolling window (720 hourly bars).
    """
    lookback = DVOL_LOOKBACK_DAYS * 24  # hours

    btc_hist = await fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency="BTC")
    eth_hist = await fetch_dvol_history(days=DVOL_LOOKBACK_DAYS + 2, currency="ETH")

    if not btc_hist:
        raise RuntimeError("Empty BTC DVOL history from Deribit")
    if not eth_hist:
        raise RuntimeError("Empty ETH DVOL history from Deribit")

    btc_vals = [h["dvol"] for h in btc_hist]
    eth_vals = [h["dvol"] for h in eth_hist]

    btc_dvol, btc_mean, btc_n3z = _compute_n3z(btc_vals, lookback)
    eth_dvol, eth_mean, eth_n3z = _compute_n3z(eth_vals, lookback)

    q5c = btc_n3z - eth_n3z

    return {
        "btc_dvol":    btc_dvol,
        "btc_n3z":     btc_n3z,
        "btc_mean_30d": btc_mean,
        "eth_dvol":    eth_dvol,
        "eth_n3z":     eth_n3z,
        "eth_mean_30d": eth_mean,
        "q5c":         q5c,
        "timestamp":   datetime.now(timezone.utc),
    }
