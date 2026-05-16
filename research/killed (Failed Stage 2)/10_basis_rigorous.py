"""Rigorous test of basis signal at settlement bars."""
import sys, warnings
import numpy as np, pandas as pd
from scipy import stats as sp_stats
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import TRAIN_END, VAL_END
from framework.costs import TAKER

df   = pd.read_parquet("data/processed/ofi.parquet")
fund = pd.read_parquet("data/raw/BTCUSDT_funding.parquet")
fund.index = fund.index.floor("min")
fund = fund[~fund.index.duplicated(keep="first")].sort_index()
fund = fund.rename(columns={"fundingRate": "funding_rate"})

df["basis_z"] = (
    (df["basis"] - df["basis"].rolling(480).mean())
    / df["basis"].rolling(480).std()
)

settle_mask = df.index.isin(fund.index)
settle_df   = df[settle_mask].copy()
s_train = settle_df[settle_df.index < TRAIN_END]
s_oos   = settle_df[settle_df.index >= TRAIN_END]

RT       = TAKER.round_trip_cost()
MAKER_RT = TAKER.__class__(use_maker=True).round_trip_cost()


def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)


def perm_test(x, y, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    obs = float(sp_stats.spearmanr(x, y).statistic)
    null = np.array([
        float(sp_stats.spearmanr(rng.permutation(x), y).statistic)
        for _ in range(n)
    ])
    return obs, (np.abs(null) >= np.abs(obs)).mean(), null


def block_boot(x, y, block=3, B=1000, seed=0):
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    obs = float(sp_stats.spearmanr(x, y).statistic)
    starts = np.arange(0, n - block + 1)
    boots = []
    for _ in range(B):
        idx = np.concatenate([
            np.arange(s, min(s + block, n))
            for s in rng.choice(starts, n // block + 1)
        ])[:n]
        boots.append(float(sp_stats.spearmanr(x[idx], y[idx]).statistic))
    boots = np.array(boots)
    # Shift to null before testing: boots centred near obs, not near 0,
    # so the old |boots|>=|obs| formula gives p≈0.5 regardless of CI.
    pval = (np.abs(boots - obs) >= np.abs(obs)).mean()
    return obs, pval, boots


print("=== RIGOROUS BASIS SIGNAL TEST (settlement bars) ===")
print(f"Train n={len(s_train)},  OOS n={len(s_oos)}")
print()

print("--- Permutation tests (N=2000) ---")
for sig_col, label in [("basis", "basis (raw)"), ("basis_z", "basis_z")]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_4h", "4h"), ("ret_8h", "8h")]:
        x = s_train[sig_col].values
        y = s_train[ret_col].values
        obs_v, pval_v, null_v = perm_test(x, y)
        print(f"  {label} vs {hz}: IC={obs_v:+.5f}  p={pval_v:.4f}  "
              f"{obs_v/null_v.std():+.1f}s")

print()
print("--- Block bootstrap (block=3 settlements=24h, B=1000) ---")
for sig_col in ["basis", "basis_z"]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_8h", "8h")]:
        obs_v, pval_v, boots = block_boot(
            s_train[sig_col].values, s_train[ret_col].values, block=3, B=1000)
        ci = np.percentile(boots, [2.5, 97.5])
        print(f"  {sig_col} vs {hz}: IC={obs_v:+.5f}  p={pval_v:.4f}  "
              f"CI=[{ci[0]:+.5f}, {ci[1]:+.5f}]")

print()
print("--- Walk-forward OOS (90-day windows = 270 settlements) ---")
WINDOW_S = 90 * 3
STEP_S   = 30 * 3
for sig_col in ["basis", "basis_z"]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_8h", "8h")]:
        ics = []
        for i in range(0, len(s_oos) - WINDOW_S, STEP_S):
            w = s_oos.iloc[i: i + WINDOW_S]
            ics.append(ic(w[sig_col].values, w[ret_col].values))
        ics = np.array([v for v in ics if np.isfinite(v)])
        frac = (ics < 0).mean() * 100
        print(f"  {sig_col} vs {hz}: n={len(ics)}  "
              f"mean={ics.mean():+.5f}  std={ics.std():.5f}  "
              f"frac_neg={frac:.1f}%")

print()
sigma_1h = float(s_train["ret_1h"].std())
sigma_8h = float(s_train["ret_8h"].std())
bk_1h    = RT       / (sigma_1h * np.sqrt(2 / np.pi))
bk_8h    = RT       / (sigma_8h * np.sqrt(2 / np.pi))
bk_8h_mk = MAKER_RT / (sigma_8h * np.sqrt(2 / np.pi))

ic_basis_1h  = abs(ic(s_train["basis"].values,   s_train["ret_1h"].values))
ic_basisz_8h = abs(ic(s_train["basis_z"].values,  s_train["ret_8h"].values))

print(f"sigma_1h (settle) = {sigma_1h*100:.4f}%   IC_break(1h,taker) = {bk_1h:.4f}")
print(f"sigma_8h (settle) = {sigma_8h*100:.4f}%   IC_break(8h,taker) = {bk_8h:.4f}")
print(f"                                   IC_break(8h,maker) = {bk_8h_mk:.4f}")
print(f"IC(basis,    ret_1h) = {ic_basis_1h:.5f}  ({ic_basis_1h/bk_1h:.3f}x taker breakeven)")
print(f"IC(basis_z,  ret_8h) = {ic_basisz_8h:.5f}  ({ic_basisz_8h/bk_8h:.3f}x taker,  "
      f"{ic_basisz_8h/bk_8h_mk:.3f}x maker breakeven)")
