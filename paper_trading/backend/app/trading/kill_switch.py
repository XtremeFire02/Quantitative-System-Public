"""
System-wide kill switch.

When active, no new trades are opened by any strategy. Existing open trades
still run to expiry (time-based exit is unaffected). The switch survives
process restarts because it is persisted in the database.

Usage
-----
  from app.trading.kill_switch import check_kill_switch, KillSwitchActive
  check_kill_switch(db)   # raises KillSwitchActive if armed

Arm / disarm via API:
  POST /api/risk/kill-switch          {"active": true,  "reason": "manual halt"}
  POST /api/risk/kill-switch          {"active": false, "reason": "resume"}
  GET  /api/risk/kill-switch          → current state
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import SystemLog


# ── Exception ─────────────────────────────────────────────────────────────────

class KillSwitchActive(Exception):
    pass


# ── In-memory cache (avoids a DB read on every signal evaluation) ─────────────

_cached: bool | None = None   # None = not yet loaded


def check_kill_switch(db: Session) -> None:
    """Raise KillSwitchActive if the kill switch is currently armed."""
    if _get_state(db):
        raise KillSwitchActive("Kill switch is active — no new trades until disarmed")


def arm(db: Session, reason: str = "manual") -> dict:
    """Arm the kill switch. Returns new state dict."""
    return _set_state(db, active=True, reason=reason)


def disarm(db: Session, reason: str = "manual") -> dict:
    """Disarm the kill switch. Returns new state dict."""
    return _set_state(db, active=False, reason=reason)


def get_state(db: Session) -> dict:
    active = _get_state(db)
    return {"active": active, "checked_at": datetime.now(timezone.utc).isoformat()}


# ── Storage (SystemLog table as a simple key-value store) ─────────────────────
# We reuse SystemLog rather than add another table. The kill switch state is
# the most recent row with component="kill_switch".

_KS_COMPONENT = "kill_switch"
_STATE_ACTIVE  = "ARMED"
_STATE_INACTIVE = "DISARMED"


def _get_state(db: Session) -> bool:
    global _cached
    if _cached is not None:
        return _cached

    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == _KS_COMPONENT)
        .order_by(SystemLog.id.desc())
        .first()
    )
    _cached = (row is not None and row.message == _STATE_ACTIVE)
    return _cached


def _set_state(db: Session, active: bool, reason: str) -> dict:
    global _cached
    msg = _STATE_ACTIVE if active else _STATE_INACTIVE
    db.add(SystemLog(
        level="WARNING" if active else "INFO",
        component=_KS_COMPONENT,
        message=msg,
        timestamp=datetime.now(timezone.utc),
    ))
    db.add(SystemLog(
        level="WARNING" if active else "INFO",
        component="kill_switch_reason",
        message=reason,
        timestamp=datetime.now(timezone.utc),
    ))
    db.commit()
    _cached = active
    return {"active": active, "reason": reason, "set_at": datetime.now(timezone.utc).isoformat()}


def invalidate_cache() -> None:
    """Force a DB re-read on the next check. Call after direct DB edits."""
    global _cached
    _cached = None
