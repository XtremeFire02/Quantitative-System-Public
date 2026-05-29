"""
Historical replay — verifies that the live backend logic reproduces
the research backtest numbers: ~199 trades, Sharpe ~+2.95 OOS 2024-2026.

Reads the same parquet files used by research/21_strategy_backtest.py
and applies the frozen strategy rule (N3z > threshold AND DVOL >= regime filter).
Parquet files are stored locally and excluded from the repository.
Strategy thresholds are loaded from environment variables.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

# Navigate from paper_trading/backend/app/api/ to project root
_API_DIR = Path(__file__).resolve().parent         # .../app/api/
_PROJECT_ROOT = _API_DIR.parent.parent.parent.parent  # project root
_DATA_RAW = _PROJECT_ROOT / "data" / "raw"

KLINES_PATH = _DATA_RAW / "BTCUSDT_1m_klines.parquet"
DVOL_PATH = _DATA_RAW / "BTC_deribit_dvol_1h.parquet"
FUNDING_PATH = _DATA_RAW / "BTCUSDT_funding.parquet"

# Frozen strategy parameters — thresholds loaded from environment variables.
N3Z_THRESH = float(os.getenv("N3Z_THRESHOLD", "0"))
DVOL_THRESH = float(os.getenv("DVOL_THRESHOLD", "0"))
DVOL_LOOKBACK_HOURS = 30 * 24   # 720
ONE_WAY_COST = 0.0003            # 3bp per leg (maker fee + slippage)

PERIODS = [
    ("Train 2023",   "2023-01-01", "2024-01-01"),
    ("OOS 2024-H1",  "2024-01-01", "2024-07-01"),
    ("OOS 2024-H2",  "2024-07-01", "2025-01-01"),
    ("OOS 2025-H1",  "2025-01-01", "2025-07-01"),
    ("OOS 2025-H2",  "2025-07-01", "2026-01-01"),
    ("OOS 2026-YTD", "2026-01-01", "2099-01-01"),
]

router = APIRouter()


@router.get("/replay")
def run_replay(
    start: str = Query(default="2024-01-01", description="OOS start date (YYYY-MM-DD)"),
    include_train: bool = Query(default=False, description="Include 2023 training period"),
):
    """
    Run the historical strategy replay against local parquet files.
    Returns per-trade results and summary statistics.
    Target (OOS 2024-2026): n≈199 trades, Sharpe≈+2.95, PnL≈+11,228bp.
    """
    for path in [KLINES_PATH, DVOL_PATH, FUNDING_PATH]:
        if not path.exists():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Parquet file not found: {path.name}. "
                    "Historical data files are excluded from the repository. "
                    "Run data/download.py and data/download_phase2.py to fetch them."
                ),
            )

    try:
        import numpy as np
        import pandas as pd
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="pandas/numpy not installed. Run: pip install pandas numpy pyarrow",
        )

    # Load parquets
    klines = pd.read_parquet(KLINES_PATH)[["close"]]
    dvol_raw = pd.read_parquet(DVOL_PATH)[["close"]].rename(columns={"close": "dvol"})
    fund = pd.read_parquet(FUNDING_PATH)[["fundingRate"]]

    # Ensure UTC timezone on all indices
    for df in [klines, dvol_raw, fund]:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

    # N3z: 30d rolling z-score on hourly DVOL
    dvol_raw["n3_z"] = (
        (dvol_raw["dvol"] - dvol_raw["dvol"].rolling(DVOL_LOOKBACK_HOURS).mean())
        / dvol_raw["dvol"].rolling(DVOL_LOOKBACK_HOURS).std()
    )
    dvol_1m = dvol_raw.resample("1min").ffill()

    # 24h forward log-return on 1m close
    log_c = np.log(klines["close"])
    klines = klines.copy()
    klines["r24h"] = log_c.shift(-1440) - log_c

    # Funding: 24h total paid by long (sum of 3 8h settlements in next 24h)
    fund_1m = fund[["fundingRate"]].resample("1min").ffill()
    fund_1m["fund_per_min"] = fund_1m["fundingRate"] / 480.0
    fund_1m["fund_24h"] = fund_1m["fund_per_min"].rolling(1440).sum().shift(-1440)
    klines["fund_24h"] = fund_1m["fund_24h"].reindex(klines.index)

    # Merge DVOL onto 1m frame
    df = klines.join(dvol_1m[["dvol", "n3_z"]], how="inner").dropna(subset=["dvol"])

    # Sample daily (one observation per day at daily close = every 1440 bars)
    daily = df.iloc[::1440].copy()
    daily = daily.dropna(subset=["n3_z", "r24h", "fund_24h"])

    # Apply start date filter
    start_ts = pd.Timestamp(start, tz="UTC")
    if not include_train:
        daily_filtered = daily[daily.index >= start_ts]
    else:
        daily_filtered = daily[daily.index >= pd.Timestamp("2023-01-01", tz="UTC")]

    if len(daily_filtered) < 10:
        raise HTTPException(status_code=422, detail="Insufficient data for requested date range.")

    # Build trades with frozen rule
    all_trades = _build_trades(daily_filtered)
    summary = _compute_stats(all_trades)

    # Period breakdown
    period_rows = []
    for label, ps, pe in PERIODS:
        sub = daily[
            (daily.index >= pd.Timestamp(ps, tz="UTC")) &
            (daily.index < pd.Timestamp(pe, tz="UTC"))
        ]
        if len(sub) < 2:
            continue
        t = _build_trades(sub)
        if len(t) < 2:
            continue
        st = _compute_stats(t)
        is_oos = not label.startswith("Train")
        period_rows.append({
            "label": label,
            "start": ps,
            "end": pe if pe != "2099-01-01" else daily.index.max().strftime("%Y-%m-%d"),
            "n_trades": st["n_trades"],
            "sharpe": st["sharpe"],
            "total_pnl_bp": st["total_pnl_bp"],
            "max_dd_bp": st["max_dd_bp"],
            "win_rate": st["win_rate"],
            "avg_win_bp": st["avg_win_bp"],
            "avg_loss_bp": st["avg_loss_bp"],
            "exposure_pct": st["exposure_pct"],
            "longs": int((t["pos"] > 0).sum()),
            "shorts": int((t["pos"] < 0).sum()),
            "is_oos": is_oos,
        })

    # Per-trade list
    trade_list = []
    if len(all_trades) > 0:
        for idx, row in all_trades.iterrows():
            trade_list.append({
                "date": idx.strftime("%Y-%m-%d"),
                "side": "long" if row["pos"] > 0 else "short",
                "n3z": round(float(row["n3z"]), 3),
                "dvol": round(float(row["dvol"]), 1),
                "r24h_bp": round(float(row["r24h"]) * 10000, 1),
                "fund_24h_bp": round(float(row["fund_24h"]) * 10000, 1),
                "net_pnl_bp": round(float(row["net_r"]) * 10000, 1),
                "cumulative_pnl_bp": round(float(row["cumulative_pnl"]) * 10000, 1),
            })

    data_start = daily.index.min().strftime("%Y-%m-%d") if len(daily) > 0 else "N/A"
    data_end = daily.index.max().strftime("%Y-%m-%d") if len(daily) > 0 else "N/A"

    return {
        "status": "ok",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_range": {"start": data_start, "end": data_end},
        "query_start": start,
        "parameters": {
            "n3z_threshold": N3Z_THRESH,
            "dvol_threshold": DVOL_THRESH,
            "hold_hours": 24,
            "cost_model": "maker (3bp per leg, 6bp RT)",
        },
        "reference_targets": {
            "n_trades": 199,
            "sharpe": 2.95,
            "total_pnl_bp": 11228,
            "max_dd_bp": -1612,
            "win_rate": 0.538,
            "note": "OOS 2024-2026 from research/21_strategy_backtest.py",
        },
        "summary": summary,
        "period_breakdown": period_rows,
        "trades": trade_list,
    }


def _build_trades(dly):
    """Apply frozen rule and return a DataFrame of trades."""
    import numpy as np
    import pandas as pd

    d = dly.dropna(subset=["n3_z", "r24h", "fund_24h", "dvol"])
    if len(d) == 0:
        return pd.DataFrame()

    regime = d["dvol"] >= DVOL_THRESH
    signal = np.where(d["n3_z"] > N3Z_THRESH, 1.0,
                      np.where(d["n3_z"] < -N3Z_THRESH, -1.0, 0.0))
    pos = np.where(regime, signal, 0.0)

    rows = []
    prev_pos = 0.0
    for i, (idx, row) in enumerate(d.iterrows()):
        p = float(pos[i])
        cost = 0.0
        if p != prev_pos:
            if prev_pos != 0:
                cost += ONE_WAY_COST
            if p != 0:
                cost += ONE_WAY_COST
        prev_pos = p

        if p == 0:
            continue

        gross_r = row["r24h"] - row["fund_24h"]
        net_r = p * gross_r - cost * abs(p)

        rows.append({
            "date": idx,
            "pos": p,
            "n3z": row["n3_z"],
            "dvol": row["dvol"],
            "r24h": row["r24h"],
            "fund_24h": row["fund_24h"],
            "gross_r": p * gross_r,
            "net_r": net_r,
            "cost": cost,
        })

    if not rows:
        return __import__("pandas").DataFrame()

    df = __import__("pandas").DataFrame(rows).set_index("date")
    df["cumulative_pnl"] = df["net_r"].cumsum()
    return df


def _compute_stats(trades_df) -> dict:
    import math as _math

    if trades_df is None or len(trades_df) == 0:
        return {
            "n_trades": 0, "sharpe": None, "total_pnl_bp": 0,
            "max_dd_bp": 0, "win_rate": None, "avg_win_bp": None,
            "avg_loss_bp": None, "exposure_pct": None,
        }

    r = trades_df["net_r"]
    n = len(r)
    winners = r[r > 0]
    losers = r[r < 0]

    mean = float(r.mean())
    std = float(r.std()) if n > 1 else 0.0
    sharpe = round(mean / std * _math.sqrt(252), 3) if std > 0 else None

    cum = r.cumsum()
    peak = cum.cummax()
    max_dd = float((cum - peak).min())

    return {
        "n_trades": n,
        "sharpe": sharpe,
        "total_pnl_bp": round(float(r.sum()) * 10000, 1),
        "max_dd_bp": round(max_dd * 10000, 1),
        "win_rate": round(len(winners) / n, 4) if n > 0 else None,
        "avg_win_bp": round(float(winners.mean()) * 10000, 1) if len(winners) > 0 else None,
        "avg_loss_bp": round(float(losers.mean()) * 10000, 1) if len(losers) > 0 else None,
        "exposure_pct": None,  # set per-period by caller if needed
    }
