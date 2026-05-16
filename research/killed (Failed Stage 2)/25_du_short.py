"""
DU Regime Short Side Research
==============================

Hypothesis: price down + OI up => new short positions entering =>
            possible continuation of downward move => SHORT signal.

DU regime definition:
  dp_24h < 0  (price declined over prior 24h)
  doi_24h > 0 (open interest increased over prior 24h)

This is tested as a completely separate signal from P3 (DD long).
Do NOT combine DU short with DD long until each leg is validated
independently.

Test grid:
  DVOL thresholds : 54, 57, 60
  Hold periods    : 24h, 48h, 72h
  Side            : SHORT only

Cost model: maker (6bp RT).
Bootstrap: 2000 samples, block_size=21, seed=42.
Report p=0.000 as p<0.0005 (2000 samples cannot resolve below that).

Sections:
  1.  DU regime descriptive stats (full sample)
  2.  DU short IC screen (full OOS)
  3.  DVOL threshold x hold period grid (OOS 2024+)
  4.  Period breakdown (half-year)
  5.  Year-by-year
  6.  DVOL band decomposition (DU short, 24h, OOS 2024+)
  7.  Comparison: DD long vs DU short vs combined
  8.  Independence from N3
  9.  Sub-period IC stability
 10.  Verdict
"""
import sys, warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from framework.costs import CostModel

RAW   = Path("data/raw")
MAKER = CostModel(use_maker=True)
SEP   = "=" * 72

RNG   = np.random.default_rng(42)

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data...")
klines   = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
dvol_raw = pd.read_parquet(RAW / "BTC_deribit_dvol_1h.parquet")[["close"]].rename(columns={"close": "dvol"})
fund     = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")
oi_5m    = pd.read_parquet(RAW / "BTCUSDT_oi_5m.parquet")

df    = klines[["close"]].copy()
log_c = np.log(df["close"])

for h in [24, 48, 72]:
    df[f"r{h}h"] = log_c.shift(-h * 60) - log_c

fund_1m = fund[["fundingRate"]].resample("1min").ffill()
fund_1m["fund_per_min"] = fund_1m["fundingRate"] / 480.0
for h in [24, 48, 72]:
    mins = h * 60
    df[f"fund_{h}h"] = (fund_1m["fund_per_min"]
                        .rolling(mins).sum()
                        .shift(-mins)
                        .reindex(df.index))

dvol_raw["n3_z"] = (
    (dvol_raw["dvol"] - dvol_raw["dvol"].rolling(720).mean())
    / dvol_raw["dvol"].rolling(720).std()
)
dvol1m = dvol_raw.resample("1min").ffill()
df = df.join(dvol1m[["dvol", "n3_z"]], how="inner").dropna(subset=["dvol"])

oi_1m = oi_5m["sumOpenInterest"].resample("1min").ffill().reindex(df.index)

df["r24h_past"] = log_c.diff(1440)
df["doi_past"]  = (oi_1m - oi_1m.shift(1440)) / oi_1m.shift(1440)

print(f"  Data: {df.index.min().date()} to {df.index.max().date()} ({len(df):,} bars)")

# ── Daily frame ────────────────────────────────────────────────────────────────
daily = df.iloc[::1440].copy()
daily = daily.dropna(subset=["n3_z", "dvol"])

def classify(dp, doi):
    if pd.isna(dp) or pd.isna(doi):
        return np.nan
    if dp >= 0 and doi >= 0: return "UU"
    if dp >= 0 and doi <  0: return "UD"
    if dp <  0 and doi >= 0: return "DU"
    return "DD"

daily["regime"]   = [classify(dp, doi) for dp, doi in zip(daily["r24h_past"], daily["doi_past"])]
daily["is_du"]    = (daily["regime"] == "DU").astype(float)
daily["is_dd"]    = (daily["regime"] == "DD").astype(float)

N3Z_THRESH  = 0.75
N3_DVOL_THR = 54.0
daily["n3_long"] = ((daily["n3_z"] > N3Z_THRESH) &
                    (daily["dvol"] >= N3_DVOL_THR)).astype(float)

# Signal for IC: +1 if DU (expect short edge, so positive signal => negative fwd return)
# We flip sign so that IC > 0 means "DU predicts downward move" (our short makes money)
daily["du_signal"] = daily["is_du"]   # raw: 1 when DU, 0 otherwise

# For IC, compare signal vs NEGATIVE forward return (short perspective)
# ic_raw = spearman(du_signal, -r{h}h); or just compute as spearman(is_du, fwd_ret) < 0

PERIODS = [
    ("Train 2023",   "2023-01-01", "2024-01-01"),
    ("OOS 2024-H1",  "2024-01-01", "2024-07-01"),
    ("OOS 2024-H2",  "2024-07-01", "2025-01-01"),
    ("OOS 2025-H1",  "2025-01-01", "2025-07-01"),
    ("OOS 2025-H2",  "2025-07-01", "2026-01-01"),
    ("OOS 2026-YTD", "2026-01-01", "2027-01-01"),
]
OOS = pd.Timestamp("2024-01-01", tz="UTC")


# ── Core helpers ───────────────────────────────────────────────────────────────
def build_trades_short(dly, signal_col, hold_h=24, dvol_lo=54.0, dvol_hi=9999.0,
                       cost_model=MAKER):
    """
    SHORT when signal_col > 0 and dvol_lo <= dvol < dvol_hi.
    Short PnL = -pos * (r_Xh - fund_Xh) - cost
    For a short: funding is received (not paid), so we ADD fund_col.
    """
    ret_col  = f"r{hold_h}h"
    fund_col = f"fund_{hold_h}h"
    d = dly.dropna(subset=[signal_col, ret_col, fund_col, "dvol"])
    regime_ok = (d["dvol"] >= dvol_lo) & (d["dvol"] < dvol_hi)
    sig_on    = d[signal_col] > 0
    pos_long  = np.where(regime_ok & sig_on, 1.0, 0.0)   # 1 = we want to be SHORT
    pos       = -pos_long                                   # actual position is -1

    trades, prev = [], 0.0
    for i, (idx, row) in enumerate(d.iterrows()):
        p = float(pos[i])
        cost = 0.0
        if p != prev:
            if prev != 0: cost += cost_model.one_way_cost()
            if p   != 0: cost += cost_model.one_way_cost()
        prev = p
        if p == 0:
            continue
        # Short PnL: -1 * (price_return - funding); short receives funding
        # funding_rate is cost to LONG; SHORT receives it
        gross_r = p * (row[ret_col] - row[fund_col])   # p=-1 => -(r-f) = -r+f
        net_r   = gross_r - cost
        trades.append({
            "date":     idx,
            "pos":      p,
            "dvol":     row["dvol"],
            "r24h":     row[ret_col],
            "fund":     row[fund_col],
            "gross_r":  gross_r,
            "net_r":    net_r,
            "cost":     cost,
        })
    if not trades:
        return pd.DataFrame()
    df_t = pd.DataFrame(trades).set_index("date")
    df_t["cumulative_pnl"] = df_t["net_r"].cumsum()
    return df_t


def stats(df_t):
    if df_t is None or len(df_t) == 0:
        return {"n": 0, "sharpe": None, "pnl_bp": 0, "maxdd_bp": 0, "win": None}
    r = df_t["net_r"]
    n = len(r)
    mu  = float(r.mean())
    std = float(r.std()) if n > 1 else 0.0
    sh  = round(mu / std * np.sqrt(252), 3) if std > 0 else None
    cum  = r.cumsum()
    peak = cum.cummax()
    mdd  = float((cum - peak).min())
    w    = (r > 0).mean()
    return {
        "n":       n,
        "sharpe":  sh,
        "pnl_bp":  round(float(r.sum()) * 10000, 1),
        "maxdd_bp": round(mdd * 10000, 1),
        "win":     round(float(w), 3),
    }


def block_bootstrap_p(df_t, n_boot=2000, block_size=21):
    """One-sided p-value: P(Sharpe > observed | null)."""
    if df_t is None or len(df_t) < 5:
        return 1.0
    r = df_t["net_r"].values
    n = len(r)
    if n == 0:
        return 1.0
    obs_mean = float(r.mean())
    if obs_mean <= 0:
        return 1.0
    obs_std = float(r.std())
    if obs_std == 0:
        return 0.0

    count = 0
    for _ in range(n_boot):
        starts = RNG.integers(0, n, size=max(n // block_size, 1))
        sample = np.concatenate([r[s:s + block_size] for s in starts])[:n]
        sample -= sample.mean()   # centre under null
        bm = sample.mean()
        bstd = sample.std()
        if bstd > 0 and (bm / bstd) >= (obs_mean / obs_std):
            count += 1
    p = count / n_boot
    return p if p >= 0.0005 else 0.0   # floor at reporting limit


def p_str(p):
    if p == 0.0:
        return "p<0.0005"
    return f"p={p:.3f}"


def ic_spearman(dly, hold_h=24, signal_col="du_signal"):
    """IC = Spearman(signal, -fwd_ret) so that positive IC means short edge."""
    from scipy import stats as sp_stats
    col = f"r{hold_h}h"
    d = dly.dropna(subset=[signal_col, col])
    if len(d) < 10:
        return np.nan, 1.0
    rho, pv = sp_stats.spearmanr(d[signal_col], -d[col])
    return float(rho), float(pv)


# ============================================================================
# SECTION 1 — DU Regime Descriptive Stats
# ============================================================================
print(f"\n{SEP}")
print("SECTION 1: DU Regime Descriptive Stats")
print(SEP)

regime_counts = daily["regime"].value_counts()
n_total = len(daily.dropna(subset=["regime"]))
print(f"{'Regime':<8} {'n':>6} {'%':>7}  mean_r24h(bp)  std_r24h(bp)")
for reg in ["UU", "UD", "DU", "DD"]:
    sub = daily[daily["regime"] == reg].dropna(subset=["r24h"])
    n   = len(sub)
    pct = n / n_total * 100
    mr  = float(sub["r24h"].mean()) * 10000 if n > 0 else np.nan
    sr  = float(sub["r24h"].std())  * 10000 if n > 0 else np.nan
    print(f"  {reg:<6} {n:>6}  {pct:>6.1f}%    {mr:>+8.1f}          {sr:>7.1f}")

du_sub = daily[daily["regime"] == "DU"].dropna(subset=["r24h"])
print(f"\nDU mean 24h return (long perspective): {float(du_sub['r24h'].mean())*10000:+.1f} bp")
print(f"DU mean 24h return (short perspective): {-float(du_sub['r24h'].mean())*10000:+.1f} bp")
print(f"DU n (full sample): {len(du_sub)}")


# ============================================================================
# SECTION 2 — DU Short IC Screen
# ============================================================================
print(f"\n{SEP}")
print("SECTION 2: DU Short IC Screen (full OOS 2024+)")
print(SEP)

daily_oos = daily[daily.index >= OOS].copy()
print(f"OOS observations: {len(daily_oos)}")

print(f"\n{'Hold':>6}  {'IC':>8}  {'p-raw':>8}  {'p-boot':>8}  {'DU n':>6}")
for h in [24, 48, 72]:
    ic, pv = ic_spearman(daily_oos, h, "du_signal")
    du_n   = int(daily_oos["is_du"].sum())
    # Bootstrap p for IC directly
    d = daily_oos.dropna(subset=["du_signal", f"r{h}h"])
    sigs = d["du_signal"].values
    rets = -d[f"r{h}h"].values   # negate for short perspective
    obs_ic, _ = ic_spearman(daily_oos, h, "du_signal")
    n_b = len(sigs)
    boot_count = 0
    for _ in range(2000):
        idx = RNG.integers(0, n_b, size=n_b)
        s = sigs[idx]; r = rets[idx]
        from scipy import stats as sp_stats
        rho_b, _ = sp_stats.spearmanr(s, r)
        if rho_b >= obs_ic:
            boot_count += 1
    p_boot = boot_count / 2000
    p_boot_str = "p<0.0005" if p_boot < 0.0005 else f"p={p_boot:.3f}"
    print(f"  {h:>4}h  {ic:>+8.4f}  {pv:>8.3f}  {p_boot_str:>8}  {du_n:>6}")


# ============================================================================
# SECTION 3 — DVOL Threshold x Hold Period Grid (OOS 2024+)
# ============================================================================
print(f"\n{SEP}")
print("SECTION 3: DVOL Threshold x Hold Period Grid — DU SHORT (OOS 2024+)")
print(SEP)
print(f"{'DVOL>=':>7}  {'Hold':>5}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'MaxDD(bp)':>10}  {'Win%':>6}  {'p-boot':>8}")

for dvol_lo in [54, 57, 60]:
    for h in [24, 48, 72]:
        t = build_trades_short(daily_oos, "is_du", hold_h=h, dvol_lo=dvol_lo)
        s = stats(t)
        p = block_bootstrap_p(t) if s["n"] >= 5 else 1.0
        print(f"  {dvol_lo:>5}  {h:>4}h  {s['n']:>5}  "
              f"{(s['sharpe'] or 0):>+8.3f}  {s['pnl_bp']:>+10.1f}  "
              f"{s['maxdd_bp']:>+10.1f}  {(s['win'] or 0)*100:>6.1f}  {p_str(p):>8}")
    print()


# ============================================================================
# SECTION 4 — Period Breakdown (DU short, DVOL>=54, 24h)
# ============================================================================
print(f"\n{SEP}")
print("SECTION 4: Period Breakdown — DU SHORT, DVOL>=54, 24h hold")
print(SEP)
print(f"{'Period':<16}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'MaxDD(bp)':>10}  {'Win%':>6}")

for label, ps, pe in PERIODS:
    sub = daily[
        (daily.index >= pd.Timestamp(ps, tz="UTC")) &
        (daily.index <  pd.Timestamp(pe, tz="UTC"))
    ]
    t = build_trades_short(sub, "is_du", hold_h=24, dvol_lo=54.0)
    s = stats(t)
    sh = f"{s['sharpe']:+.3f}" if s["sharpe"] is not None else "  ---"
    print(f"  {label:<14}  {s['n']:>5}  {sh:>8}  {s['pnl_bp']:>+10.1f}  "
          f"{s['maxdd_bp']:>+10.1f}  {(s['win'] or 0)*100:>6.1f}")


# ============================================================================
# SECTION 5 — Year-by-Year (DU short, DVOL>=54, 24h)
# ============================================================================
print(f"\n{SEP}")
print("SECTION 5: Year-by-Year — DU SHORT, DVOL>=54, 24h hold")
print(SEP)
print(f"{'Year':<6}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'Win%':>6}  {'p-boot':>8}")

for yr in range(2023, 2027):
    sub = daily[daily.index.year == yr]
    t = build_trades_short(sub, "is_du", hold_h=24, dvol_lo=54.0)
    s = stats(t)
    p = block_bootstrap_p(t) if s["n"] >= 5 else 1.0
    sh = f"{s['sharpe']:+.3f}" if s["sharpe"] is not None else "  ---"
    print(f"  {yr:<4}  {s['n']:>5}  {sh:>8}  {s['pnl_bp']:>+10.1f}  "
          f"{(s['win'] or 0)*100:>6.1f}  {p_str(p):>8}")


# ============================================================================
# SECTION 6 — DVOL Band Decomposition (DU short, 24h, OOS 2024+)
# ============================================================================
print(f"\n{SEP}")
print("SECTION 6: DVOL Band Decomposition — DU SHORT, 24h hold (OOS 2024+)")
print(SEP)
print(f"{'DVOL band':<14}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'Win%':>6}  {'p-boot':>8}")

bands = [(0, 51), (51, 54), (54, 57), (57, 60), (60, 9999)]
labels = ["< 51", "51-54", "54-57", "57-60", ">= 60"]
for (lo, hi), lbl in zip(bands, labels):
    t = build_trades_short(daily_oos, "is_du", hold_h=24, dvol_lo=lo, dvol_hi=hi)
    s = stats(t)
    p = block_bootstrap_p(t) if s["n"] >= 5 else 1.0
    sh = f"{s['sharpe']:+.3f}" if s["sharpe"] is not None else "  ---"
    print(f"  {lbl:<12}  {s['n']:>5}  {sh:>8}  {s['pnl_bp']:>+10.1f}  "
          f"{(s['win'] or 0)*100:>6.1f}  {p_str(p):>8}")


# ============================================================================
# SECTION 7 — Comparison: DD Long vs DU Short vs Combined
# ============================================================================
print(f"\n{SEP}")
print("SECTION 7: DD Long vs DU Short vs Combined (OOS 2024+, DVOL>=54, 24h)")
print(SEP)

# Build DD long trades for comparison
daily_oos["r24h_pos"] = daily_oos["r24h"]   # long perspective
def build_trades_long(dly, signal_col, hold_h=24, dvol_lo=54.0):
    ret_col  = f"r{hold_h}h"
    fund_col = f"fund_{hold_h}h"
    d = dly.dropna(subset=[signal_col, ret_col, fund_col, "dvol"])
    regime_ok = (d["dvol"] >= dvol_lo)
    sig_on    = d[signal_col] > 0
    pos       = np.where(regime_ok & sig_on, 1.0, 0.0)
    trades, prev = [], 0.0
    for i, (idx, row) in enumerate(d.iterrows()):
        p = float(pos[i])
        cost = 0.0
        if p != prev:
            if prev != 0: cost += MAKER.one_way_cost()
            if p   != 0: cost += MAKER.one_way_cost()
        prev = p
        if p == 0: continue
        gross_r = p * (row[ret_col] - row[fund_col])
        net_r   = gross_r - cost
        trades.append({"date": idx, "pos": p, "dvol": row["dvol"],
                        "r24h": row[ret_col], "fund": row[fund_col],
                        "gross_r": gross_r, "net_r": net_r, "cost": cost})
    if not trades: return pd.DataFrame()
    df_t = pd.DataFrame(trades).set_index("date")
    df_t["cumulative_pnl"] = df_t["net_r"].cumsum()
    return df_t

t_dd = build_trades_long(daily_oos, "is_dd", hold_h=24, dvol_lo=54.0)
t_du = build_trades_short(daily_oos, "is_du", hold_h=24, dvol_lo=54.0)

# Combined: all days where either signal fires
# Note: on days both fire, take the position as sum (long + short = flat, net 0)
# Treat as two separate signals running simultaneously
if len(t_dd) > 0 and len(t_du) > 0:
    combined_r = pd.concat([t_dd[["net_r"]], t_du[["net_r"]]]).groupby(level=0)["net_r"].sum()
    combined_df = pd.DataFrame({"net_r": combined_r})
    combined_df["cumulative_pnl"] = combined_df["net_r"].cumsum()
else:
    combined_df = pd.DataFrame()

s_dd  = stats(t_dd)
s_du  = stats(t_du)
s_comb = stats(combined_df)

p_dd   = block_bootstrap_p(t_dd)   if s_dd["n"] >= 5   else 1.0
p_du   = block_bootstrap_p(t_du)   if s_du["n"] >= 5   else 1.0
p_comb = block_bootstrap_p(combined_df) if s_comb["n"] >= 5 else 1.0

print(f"{'Strategy':<22}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'Win%':>6}  {'p-boot':>8}")
for lbl, s, p in [
    ("DD Long (P3)", s_dd, p_dd),
    ("DU Short",     s_du, p_du),
    ("DD+DU Combined", s_comb, p_comb),
]:
    sh = f"{s['sharpe']:+.3f}" if s["sharpe"] is not None else "  ---"
    print(f"  {lbl:<20}  {s['n']:>5}  {sh:>8}  {s['pnl_bp']:>+10.1f}  "
          f"{(s['win'] or 0)*100:>6.1f}  {p_str(p):>8}")

# Overlap: days both DD and DU active simultaneously
n_both = int(((daily_oos["is_dd"] > 0) & (daily_oos["is_du"] > 0)).sum())
print(f"\nDays both DD and DU active (impossible by construction): {n_both}")
print("(DD and DU are mutually exclusive — price can only go one direction)")


# ============================================================================
# SECTION 8 — Independence from N3
# ============================================================================
print(f"\n{SEP}")
print("SECTION 8: DU Short Independence from N3 (OOS 2024+, DVOL>=54, 24h)")
print(SEP)

from scipy import stats as sp_stats
du_arr = daily_oos["is_du"].fillna(0).values
n3_arr = daily_oos["n3_long"].fillna(0).values
corr, _ = sp_stats.spearmanr(du_arr, n3_arr)
print(f"Spearman correlation (is_du vs n3_long): {corr:+.4f}")

n_du_only = int(((daily_oos["is_du"] > 0) & (daily_oos["n3_long"] == 0)).sum())
n_n3_only = int(((daily_oos["n3_long"] > 0) & (daily_oos["is_du"] == 0)).sum())
n_both    = int(((daily_oos["is_du"] > 0) & (daily_oos["n3_long"] > 0)).sum())
n_du_all  = int((daily_oos["is_du"] > 0).sum())
print(f"\nDU days (OOS): {n_du_all}")
print(f"  DU only (N3 not active):  {n_du_only}  ({n_du_only/n_du_all*100:.1f}% of DU)")
print(f"  Both DU and N3 active:    {n_both}")
print(f"  N3 only (DU not active):  {n_n3_only}")

# DU excluding N3 days
daily_oos["is_du_exn3"] = ((daily_oos["is_du"] > 0) & (daily_oos["n3_long"] == 0)).astype(float)
t_du_exn3 = build_trades_short(daily_oos, "is_du_exn3", hold_h=24, dvol_lo=54.0)
s_du_exn3 = stats(t_du_exn3)
p_du_exn3 = block_bootstrap_p(t_du_exn3) if s_du_exn3["n"] >= 5 else 1.0

print(f"\n{'Subset':<28}  {'n':>5}  {'Sharpe':>8}  {'PnL(bp)':>10}  {'Win%':>6}  {'p-boot':>8}")
for lbl, s, p in [
    ("DU Short (all)",    s_du,     p_du),
    ("DU Short excl N3",  s_du_exn3, p_du_exn3),
]:
    sh = f"{s['sharpe']:+.3f}" if s["sharpe"] is not None else "  ---"
    print(f"  {lbl:<26}  {s['n']:>5}  {sh:>8}  {s['pnl_bp']:>+10.1f}  "
          f"{(s['win'] or 0)*100:>6.1f}  {p_str(p):>8}")


# ============================================================================
# SECTION 9 — Sub-period IC Stability
# ============================================================================
print(f"\n{SEP}")
print("SECTION 9: Sub-period IC Stability — DU signal (short perspective)")
print(SEP)
print(f"{'Period':<16}  {'n':>5}  {'IC_24h':>8}  {'p-raw':>8}")

for label, ps, pe in PERIODS:
    sub = daily[
        (daily.index >= pd.Timestamp(ps, tz="UTC")) &
        (daily.index <  pd.Timestamp(pe, tz="UTC"))
    ]
    sub = sub.dropna(subset=["is_du", "r24h"])
    if len(sub) < 10:
        continue
    ic, pv = ic_spearman(sub, 24, "du_signal")
    print(f"  {label:<14}  {len(sub):>5}  {ic:>+8.4f}  {pv:>8.3f}")


# ============================================================================
# SECTION 10 — Verdict
# ============================================================================
print(f"\n{SEP}")
print("SECTION 10: DU Short Verdict")
print(SEP)

t_prim = build_trades_short(daily_oos, "is_du", hold_h=24, dvol_lo=54.0)
s_prim = stats(t_prim)
p_prim = block_bootstrap_p(t_prim) if s_prim["n"] >= 5 else 1.0

print(f"\nPrimary result (OOS 2024+, DVOL>=54, 24h hold):")
print(f"  n={s_prim['n']}, Sharpe={s_prim['sharpe']}, PnL={s_prim['pnl_bp']:+.0f}bp, "
      f"Win={s_prim['win']*100:.1f}%, {p_str(p_prim)}")

print("\nKill criteria (any one is sufficient to kill):")
print(f"  Sharpe <= 0:        {'FAIL' if (s_prim['sharpe'] or 0) <= 0 else 'pass'}")
print(f"  p-boot >= 0.10:     {'FAIL' if p_prim >= 0.10 else 'pass'}")
print(f"  n < 10 trades:      {'FAIL' if s_prim['n'] < 10 else 'pass'}")

if (s_prim["sharpe"] or 0) > 0 and p_prim < 0.10 and s_prim["n"] >= 10:
    print("\nVerdict: SURVIVOR — proceed to position-level deep dive")
    print("  Next step: period-by-period Sharpe breakdown and independence from N3")
else:
    print("\nVerdict: KILLED at IC/backtest screen")
    print("  DU short does not show consistent edge with the tested parameters.")
    print("  The continuation hypothesis is not supported in this dataset.")

print(f"\n{SEP}")
print("Done.")
