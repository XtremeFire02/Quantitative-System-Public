"""
Mechanism-Driven Signals: Families 1 & 2
==========================================

All signals here derive from *forced* or *deterministic* trading behaviour —
not from observing past order flow and hoping the pattern repeats.

Family 1 — Arbitrage-Forced Convergence
----------------------------------------
Signal H1: Basis dislocation (close vs 8h funding mark)
  The 8h funding mark is constant over each period. When the current traded
  price diverges far from that mark, two forces converge it:
    (a) Direct basis arbitrage (stat arb desks short the premium)
    (b) Funding rate self-correction at next settlement

  Hypothesis: high basis_pct_rank → price mean-reverts toward mark → SHORT
              low  basis_pct_rank → price reverts up              → LONG

Signal H2: Funding rate as carry signal (not curvature)
  When funding is high positive, longs are paying shorts every 8h.
  Rational shorts will hold because they are getting paid.
  The trade eventually reverses when: (i) longs capitulate, or
  (ii) the spot price rises enough that shorts close.

  Hypothesis: high |funding| with sign = direction of carry → sign-flip at extremes

Family 2 — Crowded-Trade Exhaustion
--------------------------------------
Signal I1: Trapped positioning (funding × price direction divergence)
  If funding is strongly positive (longs crowded) AND price has fallen over
  the past 8h (longs are losing), we have trapped longs paying to hold
  losing positions. They must eventually capitulate.

  Hypothesis: positive funding × negative 8h ret → bearish continuation
              (not mean reversion — continuation of the unwind)

Signal I2: Funding saturation (extreme level with adverse cumulative return)
  Use the existing funding_pct_rank. Only enter at top/bottom 10% of
  funding distribution. Test whether extreme funding alone predicts the
  next 8h return.

Signal I3: Funding + Basis joint extreme
  Both extreme funding AND the price trading above/below mark simultaneously
  is a double signal that the crowding is at an inflection point.

Note on data in ofi.parquet
  basis          = (close - mark_price) / mark_price  (negative = price below mark)
  mark_price     = 8h funding mark (constant per 8h period)
  funding_rate   = 8h rate (fractional)
  funding_zscore = z-score vs rolling distribution
  funding_pct_rank = percentile rank
"""
import sys, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.splits import TRAIN_END, VAL_END
from framework.costs import TAKER

PROC    = Path("data/processed")
RAW     = Path("data/raw")
RESULTS = Path("results")
RESULTS.mkdir(exist_ok=True)

MAX_SAMP = 50_000
N_PERMS  = 2_000
BOOT_B   = 1_000
BORDER   = "=" * 72

out_lines = []
def pr(*args):
    line = " ".join(str(a) for a in args)
    line = line.replace("−", "-").replace("→", "->")
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    out_lines.append(line)


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
    pval = ((boots - obs) * np.sign(obs) <= 0).mean()   # one-sided: boot < obs
    return obs, pval, boots


# ── Load data ──────────────────────────────────────────────────────────────────
pr("Loading data...")
df   = pd.read_parquet(PROC / "ofi.parquet")
fund = pd.read_parquet(RAW  / "BTCUSDT_funding.parquet")
fund.index = fund.index.floor("min")
fund = fund[~fund.index.duplicated(keep="first")].sort_index()
fund = fund.rename(columns={"fundingRate": "funding_rate"})

pr(f"ofi.parquet columns: {list(df.columns)}")
pr(f"basis range: [{df['basis'].min():.6f}, {df['basis'].max():.6f}]")
pr(f"basis std: {df['basis'].std():.6f}")
pr(f"funding_pct_rank range: [{df['funding_pct_rank'].min():.3f}, {df['funding_pct_rank'].max():.3f}]")


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

# H1: Basis features
df["basis_z"]        = (df["basis"] - df["basis"].rolling(480).mean()) / df["basis"].rolling(480).std()
df["basis_abs_z"]    = df["basis_z"].abs()
df["basis_pct_rank2"]= df["basis"].rolling(480).rank(pct=True)

# H2: Funding carry signal — signed direction of carry
# positive funding = shorts are paid = bullish for shorts = bearish for price
df["fund_carry"]     = df["funding_rate"]               # signed: + = longs pay
df["fund_carry_abs"] = df["funding_rate"].abs()
df["fund_carry_sign"]= np.sign(df["funding_rate"])      # direction of pressure

# I1: Trapped positioning = funding sign vs price direction divergence
# funding > 0 AND price has been falling = longs trapped (continuation bearish)
# funding < 0 AND price has been rising  = shorts trapped (continuation bullish)
#
# IMPORTANT: ret_8h is a FORWARD return, so shift(1) gives near-future data.
# Past 8h return must be computed from close prices directly.
df["fund_sign"]          = np.sign(df["funding_rate"])
df["price_ret_8h_past"]  = df["close"].pct_change(480)          # close[T]/close[T-480]-1
df["price_ret_1h_past"]  = df["close"].pct_change(60)           # close[T]/close[T-60]-1
df["price_sign_8h"]      = np.sign(df["price_ret_8h_past"])     # direction of last 8h
df["trapped_long"]       = (df["fund_sign"] > 0) & (df["price_sign_8h"] < 0)
df["trapped_short"]      = (df["fund_sign"] < 0) & (df["price_sign_8h"] > 0)
# Scalar: +1 when trapped, -1 when trending with funding, 0 when funding≈0
df["trapped_score"]      = df["fund_sign"] * (-df["price_sign_8h"])

# I2: Funding saturation — extreme funding alone
df["fund_extreme_pos"] = (df["funding_pct_rank"] >= 0.90).astype(float)
df["fund_extreme_neg"] = (df["funding_pct_rank"] <= 0.10).astype(float)
df["fund_extreme"]     = df["fund_extreme_pos"] - df["fund_extreme_neg"]

# I3: Joint extreme — funding AND basis both pointing same direction
# Both signals say the same thing = stronger case for convergence
df["joint_extreme"]  = df["funding_zscore"] * df["basis_z"]   # positive = aligned

# Restrict 1m tests to settlement bars only for funding signals
fund["d1"] = fund["funding_rate"].diff()
fund["d2"] = fund["funding_rate"].diff().diff()
fund["level"] = fund["funding_rate"]
fund["exhaustion"] = -fund["level"] * fund["d2"]
settle_mask  = df.index.isin(fund.index)
settle_df    = df[settle_mask].copy()

# Rebuild splits after feature construction
train_df    = df[df.index < TRAIN_END]
val_df      = df[(df.index >= TRAIN_END) & (df.index < VAL_END)]
test_df     = df[df.index >= VAL_END]
s_train     = settle_df[settle_df.index < TRAIN_END]
s_oos       = settle_df[settle_df.index >= TRAIN_END]
RT = TAKER.round_trip_cost()

pr(f"\nTrain: {len(train_df):,}  Val: {len(val_df):,}  Test: {len(test_df):,}")
pr(f"Settlement train: {len(s_train):,}  OOS: {len(s_oos):,}")


# ══════════════════════════════════════════════════════════════════════════════
#  H1: BASIS DISLOCATION MEAN REVERSION
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("FAMILY 1 — ARBITRAGE-FORCED CONVERGENCE")
pr(BORDER)

pr("\n[H1a] Basis IC profile (all 1m bars, train)")
pr(f"  {'Signal':<22}  {'1m':>8} {'5m':>8} {'15m':>8} {'1h':>8} {'4h':>8} {'8h':>8}")
for label, col in [
    ("basis (raw)",      "basis"),
    ("basis_z",          "basis_z"),
    ("basis_pct_rank2",  "basis_pct_rank2"),
    ("|basis_z|",        "basis_abs_z"),
]:
    sig = train_df[col].values
    row = [spearman_ic(sig, train_df[rc].values)
           for rc in ["ret_1m","ret_5m","ret_15m","ret_1h","ret_4h","ret_8h"]]
    pr(f"  {label:<22}  " + " ".join(f"{v:>+8.5f}" for v in row))

pr("\n[H1b] Basis at settlement bars only (IC vs ret_8h)")
for label, col in [
    ("basis (raw)",     "basis"),
    ("basis_z",         "basis_z"),
    ("joint_extreme",   "joint_extreme"),
]:
    sig = s_train[col].values
    for rc in ["ret_1h","ret_4h","ret_8h"]:
        ic = spearman_ic(sig, s_train[rc].values)
        pr(f"  {label:<22}  vs {rc}: IC={ic:+.5f}")

pr("\n[H1c] Permutation test: basis vs ret_1h (all 1m bars)")
obs, pval, null = permutation_test(train_df["basis_z"].values, train_df["ret_1h"].values)
pr(f"  IC={obs:+.5f}  p={pval:.4f}  {obs/null.std():+.1f}s  null_std={null.std():.5f}")

pr("\n[H1d] Permutation test: basis vs ret_8h (settlement bars only)")
obs_s, pval_s, null_s = permutation_test(s_train["basis_z"].values, s_train["ret_8h"].values)
pr(f"  IC={obs_s:+.5f}  p={pval_s:.4f}  {obs_s/null_s.std():+.1f}s")

pr("\n[H1e] Block bootstrap: basis_z vs ret_1h (block=480=8h, B=1000)")
obs_b, pval_b, boot_b = block_bootstrap(
    train_df["basis_z"].values, train_df["ret_1h"].values, block=480, B=BOOT_B)
ci_lo, ci_hi = np.percentile(boot_b, [2.5, 97.5])
pr(f"  IC={obs_b:+.5f}  p={pval_b:.4f}  95%CI=[{ci_lo:+.5f},{ci_hi:+.5f}]")

pr("\n[H1f] Conditional IC by |basis| quartile (train, vs ret_1h)")
q_vals = train_df["basis_abs_z"].quantile([0.25, 0.5, 0.75, 1.0]).values
q_lo   = [0.0] + list(train_df["basis_abs_z"].quantile([0.25,0.5,0.75]).values)
for i, (lo_val, hi_val) in enumerate(zip(q_lo, q_vals)):
    mask = (train_df["basis_abs_z"] >= lo_val) & (train_df["basis_abs_z"] < hi_val)
    sub  = train_df[mask]
    ic   = spearman_ic(sub["basis_z"].values, sub["ret_1h"].values)
    pr(f"  |basis_z| Q{i+1} (n={mask.sum():>7,}) : IC(1h)={ic:+.5f}")

pr("\n[H1g] OOS walk-forward IC (basis_z vs ret_1h, 30-day windows)")
oos = pd.concat([val_df, test_df])
WINDOW, STEP = 30*1440, 7*1440
oos_ics = []
for i in range(0, len(oos) - WINDOW, STEP):
    w = oos.iloc[i:i+WINDOW]
    oos_ics.append(spearman_ic(w["basis_z"].values, w["ret_1h"].values))
oos_ics = np.array([x for x in oos_ics if np.isfinite(x)])
pr(f"  n_windows={len(oos_ics)}  mean_IC={oos_ics.mean():+.5f}  std={oos_ics.std():.5f}")
pr(f"  frac_same_dir={((oos_ics * obs_b) > 0).mean()*100:.1f}%  "
   f"95%CI=[{np.percentile(oos_ics,2.5):+.5f},{np.percentile(oos_ics,97.5):+.5f}]")


# ══════════════════════════════════════════════════════════════════════════════
#  H2: FUNDING CARRY (direction of carry pressure)
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("H2: FUNDING CARRY AS DIRECTIONAL SIGNAL (settlement bars)")
pr(BORDER)

pr("\n[H2a] IC profile: funding features vs forward returns (train, settlement bars)")
pr(f"  {'Signal':<26}  {'ret_1h':>8} {'ret_4h':>8} {'ret_8h':>8}")
for label, col in [
    ("fund_carry (raw)",       "funding_rate"),
    ("funding_pct_rank",       "funding_pct_rank"),
    ("funding_zscore",         "funding_zscore"),
    ("fund_extreme",           "fund_extreme"),
    ("fund_extreme_pos",       "fund_extreme_pos"),
]:
    sig = s_train[col].values
    row = [spearman_ic(sig, s_train[rc].values) for rc in ["ret_1h","ret_4h","ret_8h"]]
    pr(f"  {label:<26}  " + " ".join(f"{v:>+8.5f}" for v in row))

pr("\n[H2b] Permutation test: funding_pct_rank vs ret_8h (settlement bars)")
obs_f, pval_f, null_f = permutation_test(
    s_train["funding_pct_rank"].values, s_train["ret_8h"].values)
pr(f"  IC={obs_f:+.5f}  p={pval_f:.4f}  {obs_f/null_f.std():+.1f}s")

pr("\n[H2c] Conditional IC: top/bottom 10% vs 20% vs all funding (vs ret_8h)")
for gate_pct, label in [(0.90, "top/bot 10%"), (0.80, "top/bot 20%"), (0.70, "top/bot 30%"), (0.00, "all")]:
    if gate_pct == 0:
        mask = np.ones(len(s_train), dtype=bool)
    else:
        mask = (s_train["funding_pct_rank"] >= gate_pct) | (s_train["funding_pct_rank"] <= (1-gate_pct))
    sub = s_train[mask]
    ic  = spearman_ic(sub["funding_pct_rank"].values, sub["ret_8h"].values)
    pr(f"  {label:<15}  n={mask.sum():>4,}  IC(ret_8h)={ic:+.5f}")

pr("\n[H2d] OOS IC: funding_pct_rank vs ret_8h (settlement bars OOS)")
oos_settle_ics = []
WINDOW_S = 90*3  # 90 days × 3 settlements/day
STEP_S   = 30*3
for i in range(0, len(s_oos) - WINDOW_S, STEP_S):
    w = s_oos.iloc[i:i+WINDOW_S]
    oos_settle_ics.append(spearman_ic(w["funding_pct_rank"].values, w["ret_8h"].values))
oos_settle_ics = np.array([x for x in oos_settle_ics if np.isfinite(x)])
pr(f"  n_windows={len(oos_settle_ics)}  mean_IC={oos_settle_ics.mean():+.5f}  "
   f"std={oos_settle_ics.std():.5f}  frac_correct={(oos_settle_ics * obs_f > 0).mean()*100:.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  I1: TRAPPED POSITIONING (funding × price direction divergence)
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("FAMILY 2 — CROWDED-TRADE EXHAUSTION")
pr(BORDER)

pr("\n[I1a] Trapped positioning IC (train, settlement bars)")
pr(f"  {'Signal':<26}  {'ret_1h':>8} {'ret_4h':>8} {'ret_8h':>8}")
for label, col in [
    ("trapped_score",  "trapped_score"),
    ("joint_extreme",  "joint_extreme"),
]:
    sig = s_train[col].values
    row = [spearman_ic(sig, s_train[rc].values) for rc in ["ret_1h","ret_4h","ret_8h"]]
    pr(f"  {label:<26}  " + " ".join(f"{v:>+8.5f}" for v in row))

pr("\n[I1b] Trapped positioning at 1m level")
for label, col in [
    ("trapped_score",  "trapped_score"),
    ("joint_extreme",  "joint_extreme"),
]:
    sig = train_df[col].values
    row = [spearman_ic(sig, train_df[rc].values) for rc in ["ret_1h","ret_4h","ret_8h"]]
    pr(f"  {label:<26}  " + " ".join(f"{v:>+8.5f}" for v in row))

pr("\n[I1c] Permutation test: trapped_score vs ret_8h (settlement bars)")
obs_t, pval_t, null_t = permutation_test(
    s_train["trapped_score"].values, s_train["ret_8h"].values)
pr(f"  IC={obs_t:+.5f}  p={pval_t:.4f}  {obs_t/null_t.std():+.1f}s")

pr("\n[I1d] Joint extreme IC (fund × basis aligned)")
obs_j, pval_j, null_j = permutation_test(
    train_df["joint_extreme"].values, train_df["ret_1h"].values)
pr(f"  IC(1h, all 1m)={obs_j:+.5f}  p={pval_j:.4f}  {obs_j/null_j.std():+.1f}s")
obs_j8, pval_j8, _ = permutation_test(
    s_train["joint_extreme"].values, s_train["ret_8h"].values)
pr(f"  IC(8h, settle) ={obs_j8:+.5f}  p={pval_j8:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
#  I2: EXTREME FUNDING COMBINED WITH BASIS (top/bot 10% funding)
# ══════════════════════════════════════════════════════════════════════════════
pr("\n[I2] Extreme funding regime: IC by funding + basis quintile (train)")
pr("  (Only when funding is in top/bottom 10% — true crowding events)")
extreme_mask = (s_train["funding_pct_rank"] >= 0.90) | (s_train["funding_pct_rank"] <= 0.10)
sub_extreme  = s_train[extreme_mask]
pr(f"  Extreme funding events: {extreme_mask.sum()} of {len(s_train)} settlements ({extreme_mask.mean()*100:.1f}%)")
for rc in ["ret_1h","ret_4h","ret_8h"]:
    ic_f  = spearman_ic(sub_extreme["funding_pct_rank"].values, sub_extreme[rc].values)
    ic_b  = spearman_ic(sub_extreme["basis_z"].values, sub_extreme[rc].values)
    ic_j  = spearman_ic(sub_extreme["joint_extreme"].values, sub_extreme[rc].values)
    pr(f"  {rc}: fund_rank IC={ic_f:+.5f}  basis_z IC={ic_b:+.5f}  joint IC={ic_j:+.5f}")

# How does the extreme funding IC compare to what's needed?
pr("\n[I3] Breakeven analysis (settlement-level, 8h horizon)")
sigma_8h = float(s_train["ret_8h"].std())
ic_bk_8h = RT / (sigma_8h * np.sqrt(2/np.pi))
best_ic   = max(
    abs(spearman_ic(s_train["funding_pct_rank"].values, s_train["ret_8h"].values)),
    abs(spearman_ic(sub_extreme["funding_pct_rank"].values, sub_extreme["ret_8h"].values)),
    abs(spearman_ic(s_train["joint_extreme"].values, s_train["ret_8h"].values)),
)
pr(f"  sigma_8h = {sigma_8h*100:.4f}%  IC_breakeven = {ic_bk_8h:.4f}")
pr(f"  Best IC found (across funding signals) = {best_ic:.5f}")
pr(f"  Ratio = {best_ic/ic_bk_8h:.3f}x  (need 1.0x to break even at taker costs)")
pr(f"  At MAKER costs: IC_bk = {TAKER.__class__(use_maker=True).round_trip_cost()/(sigma_8h*np.sqrt(2/np.pi)):.4f}")

pr("\n[I4] Breakeven analysis (1m level, basis_z, 1h horizon)")
sigma_1h = float(train_df["ret_1h"].std())
ic_bk_1h = RT / (sigma_1h * np.sqrt(2/np.pi))
ic_basis_1h = abs(spearman_ic(train_df["basis_z"].values, train_df["ret_1h"].values))
pr(f"  sigma_1h = {sigma_1h*100:.4f}%  IC_breakeven = {ic_bk_1h:.4f}")
pr(f"  IC(basis_z, ret_1h) = {ic_basis_1h:.5f}")
pr(f"  Ratio = {ic_basis_1h/ic_bk_1h:.3f}x")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SUMMARY — MECHANISM-DRIVEN SIGNALS")
pr(BORDER)
pr(f"  {'Signal':<35} {'Best IC':>8} {'Horizon':>8} {'p-val':>7} {'vs BEven':>9}")

rows = [
    ("Basis dislocation (basis_z)",       obs_b,  "1h",   pval_b,   ic_bk_1h),
    ("Basis at settlement (basis_z)",      obs_s,  "8h",   pval_s,   ic_bk_8h),
    ("Funding pct_rank",                   obs_f,  "8h",   pval_f,   ic_bk_8h),
    ("Trapped positioning",                obs_t,  "8h",   pval_t,   ic_bk_8h),
    ("Joint extreme (fund x basis)",       obs_j8, "8h",   pval_j8,  ic_bk_8h),
]
for label, ic, hz, pval, bk in rows:
    ratio = abs(ic)/bk if bk > 0 else np.nan
    pr(f"  {label:<35} {ic:>+8.5f} {hz:>8}  {pval:>6.4f}  {ratio:>8.3f}x")

out_path = RESULTS / "signal_mechanism_tests.txt"
out_path.write_text("\n".join(out_lines), encoding="utf-8")
pr(f"\nSaved: {out_path}")
