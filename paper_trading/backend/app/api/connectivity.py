"""
Exchange connectivity monitor.

GET /api/connectivity

Probes Binance FAPI and Deribit REST with lightweight requests and reports
round-trip latency for each feed. Used by operators to verify network health
before deploying or diagnosing data staleness.

Probe logic lives in app.data.exchange_probe and is shared with the daily
signal job, which uses the same probes as an enforcement pre-flight — if any
critical feed is unreachable, the job aborts before touching the DB.

Latency thresholds: warn > 200ms, critical > 1000ms.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.data.exchange_probe import _CRITICAL_MS, _WARN_MS, probe_all, to_dict

router = APIRouter()


@router.get("/connectivity")
async def get_connectivity():
    probes, overall_level = await probe_all()
    probe_dicts = [to_dict(p) for p in probes]
    max_latency = max((p.latency_ms or 0) for p in probes)

    return {
        "overall":       overall_level,
        "max_latency_ms": max_latency,
        "probes":        probe_dicts,
        "thresholds":    {"warn_ms": _WARN_MS, "critical_ms": _CRITICAL_MS},
        "checked_at":    datetime.now(timezone.utc).isoformat(),
    }
