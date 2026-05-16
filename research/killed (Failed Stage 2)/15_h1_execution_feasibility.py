"""H1 Execution Feasibility Study.

Central question: can H1 be traded profitably with maker orders?
IC is a necessary condition.  This script tests the sufficient conditions:
  1. Can we enter before the signal is gone (timing)?
  2. Is the spread wide enough to queue a limit order (liquidity)?
  3. Are maker fills adversely selected (fills arrive when we're wrong)?
  4. Does selective entry (|basis| threshold) recover a viable OOS IC?
  5. Which settlement hours (00:00 / 08:00 / 16:00 UTC) carry the edge?
  6. Realistic combined scenario: timing + threshold + fill-rate haircut.

All sections use OOS data (2024) to avoid in-sample optimisation.
"""
import sys, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import TRAIN_END, VAL_END
from framework.costs import TAKER

# ─── Data ────────────────────────────────────────────────────────────────────
df   = pd.read_parquet("data/processed/ofi.parquet")
fund = pd.read_parquet("data/raw/BTCUSDT_funding.parquet")
fund.index = fund.index.floor("min")
fund = fund[~fund.index.duplicated(keep="first")].sort_index()

settle_df  = df[df.index.isin(fund.index)].copy()
oos_settle = settle_df[settle_df.index >= TRAIN_END].dropna(subset=["basis"])
oos_times  = oos_settle.index

print(f"OOS settlement bars (basis non-NaN): {len(oos_settle):,}  "
      f"({oos_settle.index[0].date()} to {oos_settle.index[-1].date()})")

# ─── Helpers ─────────────────────────────────────────────────────────────────
MKR    = TAKER.__class__(use_maker=True).round_trip_cost()
hl_col = (df["high"] - df["low"]) / df["close"]

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def bk(sigma):
    return MKR / (sigma * np.sqrt(2 / np.pi))

def ret_between(t_a, t_b):
    if t_a not in df.index or t_b not in df.index:
        return np.nan
    return float(np.log(df.loc[t_b, "close"] / df.loc[t_a, "close"]))

# ─── 1. Pre-settlement entry timing (OOS) ────────────────────────────────────
print("\n=== 1. PRE-SETTLEMENT ENTRY TIMING (OOS 2024) ===")
print("Signal: basis_t, entry at t-k, exit at t+60min\n")
print(f"  {'k':>6}  {'n':>5}  {'IC':>8}  {'Ratio(mkr)':>11}  {'HL_entry%':>10}")
print("  " + "-" * 50)

basis_oos = oos_settle["basis"].values

for k in [0, 1, 2, 3, 5, 8, 10, 15, 20, 30]:
    rets, hls = [], []
    for t in oos_times:
        t_en = t - pd.Timedelta(minutes=k)
        t_ex = t + pd.Timedelta(minutes=60)
        rets.append(ret_between(t_en, t_ex))
        hls.append(float(hl_col.loc[t_en]) if t_en in df.index else np.nan)
    rets = np.array(rets)
    hls  = np.array(hls)
    m    = np.isfinite(basis_oos) & np.isfinite(rets)
    ic_v = ic(basis_oos[m], rets[m])
    bk_v = bk(np.nanstd(rets[m]))
    hl_m = np.nanmean(hls) * 100
    print(f"  t-{k:>3}m  {m.sum():>5}  {ic_v:>+8.4f}  "
          f"{abs(ic_v)/bk_v:>10.3f}x  {hl_m:>9.5f}%")

# ─── 2. Spread proxy around settlement ───────────────────────────────────────
print("\n=== 2. SPREAD PROXY (HL range) AROUND SETTLEMENT ===")
print(f"Maker RT cost = {MKR*100:.3f}%.  Fill plausible when HL > maker RT.\n")
print(f"  {'offset':>7}  {'mean_HL%':>10}  {'pct_HL>MakerRT':>16}  {'n':>5}")
print("  " + "-" * 45)

for off in [-30, -20, -15, -10, -5, -3, -2, -1, 0, 1, 2, 5]:
    bars = []
    for t in oos_times[:600]:
        t_k = t + pd.Timedelta(minutes=off)
        if t_k in df.index:
            bars.append(float(hl_col.loc[t_k]))
    if not bars:
        continue
    bars = np.array(bars)
    pct  = (bars > MKR).mean() * 100
    print(f"  t{off:>+4}min  {np.mean(bars)*100:>10.5f}%  "
          f"{pct:>15.1f}%  {len(bars):>5}")

# ─── 3. Adverse-selection proxy ──────────────────────────────────────────────
print("\n=== 3. ADVERSE-SELECTION PROXY (OOS) ===")
print("Maker short at t-k when basis>0 (predict DOWN).")
print("Fill occurs if price RISES before settlement  -> fills on wrong-direction bars.\n")
print(f"  {'k':>5}  {'n':>5}  {'pre_move_vs_signal%':>22}  {'adverse_fill%':>15}")
print("  " + "-" * 55)
# adverse_fill_pct = fraction of bars where pre-settlement move is AGAINST signal
# (i.e. fill arrived but signal says we shouldn't want it)

for k in [1, 2, 3, 5, 8, 10, 15]:
    same, adv, total = 0, 0, 0
    for i, t in enumerate(oos_times):
        t_en = t - pd.Timedelta(minutes=k)
        if t_en not in df.index:
            continue
        bv = float(basis_oos[i]) if np.isfinite(basis_oos[i]) else np.nan
        if not np.isfinite(bv):
            continue
        r_pre = ret_between(t_en, t)
        if not np.isfinite(r_pre):
            continue
        # signal direction: basis>0 → short → expect r<0
        signal_dir = -np.sign(bv)          # +1 means expect price up (we're long)
        move_dir   = np.sign(r_pre)        # actual pre-settle move
        total += 1
        if signal_dir == move_dir:
            same += 1   # pre-move is WITH signal = maker NOT filled (price ran away)
        else:
            adv  += 1   # pre-move is AGAINST signal = maker probably filled (adverse)
    if total < 10:
        continue
    print(f"  t-{k:>2}m  {total:>5}  {same/total*100:>21.1f}%  {adv/total*100:>14.1f}%")

print("\n  pre_move_vs_signal%: price ran WITH signal before settle (unfilled maker).")
print("  adverse_fill%: price ran AGAINST signal (maker fills, then settles wrong way).")
print("  Ideal: adverse_fill% < 50%  (fills arrive when we're ultimately right).")

# ─── 4. Selective entry by |basis| threshold (OOS) ───────────────────────────
print("\n=== 4. SELECTIVE ENTRY BY |BASIS| THRESHOLD (OOS 2024) ===")
print(f"  {'pctile':>7}  {'n':>5}  {'IC':>8}  {'Ratio(mkr)':>11}  {'approx_n/yr':>12}")
print("  " + "-" * 50)

# Use at-settlement entry (k=0) for this test
rets_t0 = np.array([ret_between(t, t + pd.Timedelta(minutes=60)) for t in oos_times])
b_fin   = basis_oos
fin_m   = np.isfinite(b_fin) & np.isfinite(rets_t0)
b_f     = b_fin[fin_m]
r_f     = rets_t0[fin_m]
n_years = len(oos_times) / (365 * 3)   # approximate years covered

for pctile in [0, 20, 40, 50, 60, 70, 80, 90]:
    thresh = np.nanpercentile(np.abs(b_f), pctile)
    mask   = np.abs(b_f) > thresh
    if mask.sum() < 15:
        continue
    ic_v = ic(b_f[mask], r_f[mask])
    bk_v = bk(np.nanstd(r_f[mask]))
    n_yr = int(mask.sum() / n_years)
    print(f"  >{pctile:>3}th   {mask.sum():>5}  {ic_v:>+8.4f}  "
          f"{abs(ic_v)/bk_v:>10.3f}x  {n_yr:>12}")

# ─── 5. Settlement hour breakdown (OOS) ──────────────────────────────────────
print("\n=== 5. SETTLEMENT HOUR BREAKDOWN (OOS 2024) ===")
print(f"  {'Hour UTC':>9}  {'n':>5}  {'IC(1h)':>8}  {'Ratio':>7}  {'mean_HL%':>10}")
print("  " + "-" * 48)

for hour in [0, 8, 16]:
    mask_h = oos_settle.index.hour == hour
    sub    = oos_settle[mask_h]
    if len(sub) < 20:
        continue
    bv  = sub["basis"].values
    rets_h = np.array([ret_between(t, t + pd.Timedelta(minutes=60)) for t in sub.index])
    hl_h   = np.array([float(hl_col.loc[t]) if t in df.index else np.nan for t in sub.index])
    ic_v   = ic(bv, rets_h)
    bk_v   = bk(np.nanstd(rets_h))
    hl_m   = np.nanmean(hl_h) * 100
    print(f"  {hour:>6}:00    {len(sub):>5}  {ic_v:>+8.4f}  "
          f"{abs(ic_v)/bk_v:>6.3f}x  {hl_m:>9.5f}%")

# ─── 6. Combined scenario ────────────────────────────────────────────────────
print("\n=== 6. COMBINED SCENARIO (OOS 2024) ===")
print("Best timing: k=5min entry, |basis|>50th pctile, all settlement hours\n")

thresh_50 = np.nanpercentile(np.abs(b_f), 50)
sel_mask  = np.abs(b_f) > thresh_50
sel_times = np.array(oos_times)[fin_m][sel_mask]
b_sel     = b_f[sel_mask]

rets_k5 = np.array([ret_between(t - pd.Timedelta(minutes=5),
                                 t + pd.Timedelta(minutes=60))
                    for t in sel_times])

m5 = np.isfinite(b_sel) & np.isfinite(rets_k5)
ic_s  = ic(b_sel[m5], rets_k5[m5])
sig_s = np.nanstd(rets_k5[m5])
bk_s  = bk(sig_s)
ratio = abs(ic_s) / bk_s if ic_s is not None else np.nan
n_yr  = int(m5.sum() / n_years)

print(f"  n trades (OOS sample)  : {m5.sum()}")
print(f"  approx n per year      : {n_yr}")
print(f"  IC (k=5, |b|>50th)     : {ic_s:+.4f}")
print(f"  sigma_r                : {sig_s*100:.4f}%")
print(f"  Ratio to maker BK      : {ratio:.3f}x")
print()

for fill_rate in [1.0, 0.75, 0.50]:
    eff_ratio = ratio  # per-trade edge unchanged by fill rate
    eff_n     = int(n_yr * fill_rate)
    print(f"  Fill rate {fill_rate*100:.0f}%:  "
          f"~{eff_n} trades/yr  ratio={eff_ratio:.3f}x maker  "
          f"{'ABOVE BK' if eff_ratio > 1.0 else 'below BK'}")

print()
print("  Note: fill rate reduces annual capacity but not per-trade IC.")
print("  Adverse selection (section 3) is the real risk: if fills arrive")
print("  only on losing bars, the realised IC will be lower than measured.")
print()
print("Done.")
