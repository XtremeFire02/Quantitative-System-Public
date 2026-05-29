"""
Experiment tracking API.

Records per-run metadata for every research script that tests a hypothesis.
Provides an auditable log of what was tested, with what parameters, and what was decided.

GET  /api/experiments           — all runs (newest first)
GET  /api/experiments/{run_id}  — single run
POST /api/experiments           — log a new run
PATCH /api/experiments/{run_id} — update verdict / notes
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import ExperimentRun, get_db

router = APIRouter()

VALID_VERDICTS = {"passed", "failed", "killed", "pending"}


class NewRun(BaseModel):
    run_id: str
    script_name: str | None = None
    strategy_name: str | None = None
    commit_hash: str | None = None
    data_range_start: str | None = None
    data_range_end: str | None = None
    parameters: dict | None = None
    metrics: dict | None = None
    verdict: str = "pending"
    notes: str | None = None


class VerdictUpdate(BaseModel):
    verdict: str
    notes: str | None = None


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db)):
    rows = db.query(ExperimentRun).order_by(ExperimentRun.created_at.desc()).all()
    return [_serialize(r) for r in rows]


@router.get("/experiments/{run_id}")
def get_experiment(run_id: str, db: Session = Depends(get_db)):
    row = db.query(ExperimentRun).filter(ExperimentRun.run_id == run_id).first()
    if not row:
        raise HTTPException(404, f"Experiment '{run_id}' not found")
    return _serialize(row)


@router.post("/experiments", status_code=201)
def create_experiment(body: NewRun, db: Session = Depends(get_db)):
    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(400, f"Invalid verdict. Use: {sorted(VALID_VERDICTS)}")

    existing = db.query(ExperimentRun).filter(ExperimentRun.run_id == body.run_id).first()
    if existing:
        raise HTTPException(409, f"run_id '{body.run_id}' already exists")

    row = ExperimentRun(
        run_id=body.run_id,
        script_name=body.script_name,
        strategy_name=body.strategy_name,
        commit_hash=body.commit_hash,
        data_range_start=body.data_range_start,
        data_range_end=body.data_range_end,
        parameters=json.dumps(body.parameters) if body.parameters else None,
        metrics=json.dumps(body.metrics) if body.metrics else None,
        verdict=body.verdict,
        notes=body.notes,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.patch("/experiments/{run_id}")
def update_experiment(run_id: str, body: VerdictUpdate, db: Session = Depends(get_db)):
    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(400, f"Invalid verdict. Use: {sorted(VALID_VERDICTS)}")
    row = db.query(ExperimentRun).filter(ExperimentRun.run_id == run_id).first()
    if not row:
        raise HTTPException(404, f"Experiment '{run_id}' not found")
    row.verdict = body.verdict
    if body.notes is not None:
        row.notes = body.notes
    db.commit()
    db.refresh(row)
    return _serialize(row)


def _serialize(row: ExperimentRun) -> dict:
    def _iso(ts):
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()

    def _json(raw):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    return {
        "run_id":           row.run_id,
        "script_name":      row.script_name,
        "strategy_name":    row.strategy_name,
        "commit_hash":      row.commit_hash,
        "data_range_start": row.data_range_start,
        "data_range_end":   row.data_range_end,
        "parameters":       _json(row.parameters),
        "metrics":          _json(row.metrics),
        "verdict":          row.verdict,
        "notes":            row.notes,
        "created_at":       _iso(row.created_at),
    }
