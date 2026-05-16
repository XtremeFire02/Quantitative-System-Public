"""Signal E: Continuous Mark-Index Premium Basis (1m klines).

Mechanism: The premium index basis b_t = (mark - index)/index is the raw
input to the Binance funding rate TWAP.  When b_t > 0, longs implicitly pay
a carry cost that is not yet crystallised; index arbitrageurs short the perp
and buy spot, pushing mark → index.  The hypothesis is that an elevated
(or depressed) basis predicts a partial return reversal over short horizons
as this arbitrage pressure plays out.

This is the continuous-time analogue of H1 (settlement-bar basis), giving
~525k train observations vs ~500 for H1.
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
prem = pd.read_parquet("data/raw/BTCUSDT_premium_index_1m.parquet")
ofi  = pd.read_parquet("data/processed/ofi.parquet")

common = ofi.index.intersection(prem.index)
print(f"Common timestamps : {len(common):,}  ({common[0].date()} to {common[-1].date()})")

df = ofi.loc[common].copy()
df["mark_close"]  = prem.loc[common, "mark_close"].astype(float)
df["index_close"] = prem.loc[common, "index_close"].astype(float)
df["basis_pct"]   = prem.loc[common, "basis_pct"].astype(float)

# ─── Signal construction ─────────────────────────────────────────────────────
W = 480  # 8h rolling window

# E1: z-scored basis (main signal — centred, scaled)
df["basis_z"] = (
    (df["basis_pct"] - df["basis_pct"].rolling(W).mean())
    / df["basis_pct"].rolling(W).std()
)

# E2: Basis momentum — rate of change over 30m
df["basis_mom30"] = df["basis_pct"].diff(30)

# E3: Signed rank (–0.5 centred percentile rank in 8h window)
df["basis_rank"] = df["basis_pct"].rolling(W).rank(pct=True) - 0.5

# Drop warm-up
df = df.dropna(subset=["basis_z", "basis_rank"])

# ─── Splits ──────────────────────────────────────────────────────────────────
train = df[df.index < TRAIN_END]
oos   = df[df.index >= TRAIN_END]
print(f"Train : {len(train):,}   OOS : {len(oos):,}")
print()

# ─── Helpers ─────────────────────────────────────────────────────────────────
RT       = TAKER.round_trip_cost()
MAKER_RT = TAKER.__class__(use_maker=True).round_trip_cost()

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def perm_test(x, y, n=2000, seed=42, max_n=50_000):
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    idx = np.where(m)[0]
    if len(idx) > max_n:
        idx = rng.choice(idx, max_n, replace=False)
        idx.sort()
    x2, y2 = x[idx], y[idx]
    obs  = float(sp_stats.spearmanr(x2, y2).statistic)
    null = np.array([
        float(sp_stats.spearmanr(rng.permutation(x2), y2).statistic)
        for _ in range(n)
    ])
    return obs, (np.abs(null) >= np.abs(obs)).mean(), null

def block_boot(x, y, block=60, B=500, seed=0, max_n=50_000):
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    idx = np.where(m)[0]
    if len(idx) > max_n:
        # take a contiguous sub-sample to preserve block structure
        start = rng.integers(0, len(idx) - max_n)
        idx = idx[start: start + max_n]
    x2, y2 = x[idx], y[idx]
    n   = len(x2)
    obs = float(sp_stats.spearmanr(x2, y2).statistic)
    starts = np.arange(0, n - block + 1)
    boots  = []
    for _ in range(B):
        s_idx = np.concatenate([
            np.arange(s, min(s + block, n))
            for s in rng.choice(starts, n // block + 1)
        ])[:n]
        boots.append(float(sp_stats.spearmanr(x2[s_idx], y2[s_idx]).statistic))
    boots = np.array(boots)
    # Shift to null before testing (see 10_basis_rigorous.py for explanation)
    pval  = (np.abs(boots - obs) >= np.abs(obs)).mean()
    return obs, pval, boots

def bk(sigma, rt=RT):
    return rt / (sigma * np.sqrt(2 / np.pi))

# ─── IC profile across horizons ──────────────────────────────────────────────
print("=== E1: IC PROFILE — basis_z vs forward returns ===")
print(f"{'Signal':<14} {'Horizon':<8} {'IC':>8} {'|IC|/bk_t':>10} {'|IC|/bk_m':>10}")
print("-" * 52)

for sig_col in ["basis_pct", "basis_z", "basis_rank", "basis_mom30"]:
    for ret_col, label in [
        ("ret_1m",  "1m"),
        ("ret_5m",  "5m"),
        ("ret_15m", "15m"),
        ("ret_1h",  "1h"),
        ("ret_4h",  "4h"),
        ("ret_8h",  "8h"),
    ]:
        if ret_col not in train.columns:
            continue
        ic_v = ic(train[sig_col].values, train[ret_col].values)
        sig  = train[ret_col].std()
        bkt  = bk(sig, RT)
        bkm  = bk(sig, MAKER_RT)
        print(f"  {sig_col:<12} {label:<8} {ic_v:+.5f}  {abs(ic_v)/bkt:>9.3f}x  {abs(ic_v)/bkm:>9.3f}x")
    print()

# ─── Permutation tests on best candidate ─────────────────────────────────────
print("=== E2: PERMUTATION TESTS (N=2000, subsample 50k) ===")
for sig_col in ["basis_z", "basis_rank"]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_4h", "4h"), ("ret_8h", "8h")]:
        obs_v, pval_v, null_v = perm_test(
            train[sig_col].values, train[ret_col].values)
        z = obs_v / null_v.std() if null_v.std() > 0 else np.nan
        print(f"  {sig_col:<14} vs {hz}: IC={obs_v:+.5f}  p={pval_v:.4f}  {z:+.1f}s")
print()

# ─── Block bootstrap (block=60min = 1h of 1m bars) ───────────────────────────
print("=== E3: BLOCK BOOTSTRAP (block=60, B=500) ===")
for sig_col in ["basis_z", "basis_rank"]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_8h", "8h")]:
        obs_v, pval_v, boots = block_boot(
            train[sig_col].values, train[ret_col].values,
            block=60, B=500)
        ci = np.percentile(boots, [2.5, 97.5])
        print(f"  {sig_col:<14} vs {hz}: IC={obs_v:+.5f}  p={pval_v:.4f}  "
              f"CI=[{ci[0]:+.5f}, {ci[1]:+.5f}]")
print()

# ─── Walk-forward OOS ────────────────────────────────────────────────────────
print("=== E4: WALK-FORWARD OOS (30-day windows, 10-day step) ===")
WINDOW = 30 * 24 * 60   # 30 days in 1m bars
STEP   = 10 * 24 * 60   # 10-day step

for sig_col in ["basis_z", "basis_rank"]:
    for ret_col, hz in [("ret_1h", "1h"), ("ret_8h", "8h")]:
        ics = []
        for i in range(0, len(oos) - WINDOW, STEP):
            w = oos.iloc[i: i + WINDOW]
            ics.append(ic(w[sig_col].values, w[ret_col].values))
        ics = np.array([v for v in ics if np.isfinite(v)])
        frac_neg = (ics < 0).mean() * 100
        print(f"  {sig_col:<14} vs {hz}: n={len(ics):2d}  "
              f"mean={ics.mean():+.5f}  std={ics.std():.5f}  "
              f"frac_neg={frac_neg:.0f}%")
print()

# ─── Breakeven summary ───────────────────────────────────────────────────────
print("=== E5: BREAKEVEN SUMMARY ===")
for ret_col, hz in [("ret_1m","1m"),("ret_5m","5m"),("ret_15m","15m"),
                     ("ret_1h","1h"),("ret_4h","4h"),("ret_8h","8h")]:
    if ret_col not in train.columns:
        continue
    sig   = float(train[ret_col].std())
    bkt   = bk(sig, RT)
    bkm   = bk(sig, MAKER_RT)
    ic_v  = ic(train["basis_z"].values, train[ret_col].values)
    print(f"  {hz:<5}  sigma={sig*100:.4f}%  bk_taker={bkt:.4f}  bk_maker={bkm:.4f}  "
          f"IC={ic_v:+.5f}  ratio_maker={abs(ic_v)/bkm:.3f}x")

print()
print("Done.")
