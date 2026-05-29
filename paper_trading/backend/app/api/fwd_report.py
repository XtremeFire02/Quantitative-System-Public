"""Forward-validation report API — compares live paper-trade behavior to research expectations."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SystemLog, get_db
from app.jobs.fwd_validation_report_job import run_fwd_validation_report

router = APIRouter()


@router.get("/forward-validation/report")
def get_fwd_validation_report(db: Session = Depends(get_db)):
    """
    Return the most recent forward-validation comparison snapshot.

    Serves the cached SystemLog entry written by the daily job (01:00 UTC).
    Falls back to generating a fresh report if no cached entry exists yet.

    Response shape:
        generated_at  : ISO timestamp of when the report was generated
        strategies    : per-strategy live stats + comparison to research baseline
        summary       : aggregate counts (on_track / drift_detected / no_baseline / insufficient_data)
    """
    last = (
        db.query(SystemLog)
        .filter(SystemLog.component == "fwd_validation", SystemLog.level == "REPORT")
        .order_by(SystemLog.timestamp.desc())
        .first()
    )
    if last and last.message:
        try:
            return json.loads(last.message)
        except json.JSONDecodeError:
            pass

    # No cached snapshot — generate now and let the job persist it
    return run_fwd_validation_report(db=db)


@router.post("/forward-validation/report/refresh")
def refresh_fwd_validation_report(db: Session = Depends(get_db)):
    """Force-regenerate the forward-validation report regardless of cache."""
    return run_fwd_validation_report(db=db)
