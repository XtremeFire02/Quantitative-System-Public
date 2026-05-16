"""Alerts API — read, acknowledge, and clear system alerts."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db, Alert

router = APIRouter()


@router.get("/alerts")
def get_alerts(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Alert).order_by(Alert.timestamp.desc())
    if unread_only:
        q = q.filter(Alert.is_read == False)
    rows = q.limit(limit).all()
    return [_serialize(a) for a in rows]


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    db.commit()
    return {"status": "ok", "alert_id": alert_id}


@router.post("/alerts/mark-all-read")
def mark_all_read(db: Session = Depends(get_db)):
    updated = db.query(Alert).filter(Alert.is_read == False).update({"is_read": True})
    db.commit()
    return {"status": "ok", "marked_read": updated}


@router.get("/alerts/summary")
def alert_summary(db: Session = Depends(get_db)):
    rows = (
        db.query(Alert.category, func.count(Alert.id).label("n"))
        .filter(Alert.is_read == False)
        .group_by(Alert.category)
        .all()
    )
    return {
        "total_unread": sum(r.n for r in rows),
        "by_category":  {r.category: r.n for r in rows},
    }


def _serialize(a: Alert) -> dict:
    exposure = None
    if a.exposure:
        try:
            exposure = json.loads(a.exposure)
        except Exception:
            exposure = None
    return {
        "id":           a.id,
        "timestamp":    _iso(a.timestamp),
        "category":     a.category,
        "title":        a.title,
        "body":         a.body,
        "strategy":     a.strategy,
        "market":       a.market,
        "exposure":     exposure,
        "action_taken": a.action_taken,
        "is_read":      a.is_read,
    }


def _iso(ts) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()
