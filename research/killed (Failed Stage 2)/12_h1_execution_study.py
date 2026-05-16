"""H1 Execution Feasibility Study.

Questions:
  1. Entry timing  — does the return reversal happen before, at, or after settlement?
  2. Signal conditioning — is the edge concentrated in extreme basis / funding periods?
  3. Regime survival — does the signal hold in 2024 OOS?
  4. H1 + H2 combination — what is the empirical IC correlation?

All tests use settlement-bar observations (funding timestamps) from ofi.parquet.
"""
import sys, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import TRAIN_END, VAL_END
from framework.costs import TAKER

# ─── Data ────────────────────────────────────────────────────────────────────
df   = pd.read_parquet("data/processed/ofi.parquet")
fund = pd.read_parquet("data/raw/BTCUSDT_funding.parquet")
fund.index = fund.index.floor("min")
fund = fund[~fund.index.duplicated(keep="first")].sort_index()

# Settlement mask: rows where a funding event occurred
settle_mask = df.index.isin(fund.index)
settle_df   = df[settle_mask].copy()

# Mark the settlement rows in the full 1m df for timing analysis
df["at_settlement"] = settle_mask

# ─── Cost model ──────────────────────────────────────────────────────────────
RT    = TAKER.round_trip_cost()
MKR   = TAKER.__class__(use_maker=True).round_trip_cost()

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def bk(sigma, rt=MKR):
    return rt / (sigma * np.sqrt(2 / np.pi))

# ─── 1. ENTRY TIMING: return profile around settlement ───────────────────────
# For each settlement bar t, compute cumulative return from t-k to t+k for
# k = 1, 5, 10, 15, 30, 60, 120 minutes.
# Then correlate basis_t (at settlement) with each of those returns.
print("=== Q1: RETURN PROFILE AROUND SETTLEMENT ===")
print("basis(t) vs cumulative return from t+a to t+b minutes\n")

# Compute signal: basis = (close - mark_price)/mark_price at settlement
settle_times = settle_df.index

# Build minute-indexed returns relative to settlement bar
horizons = [(-60,-1), (-30,-1), (-15,-1), (-5,-1),
            (0, 0), (1, 5), (1, 10), (1, 15), (1, 30), (1, 60), (1, 120)]

basis_signal = settle_df["basis"].values  # signal at settlement

results = []
for (a, b) in horizons:
    rets = []
    for t in settle_times:
        # Return from t+a minutes to t+b minutes
        t_a = t + pd.Timedelta(minutes=a)
        t_b = t + pd.Timedelta(minutes=b)
        if t_a not in df.index or t_b not in df.index:
            rets.append(np.nan)
            continue
        r = np.log(df.loc[t_b, "close"] / df.loc[t_a, "close"])
        rets.append(r)
    rets = np.array(rets)
    ic_v  = ic(basis_signal, rets)
    # Only use train period
    train_mask = settle_times < TRAIN_END
    ic_tr = ic(basis_signal[train_mask], rets[train_mask])
    results.append((a, b, ic_v, ic_tr))
    window = f"({a:+d},{b:+d})" if a != b else f"({a:+d})"
    print(f"  Window {window:>12} : IC(all)={ic_v:+.5f}   IC(train)={ic_tr:+.5f}")

print()

# ─── 2. PRE-SETTLEMENT WINDOW: restrict entry to t-5 to t-15 before settle ──
print("=== Q2: PRE-SETTLEMENT ENTRY (enter at t-k, exit at t+1h) ===")
print("Signal: basis at settlement bar t, entry at t-k, hold 1h\n")

s_train = settle_df[settle_df.index < TRAIN_END]
s_oos   = settle_df[settle_df.index >= TRAIN_END]

for k in [5, 10, 15, 30]:
    rets = []
    for t in s_train.index:
        t_entry = t - pd.Timedelta(minutes=k)
        t_exit  = t + pd.Timedelta(minutes=60)
        if t_entry not in df.index or t_exit not in df.index:
            rets.append(np.nan)
            continue
        r = np.log(df.loc[t_exit, "close"] / df.loc[t_entry, "close"])
        rets.append(r)
    rets = np.array(rets)
    sig  = s_train["basis"].values
    ic_v = ic(sig, rets)
    sigma = np.nanstd(rets)
    bk_v  = bk(sigma, MKR)
    print(f"  Entry at t-{k:>2}min:  IC={ic_v:+.5f}   sigma={sigma*100:.4f}%"
          f"   IC_break_maker={bk_v:.4f}   ratio={abs(ic_v)/bk_v:.3f}x")

print()

# ─── 3. REGIME CONDITIONING ──────────────────────────────────────────────────
print("=== Q3: REGIME CONDITIONING (train only) ===")

# Condition on extremes of basis and funding
basis_vals  = s_train["basis"].values
fund_vals   = s_train["funding_rate"].values
fund_abs    = np.abs(fund_vals)
fund_z      = s_train["funding_zscore"].values
ret_1h      = s_train["ret_1h"].values

# Quantile thresholds on |basis| and |funding|
for label, mask_fn in [
    ("All settlement bars",     lambda: np.ones(len(s_train), dtype=bool)),
    ("|basis| > 50th pctile",   lambda: np.abs(basis_vals) > np.nanpercentile(np.abs(basis_vals), 50)),
    ("|basis| > 75th pctile",   lambda: np.abs(basis_vals) > np.nanpercentile(np.abs(basis_vals), 75)),
    ("|basis| > 90th pctile",   lambda: np.abs(basis_vals) > np.nanpercentile(np.abs(basis_vals), 90)),
    ("|fund| > 50th pctile",    lambda: fund_abs > np.nanpercentile(fund_abs, 50)),
    ("|fund| > 75th pctile",    lambda: fund_abs > np.nanpercentile(fund_abs, 75)),
    ("|fund_z| > 1",            lambda: np.abs(fund_z) > 1),
    ("basis and fund same dir", lambda: np.sign(basis_vals) == np.sign(fund_vals)),
]:
    m = mask_fn()
    n = m.sum()
    if n < 30:
        print(f"  {label:<30} n={n:4d}  (too few)")
        continue
    ic_v  = ic(basis_vals[m], ret_1h[m])
    sigma = np.nanstd(ret_1h[m])
    bk_v  = bk(sigma, MKR)
    print(f"  {label:<30} n={n:4d}  IC={ic_v:+.5f}   ratio={abs(ic_v)/bk_v:.3f}x maker")

print()

# ─── 4. OOS SURVIVAL BY YEAR ─────────────────────────────────────────────────
print("=== Q4: OOS SURVIVAL BY PERIOD ===")

for label, start, end in [
    ("Train  2023",       "2023-01-01", "2024-01-01"),
    ("Val    2024-H1",    "2024-01-01", "2024-07-01"),
    ("Test   2024-H2",    "2024-07-01", "2025-01-01"),
]:
    mask = (settle_df.index >= pd.Timestamp(start, tz="UTC")) & \
           (settle_df.index <  pd.Timestamp(end,   tz="UTC"))
    sub  = settle_df[mask]
    if len(sub) < 20:
        print(f"  {label}: too few obs")
        continue
    ic_v = ic(sub["basis"].values, sub["ret_1h"].values)
    sigma = sub["ret_1h"].std()
    bk_v  = bk(sigma, MKR)
    print(f"  {label}: n={len(sub):4d}  IC={ic_v:+.6f}  ratio={abs(ic_v)/bk_v:.3f}x maker")

print()

# ─── 4b. REGIME CONDITIONING IN OOS ─────────────────────────────────────────
print("=== Q4b: REGIME CONDITIONING — OOS (2024) ===")

for label, pctile in [("All bars", None), (">50th pctile", 50), (">75th pctile", 75)]:
    for period_label, start, end in [
        ("Val 2024-H1", "2024-01-01", "2024-07-01"),
        ("Test 2024-H2", "2024-07-01", "2025-01-01"),
    ]:
        mask = (settle_df.index >= pd.Timestamp(start, tz="UTC")) & \
               (settle_df.index <  pd.Timestamp(end,   tz="UTC"))
        sub = settle_df[mask]
        bvals = sub["basis"].values
        r1h   = sub["ret_1h"].values
        if pctile is not None:
            threshold = np.nanpercentile(np.abs(bvals), pctile)
            cond = np.abs(bvals) > threshold
        else:
            cond = np.ones(len(sub), dtype=bool)
        n = cond.sum()
        if n < 15:
            print(f"  {label:<20} {period_label}: n={n:3d} (too few)")
            continue
        ic_v  = ic(bvals[cond], r1h[cond])
        sigma = np.nanstd(r1h[cond])
        bk_v  = bk(sigma, MKR)
        print(f"  {label:<20} {period_label}: n={n:3d}  IC={ic_v:+.5f}  ratio={abs(ic_v)/bk_v:.3f}x maker")
    print()

# ─── 5. H1 + H2 COMBINATION ──────────────────────────────────────────────────
print("=== Q5: H1 + H2 COMBINATION ===")

# H2 signal: funding_pct_rank (already in ofi)
h1 = s_train["basis"].values
h2 = s_train["funding_pct_rank"].values
r  = s_train["ret_1h"].values

ic_h1 = ic(h1, r)
ic_h2 = ic(h2, r)

# Normalise both to z-score, then add
valid = np.isfinite(h1) & np.isfinite(h2) & np.isfinite(r)
h1_z  = (h1 - np.nanmean(h1)) / np.nanstd(h1)
h2_z  = (h2 - np.nanmean(h2)) / np.nanstd(h2)
combo = h1_z + h2_z

ic_combo = ic(combo[valid], r[valid])
rho_signals = float(sp_stats.spearmanr(h1[valid], h2[valid]).statistic)

sigma_1h = s_train["ret_1h"].std()
bk_v = bk(sigma_1h, MKR)

print(f"  IC(H1, ret_1h)     = {ic_h1:+.5f}  ({abs(ic_h1)/bk_v:.3f}x maker)")
print(f"  IC(H2, ret_1h)     = {ic_h2:+.5f}  ({abs(ic_h2)/bk_v:.3f}x maker)")
print(f"  Spearman(H1, H2)   = {rho_signals:+.4f}  (signal correlation)")
print(f"  IC(H1+H2, ret_1h)  = {ic_combo:+.5f}  ({abs(ic_combo)/bk_v:.3f}x maker)")
print()

# Theoretical naive combination (if correlation = rho)
rho = rho_signals
# Combined IC prediction under linear IC model:
# IC_combo = (IC_h1 + IC_h2) / sqrt(2 + 2*rho)  (equal weight, unit variance)
ic_theory = (abs(ic_h1) + abs(ic_h2)) / np.sqrt(2 + 2 * abs(rho))
print(f"  Theoretical combined IC (equal weight): {ic_theory:.5f}")
print(f"  Theoretical ratio to maker BK:          {ic_theory/bk_v:.3f}x")

print()

# ─── 6. PRE-SETTLEMENT SPREAD PROXY ──────────────────────────────────────────
print("=== Q6: SPREAD PROXY AROUND SETTLEMENT (high-low range as spread proxy) ===")
print("Note: ofi.parquet has OHLCV but not bid/ask.  Using (high-low)/close as")
print("a spread proxy at 1m granularity.\n")

spread_col = (df["high"] - df["low"]) / df["close"]

# Compare spread in windows before/after vs. average
for offset_min in [-30, -15, -5, -1, 0, 1, 5, 15, 30]:
    bars = []
    for t in settle_times[:500]:  # first 500 settlements for speed
        t_k = t + pd.Timedelta(minutes=offset_min)
        if t_k in df.index:
            bars.append(float(spread_col.loc[t_k]))
    if bars:
        print(f"  t{offset_min:+3d}min:  mean_hl_range = {np.mean(bars)*100:.5f}%"
              f"   n={len(bars)}")

print()
print("Done.")
