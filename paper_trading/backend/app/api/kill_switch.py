"""
Kill switch API.

GET  /api/risk/kill-switch          → current state
POST /api/risk/kill-switch          → {"active": true|false, "reason": "..."}
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_api_key
from app.trading import kill_switch as ks

router = APIRouter()


class KillSwitchUpdate(BaseModel):
    active: bool
    reason: str = "manual"


@router.get("/risk/kill-switch")
def get_kill_switch(db: Session = Depends(get_db)):
    return ks.get_state(db)


@router.post("/risk/kill-switch", dependencies=[Depends(require_api_key)])
def set_kill_switch(body: KillSwitchUpdate, db: Session = Depends(get_db)):
    if body.active:
        return ks.arm(db, reason=body.reason)
    else:
        return ks.disarm(db, reason=body.reason)
