"""
P3 OI-Price Divergence historical replay.

Reads the same parquet files used by research/24_deepdive.py and applies
the frozen P3 rule: DD regime AND DVOL >= threshold, long, 24h hold.

Reference target (OOS 2024+, DVOL>=54, 24h hold):
  n=99, Sharpe=+5.37, PnL=+9510bp, MaxDD=-972bp, Win=65.7%

Any significant deviation from these targets indicates a bug in the
live evaluator or a data alignment problem.
"""
import math
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException

_API_DIR      = Path(__file__).resolve().parent
_PROJECT_ROOT = _API_DIR.parent.parent.parent.parent
_DATA_RAW     = _PROJECT_ROOT / "data" / "raw"

KLINES_PATH  = _DATA_RAW / "BTCUSDT_1m_klines.parquet"
DVOL_PATH    = _DATA_RAW / "BTC_deribit_dvol_1h.parquet"
FUNDING_PATH = _DATA_RAW / "BTCUSDT_funding.parquet"
OI_PATH      = _DATA_RAW / "BTCUSDT_oi_5m.parquet"

ONE_WAY_COST      = 0.0003   # 3bp per leg (maker fee + slippage)
DVOL_LOOKBACK_H   = 30 * 24

PERIODS = [
    ("Train 2023",   "2023-01-01", "2024-01-01"),
    ("OOS 2024-H1",  "2024-01-01", "2024-07-01"),
    ("OOS 2024-H2",  "2024-07-01", "2025-01-01"),
    ("OOS 2025-H1",  "2025-01-01", "2025-07-01"),
    ("OOS 2025-H2",  "2025-07-01", "2026-01-01"),
    ("OOS 2026-YTD", "2026-01-01", "2099-01-01"),
]

# Reference numbers from research/24_deepdive.py — OOS 2024+, DVOL>=54, 24h hold
REFERENCE = {
    "dvol_threshold": 54.0,
    "n_trades":       99,
    "sharpe":         5.37,
    "total_pnl_bp":   9510,
    "max_dd_bp":      -972,
    "win_rate":       0.657,
    "note":           "OOS 2024-2026 from research/24_deepdive.py (DD regime, DVOL>=54, 24h hold, maker cost)",
}

router = APIRouter()


@router.get("/replay/p3")
def run_p3_replay(
    dvol_threshold: float = Query(default=54.0, description="DVOL >= threshold to take trade"),
    start: str = Query(default="2024-01-01", description="OOS start date (YYYY-MM-DD)"),
    include_train: bool = Query(default=False),
):
    """
    Historical replay of the P3 OI-PD DD-regime strategy.

    Reference (OOS 2024+, DVOL>=54, 24h hold): n=99, Sharpe=+5.37, PnL=+9510bp.
    A Sharpe within ±1.0 and PnL within ±1500bp of reference is considered a match.
    """
    for path, label in [
        (KLINES_PATH,  "BTCUSDT_1m_klines.parquet"),
        (DVOL_PATH,    "BTC_deribit_dvol_1h.parquet"),
        (FUNDING_PATH, "BTCUSDT_funding.parquet"),
        (OI_PATH,      "BTCUSDT_oi_5m.parquet"),
    ]:
        if not path.exists():
            raise HTTPException(
                status_code=503,
                detail=f"Parquet file not found: {label}. Run data/download.py to fetch it.",
            )

    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        raise HTTPException(status_code=503, detail="pandas/numpy not installed.")

    # ── Load data ────────────────────────────────────────────────────────────
    klines  = pd.read_parquet(KLINES_PATH)[["close"]]
    dvol_h  = pd.read_parquet(DVOL_PATH)[["close"]].rename(columns={"close": "dvol"})
    fund    = pd.read_parquet(FUNDING_PATH)[["fundingRate"]]
    oi_5m   = pd.read_parquet(OI_PATH)

    for df in [klines, dvol_h, fund, oi_5m]:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

    # ── DVOL on 1m grid ──────────────────────────────────────────────────────
    dvol_1m = dvol_h.resample("1min").ffill()

    # ── 24h forward log-return ───────────────────────────────────────────────
    log_c = np.log(klines["close"])
    klines = klines.copy()
    klines["r24h"] = log_c.shift(-1440) - log_c

    # ── 24h funding paid by long ─────────────────────────────────────────────
    fund_1m = fund.resample("1min").ffill()
    fund_1m["fund_per_min"] = fund_1m["fundingRate"] / 480.0
    fund_1m["fund_24h"] = fund_1m["fund_per_min"].rolling(1440).sum().shift(-1440)
    klines["fund_24h"] = fund_1m["fund_24h"].reindex(klines.index)

    # ── DVOL join ────────────────────────────────────────────────────────────
    df = klines.join(dvol_1m[["dvol"]], how="inner").dropna(subset=["dvol"])

    # ── OI on 1m grid ────────────────────────────────────────────────────────
    oi_col = "sumOpenInterest" if "sumOpenInterest" in oi_5m.columns else oi_5m.columns[0]
    oi_1m  = oi_5m[[oi_col]].rename(columns={oi_col: "oi"}).resample("1min").ffill()
    df     = df.join(oi_1m[["oi"]], how="left")

    # ── Sample daily ─────────────────────────────────────────────────────────
    daily = df.iloc[::1440].copy()

    # Compute dd/doi and regime on the daily frame
    daily["dp"]  = daily["close"].pct_change()
    daily["doi"] = daily["oi"].pct_change()
    daily["is_dd"] = ((daily["dp"] < 0) & (daily["doi"] < 0)).astype(float)

    daily = daily.dropna(subset=["dp", "doi", "r24h", "fund_24h", "dvol"])

    # ── Date filter ──────────────────────────────────────────────────────────
    start_ts = pd.Timestamp(start, tz="UTC")
    if include_train:
        daily_q = daily[daily.index >= pd.Timestamp("2023-01-01", tz="UTC")]
    else:
        daily_q = daily[daily.index >= start_ts]

    if len(daily_q) < 10:
        raise HTTPException(status_code=422, detail="Insufficient data for requested range.")

    # ── Full period trades ────────────────────────────────────────────────────
    all_trades = _build_trades(daily_q, dvol_threshold)
    summary    = _stats(all_trades)

    # ── Period breakdown ─────────────────────────────────────────────────────
    period_rows = []
    for label, ps, pe in PERIODS:
        sub = daily[
            (daily.index >= pd.Timestamp(ps, tz="UTC")) &
            (daily.index <  pd.Timestamp(pe, tz="UTC"))
        ]
        t = _build_trades(sub, dvol_threshold)
        if len(t) < 2:
            continue
        st = _stats(t)
        period_rows.append({
            "label":         label,
            "is_oos":        not label.startswith("Train"),
            "n_trades":      st["n_trades"],
            "sharpe":        st["sharpe"],
            "total_pnl_bp":  st["total_pnl_bp"],
            "max_dd_bp":     st["max_dd_bp"],
            "win_rate":      st["win_rate"],
        })

    # ── Per-trade list ────────────────────────────────────────────────────────
    trade_list = []
    for idx, row in all_trades.iterrows():
        trade_list.append({
            "date":             idx.strftime("%Y-%m-%d"),
            "dp_pct":           round(float(row["dp"]) * 100, 3),
            "doi_pct":          round(float(row["doi"]) * 100, 3),
            "dvol":             round(float(row["dvol"]), 1),
            "r24h_bp":          round(float(row["r24h"]) * 10000, 1),
            "fund_24h_bp":      round(float(row["fund_24h"]) * 10000, 1),
            "net_pnl_bp":       round(float(row["net_r"]) * 10000, 1),
            "cumulative_pnl_bp": round(float(row["cumulative_pnl"]) * 10000, 1),
        })

    # ── Reference match check ────────────────────────────────────────────────
    match_note = None
    if dvol_threshold == 54.0 and start == "2024-01-01":
        sh_diff  = abs((summary["sharpe"] or 0) - REFERENCE["sharpe"])
        pnl_diff = abs(summary["total_pnl_bp"] - REFERENCE["total_pnl_bp"])
        n_diff   = abs(summary["n_trades"]      - REFERENCE["n_trades"])
        if sh_diff <= 1.0 and pnl_diff <= 1500 and n_diff <= 10:
            match_note = "PASS: replay matches research within tolerance"
        else:
            match_note = (
                f"WARN: deviation detected — "
                f"Sh diff={sh_diff:.2f}, PnL diff={pnl_diff:.0f}bp, n diff={n_diff}"
            )

    return {
        "status":            "ok",
        "computed_at":       datetime.now(timezone.utc).isoformat(),
        "signal":            "P3_OIPD_DD",
        "rule":              "DD regime (dp<0 AND doi<0) AND DVOL >= threshold, LONG, 24h hold, maker 3bp/leg",
        "dvol_threshold":    dvol_threshold,
        "query_start":       start,
        "reference_targets": REFERENCE,
        "reference_match":   match_note,
        "summary":           summary,
        "period_breakdown":  period_rows,
        "trades":            trade_list,
    }


def _build_trades(dly, dvol_threshold: float):
    import pandas as pd
    import numpy as np

    d = dly.dropna(subset=["dp", "doi", "r24h", "fund_24h", "dvol"])
    if len(d) == 0:
        return pd.DataFrame()

    pos = np.where((d["is_dd"] > 0) & (d["dvol"] >= dvol_threshold), 1.0, 0.0)

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
        net_r   = p * gross_r - cost

        rows.append({
            "date":     idx,
            "dp":       row["dp"],
            "doi":      row["doi"],
            "dvol":     row["dvol"],
            "r24h":     row["r24h"],
            "fund_24h": row["fund_24h"],
            "net_r":    net_r,
            "cost":     cost,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("date")
    df["cumulative_pnl"] = df["net_r"].cumsum()
    return df


def _stats(trades_df) -> dict:
    if trades_df is None or len(trades_df) == 0:
        return {"n_trades": 0, "sharpe": None, "total_pnl_bp": 0,
                "max_dd_bp": 0, "win_rate": None}

    r  = trades_df["net_r"]
    n  = len(r)
    mu = float(r.mean())
    sd = float(r.std()) if n > 1 else 0.0
    sh = round(mu / sd * math.sqrt(252), 3) if sd > 0 else None

    cum  = r.cumsum()
    peak = cum.cummax()
    mdd  = float((cum - peak).min())

    winners = r[r > 0]
    return {
        "n_trades":      n,
        "sharpe":        sh,
        "total_pnl_bp":  round(float(r.sum()) * 10000, 1),
        "max_dd_bp":     round(mdd * 10000, 1),
        "win_rate":      round(len(winners) / n, 4) if n > 0 else None,
    }
