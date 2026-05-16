"""
Audit log — immutable record of every trade decision.

GET /api/audit                → recent decision log entries (default last 200)
GET /api/audit?limit=N        → last N entries
GET /api/audit?since=ISO8601  → entries after timestamp

Sources (read-only, never modified):
  system_logs  — daily_job, portfolio_risk, kill_switch components
  signals      — every evaluation with entry decision + reason
  trades       — every open / close event

Entries are returned newest-first and are never mutated.
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db, SystemLog, Signal, Trade

router = APIRouter()

_AUDIT_COMPONENTS = {"daily_job", "kill_switch", "portfolio_risk", "risk_check"}


@router.get("/audit")
def get_audit_log(
    limit: int = Query(200, ge=1, le=2000),
    since: Optional[str] = Query(None, description="ISO-8601 timestamp; return entries after this"),
    db: Session = Depends(get_db),
):
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            pass

    events = []

    # ── SystemLog events ──────────────────────────────────────────────────────
    q = db.query(SystemLog).filter(SystemLog.component.in_(_AUDIT_COMPONENTS))
    if since_dt:
        q = q.filter(SystemLog.timestamp > since_dt)
    for row in q.order_by(SystemLog.id.desc()).limit(limit).all():
        events.append({
            "source": "system_log",
            "id": row.id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "level": row.level,
            "component": row.component,
            "event": row.message,
            "details": None,
        })

    # ── Signal evaluations ────────────────────────────────────────────────────
    q = db.query(Signal)
    if since_dt:
        q = q.filter(Signal.timestamp > since_dt)
    for row in q.order_by(Signal.id.desc()).limit(limit).all():
        events.append({
            "source": "signal",
            "id": row.id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "level": "INFO" if not row.entry_signal else "WARNING",
            "component": f"signal/{row.strategy_name}",
            "event": "ENTRY" if row.entry_signal else "NO_ENTRY",
            "details": {
                "strategy": row.strategy_name,
                "market": row.market,
                "dvol": row.dvol,
                "n3_z": row.n3_z,
                "reason": row.reason,
            },
        })

    # ── Trade open / close events ─────────────────────────────────────────────
    q = db.query(Trade)
    if since_dt:
        q = q.filter(Trade.entry_timestamp > since_dt)
    for row in q.order_by(Trade.id.desc()).limit(limit).all():
        events.append({
            "source": "trade_open",
            "id": row.id,
            "timestamp": row.entry_timestamp.isoformat() if row.entry_timestamp else None,
            "level": "WARNING",
            "component": f"trade/{row.strategy_name}",
            "event": "TRADE_OPENED",
            "details": {
                "trade_id": row.id,
                "strategy": row.strategy_name,
                "market": row.market,
                "side": row.side,
                "entry_price": row.entry_price,
                "planned_exit": row.planned_exit_timestamp.isoformat() if row.planned_exit_timestamp else None,
                "entry_reason": row.entry_reason,
            },
        })
        if row.status == "closed" and row.exit_timestamp:
            events.append({
                "source": "trade_close",
                "id": row.id,
                "timestamp": row.exit_timestamp.isoformat(),
                "level": "INFO",
                "component": f"trade/{row.strategy_name}",
                "event": "TRADE_CLOSED",
                "details": {
                    "trade_id": row.id,
                    "strategy": row.strategy_name,
                    "market": row.market,
                    "exit_price": row.exit_price,
                    "net_pnl_bp": row.net_pnl_bp,
                    "exit_reason": row.exit_reason,
                },
            })

    # Sort all events newest-first, trim to limit
    events.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    events = events[:limit]

    return {
        "count": len(events),
        "limit": limit,
        "since": since,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
