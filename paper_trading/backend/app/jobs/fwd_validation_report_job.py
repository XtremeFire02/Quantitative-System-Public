"""
Forward-validation report job.

Compares live paper-trade performance against research expectations
stored in the ExperimentRun registry. Runs daily at 01:00 UTC.

For each strategy that has at least one closed live trade:
  1. Compute live stats: Sharpe, win rate, average net PnL (bp).
  2. Look up the most recent passed ExperimentRun for that strategy.
  3. Compare: flag strategies where live Sharpe < DRIFT_WARN_PCT × research Sharpe.

The report is stored as a SystemLog row at level="REPORT" so the API
endpoint can serve the cached result without re-computing on every request.

Drift flag conditions (all require ≥ MIN_LIVE_TRADES closed):
  - live Sharpe < DRIFT_WARN_PCT × research Sharpe  → "drift_detected"
  - no passed experiment run found                   → "no_baseline"
  - research baseline Sharpe ≤ 0                     → "no_baseline" (defensive)
  - < MIN_LIVE_TRADES closed                         → "insufficient_data"
  - otherwise                                        → "on_track"

Sharpe convention:
    Live and research both annualize trade-level returns with sqrt(252),
    matching the research code under research/validated/. The ratio
    live_sharpe / research_sharpe is convention-invariant, so drift
    detection stays valid even though the absolute Sharpe is inflated
    relative to a sqrt(trades_per_year) annualization.
    See app/api/performance.py module docstring for full discussion.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import ExperimentRun, SessionLocal, SystemLog, Trade

_DRIFT_WARN_PCT = 0.80   # flag when live Sharpe falls below 80% of research baseline
_MIN_LIVE_TRADES = 5     # minimum closed trades before comparison is meaningful


def run_fwd_validation_report(db: Session | None = None) -> dict:
    """
    Generate and persist a forward-validation comparison report.

    Can be called as a scheduled job (db=None → opens its own session)
    or from the API endpoint with an injected session.
    """
    _own_session = db is None
    if _own_session:
        db = SessionLocal()

    try:
        strategy_names: list[str] = [
            row[0]
            for row in db.query(Trade.strategy_name)
            .filter(Trade.status == "closed")
            .distinct()
            .all()
        ]

        report: dict = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": {},
            "summary": {
                "total_strategies": len(strategy_names),
                "on_track": 0,
                "drift_detected": 0,
                "no_baseline": 0,
                "insufficient_data": 0,
            },
        }

        for name in sorted(strategy_names):
            live = _live_stats(db, name)
            baseline = _research_baseline(db, name)
            comparison = _compare(live, baseline)
            report["strategies"][name] = {"live": live, "comparison": comparison}
            status = comparison["status"]
            if status in report["summary"]:
                report["summary"][status] += 1

        # Persist as a REPORT-level system log for the API cache layer
        db.add(SystemLog(
            level="REPORT",
            component="fwd_validation",
            message=json.dumps(report),
        ))
        db.commit()

        return report

    finally:
        if _own_session:
            db.close()


def _live_stats(db: Session, strategy_name: str) -> dict:
    trades = (
        db.query(Trade)
        .filter(Trade.strategy_name == strategy_name, Trade.status == "closed")
        .order_by(Trade.exit_timestamp.asc())
        .all()
    )
    if not trades:
        return {"n_closed": 0}
    pnls = [t.net_pnl_bp or 0.0 for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n_closed": len(trades),
        "sharpe": _sharpe(pnls),
        "win_rate": round(wins / len(pnls), 4),
        "avg_pnl_bp": round(sum(pnls) / len(pnls), 2),
        "total_pnl_bp": round(sum(pnls), 2),
        "first_trade": _iso(trades[0].entry_timestamp),
        "last_trade": _iso(trades[-1].exit_timestamp),
    }


def _research_baseline(db: Session, strategy_name: str) -> dict | None:
    run = (
        db.query(ExperimentRun)
        .filter(
            ExperimentRun.strategy_name == strategy_name,
            ExperimentRun.verdict == "passed",
        )
        .order_by(ExperimentRun.created_at.desc())
        .first()
    )
    if run is None:
        return None
    try:
        metrics = json.loads(run.metrics) if run.metrics else {}
    except (json.JSONDecodeError, TypeError):
        metrics = {}
    return {
        "run_id": run.run_id,
        "data_range": f"{run.data_range_start} → {run.data_range_end}",
        "metrics": metrics,
    }


def _compare(live: dict, baseline: dict | None) -> dict:
    n = live.get("n_closed", 0)

    if baseline is None:
        return {
            "status": "no_baseline",
            "live_sharpe": live.get("sharpe"),
            "research_sharpe": None,
            "sharpe_achievement_pct": None,
            "live_win_rate": live.get("win_rate"),
            "research_win_rate": None,
            "drift_flag": False,
            "message": "No passed experiment run registered for this strategy.",
        }

    if n < _MIN_LIVE_TRADES:
        return {
            "status": "insufficient_data",
            "live_sharpe": live.get("sharpe"),
            "research_sharpe": None,
            "sharpe_achievement_pct": None,
            "live_win_rate": live.get("win_rate"),
            "research_win_rate": None,
            "drift_flag": False,
            "message": f"Only {n} closed trades; need ≥{_MIN_LIVE_TRADES} to compare.",
        }

    bm = baseline.get("metrics", {})
    # Prefer explicit None checks over `or` so we don't skip a legitimate 0.0
    # in favor of the next fallback key.
    research_sharpe = bm.get("sharpe")
    if research_sharpe is None:
        research_sharpe = bm.get("oos_sharpe")
    if research_sharpe is None:
        research_sharpe = bm.get("sharpe_ratio")
    live_sharpe = live.get("sharpe")

    # Ratio comparison only makes sense when the research baseline is positive.
    # A passed experiment with non-positive Sharpe is a registry integrity issue
    # (it should never have been promoted), so we degrade to "no_baseline" rather
    # than emit a misleading achievement_pct (e.g. a less-negative live Sharpe
    # would yield a low ratio and falsely trip the drift flag).
    if research_sharpe is None or research_sharpe <= 0:
        return {
            "status": "no_baseline",
            "live_sharpe": live_sharpe,
            "research_sharpe": research_sharpe,
            "sharpe_achievement_pct": None,
            "live_win_rate": live.get("win_rate"),
            "research_win_rate": bm.get("win_rate"),
            "drift_flag": False,
            "research_run_id": baseline.get("run_id"),
            "research_data_range": baseline.get("data_range"),
            "message": (
                "Research baseline Sharpe is non-positive; cannot compute drift ratio."
                if research_sharpe is not None
                else "Research baseline does not expose a Sharpe metric."
            ),
        }

    achievement_pct = None
    drift = False
    if live_sharpe is not None:
        achievement_pct = round(live_sharpe / research_sharpe * 100, 1)
        drift = achievement_pct < _DRIFT_WARN_PCT * 100

    return {
        "status": "drift_detected" if drift else "on_track",
        "live_sharpe": live_sharpe,
        "research_sharpe": research_sharpe,
        "sharpe_achievement_pct": achievement_pct,
        "live_win_rate": live.get("win_rate"),
        "research_win_rate": bm.get("win_rate"),
        "live_avg_pnl_bp": live.get("avg_pnl_bp"),
        "research_avg_pnl_bp": bm.get("avg_pnl_bp"),
        "drift_flag": drift,
        "research_run_id": baseline.get("run_id"),
        "research_data_range": baseline.get("data_range"),
        "message": (
            f"Live Sharpe {live_sharpe:.2f} vs research {research_sharpe:.2f} "
            f"({achievement_pct:.0f}% of baseline)."
            if live_sharpe is not None and research_sharpe is not None
            else "Sharpe comparison unavailable."
        ),
    }


def _iso(ts) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _sharpe(pnls: list[float]) -> float | None:
    n = len(pnls)
    if n < 3:
        return None
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return None
    return round(mean / std * math.sqrt(252), 4)
