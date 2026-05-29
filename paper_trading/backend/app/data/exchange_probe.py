"""
Exchange connectivity probe — shared by the daily signal job (enforcement)
and GET /api/connectivity (observability).

Runs lightweight HTTP requests against each exchange's cheapest public
endpoint and returns structured probe results with latency measurements.

This module has no database or config dependencies beyond BINANCE_FAPI_BASE
and DERIBIT_BASE so it can be imported early in the startup path.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import BINANCE_FAPI_BASE, DERIBIT_BASE

_WARN_MS = 200.0
_CRITICAL_MS = 1000.0
_TIMEOUT_S = 5.0

_PROBES = [
    {
        "name":   "binance_fapi_price",
        "url":    f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/price",
        "params": {"symbol": "BTCUSDT"},
        "feed":   "price",
    },
    {
        "name":   "binance_fapi_premium",
        "url":    f"{BINANCE_FAPI_BASE}/fapi/v1/premiumIndex",
        "params": {"symbol": "BTCUSDT"},
        "feed":   "mark_price",
    },
    {
        "name":   "deribit_dvol",
        "url":    f"{DERIBIT_BASE}/get_index_price",
        "params": {"index_name": "dvol_btc"},
        "feed":   "dvol",
    },
]


@dataclass
class ProbeResult:
    name: str
    feed: str
    latency_ms: float | None
    status_code: int | None
    ok: bool
    level: str        # "ok" | "warn" | "critical"
    error: str | None


async def probe_all() -> tuple[list[ProbeResult], str]:
    """
    Probe all exchange endpoints in parallel.

    Returns (results, overall_level) where overall_level is the worst
    individual level: "ok" | "warn" | "critical".
    """
    import asyncio

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        tasks = [_probe_one(client, p) for p in _PROBES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    probes: list[ProbeResult] = []
    for r, p in zip(results, _PROBES):
        if isinstance(r, Exception):
            probes.append(ProbeResult(
                name=p["name"], feed=p["feed"],
                latency_ms=None, status_code=None,
                ok=False, level="critical", error=str(r),
            ))
        else:
            probes.append(r)

    worst = "ok"
    for p in probes:
        if p.level == "critical":
            worst = "critical"
            break
        if p.level == "warn" and worst == "ok":
            worst = "warn"

    return probes, worst


async def _probe_one(client: httpx.AsyncClient, probe: dict) -> ProbeResult:
    t0 = time.perf_counter()
    ok = False
    status_code = None
    error = None
    latency_ms = None

    try:
        r = await client.get(probe["url"], params=probe["params"])
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        status_code = r.status_code
        ok = r.status_code == 200
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        error = str(e)

    level = "ok"
    if not ok:
        level = "critical"
    elif latency_ms is not None and latency_ms >= _CRITICAL_MS:
        level = "critical"
    elif latency_ms is not None and latency_ms >= _WARN_MS:
        level = "warn"

    return ProbeResult(
        name=probe["name"], feed=probe["feed"],
        latency_ms=latency_ms, status_code=status_code,
        ok=ok, level=level, error=error,
    )


def to_dict(result: ProbeResult) -> dict:
    return {
        "name":        result.name,
        "feed":        result.feed,
        "latency_ms":  result.latency_ms,
        "status_code": result.status_code,
        "ok":          result.ok,
        "level":       result.level,
        "error":       result.error,
    }
