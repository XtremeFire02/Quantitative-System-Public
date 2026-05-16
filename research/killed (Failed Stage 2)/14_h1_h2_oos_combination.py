"""H1 + H2 OOS Combination Study.

Questions:
  1. Does H2 (funding carry) have independent OOS alpha in 2024?
  2. Does the H1+H2 combo outperform H1 alone OOS?
  3. Does H2 compensate when H1 collapses in 2024-H1 (BTC bull rally)?
  4. What combination weight maximises OOS IC?
  5. Walk-forward stability of the combo on OOS data.
  6. Does the 8h horizon show better combo performance?

Data: ofi.parquet (2023-2024), settlement bars only.
Train: 2023 (1,095 bars)   OOS: 2024 (Val=H1, Test=H2)
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

settle_df = df[df.index.isin(fund.index)].copy()
print(f"Settlement bars : {len(settle_df):,}  "
      f"({settle_df.index[0].date()} to {settle_df.index[-1].date()})")

# ─── Cost model ──────────────────────────────────────────────────────────────
MKR = TAKER.__class__(use_maker=True).round_trip_cost()

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def bk(sigma):
    return MKR / (sigma * np.sqrt(2 / np.pi))

# ─── Signal normalisation (training stats only → no lookahead) ────────────────
s_train = settle_df[settle_df.index < TRAIN_END].copy()
s_val   = settle_df[(settle_df.index >= TRAIN_END) & (settle_df.index < VAL_END)].copy()
s_test  = settle_df[settle_df.index >= VAL_END].copy()
s_oos   = settle_df[settle_df.index >= TRAIN_END].copy()

h1_col, h2_col = "basis", "funding_pct_rank"

# Diagnostics: check NaN coverage before any normalisation
print(f"\nNaN check on settlement bars:")
for period, sub in [("Train 2023", s_train), ("Val 2024-H1", s_val), ("Test 2024-H2", s_test)]:
    n_total = len(sub)
    n_h1 = sub[h1_col].notna().sum()
    n_h2 = sub[h2_col].notna().sum() if h2_col in sub.columns else 0
    n_r1 = sub["ret_1h"].notna().sum() if "ret_1h" in sub.columns else 0
    print(f"  {period:<18}  total={n_total:4d}  {h1_col}={n_h1:4d}  "
          f"{h2_col}={n_h2:4d}  ret_1h={n_r1:4d}")

h1_mu, h1_sd = s_train[h1_col].mean(), s_train[h1_col].std()
h2_mu, h2_sd = s_train[h2_col].mean(), s_train[h2_col].std()

for s in (s_train, s_val, s_test, s_oos):
    s["h1_z"] = (s[h1_col] - h1_mu) / h1_sd
    s["h2_z"] = (s[h2_col] - h2_mu) / h2_sd
    s["combo"] = s["h1_z"] + s["h2_z"]

# ─── 1. Training baseline ─────────────────────────────────────────────────────
print("\n=== 1. TRAINING BASELINE (2023, n=1095) ===")
print(f"  {'Signal':<12}  {'IC(1h)':>8}  {'Ratio(maker)':>12}  {'IC(8h)':>8}  {'Ratio 8h':>10}")
print("  " + "-" * 57)
for label, sig in [("H1 (basis)", "h1_z"), ("H2 (fund)", "h2_z"), ("H1+H2", "combo")]:
    sub = s_train.dropna(subset=[sig, "ret_1h", "ret_8h"])
    ic1 = ic(sub[sig].values, sub["ret_1h"].values)
    ic8 = ic(sub[sig].values, sub["ret_8h"].values)
    b1  = bk(sub["ret_1h"].std())
    b8  = bk(sub["ret_8h"].std())
    print(f"  {label:<12}  {ic1:>+8.4f}  {abs(ic1)/b1:>11.3f}x  "
          f"{ic8:>+8.4f}  {abs(ic8)/b8:>9.3f}x")

rho = float(sp_stats.spearmanr(
    s_train.dropna(subset=["h1_z","h2_z"])["h1_z"],
    s_train.dropna(subset=["h1_z","h2_z"])["h2_z"]
).statistic)
print(f"\n  rho(H1, H2) in training : {rho:+.4f}")
ic_theory = (abs(ic(s_train["h1_z"].values, s_train["ret_1h"].values)) +
             abs(ic(s_train["h2_z"].values, s_train["ret_1h"].values))) / np.sqrt(2 + 2*abs(rho))
bk_1h = bk(s_train["ret_1h"].std())
print(f"  Theoretical IC combo    : {ic_theory:.4f}  ({ic_theory/bk_1h:.3f}x maker)")

# ─── 2. OOS performance by period ────────────────────────────────────────────
print("\n=== 2. OOS PERFORMANCE BY PERIOD ===")
print(f"  {'Period':<18}  {'n':>4}  {'IC H1':>7}  {'IC H2':>7}  "
      f"{'IC Combo':>9}  {'Ratio H1':>9}  {'Ratio Combo':>12}")
print("  " + "-" * 75)
for label, sub in [("Train 2023",    s_train),
                   ("Val   2024-H1", s_val),
                   ("Test  2024-H2", s_test),
                   ("OOS   2024",    s_oos)]:
    sub = sub.dropna(subset=["h1_z", "h2_z", "ret_1h"])
    if len(sub) < 20:
        continue
    ic1  = ic(sub["h1_z"].values,  sub["ret_1h"].values)
    ic2  = ic(sub["h2_z"].values,  sub["ret_1h"].values)
    ic_c = ic(sub["combo"].values, sub["ret_1h"].values)
    bk_v = bk(sub["ret_1h"].std())
    print(f"  {label:<18}  {len(sub):>4}  {ic1:>+7.4f}  {ic2:>+7.4f}  "
          f"{ic_c:>+9.4f}  {abs(ic1)/bk_v:>8.3f}x  {abs(ic_c)/bk_v:>11.3f}x")

# ─── 3. 8h horizon breakdown ─────────────────────────────────────────────────
print("\n=== 3. 8H HORIZON BREAKDOWN ===")
print(f"  {'Period':<18}  {'n':>4}  {'IC H1':>7}  {'IC H2':>7}  "
      f"{'IC Combo':>9}  {'Ratio H1':>9}  {'Ratio Combo':>12}")
print("  " + "-" * 75)
for label, sub in [("Train 2023",    s_train),
                   ("Val   2024-H1", s_val),
                   ("Test  2024-H2", s_test),
                   ("OOS   2024",    s_oos)]:
    sub = sub.dropna(subset=["h1_z", "h2_z", "ret_8h"])
    if len(sub) < 20:
        continue
    ic1  = ic(sub["h1_z"].values,  sub["ret_8h"].values)
    ic2  = ic(sub["h2_z"].values,  sub["ret_8h"].values)
    ic_c = ic(sub["combo"].values, sub["ret_8h"].values)
    bk_v = bk(sub["ret_8h"].std())
    print(f"  {label:<18}  {len(sub):>4}  {ic1:>+7.4f}  {ic2:>+7.4f}  "
          f"{ic_c:>+9.4f}  {abs(ic1)/bk_v:>8.3f}x  {abs(ic_c)/bk_v:>11.3f}x")

# ─── 4. Signal correlation stability ─────────────────────────────────────────
print("\n=== 4. SIGNAL CORRELATION STABILITY ===")
for label, sub in [("Train 2023",    s_train),
                   ("Val   2024-H1", s_val),
                   ("Test  2024-H2", s_test)]:
    sub = sub.dropna(subset=["h1_z", "h2_z"])
    if len(sub) < 20:
        continue
    r = float(sp_stats.spearmanr(sub["h1_z"], sub["h2_z"]).statistic)
    print(f"  {label:<18}  n={len(sub):4d}  rho(H1, H2) = {r:+.4f}")

# ─── 5. Combination weight sensitivity (OOS 2024) ────────────────────────────
print("\n=== 5. WEIGHT SENSITIVITY (OOS 2024, 1h horizon) ===")
print("  w=1.0: H1 only   w=0.5: equal weight   w=0.0: H2 only")
print(f"  {'w_H1':>5}  {'IC':>8}  {'Ratio(maker)':>12}")
print("  " + "-" * 30)
sub_oos = s_oos.dropna(subset=["h1_z", "h2_z", "ret_1h"])
bk_oos  = bk(sub_oos["ret_1h"].std())
best_w, best_ic = 0.5, -np.inf
for w in np.arange(0.0, 1.01, 0.1):
    combo_w = w * sub_oos["h1_z"] + (1 - w) * sub_oos["h2_z"]
    ic_v    = ic(combo_w.values, sub_oos["ret_1h"].values)
    if ic_v is not None and abs(ic_v) > best_ic:
        best_ic, best_w = abs(ic_v), w
        flag = "  <-- best"
    else:
        flag = ""
    print(f"  {w:.1f}    {ic_v:>+8.4f}  {abs(ic_v)/bk_oos:>11.3f}x{flag}")
print(f"\n  Best OOS weight: w_H1 = {best_w:.1f}")

# ─── 6. H2 compensation test (2024-H1 when H1 collapses) ─────────────────────
print("\n=== 6. H2 COMPENSATION IN 2024-H1 (when H1 reverses) ===")
sub_v = s_val.dropna(subset=["h1_z", "h2_z", "ret_1h"])
bk_v  = bk(sub_v["ret_1h"].std())
ic1   = ic(sub_v["h1_z"].values,  sub_v["ret_1h"].values)
ic2   = ic(sub_v["h2_z"].values,  sub_v["ret_1h"].values)
ic_c  = ic(sub_v["combo"].values, sub_v["ret_1h"].values)
print(f"  n = {len(sub_v)}")
print(f"  H1        : IC={ic1:+.4f}  ({abs(ic1)/bk_v:.3f}x maker)  [collapses in bull market]")
print(f"  H2        : IC={ic2:+.4f}  ({abs(ic2)/bk_v:.3f}x maker)")
print(f"  H1+H2     : IC={ic_c:+.4f}  ({abs(ic_c)/bk_v:.3f}x maker)")

aligned = (np.sign(sub_v["h1_z"]) == np.sign(sub_v["h2_z"])).mean() * 100
print(f"  Signals agree direction: {aligned:.1f}%  (if <50%, H2 partially offsets H1)")

# Condition on |H2| > 75th pctile
q75 = sub_v["h2_z"].abs().quantile(0.75)
strong = sub_v[sub_v["h2_z"].abs() > q75]
if len(strong) >= 15:
    ic_s  = ic(strong["combo"].values, strong["ret_1h"].values)
    bk_s  = bk(strong["ret_1h"].std())
    print(f"  Combo on |H2|>75th pctile (n={len(strong)}): IC={ic_s:+.4f} ({abs(ic_s)/bk_s:.3f}x)")

# ─── 7. Walk-forward OOS (90-day windows, 30-day step) ───────────────────────
print("\n=== 7. WALK-FORWARD OOS (90-day windows, 30-day step) ===")
WINDOW_S = 90 * 3
STEP_S   = 30 * 3

for sig_label, sig_col in [("H1",    "h1_z"),
                            ("H2",    "h2_z"),
                            ("H1+H2", "combo")]:
    vals = s_oos.dropna(subset=[sig_col, "ret_1h"])
    ics_wf, dates_wf = [], []
    for i in range(0, len(vals) - WINDOW_S, STEP_S):
        w = vals.iloc[i: i + WINDOW_S]
        ics_wf.append(ic(w[sig_col].values, w["ret_1h"].values))
        dates_wf.append(w.index[0].date())
    ics_wf = np.array([v for v in ics_wf if np.isfinite(v)])
    if len(ics_wf) == 0:
        print(f"  {sig_label}: no windows")
        continue
    frac_neg = (ics_wf < 0).mean() * 100
    print(f"  {sig_label:<8}  n={len(ics_wf):2d} windows  "
          f"mean={ics_wf.mean():+.4f}  std={ics_wf.std():.4f}  "
          f"frac_neg={frac_neg:.0f}%")
    for v, d in zip(ics_wf, dates_wf):
        print(f"    {d}:  IC={v:+.4f}")
    print()

print("Done.")
