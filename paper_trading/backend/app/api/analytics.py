"""
Institutional analytics: Sharpe CI, VaR/CVaR, Kelly criterion, rolling IC,
Sortino ratio, Calmar ratio, return distribution statistics.
GET /api/analytics/deep?strategy=N3_DVOL_LONG
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import Trade, get_db

router = APIRouter()


# ── Pure-Python statistics ────────────────────────────────────────────────────

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n < ddof + 1:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _percentile(xs: list[float], p: float) -> float:
    """p in [0, 100]. Linear interpolation."""
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 5:
        return None
    xs, ys = xs[:n], ys[:n]
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


# ── Ratio estimators ──────────────────────────────────────────────────────────

def _sharpe_with_ci(pnl: list[float], trades_per_year: float) -> dict:
    """
    Annualised Sharpe ratio with 95% confidence interval.
    Standard error from Lo (2002): SE(SR̂) ≈ sqrt((1 + SR̂²/2) / n).
    'significant' = CI lower bound > 0 (one-sided α=2.5%).
    """
    n = len(pnl)
    if n < 4:
        return {"value": None, "ci_lo": None, "ci_hi": None, "se": None,
                "n": n, "significant": False}
    mu = _mean(pnl)
    sigma = _std(pnl, ddof=1)
    if sigma == 0:
        return {"value": None, "ci_lo": None, "ci_hi": None, "se": None,
                "n": n, "significant": False}
    sr_trade = mu / sigma
    sr_ann = sr_trade * math.sqrt(trades_per_year)
    se = math.sqrt((1 + sr_ann ** 2 / 2) / n)
    z = 1.96
    return {
        "value":       round(sr_ann, 3),
        "ci_lo":       round(sr_ann - z * se, 3),
        "ci_hi":       round(sr_ann + z * se, 3),
        "se":          round(se, 4),
        "n":           n,
        "significant": (sr_ann - z * se) > 0,
        "min_n_for_significance": _min_n_for_sig(sr_ann),
    }


def _min_n_for_sig(sr: float) -> int | None:
    """Minimum n so that 95% CI excludes zero. Inverse of SE formula."""
    if sr <= 0:
        return None
    z = 1.96
    # z * sqrt((1 + sr²/2) / n) < sr  → n > z² * (1 + sr²/2) / sr²
    n = math.ceil(z ** 2 * (1 + sr ** 2 / 2) / sr ** 2)
    return n


def _var_cvar(pnl: list[float]) -> dict:
    """Historical simulation VaR and CVaR at 95% and 99%."""
    if len(pnl) < 10:
        return {"var_95": None, "var_99": None, "cvar_95": None, "cvar_99": None}
    var_95 = _percentile(pnl, 5.0)
    var_99 = _percentile(pnl, 1.0)
    tail_95 = [x for x in pnl if x <= var_95]
    tail_99 = [x for x in pnl if x <= var_99]
    return {
        "var_95":  round(var_95, 2),
        "var_99":  round(var_99, 2),
        "cvar_95": round(_mean(tail_95), 2) if tail_95 else None,
        "cvar_99": round(_mean(tail_99), 2) if tail_99 else None,
    }


def _kelly(win_rate: float | None, avg_win: float | None, avg_loss: float | None) -> dict:
    """
    Full Kelly and fractional Kelly position sizes.
    f* = (p·b − q) / b  where b = avg_win / |avg_loss|.
    Institutional practice is to trade 0.25×Kelly.
    """
    if None in (win_rate, avg_win, avg_loss) or (avg_loss or 0) >= 0 or (avg_win or 0) <= 0:
        return {"full_kelly_pct": None, "quarter_kelly_pct": None,
                "half_kelly_pct": None, "b_ratio": None, "edge": None}
    p = win_rate
    q = 1.0 - p
    b = avg_win / abs(avg_loss)
    f_star = (p * b - q) / b
    return {
        "full_kelly_pct":    round(f_star * 100, 2),
        "half_kelly_pct":    round(max(0.0, f_star * 0.50 * 100), 2),
        "quarter_kelly_pct": round(max(0.0, f_star * 0.25 * 100), 2),
        "b_ratio":           round(b, 3),
        "edge":              round(f_star, 4),
        "positive_edge":     f_star > 0,
    }


def _rolling_ic(sigs: list[float], rets: list[float], window: int) -> list[dict]:
    """Rolling Pearson IC over a sliding window of trades."""
    n = len(sigs)
    out = []
    for i in range(window, n + 1):
        ic = _pearson(sigs[i - window: i], rets[i - window: i])
        out.append({"trade_n": i, "ic": round(ic, 4) if ic is not None else None})
    return out


def _distribution_stats(pnl: list[float]) -> dict:
    n = len(pnl)
    if n < 4:
        return {}
    mu = _mean(pnl)
    sigma = _std(pnl, ddof=1)
    if sigma == 0:
        return {"mean_bp": round(mu, 2), "std_bp": 0}
    skew = sum(((x - mu) / sigma) ** 3 for x in pnl) / n
    kurt = sum(((x - mu) / sigma) ** 4 for x in pnl) / n - 3  # excess
    return {
        "mean_bp":          round(mu, 2),
        "std_bp":           round(sigma, 2),
        "skewness":         round(skew, 3),
        "excess_kurtosis":  round(kurt, 3),
        "max_win_bp":       round(max(pnl), 1),
        "max_loss_bp":      round(min(pnl), 1),
        "positive_skew":    skew > 0,
    }


def _build_histogram(pnl: list[float], n_bins: int = 20) -> list[dict]:
    if not pnl:
        return []
    lo, hi = min(pnl), max(pnl)
    if lo == hi:
        return [{"bin_lo": lo, "bin_hi": hi, "count": len(pnl)}]
    width = (hi - lo) / n_bins
    bins = [0] * n_bins
    for v in pnl:
        idx = min(int((v - lo) / width), n_bins - 1)
        bins[idx] += 1
    return [
        {"bin_lo": round(lo + i * width, 1),
         "bin_hi": round(lo + (i + 1) * width, 1),
         "count":  bins[i]}
        for i in range(n_bins)
    ]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/analytics/deep")
def get_deep_analytics(
    strategy: Optional[str] = Query(None, description="Filter by strategy name"),
    db: Session = Depends(get_db),
):
    """
    Institutional analytics suite:
    · Sharpe ratio with 95% confidence interval (Lo 2002 SE estimator)
    · Sortino ratio (downside deviation only)
    · Calmar ratio (annualised return / max drawdown)
    · Historical VaR and CVaR at 95% and 99%
    · Kelly criterion — full, half, quarter-Kelly
    · Rolling IC (signal z-score → return correlation)
    · Return distribution: skewness, excess kurtosis, histogram
    · Minimum sample size for statistical significance
    """
    q = db.query(Trade).filter(
        Trade.status == "closed",
        Trade.net_pnl_bp.isnot(None),
    )
    if strategy:
        q = q.filter(Trade.strategy_name == strategy)
    trades = q.order_by(Trade.exit_timestamp.asc()).all()

    if not trades:
        return {"error": "No closed trades", "n": 0, "strategy": strategy}

    pnl = [float(t.net_pnl_bp) for t in trades]
    n = len(pnl)

    # Estimate annualised trade frequency
    first_dt = trades[0].entry_timestamp
    last_dt  = trades[-1].entry_timestamp
    if first_dt and last_dt and first_dt != last_dt:
        days = max(1, (last_dt - first_dt).total_seconds() / 86400)
        trades_per_year = n / days * 365.25
    else:
        trades_per_year = 12.0  # conservative fallback

    # Basic win/loss stats
    winners = [p for p in pnl if p > 0]
    losers  = [p for p in pnl if p < 0]
    win_rate  = len(winners) / n if n else None
    avg_win   = _mean(winners) if winners else None
    avg_loss  = _mean(losers)  if losers  else None
    profit_factor = (
        sum(winners) / abs(sum(losers))
        if losers and winners else None
    )

    # Sharpe with CI
    sharpe = _sharpe_with_ci(pnl, trades_per_year)

    # Sortino (downside std only)
    down_std = _std(losers, ddof=1) if len(losers) >= 2 else None
    sortino = (
        round(_mean(pnl) / down_std * math.sqrt(trades_per_year), 3)
        if down_std else None
    )

    # Calmar: annualised mean return / maximum drawdown (in bp)
    cumul = 0.0
    peak  = 0.0
    max_dd_bp = 0.0
    equity_curve = []
    for p in pnl:
        cumul += p
        peak = max(peak, cumul)
        max_dd_bp = max(max_dd_bp, peak - cumul)
        equity_curve.append(round(cumul, 2))
    annual_return_bp = _mean(pnl) * trades_per_year
    calmar = round(annual_return_bp / max_dd_bp, 3) if max_dd_bp > 0 else None

    # VaR / CVaR
    risk = _var_cvar(pnl)

    # Kelly
    kelly = _kelly(win_rate, avg_win, avg_loss)

    # Rolling IC on N3 z-score signal
    n3_pairs = [
        (float(t.entry_n3_z), float(t.net_pnl_bp))
        for t in trades
        if t.entry_n3_z is not None
    ]
    overall_ic = _pearson([s for s, _ in n3_pairs], [r for _, r in n3_pairs])
    rolling_ic: list[dict] = []
    ic_window = 10
    if len(n3_pairs) >= ic_window:
        sigs = [s for s, _ in n3_pairs]
        rets = [r for _, r in n3_pairs]
        rolling_ic = _rolling_ic(sigs, rets, ic_window)

    # Distribution
    dist = _distribution_stats(pnl)
    hist = _build_histogram(pnl, 20)

    # Yearly breakdown
    yearly: dict[int, list[float]] = {}
    for t in trades:
        yr = (t.exit_timestamp or t.entry_timestamp)
        if yr:
            yearly.setdefault(yr.year, []).append(float(t.net_pnl_bp))
    yearly_stats = []
    for yr in sorted(yearly):
        yp = yearly[yr]
        yw = [p for p in yp if p > 0]
        yl = [p for p in yp if p < 0]
        yr_tpy = len(yp)  # trades that year
        yr_sharpe = _sharpe_with_ci(yp, max(1.0, yr_tpy))
        yearly_stats.append({
            "year":          yr,
            "n":             len(yp),
            "total_pnl_bp":  round(sum(yp), 1),
            "mean_pnl_bp":   round(_mean(yp), 2),
            "sharpe":        yr_sharpe["value"],
            "win_rate":      round(len(yw) / len(yp), 3),
            "avg_win_bp":    round(_mean(yw), 1) if yw else None,
            "avg_loss_bp":   round(_mean(yl), 1) if yl else None,
        })

    return {
        "strategy":             strategy or "all",
        "n":                    n,
        "trades_per_year":      round(trades_per_year, 1),
        "win_rate":             round(win_rate, 3) if win_rate is not None else None,
        "avg_win_bp":           round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_bp":          round(avg_loss, 2) if avg_loss is not None else None,
        "profit_factor":        round(profit_factor, 3) if profit_factor is not None else None,
        "max_drawdown_bp":      round(max_dd_bp, 1),
        "sharpe":               sharpe,
        "sortino":              sortino,
        "calmar":               calmar,
        "risk":                 risk,
        "kelly":                kelly,
        "signal_ic": {
            "overall_ic":   round(overall_ic, 4) if overall_ic is not None else None,
            "n_pairs":      len(n3_pairs),
            "rolling":      rolling_ic,
            "ic_window":    ic_window,
            "decaying":     (
                rolling_ic[-1]["ic"] < rolling_ic[0]["ic"]
                if len(rolling_ic) >= 2
                and rolling_ic[0]["ic"] is not None
                and rolling_ic[-1]["ic"] is not None
                else None
            ),
        },
        "distribution":         dist,
        "histogram":            hist,
        "equity_curve":         equity_curve,
        "yearly_breakdown":     yearly_stats,
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }
