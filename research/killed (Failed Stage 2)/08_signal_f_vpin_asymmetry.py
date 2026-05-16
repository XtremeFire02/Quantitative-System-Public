"""
Signal F: Directional VPIN Asymmetry
=====================================
Standard VPIN = rolling mean of |buy - sell| / vol  (symmetric, discards direction)

Hypothesis: the *signed* imbalance smoothed over 50 bars — separate buy-side vs
sell-side informed activity — predicts returns with a REVERSAL sign.

Mechanism: when VPIN_buy >> VPIN_sell, a sustained wave of aggressive buying has
absorbed the available ask liquidity. Passive limit-order providers have been run
over. The next period they widen spreads and pull bids, causing a mean reversion.
Equivalently: if the buying is truly informed, the price has already moved; the
residual signal is negative (you're late).

Signals tested
--------------
  vpin_asym     = EMA50(tbv/vol) - EMA50(tsv/vol)         directional imbalance
  vpin_asym_z   = (vpin_asym - roll300.mean) / roll300.std  z-score normalised
  vpin_buy      = EMA50(tbv/vol)                            buy-side intensity
  vpin_sell     = EMA50(tsv/vol)                            sell-side intensity
  ofi_ema       = EMA50(ofi_quote)                          smoothed OFI baseline
"""
import sys, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import split, TRAIN_END, VAL_END
from framework.costs import TAKER

PROC    = Path("data/processed")
RESULTS = Path("results")
RESULTS.mkdir(exist_ok=True)

MAX_SAMP = 50_000
N_PERMS  = 2_000
BOOT_B   = 1_000
BORDER   = "=" * 72

out_lines = []
def pr(*args):
    line = " ".join(str(a) for a in args)
    line = line.replace("−", "-")
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    out_lines.append(line)


# ── helpers ────────────────────────────────────────────────────────────────────

def spearman_ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def _subsample(x, y, rng):
    if len(x) <= MAX_SAMP:
        return x, y
    idx = rng.choice(len(x), MAX_SAMP, replace=False)
    idx.sort()
    return x[idx], y[idx]

def permutation_test(x, y, n_perms=N_PERMS, seed=42):
    rng   = np.random.default_rng(seed)
    xs, ys = _subsample(np.asarray(x, float), np.asarray(y, float), rng)
    m     = np.isfinite(xs) & np.isfinite(ys)
    xs, ys = xs[m], ys[m]
    obs   = float(sp_stats.spearmanr(xs, ys).statistic)
    nulls = np.empty(n_perms)
    for i in range(n_perms):
        nulls[i] = float(sp_stats.spearmanr(rng.permutation(xs), ys).statistic)
    pval = (np.abs(nulls) >= np.abs(obs)).mean()
    return obs, pval, nulls

def block_bootstrap(x, y, block=60, B=BOOT_B, seed=0):
    rng    = np.random.default_rng(seed)
    xf, yf = np.asarray(x, float), np.asarray(y, float)
    m      = np.isfinite(xf) & np.isfinite(yf)
    xf, yf = xf[m], yf[m]
    n      = len(xf)
    obs    = float(sp_stats.spearmanr(xf, yf).statistic)
    starts = np.arange(0, n - block + 1)
    boots  = np.empty(B)
    for i in range(B):
        idx    = np.concatenate([np.arange(s, min(s + block, n))
                                 for s in rng.choice(starts, n // block + 1)])[:n]
        boots[i] = float(sp_stats.spearmanr(xf[idx], yf[idx]).statistic)
    # Shift to null before testing (see 10_basis_rigorous.py for explanation)
    pval = (np.abs(boots - obs) >= np.abs(obs)).mean()
    return obs, pval, boots


# ── load data ──────────────────────────────────────────────────────────────────

pr("Loading data...")
df = pd.read_parquet(PROC / "ofi.parquet")


# ── feature construction ───────────────────────────────────────────────────────

pr("Building directional VPIN features...")

tbv = df["taker_buy_base_volume"]
vol = df["volume"]
tsv = vol - tbv                               # taker sell volume

buy_ratio  = (tbv / vol.replace(0, np.nan)).fillna(0.5)
sell_ratio = (tsv / vol.replace(0, np.nan)).fillna(0.5)

# EMA-based VPIN components (span=50 ≈ 50-bar rolling mean, but causal)
SPAN = 50
df["vpin_buy"]  = buy_ratio.ewm(span=SPAN, adjust=False).mean()
df["vpin_sell"] = sell_ratio.ewm(span=SPAN, adjust=False).mean()
df["vpin_asym"] = df["vpin_buy"] - df["vpin_sell"]   # directional: positive = buy-heavy

# Z-score normalise over 300-bar rolling window
roll = df["vpin_asym"].rolling(300)
df["vpin_asym_z"] = (df["vpin_asym"] - roll.mean()) / roll.std()

# Smoothed OFI for comparison baseline
ofi = (tbv / vol.replace(0, np.nan) - 0.5).fillna(0.0)
df["ofi_ema50"]  = ofi.ewm(span=50,  adjust=False).mean()
df["ofi_ema300"] = ofi.ewm(span=300, adjust=False).mean()

# Curvature: rate of change of asymmetry (second signal derived from F)
df["vpin_asym_d1"] = df["vpin_asym"].diff(5)    # 5-bar first difference
df["vpin_asym_d2"] = df["vpin_asym"].diff(5).diff(5)

# Split AFTER feature construction
train_df = df[df.index < TRAIN_END].copy()
val_df   = df[(df.index >= TRAIN_END) & (df.index < VAL_END)].copy()
test_df  = df[df.index >= VAL_END].copy()

pr(f"Train: {len(train_df):,}  Val: {len(val_df):,}  Test: {len(test_df):,}")
pr(f"\nvpin_asym  — mean={df['vpin_asym'].mean():+.6f}  "
   f"std={df['vpin_asym'].std():.6f}  "
   f"skew={df['vpin_asym'].skew():.3f}")
pr(f"vpin_asym_z— mean={df['vpin_asym_z'].dropna().mean():+.6f}  "
   f"std={df['vpin_asym_z'].dropna().std():.4f}")


# ══════════════════════════════════════════════════════════════════════════════
#  F1: IC PROFILE ACROSS HORIZONS
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL F: DIRECTIONAL VPIN ASYMMETRY — HYPOTHESIS TESTS")
pr(BORDER)

pr("\n[F1] IC profile — all F variants vs forward returns (train)")
pr(f"  {'Signal':<22}  {'1m':>8} {'5m':>8} {'15m':>8} {'1h':>8} {'4h':>8}")

signals_f = [
    ("vpin_asym",    "vpin_asym"),
    ("vpin_asym_z",  "vpin_asym_z"),
    ("vpin_buy",     "vpin_buy"),
    ("vpin_sell",    "vpin_sell"),
    ("ofi_ema50",    "ofi_ema50"),
    ("ofi_ema300",   "ofi_ema300"),
    ("vpin_asym_d1", "vpin_asym_d1"),
    ("vpin_asym_d2", "vpin_asym_d2"),
]

for label, col in signals_f:
    sig = train_df[col].values
    row = []
    for rc in ["ret_1m", "ret_5m", "ret_15m", "ret_1h", "ret_4h"]:
        row.append(spearman_ic(sig, train_df[rc].values))
    pr(f"  {label:<22}  "
       f"{row[0]:>+8.5f} {row[1]:>+8.5f} {row[2]:>+8.5f} "
       f"{row[3]:>+8.5f} {row[4]:>+8.5f}")


# ══════════════════════════════════════════════════════════════════════════════
#  F2: PERMUTATION TESTS ON PRIMARY SIGNALS
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n[F2] Permutation tests (N={N_PERMS}, subsample {MAX_SAMP:,})")
combos = [
    ("vpin_asym   vs ret_5m",  "vpin_asym",   "ret_5m"),
    ("vpin_asym   vs ret_15m", "vpin_asym",   "ret_15m"),
    ("vpin_asym   vs ret_1h",  "vpin_asym",   "ret_1h"),
    ("vpin_asym_z vs ret_5m",  "vpin_asym_z", "ret_5m"),
    ("vpin_asym_z vs ret_1h",  "vpin_asym_z", "ret_1h"),
    ("ofi_ema50   vs ret_5m",  "ofi_ema50",   "ret_5m"),
]
for label, sc, rc in combos:
    obs, pval, null = permutation_test(train_df[sc].values, train_df[rc].values)
    nsig = obs / null.std() if null.std() > 0 else np.nan
    pr(f"  {label:<36}  IC={obs:+.5f}  p={pval:.4f}  {nsig:+.1f}s")


# ══════════════════════════════════════════════════════════════════════════════
#  F3: BLOCK BOOTSTRAP (autocorrelation-robust)
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n[F3] Block bootstrap (block=60, B={BOOT_B})")
for label, sc, rc, blk in [
    ("vpin_asym   vs ret_5m",  "vpin_asym",   "ret_5m",  30),
    ("vpin_asym   vs ret_1h",  "vpin_asym",   "ret_1h",  60),
    ("vpin_asym_z vs ret_5m",  "vpin_asym_z", "ret_5m",  30),
    ("vpin_asym_z vs ret_1h",  "vpin_asym_z", "ret_1h",  60),
]:
    obs, pval, boot = block_bootstrap(train_df[sc].values, train_df[rc].values,
                                      block=blk, B=BOOT_B)
    nsig = obs / boot.std() if boot.std() > 0 else np.nan
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    pr(f"  {label:<36}  IC={obs:+.5f}  p={pval:.4f}  "
       f"95%CI=[{ci_lo:+.5f},{ci_hi:+.5f}]  {nsig:+.1f}s")


# ══════════════════════════════════════════════════════════════════════════════
#  F4: LEAD-LAG PROFILE (decay of predictive power)
# ══════════════════════════════════════════════════════════════════════════════
pr("\n[F4] Lead-lag profile — vpin_asym IC vs ret shifted 0..120 bars")
sig_f = train_df["vpin_asym"].values
ret_f = train_df["ret_1m"].values
n_f   = len(sig_f)
for lag in [0, 1, 2, 3, 5, 10, 15, 30, 60, 120]:
    if lag == 0:
        ic = spearman_ic(sig_f, ret_f)
    else:
        ic = spearman_ic(sig_f[:-lag], ret_f[lag:])
    pr(f"  lag={lag:>4}  IC={ic:+.6f}")


# ══════════════════════════════════════════════════════════════════════════════
#  F5: CONDITIONAL IC — does signal strengthen in high-vol regimes?
# ══════════════════════════════════════════════════════════════════════════════
pr("\n[F5] Conditional IC — split by rolling realized vol (train)")
rv20 = train_df["ret_1m"].rolling(20).std()
for qt, label in [(0.33, "low vol"), (0.66, "mid vol"), (1.00, "high vol")]:
    lo = 0 if label == "low vol" else (0.33 if label == "mid vol" else 0.66)
    mask = (rv20 > rv20.quantile(lo)) & (rv20 <= rv20.quantile(qt))
    sub  = train_df[mask]
    ic5  = spearman_ic(sub["vpin_asym"].values, sub["ret_5m"].values)
    ic1h = spearman_ic(sub["vpin_asym"].values, sub["ret_1h"].values)
    pr(f"  {label:<10}  n={mask.sum():>7,}  IC(5m)={ic5:+.5f}  IC(1h)={ic1h:+.5f}")


# ══════════════════════════════════════════════════════════════════════════════
#  F6: WALK-FORWARD OOS IC
# ══════════════════════════════════════════════════════════════════════════════
pr("\n[F6] Walk-forward OOS IC — vpin_asym vs ret_5m (30-day windows, val+test)")
oos_df  = pd.concat([val_df, test_df])
WINDOW  = 30 * 1440    # 30 days of 1m bars
STEP    = 7  * 1440    # re-evaluate weekly
oos_ics = []
for i in range(0, len(oos_df) - WINDOW, STEP):
    w  = oos_df.iloc[i: i + WINDOW]
    ic = spearman_ic(w["vpin_asym"].values, w["ret_5m"].values)
    oos_ics.append(ic)
oos_ics = np.array([x for x in oos_ics if np.isfinite(x)])
pr(f"  OOS windows: {len(oos_ics)}")
pr(f"  Mean IC: {oos_ics.mean():+.5f}  Std: {oos_ics.std():.5f}")
pr(f"  Frac same direction as train: {(oos_ics < 0).mean()*100:.1f}%")
pr(f"  95% CI: [{np.percentile(oos_ics,2.5):+.5f}, {np.percentile(oos_ics,97.5):+.5f}]")

pr("\n[F7] Walk-forward OOS IC — vpin_asym vs ret_1h (30-day windows, val+test)")
oos_ics_1h = []
for i in range(0, len(oos_df) - WINDOW, STEP):
    w  = oos_df.iloc[i: i + WINDOW]
    ic = spearman_ic(w["vpin_asym"].values, w["ret_1h"].values)
    oos_ics_1h.append(ic)
oos_ics_1h = np.array([x for x in oos_ics_1h if np.isfinite(x)])
pr(f"  OOS windows: {len(oos_ics_1h)}")
pr(f"  Mean IC: {oos_ics_1h.mean():+.5f}  Std: {oos_ics_1h.std():.5f}")
pr(f"  Frac same direction as train: {(oos_ics_1h < 0).mean()*100:.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  F8: BREAKEVEN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
TAKER_RT = TAKER.round_trip_cost()   # e.g. 0.0010 = 10 bps
pr(f"\n[F8] Breakeven IC — taker cost = {TAKER_RT*100:.2f}% RT")
pr(f"  {'Horizon':<10} {'sigma_ret':>10} {'IC_break':>10} {'best_IC':>10} {'ratio':>8}")
horizons = [("5m", "ret_5m"), ("15m", "ret_15m"), ("1h", "ret_1h"), ("4h", "ret_4h")]
for hz_label, rc in horizons:
    sigma  = float(train_df[rc].std())
    ic_bk  = TAKER_RT / (sigma * np.sqrt(2 / np.pi))
    best_ic = max(abs(spearman_ic(train_df["vpin_asym"].values, train_df[rc].values)),
                  abs(spearman_ic(train_df["vpin_asym_z"].values, train_df[rc].values)))
    ratio  = best_ic / ic_bk if ic_bk > 0 else np.nan
    pr(f"  {hz_label:<10} {sigma*100:>9.4f}% {ic_bk:>10.4f} {best_ic:>10.5f} {ratio:>7.3f}x")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SUMMARY")
pr(BORDER)

# save
out_path = RESULTS / "signal_f_vpin_asymmetry.txt"
out_path.write_text("\n".join(out_lines), encoding="utf-8")
pr(f"Saved: {out_path}")
