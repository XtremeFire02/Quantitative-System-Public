"""
Data quality dashboard.

GET /api/system/data-quality — checks all data feeds for completeness and freshness.

Checks:
  - Market data (BTCUSDT prices): expected daily rows vs. actual
  - DVOL: last received timestamp, gap detection
  - Signal evaluations: expected daily row per active strategy vs. actual
  - API error count today (from SystemLog)
  - Duplicate signal rows
  - Abnormal DVOL values (< 10 or > 200)
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import BotConfig, MarketData, Signal, SystemLog, get_db

router = APIRouter()


@router.get("/system/data-quality")
def data_quality(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    checks = []

    # 1. Market data rows in last 7 days
    market_count = (
        db.query(func.count(MarketData.id))
        .filter(MarketData.timestamp >= seven_days_ago)
        .scalar() or 0
    )
    expected_market = 7  # one row per daily job run
    market_ok = market_count >= max(expected_market - 2, 1)
    checks.append({
        "name":     "market_data_coverage",
        "status":   "ok" if market_ok else "warn",
        "detail":   f"{market_count}/{expected_market} daily market data rows in last 7 days",
        "value":    market_count,
        "expected": expected_market,
    })

    # 2. Last market data timestamp
    last_market = db.query(MarketData).order_by(MarketData.id.desc()).first()
    if last_market:
        last_ts = last_market.timestamp
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        hours_since = (now - last_ts).total_seconds() / 3600
        market_stale = hours_since > 26  # should run daily
        checks.append({
            "name":   "market_data_freshness",
            "status": "warn" if market_stale else "ok",
            "detail": f"Last market data {hours_since:.1f}h ago",
            "value":  round(hours_since, 1),
            "expected": "≤26h",
        })

        # 3. DVOL staleness / missing
        dvol_vals = (
            db.query(MarketData.dvol)
            .filter(MarketData.timestamp >= seven_days_ago)
            .all()
        )
        n_dvol = sum(1 for (v,) in dvol_vals if v is not None)
        n_missing_dvol = len(dvol_vals) - n_dvol
        dvol_ok = n_missing_dvol == 0
        checks.append({
            "name":   "dvol_missing",
            "status": "ok" if dvol_ok else "warn",
            "detail": f"{n_missing_dvol} days with null DVOL in last 7 days",
            "value":  n_missing_dvol,
            "expected": 0,
        })

        # 4. Abnormal DVOL values
        n_abnormal = sum(
            1 for (v,) in dvol_vals
            if v is not None and (v < 10 or v > 200)
        )
        checks.append({
            "name":   "dvol_abnormal",
            "status": "ok" if n_abnormal == 0 else "warn",
            "detail": f"{n_abnormal} DVOL readings outside [10, 200] in last 7 days",
            "value":  n_abnormal,
            "expected": 0,
        })
    else:
        checks.append({
            "name": "market_data_freshness", "status": "error",
            "detail": "No market data rows at all", "value": None, "expected": "any",
        })

    # 5. Signal evaluations per active strategy (last 7 days)
    active_strategies = [
        r.strategy_name
        for r in db.query(BotConfig).filter(BotConfig.is_active == True).all()
    ]
    for strat in active_strategies:
        n_sigs = (
            db.query(func.count(Signal.id))
            .filter(Signal.strategy_name == strat, Signal.timestamp >= seven_days_ago)
            .scalar() or 0
        )
        sig_ok = n_sigs >= max(expected_market - 2, 1)
        checks.append({
            "name":     f"signal_coverage_{strat}",
            "status":   "ok" if sig_ok else "warn",
            "detail":   f"{strat}: {n_sigs}/{expected_market} evaluations in last 7 days",
            "value":    n_sigs,
            "expected": expected_market,
        })

    # 6. Duplicate signal rows (same strategy + same day)
    all_sigs = (
        db.query(Signal.strategy_name, Signal.timestamp)
        .filter(Signal.timestamp >= seven_days_ago)
        .all()
    )
    seen: set[str] = set()
    dups = 0
    for strat, ts in all_sigs:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        key = f"{strat}_{ts.strftime('%Y-%m-%d')}"
        if key in seen:
            dups += 1
        seen.add(key)
    checks.append({
        "name":   "duplicate_signals",
        "status": "ok" if dups == 0 else "warn",
        "detail": f"{dups} duplicate signal rows (same strategy+day) in last 7 days",
        "value":  dups,
        "expected": 0,
    })

    # 7. API error count today
    error_count = (
        db.query(func.count(SystemLog.id))
        .filter(SystemLog.level == "ERROR", SystemLog.timestamp >= today_start)
        .scalar() or 0
    )
    checks.append({
        "name":   "api_errors_today",
        "status": "ok" if error_count == 0 else ("warn" if error_count < 5 else "error"),
        "detail": f"{error_count} ERROR log entries today",
        "value":  error_count,
        "expected": 0,
    })

    overall = (
        "error" if any(c["status"] == "error" for c in checks)
        else "warn" if any(c["status"] == "warn" for c in checks)
        else "ok"
    )

    return {
        "status": overall,
        "checked_at": now.isoformat(),
        "n_checks": len(checks),
        "n_warn": sum(1 for c in checks if c["status"] == "warn"),
        "n_error": sum(1 for c in checks if c["status"] == "error"),
        "checks": checks,
    }
