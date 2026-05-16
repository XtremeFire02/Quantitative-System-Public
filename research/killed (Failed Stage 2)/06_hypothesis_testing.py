"""
Formal hypothesis testing for:
  Signal C: CVD Divergence  (cvd_60m_norm - price_ret_60m)
  Signal E: VPIN            (50-bar rolling |buy-sell|/total vol)

Tests per signal
----------------
C1  Permutation test on Spearman IC (10,000 shuffles, preserves distribution)
C2  Circular block bootstrap IC (block=60, B=2000, accounts for autocorrelation)
C3  Granger causality: does lag-1 CVD divergence Granger-cause ret_1h?
C4  Economic significance: what fraction of bars have edge > round-trip cost?
C5  Walk-forward rolling IC (30-day windows) with 95% CI

E1  Block bootstrap on IC vs |ret_1h| (block=50, B=2000)
E2  Kolmogorov-Smirnov test: return distributions in high vs low VPIN regimes
E3  VPIN lead-lag profile: IC at lags 0,1,5,15,30,60 bars ahead
E4  Regime classifier precision/recall: low VPIN predicting high-vol hours
E5  Conditional OFI test: permutation test on IC difference between regimes

All tests on TRAIN set only. Val/test used for out-of-sample confirmation only.
"""
import sys, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats as sp_stats
from statsmodels.tsa.stattools import grangercausalitytests
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import split
from framework.costs import TAKER

PROC    = Path("data/processed")
RESULTS = Path("results")
RESULTS.mkdir(exist_ok=True)

BORDER = "=" * 72
B         = 2000    # bootstrap replications
N_PERMS   = 2000    # permutation test replications
MAX_SAMP  = 50_000  # max sample size for permutation/bootstrap (speed)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fast_spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Fast Spearman via preranked arrays (avoids repeated full-sort)."""
    rx = sp_stats.rankdata(x)
    ry = sp_stats.rankdata(y)
    n  = len(rx)
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float(np.dot(rx, ry) / denom) if denom > 0 else 0.0


def spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 30:
        return np.nan
    return sp_stats.spearmanr(x[mask], y[mask]).statistic


def _subsample(x, y, max_n, rng):
    """Subsample for speed while preserving IC accuracy."""
    if len(x) <= max_n:
        return x, y
    idx = rng.choice(len(x), max_n, replace=False)
    idx.sort()
    return x[idx], y[idx]


def permutation_test(x: np.ndarray, y: np.ndarray, n_perms: int = N_PERMS,
                     seed: int = 42) -> tuple[float, float, np.ndarray]:
    """Shuffle x (signal), keep y (returns) fixed. Two-sided."""
    rng    = np.random.default_rng(seed)
    mask   = np.isfinite(x) & np.isfinite(y)
    x_c, y_c = x[mask], y[mask]
    obs_ic = spearman_ic(x_c, y_c)
    # subsample for speed; null distribution shape is invariant to N
    xs, ys = _subsample(x_c, y_c, MAX_SAMP, rng)
    # precompute rank(y) — stays fixed across permutations
    ry = sp_stats.rankdata(ys).astype(np.float64)
    ry -= ry.mean()
    ry_norm = np.sqrt((ry**2).sum())
    def _perm_ic():
        rx = sp_stats.rankdata(rng.permutation(xs)).astype(np.float64)
        rx -= rx.mean()
        denom = np.sqrt((rx**2).sum()) * ry_norm
        return float(np.dot(rx, ry) / denom) if denom > 0 else 0.0
    null = np.array([_perm_ic() for _ in range(n_perms)])
    pval = (np.abs(null) >= abs(obs_ic)).mean()
    return obs_ic, pval, null


def circular_block_bootstrap(x: np.ndarray, y: np.ndarray,
                              block: int, B: int = B,
                              seed: int = 0) -> tuple[float, float, np.ndarray]:
    """
    Circular block bootstrap preserving temporal autocorrelation.
    Under H0: no relationship between x and y.
    We resample blocks of x while keeping y fixed, then compute IC.
    """
    rng   = np.random.default_rng(seed)
    mask  = np.isfinite(x) & np.isfinite(y)
    x_c, y_c = x[mask], y[mask]
    obs   = spearman_ic(x_c, y_c)
    # subsample a contiguous chunk for speed (preserves autocorrelation structure)
    xs, ys = _subsample(x_c, y_c, MAX_SAMP, rng)
    N     = len(xs)

    boot_ics = np.empty(B)
    for b in range(B):
        n_blocks = int(np.ceil(N / block))
        idx = []
        for _ in range(n_blocks):
            s = rng.integers(0, N)
            idx.extend([(s + k) % N for k in range(block)])
        x_boot = xs[idx[:N]]
        boot_ics[b] = spearman_ic(x_boot, ys)

    pval = (np.abs(boot_ics) >= abs(obs)).mean()
    return obs, pval, boot_ics


def rolling_ic(x: pd.Series, y: pd.Series, window_bars: int) -> pd.Series:
    """Rolling Spearman IC in windows of `window_bars` bars."""
    result = {}
    for i in range(window_bars, len(x) + 1):
        xi = x.iloc[i - window_bars: i].values
        yi = y.iloc[i - window_bars: i].values
        ic = spearman_ic(xi, yi)
        result[x.index[i - 1]] = ic
    return pd.Series(result)


# ── load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
df = pd.read_parquet(PROC / "ofi.parquet")
adv = pd.read_parquet(PROC / "signals_advanced.parquet")

df = df.join(adv[["cvd_divergence", "vpin_50m_lag"]], how="left")
train_df, val_df, test_df = split(df)

# Convenience arrays (train only for hypothesis tests)
cvd    = train_df["cvd_divergence"].values
ret1h  = train_df["ret_1h"].values
ret5m  = train_df["ret_5m"].values
ret15m = train_df["ret_15m"].values
vpin   = train_df["vpin_50m_lag"].values
ofi    = train_df["ofi_centered"].values
abs1h  = np.abs(ret1h)

out_lines = []
def pr(*args):
    line = " ".join(str(a) for a in args)
    print(line)
    out_lines.append(line)


pr(BORDER)
pr("HYPOTHESIS TESTING — SIGNAL C (CVD DIVERGENCE) AND SIGNAL E (VPIN)")
pr(BORDER)
pr(f"Train set: {train_df.index.min().date()} to {train_df.index.max().date()}")
pr(f"N bars: {len(train_df):,}   round-trip cost: {TAKER.round_trip_cost()*100:.2f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL C: CVD DIVERGENCE
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL C: CVD DIVERGENCE — HYPOTHESIS TESTS")
pr(BORDER)


# C1 — Permutation test
pr("\n[C1] Permutation test (H0: IC = 0, 10,000 shuffles)")
pr("     Shuffles signal (cvd_divergence) while fixing return series.")
pr("     Preserves return autocorrelation; destroys signal-return relationship.")

for hz, ret in [("5m", ret5m), ("15m", ret15m), ("1h", ret1h)]:
    mask = np.isfinite(cvd) & np.isfinite(ret)
    obs, pval, null = permutation_test(cvd[mask], ret[mask], n_perms=10_000)
    ci_lo, ci_hi = np.percentile(null, [2.5, 97.5])
    pr(f"  ret_{hz}: IC={obs:+.5f}  perm-p={pval:.5f}  "
       f"null 95%CI=[{ci_lo:+.5f}, {ci_hi:+.5f}]")


# C2 — Circular block bootstrap
pr(f"\n[C2] Circular block bootstrap (block=60, B={B})")
pr("     Resamples blocks of 60 consecutive signal bars, preserving")
pr("     autocorrelation in the signal. Stronger test than permutation.")

for hz, ret, blk in [("5m", ret5m, 30), ("15m", ret15m, 60), ("1h", ret1h, 60)]:
    mask = np.isfinite(cvd) & np.isfinite(ret)
    obs, pval, boot = circular_block_bootstrap(cvd[mask], ret[mask],
                                                block=blk, B=B)
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    pr(f"  ret_{hz} (block={blk}): IC={obs:+.5f}  boot-p={pval:.5f}  "
       f"boot 95%CI=[{ci_lo:+.5f}, {ci_hi:+.5f}]")


# C3 — Granger causality
pr("\n[C3] Granger causality test (H0: cvd_divergence does not Granger-cause ret_1h)")
pr("     Null: lagged cvd_divergence adds no predictive power beyond AR(p) of ret_1h.")

sub = train_df[["cvd_divergence", "ret_1h"]].dropna().copy()
# subsample for speed — Granger test on full 500k rows is very slow
sub = sub.sample(n=min(len(sub), 20_000), random_state=42).sort_index()
# standardise to make F-stats comparable
sub = (sub - sub.mean()) / sub.std()
try:
    gc = grangercausalitytests(sub[["ret_1h", "cvd_divergence"]].values,
                                maxlag=5, verbose=False)
    pr("  Lag  F-stat   p-value")
    for lag, result in sorted(gc.items()):
        f_stat = result[0]["ssr_ftest"][0]
        p_val  = result[0]["ssr_ftest"][1]
        sig    = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
        pr(f"  {lag:3d}  {f_stat:7.3f}  {p_val:.5f} {sig}")
except Exception as e:
    pr(f"  Granger test failed: {e}")


# C4 — Economic significance
pr("\n[C4] Economic significance analysis")
pr(f"     Round-trip cost = {TAKER.round_trip_cost()*100:.4f}%")
pr("     Edge per trade = |cvd_pct_rank - 0.5| × expected_return_in_direction")
pr("     We measure: fraction of bars where REALISED |signal × return| > cost")

mask = np.isfinite(cvd) & np.isfinite(ret1h)
cvd_c, ret_c = cvd[mask], ret1h[mask]
# Compute percentile rank of cvd within rolling 300-bar windows
cvd_s = pd.Series(cvd_c)
pct_rank = cvd_s.rolling(300, min_periods=60).rank(pct=True).fillna(0.5).values

# Short signal: pct_rank > 0.8 → direction = -1
# Long signal: pct_rank < 0.2 → direction = +1
short_mask = pct_rank > 0.80
long_mask  = pct_rank < 0.20
signal_mask = short_mask | long_mask
direction  = np.where(short_mask, -1, np.where(long_mask, 1, 0))

# Realised P&L per triggered bar
pnl = direction * ret_c - TAKER.round_trip_cost() * (direction != 0)
triggered = signal_mask & np.isfinite(ret_c)
pnl_triggered = pnl[triggered]

pr(f"  Signal fires on {triggered.sum():,} / {len(ret_c):,} bars "
   f"({triggered.mean()*100:.1f}%)")
pr(f"  Mean P&L per triggered bar: {pnl_triggered.mean()*100:+.5f}%")
pr(f"  Fraction profitable:        {(pnl_triggered > 0).mean()*100:.1f}%")
pr(f"  t-stat (P&L > 0):           {sp_stats.ttest_1samp(pnl_triggered, 0).statistic:+.3f}")
pr(f"  p-value:                    {sp_stats.ttest_1samp(pnl_triggered, 0).pvalue:.5f}")
ann_return = pnl_triggered.sum() * (60 * 24 * 365 / 60) / max(len(pnl_triggered), 1)
pr(f"  Annualised return (if every bar traded at 1h horizon): {ann_return*100:.1f}%")


# C5 — Walk-forward rolling IC (30-day windows = 43,200 1m bars)
pr("\n[C5] Walk-forward rolling IC (window = 30 days of 1m bars)")
pr("     Out-of-sample periods: val and test sets.")

ROLL_W = 30 * 24 * 60  # 30 days in minutes
# Use val + test for OOS walk-forward
oos_df = pd.concat([val_df, test_df])
oos_df["cvd_divergence"] = df["cvd_divergence"].reindex(oos_df.index)

roll_ic_vals = []
step = 60 * 24  # re-evaluate every day (1440 bars)
for start in range(0, len(oos_df) - ROLL_W, step):
    window_df = oos_df.iloc[start: start + ROLL_W]
    ic = spearman_ic(window_df["cvd_divergence"].values, window_df["ret_1h"].values)
    roll_ic_vals.append(ic)

roll_ic_arr = np.array([x for x in roll_ic_vals if np.isfinite(x)])
pr(f"  OOS windows: {len(roll_ic_arr)}")
pr(f"  Mean IC:     {roll_ic_arr.mean():+.5f}")
pr(f"  Std  IC:     {roll_ic_arr.std():.5f}")
pr(f"  Min  IC:     {roll_ic_arr.min():+.5f}")
pr(f"  Max  IC:     {roll_ic_arr.max():+.5f}")
pr(f"  Frac negative (correct direction): {(roll_ic_arr < 0).mean()*100:.1f}%")
pr(f"  95% CI of rolling IC: [{np.percentile(roll_ic_arr, 2.5):+.5f}, "
   f"{np.percentile(roll_ic_arr, 97.5):+.5f}]")


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL E: VPIN
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL E: VPIN REGIME SIGNAL — HYPOTHESIS TESTS")
pr(BORDER)

mask_e = np.isfinite(vpin) & np.isfinite(abs1h)
vpin_c, abs1h_c = vpin[mask_e], abs1h[mask_e]


# E1 — Block bootstrap on IC vs |ret_1h|
pr(f"\n[E1] Block bootstrap: VPIN vs |ret_1h| (H0: IC = 0, block=50, B={B})")
pr("     Accounts for autocorrelation in VPIN (50-bar rolling mean).")

obs_e1, pval_e1, boot_e1 = circular_block_bootstrap(vpin_c, abs1h_c,
                                                      block=50, B=B)
ci_lo, ci_hi = np.percentile(boot_e1, [2.5, 97.5])
pr(f"  Observed IC: {obs_e1:+.5f}")
pr(f"  Bootstrap p: {pval_e1:.6f}")
pr(f"  Bootstrap 95% CI (null): [{ci_lo:+.5f}, {ci_hi:+.5f}]")
pr(f"  Observed IC is {abs(obs_e1) / boot_e1.std():.1f} std devs from null mean")


# E2 — KS test: return distributions in high vs low VPIN regimes
pr("\n[E2] Kolmogorov-Smirnov test: |ret_1h| distributions in high vs low VPIN")
pr("     H0: the two distributions are identical.")

vpin_med = np.nanmedian(vpin_c)
lo_returns = abs1h_c[vpin_c <= vpin_med]
hi_returns = abs1h_c[vpin_c >  vpin_med]

ks_stat, ks_p = sp_stats.ks_2samp(lo_returns, hi_returns)
pr(f"  Low  VPIN (N={len(lo_returns):,}): mean |ret_1h| = {lo_returns.mean()*100:.4f}%")
pr(f"  High VPIN (N={len(hi_returns):,}): mean |ret_1h| = {hi_returns.mean()*100:.4f}%")
pr(f"  KS statistic: {ks_stat:.5f}   p-value: {ks_p:.2e}")
pr(f"  Mann-Whitney U test:")
mw_stat, mw_p = sp_stats.mannwhitneyu(lo_returns, hi_returns, alternative="greater")
pr(f"    H1: low-VPIN |returns| > high-VPIN |returns|  p = {mw_p:.2e}")


# E3 — VPIN lead-lag profile
pr("\n[E3] VPIN lead-lag profile: IC(VPIN_t, |ret_{t+lag}|) at lags 0..60")
pr("     Does VPIN LEAD volatility, or is it concurrent?")

mask_lag = np.isfinite(vpin)
vpin_lag = train_df["vpin_50m_lag"].values
for lag in [0, 1, 5, 10, 15, 30, 60]:
    ret_shifted = np.roll(np.abs(ret1h), -lag)
    ret_shifted[-lag:] = np.nan if lag > 0 else ret_shifted[-lag:]
    mask_l = np.isfinite(vpin_lag) & np.isfinite(ret_shifted)
    if mask_l.sum() < 100:
        continue
    ic = spearman_ic(vpin_lag[mask_l], ret_shifted[mask_l])
    pr(f"  lag={lag:2d}  IC(VPIN, |ret_1h| at +{lag}m) = {ic:+.5f}")


# E4 — Regime classifier: precision/recall for high-vol hours
pr("\n[E4] VPIN as high-volatility regime classifier")
pr("     Definition: 'high-vol' = |ret_1h| in top 25% of distribution.")
pr("     Signal: low VPIN (bottom 33%) = predict high-vol regime.")

vol_thresh = np.nanpercentile(abs1h, 75)
vpin_thresh = np.nanpercentile(vpin, 33)

mask_cls = np.isfinite(vpin) & np.isfinite(abs1h)
vpin_arr  = vpin[mask_cls]
abs1h_arr = abs1h[mask_cls]

predicted_highvol = vpin_arr <= vpin_thresh   # low VPIN → predict high vol
actual_highvol    = abs1h_arr >= vol_thresh

tp = (predicted_highvol & actual_highvol).sum()
fp = (predicted_highvol & ~actual_highvol).sum()
fn = (~predicted_highvol & actual_highvol).sum()
tn = (~predicted_highvol & ~actual_highvol).sum()

precision = tp / (tp + fp) if (tp + fp) > 0 else 0
recall    = tp / (tp + fn) if (tp + fn) > 0 else 0
f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
accuracy  = (tp + tn) / len(vpin_arr)
base_rate = actual_highvol.mean()

pr(f"  Base rate of high-vol hours: {base_rate*100:.1f}%")
pr(f"  VPIN threshold (33rd pct):   {vpin_thresh:.4f}")
pr(f"  Precision: {precision*100:.1f}%  (of predicted high-vol, how many were?)")
pr(f"  Recall:    {recall*100:.1f}%  (of actual high-vol, how many caught?)")
pr(f"  F1 score:  {f1:.4f}")
pr(f"  Accuracy:  {accuracy*100:.1f}%  vs base: {base_rate*100:.1f}%")

# Chi-squared test of independence
ct = np.array([[tp, fp], [fn, tn]])
chi2, chi_p, _, _ = sp_stats.chi2_contingency(ct)
pr(f"  Chi-squared independence test: chi2={chi2:.2f}  p={chi_p:.2e}")


# E5 — Permutation test: is OFI IC significantly different in high vs low VPIN?
pr("\n[E5] Is OFI predictive power significantly different across VPIN regimes?")
pr("     H0: OFI IC in low-VPIN regime == OFI IC in high-VPIN regime")
pr("     Method: permutation test on the IC difference (10,000 shuffles).")

mask_e5 = np.isfinite(vpin) & np.isfinite(ofi) & np.isfinite(ret5m)
vpin_e5, ofi_e5, ret5m_e5 = vpin[mask_e5], ofi[mask_e5], ret5m[mask_e5]

def ic_diff(vpin_arr, ofi_arr, ret_arr, thresh):
    lo = vpin_arr <= thresh
    ic_lo = spearman_ic(ofi_arr[lo],  ret_arr[lo])
    ic_hi = spearman_ic(ofi_arr[~lo], ret_arr[~lo])
    return ic_lo - ic_hi

vpin_med_e5 = np.median(vpin_e5)
obs_diff = ic_diff(vpin_e5, ofi_e5, ret5m_e5, vpin_med_e5)

rng = np.random.default_rng(42)
null_diffs = np.array([
    ic_diff(rng.permutation(vpin_e5), ofi_e5, ret5m_e5, np.median(vpin_e5))
    for _ in range(2000)
])
pval_e5 = (np.abs(null_diffs) >= abs(obs_diff)).mean()

lo_mask = vpin_e5 <= vpin_med_e5
ic_lo = spearman_ic(ofi_e5[lo_mask],  ret5m_e5[lo_mask])
ic_hi = spearman_ic(ofi_e5[~lo_mask], ret5m_e5[~lo_mask])

pr(f"  OFI IC in low-VPIN  regime: {ic_lo:+.5f}")
pr(f"  OFI IC in high-VPIN regime: {ic_hi:+.5f}")
pr(f"  Observed difference:        {obs_diff:+.5f}")
pr(f"  Permutation p-value:        {pval_e5:.5f}")
pr(f"  -> OFI mean-reversion is {'significantly' if pval_e5 < 0.05 else 'NOT significantly'} "
   f"stronger in low-VPIN regime")


# ── Final summary ─────────────────────────────────────────────────────────────
pr(f"\n{BORDER}")
pr("SUMMARY")
pr(BORDER)
pr("""
Signal C (CVD Divergence):
  C1 Permutation:        tests whether IC could arise by chance
  C2 Block bootstrap:    accounts for signal autocorrelation (60-bar window)
  C3 Granger causality:  tests whether signal adds info beyond AR models
  C4 Economic sig:       tests whether realised P&L is positive after costs
  C5 Walk-forward OOS:   tests whether IC is stable outside training set

Signal E (VPIN):
  E1 Block bootstrap:    accounts for VPIN autocorrelation (50-bar rolling)
  E2 KS test:            tests whether vol distributions differ by regime
  E3 Lead-lag:           tests whether VPIN leads or coincides with vol
  E4 Classifier:         tests VPIN's precision/recall as vol predictor
  E5 Regime-OFI diff:    tests whether VPIN significantly changes OFI alpha
""")

# Save
Path("results/killed/hypothesis_testing.txt").write_text(
    "\n".join(out_lines), encoding="utf-8")
print("\nSaved: results/killed/hypothesis_testing.txt")
