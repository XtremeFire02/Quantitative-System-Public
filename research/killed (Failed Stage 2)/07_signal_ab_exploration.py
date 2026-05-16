"""
Signal A: Funding Rate Curvature  (d²F/dt² — sentiment exhaustion)
Signal B: Informed Flow           (trade-size z-score × quote-OFI)

Exploratory hypothesis testing before building strategy models.
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
RAW     = Path("data/raw")
RESULTS = Path("results")
RESULTS.mkdir(exist_ok=True)

MAX_SAMP  = 50_000   # subsample cap for permutation / bootstrap (speed)
N_PERMS   = 2_000
BOOT_B    = 1_000
BORDER    = "=" * 72

out_lines = []
def pr(*args):
    line = " ".join(str(a) for a in args)
    # replace unicode minus with ascii minus to avoid cp1252 issues
    line = line.replace("−", "-")
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    out_lines.append(line)


# ── fast IC helpers ────────────────────────────────────────────────────────────

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
    m     = np.isfinite(x) & np.isfinite(y)
    xc, yc = x[m], y[m]
    obs   = spearman_ic(xc, yc)
    xs, ys = _subsample(xc, yc, rng)
    ry    = sp_stats.rankdata(ys).astype(np.float64); ry -= ry.mean()
    ryn   = np.sqrt((ry**2).sum())
    def _ic():
        rx = sp_stats.rankdata(rng.permutation(xs)).astype(np.float64)
        rx -= rx.mean()
        d  = np.sqrt((rx**2).sum()) * ryn
        return float(np.dot(rx, ry) / d) if d > 0 else 0.0
    null = np.array([_ic() for _ in range(n_perms)])
    return obs, float((np.abs(null) >= abs(obs)).mean()), null

def block_bootstrap(x, y, block, B=BOOT_B, seed=0):
    rng  = np.random.default_rng(seed)
    m    = np.isfinite(x) & np.isfinite(y)
    xc, yc = x[m], y[m]
    obs  = spearman_ic(xc, yc)
    xs, ys = _subsample(xc, yc, rng)
    N    = len(xs)
    boot = np.empty(B)
    for b in range(B):
        nb  = int(np.ceil(N / block))
        idx = []
        for _ in range(nb):
            s = rng.integers(0, N)
            idx.extend([(s + k) % N for k in range(block)])
        boot[b] = spearman_ic(xs[idx[:N]], ys)
    return obs, float((np.abs(boot) >= abs(obs)).mean()), boot


# ══════════════════════════════════════════════════════════════════════════════
#  LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════
pr("Loading data...")
df   = pd.read_parquet(PROC / "ofi.parquet")
fund = pd.read_parquet(RAW  / "BTCUSDT_funding.parquet")

# Normalise funding index (some timestamps have millisecond offsets)
fund.index = fund.index.floor("min")
fund = fund[~fund.index.duplicated(keep="first")]
fund = fund.sort_index()
fund = fund.rename(columns={"fundingRate": "funding_rate"})

train_df, val_df, test_df = split(df)
pr(f"Train: {len(train_df):,} bars | Val: {len(val_df):,} | Test: {len(test_df):,}")


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL A — FUNDING RATE CURVATURE
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL A: FUNDING RATE CURVATURE")
pr(BORDER)

# ── Build 8h-level dataset ────────────────────────────────────────────────────
fund["d1"]         = fund["funding_rate"].diff()
fund["d2"]         = fund["funding_rate"].diff().diff()       # raw curvature
fund["level"]      = fund["funding_rate"]

# Exhaustion: high/low funding that is DECELERATING (sentiment running out of steam)
# Signal > 0  when:  positive funding AND d2 < 0  (crowd exhausting upward)
#                    negative funding AND d2 > 0  (crowd exhausting downward)
# i.e.  exhaustion = - level × d2  ... positive means: big level, opposite d2
fund["exhaustion"] = -fund["level"] * fund["d2"]

# Forward-filled onto 1m bars
df["fund_level"]      = fund["funding_rate"].reindex(df.index, method="ffill")
df["fund_d1"]         = fund["d1"].reindex(df.index, method="ffill")
df["fund_d2"]         = fund["d2"].reindex(df.index, method="ffill")
df["fund_exhaustion"] = fund["exhaustion"].reindex(df.index, method="ffill")

# 8h-ahead return already in df ("ret_8h"); also derive 24h return
# ret_24h = sum of three consecutive 8h returns approximated as:
df["ret_24h"] = df["ret_8h"].rolling(3, min_periods=3).sum().shift(-(3*480 - 480))
# Simpler: use existing 4h/8h
pr(f"Funding events available: {fund.shape[0]:,}")
pr(f"  d2 range: [{fund['d2'].min():.6f}, {fund['d2'].max():.6f}]")
pr(f"  exhaustion mean: {fund['exhaustion'].mean():.6e}  std: {fund['exhaustion'].std():.6e}")

# ── Restrict to SETTLEMENT BARS (every 480 1m bars) for clean 8h-level tests ─
settle_mask = df.index.isin(fund.index)
settle_df   = df[settle_mask].copy()
pr(f"Settlement bars in train/val/test: "
   f"{(settle_df.index < TRAIN_END).sum()} / "
   f"{((settle_df.index >= TRAIN_END) & (settle_df.index < VAL_END)).sum()} / "
   f"{(settle_df.index >= VAL_END).sum()}")

settle_train = settle_df[settle_df.index < TRAIN_END]

# ── IC profile across horizons ────────────────────────────────────────────────
pr("\n[A1] IC profile — Signal A features vs forward returns (train, settlement bars)")
pr(f"  {'Signal':<22} {'ret_1h':>8} {'ret_4h':>8} {'ret_8h':>8}")

for sig_name, sig_col in [
    ("d2 (raw curvature)",  "fund_d2"),
    ("exhaustion (−L×d2)", "fund_exhaustion"),
    ("d1 (momentum)",       "fund_d1"),
]:
    sig  = settle_train[sig_col].values
    ics  = []
    for ret_col in ["ret_1h", "ret_4h", "ret_8h"]:
        ret = settle_train[ret_col].values
        ics.append(spearman_ic(sig, ret))
    pr(f"  {sig_name:<22} {ics[0]:>+8.5f} {ics[1]:>+8.5f} {ics[2]:>+8.5f}")

# ── Permutation test on best signal ──────────────────────────────────────────
pr("\n[A2] Permutation test — exhaustion signal vs ret_8h (train settlement bars)")
sig_a = settle_train["fund_exhaustion"].values
ret_a = settle_train["ret_8h"].values
obs_a, pval_a, null_a = permutation_test(sig_a, ret_a)
pr(f"  Observed IC: {obs_a:+.5f}")
pr(f"  Perm p-val:  {pval_a:.5f}")
pr(f"  Null 95% CI: [{np.percentile(null_a,2.5):+.5f}, {np.percentile(null_a,97.5):+.5f}]")
pr(f"  IC / null_std = {obs_a / null_a.std():.2f}σ")

# ── Block bootstrap ───────────────────────────────────────────────────────────
pr("\n[A3] Block bootstrap — exhaustion signal vs ret_8h (block=3 settlements = 24h)")
obs_ab, pval_ab, boot_ab = block_bootstrap(sig_a, ret_a, block=3, B=BOOT_B)
pr(f"  Observed IC: {obs_ab:+.5f}  boot-p: {pval_ab:.5f}")
pr(f"  Boot 95% CI: [{np.percentile(boot_ab,2.5):+.5f}, {np.percentile(boot_ab,97.5):+.5f}]")

# ── Conditional IC: does curvature add information beyond funding level? ──────
pr("\n[A4] Conditional IC — does d2 add power beyond funding level alone?")
for thresh_pct in [0.50, 0.66, 0.75]:
    # Only look at bars where |funding| is in the top (1-thresh) of its distribution
    thresh = np.nanpercentile(np.abs(settle_train["fund_level"].values), thresh_pct * 100)
    extreme_mask = np.abs(settle_train["fund_level"].values) >= thresh
    sig_sub = settle_train["fund_exhaustion"].values[extreme_mask]
    ret_sub = settle_train["ret_8h"].values[extreme_mask]
    ic_sub  = spearman_ic(sig_sub, ret_sub)
    ic_full = spearman_ic(settle_train["fund_exhaustion"].values,
                          settle_train["ret_8h"].values)
    pr(f"  |funding| > {thresh_pct*100:.0f}th pct  n={extreme_mask.sum():,}  "
       f"IC={ic_sub:+.5f}  vs unconditional={ic_full:+.5f}")

# ── OOS IC (val + test settlement bars) ──────────────────────────────────────
pr("\n[A5] Walk-forward OOS IC — exhaustion signal vs ret_8h (val + test, 90-day windows)")
oos_settle = settle_df[settle_df.index >= TRAIN_END].copy()
WINDOW_8H  = 90 * 3  # 90 days × 3 settlements/day = 270 settlements
STEP_8H    = 30 * 3  # re-evaluate every 30 days
oos_ics_a  = []
for i in range(0, len(oos_settle) - WINDOW_8H, STEP_8H):
    w   = oos_settle.iloc[i: i + WINDOW_8H]
    ic  = spearman_ic(w["fund_exhaustion"].values, w["ret_8h"].values)
    oos_ics_a.append(ic)
oos_ics_a = np.array([x for x in oos_ics_a if np.isfinite(x)])
pr(f"  OOS windows: {len(oos_ics_a)}")
pr(f"  Mean IC:   {oos_ics_a.mean():+.5f}  Std: {oos_ics_a.std():.5f}")
pr(f"  Frac correct direction: {(oos_ics_a > 0).mean()*100:.1f}%")
pr(f"  95% CI: [{np.percentile(oos_ics_a,2.5):+.5f}, {np.percentile(oos_ics_a,97.5):+.5f}]")

# ── Also test at 1m level using forward-filled signal ────────────────────────
# Rebuild splits so Signal A columns are visible
train_df = df[df.index < TRAIN_END]
val_df   = df[(df.index >= TRAIN_END) & (df.index < VAL_END)]
test_df  = df[df.index >= VAL_END]

pr("\n[A6] 1m-bar IC profile (forward-filled exhaustion signal, train set)")
sig_1m_a = train_df["fund_exhaustion"].values
for hz, ret_col in [("5m", "ret_5m"), ("15m", "ret_15m"), ("1h", "ret_1h"), ("4h", "ret_4h")]:
    ret = train_df[ret_col].values
    ic  = spearman_ic(sig_1m_a, ret)
    pr(f"  ret_{hz}: IC={ic:+.6f}")


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL B — INFORMED FLOW  (trade-size z-score × quote-OFI)
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL B: INFORMED FLOW (TRADE-SIZE Z × QUOTE-OFI)")
pr(BORDER)

# ── Feature construction ──────────────────────────────────────────────────────
df["avg_trade_usd"]  = df["quote_volume"] / df["trade_count"].replace(0, np.nan)
df["ofi_quote"]      = df["taker_buy_quote_volume"] / df["quote_volume"].replace(0, np.nan) - 0.5
df["trade_size_z60"] = (
    (df["avg_trade_usd"] - df["avg_trade_usd"].rolling(60).mean()) /
    df["avg_trade_usd"].rolling(60).std()
)
df["trade_size_z300"] = (
    (df["avg_trade_usd"] - df["avg_trade_usd"].rolling(300).mean()) /
    df["avg_trade_usd"].rolling(300).std()
)
# Primary signal: informed flow = large trade × direction
df["informed_flow_60"]  = df["trade_size_z60"]  * df["ofi_quote"]
df["informed_flow_300"] = df["trade_size_z300"] * df["ofi_quote"]

# Smoothed versions
df["informed_flow_60_s5"]  = df["informed_flow_60"].rolling(5).mean()
df["informed_flow_60_s15"] = df["informed_flow_60"].rolling(15).mean()

# Kurtosis of avg_trade_usd (fat tail = clustering of large trades)
df["trade_size_kurt60"]  = df["avg_trade_usd"].rolling(60).kurt()
df["trade_size_kurt300"] = df["avg_trade_usd"].rolling(300).kurt()

# Rebuild train split (new columns)
train_df = df[df.index < TRAIN_END]

pr("  Features constructed:")
for col in ["avg_trade_usd", "ofi_quote", "trade_size_z60",
            "informed_flow_60", "informed_flow_60_s5", "trade_size_kurt60"]:
    s = df[col].dropna()
    pr(f"    {col:<28} mean={s.mean():+.4f}  std={s.std():.4f}  "
       f"skew={s.skew():.2f}  NaN={df[col].isna().mean()*100:.1f}%")

# ── IC profile across horizons ────────────────────────────────────────────────
pr("\n[B1] IC profile — Signal B features vs forward returns (train, 1m bars)")
pr(f"  {'Signal':<32} {'1m':>8} {'5m':>8} {'15m':>8} {'1h':>8}")

signals_b = [
    ("informed_flow_60",      "informed_flow_60"),
    ("informed_flow_60_s5",   "informed_flow_60_s5"),
    ("informed_flow_60_s15",  "informed_flow_60_s15"),
    ("informed_flow_300",     "informed_flow_300"),
    ("trade_size_z60",        "trade_size_z60"),
    ("ofi_quote (baseline)",  "ofi_quote"),
    ("trade_size_kurt60",     "trade_size_kurt60"),
]

for label, col in signals_b:
    sig  = train_df[col].values
    row  = []
    for ret_col in ["ret_1m", "ret_5m", "ret_15m", "ret_1h"]:
        row.append(spearman_ic(sig, train_df[ret_col].values))
    pr(f"  {label:<32} {row[0]:>+8.5f} {row[1]:>+8.5f} {row[2]:>+8.5f} {row[3]:>+8.5f}")

# ── IC vs absolute returns (volatility prediction) ────────────────────────────
pr("\n[B2] IC vs |ret| — does trade-size kurtosis predict volatility?")
abs_ret_1h = np.abs(train_df["ret_1h"].values)
for label, col in [
    ("trade_size_kurt60",  "trade_size_kurt60"),
    ("trade_size_kurt300", "trade_size_kurt300"),
    ("trade_size_z60",     "trade_size_z60"),
    ("informed_flow_60",   "informed_flow_60"),
]:
    ic = spearman_ic(train_df[col].values, abs_ret_1h)
    pr(f"  {label:<28} IC vs |ret_1h| = {ic:+.5f}")

# ── Permutation tests ─────────────────────────────────────────────────────────
pr(f"\n[B3] Permutation tests (H0: IC=0, {N_PERMS} perms, subsample {MAX_SAMP:,})")
for label, col, ret_col in [
    ("informed_flow_60  vs ret_5m",  "informed_flow_60",  "ret_5m"),
    ("informed_flow_60  vs ret_15m", "informed_flow_60",  "ret_15m"),
    ("informed_flow_60  vs ret_1h",  "informed_flow_60",  "ret_1h"),
    ("informed_flow_s5  vs ret_5m",  "informed_flow_60_s5",  "ret_5m"),
    ("trade_size_z60    vs ret_5m",  "trade_size_z60",    "ret_5m"),
    ("trade_size_kurt60 vs |ret_1h|","trade_size_kurt60", "ret_1h"),
]:
    sig_b = train_df[col].values
    if col == "trade_size_kurt60":
        ret   = np.abs(train_df[ret_col].values)
    else:
        ret   = train_df[ret_col].values
    obs, pval, null = permutation_test(sig_b, ret)
    n_sigma = obs / null.std() if null.std() > 0 else np.nan
    pr(f"  {label:<40} IC={obs:+.5f}  p={pval:.4f}  {n_sigma:.1f}σ")

# ── Block bootstrap on primary signal ────────────────────────────────────────
pr(f"\n[B4] Block bootstrap — informed_flow_60 vs ret_5m (block=30, B={BOOT_B})")
sig_b = train_df["informed_flow_60"].values
ret_b = train_df["ret_5m"].values
obs_b1, pval_b1, boot_b1 = block_bootstrap(sig_b, ret_b, block=30)
pr(f"  Observed IC: {obs_b1:+.5f}  boot-p: {pval_b1:.5f}")
pr(f"  Boot 95% CI: [{np.percentile(boot_b1,2.5):+.5f}, {np.percentile(boot_b1,97.5):+.5f}]")
pr(f"  IC / boot_std = {obs_b1 / boot_b1.std():.1f}σ")

pr(f"\n[B5] Block bootstrap — informed_flow_60 vs ret_1h (block=60, B={BOOT_B})")
ret_b2 = train_df["ret_1h"].values
obs_b2, pval_b2, boot_b2 = block_bootstrap(sig_b, ret_b2, block=60)
pr(f"  Observed IC: {obs_b2:+.5f}  boot-p: {pval_b2:.5f}")
pr(f"  Boot 95% CI: [{np.percentile(boot_b2,2.5):+.5f}, {np.percentile(boot_b2,97.5):+.5f}]")
pr(f"  IC / boot_std = {obs_b2 / boot_b2.std():.1f}σ")

# ── Walk-forward OOS IC ────────────────────────────────────────────────────────
pr("\n[B6] Walk-forward OOS IC — informed_flow_60 vs ret_5m (30-day windows, val+test)")
oos_df_b = pd.concat([val_df, test_df]).copy()
for col in ["avg_trade_usd", "ofi_quote", "trade_size_z60", "informed_flow_60"]:
    oos_df_b[col] = df[col].reindex(oos_df_b.index)

ROLL_W_B = 30 * 24 * 60
STEP_B   = 24 * 60
oos_ics_b = []
for i in range(0, len(oos_df_b) - ROLL_W_B, STEP_B):
    w  = oos_df_b.iloc[i: i + ROLL_W_B]
    ic = spearman_ic(w["informed_flow_60"].values, w["ret_5m"].values)
    oos_ics_b.append(ic)
oos_ics_b = np.array([x for x in oos_ics_b if np.isfinite(x)])
pr(f"  OOS windows: {len(oos_ics_b)}")
pr(f"  Mean IC:   {oos_ics_b.mean():+.5f}  Std: {oos_ics_b.std():.5f}")
pr(f"  Frac correct direction: {(oos_ics_b > 0).mean()*100:.1f}%")
pr(f"  95% CI: [{np.percentile(oos_ics_b,2.5):+.5f}, {np.percentile(oos_ics_b,97.5):+.5f}]")

pr("\n[B7] Walk-forward OOS IC — informed_flow_60 vs ret_1h (30-day windows)")
oos_ics_b1h = []
for i in range(0, len(oos_df_b) - ROLL_W_B, STEP_B):
    w  = oos_df_b.iloc[i: i + ROLL_W_B]
    ic = spearman_ic(w["informed_flow_60"].values, w["ret_1h"].values)
    oos_ics_b1h.append(ic)
oos_ics_b1h = np.array([x for x in oos_ics_b1h if np.isfinite(x)])
pr(f"  OOS windows: {len(oos_ics_b1h)}")
pr(f"  Mean IC:   {oos_ics_b1h.mean():+.5f}  Std: {oos_ics_b1h.std():.5f}")
pr(f"  Frac correct direction: {(oos_ics_b1h > 0).mean()*100:.1f}%")

# ── Lead-lag profile ───────────────────────────────────────────────────────────
pr("\n[B8] Lead-lag profile — informed_flow_60 vs future ret at lags 0..60 bars")
sig_b_arr = train_df["informed_flow_60"].values
ret_arr   = train_df["ret_1m"].values
for lag in [0, 1, 2, 5, 10, 15, 30, 60]:
    r_lag = np.roll(ret_arr, -lag)
    if lag > 0:
        r_lag[-lag:] = np.nan
    ic = spearman_ic(sig_b_arr, r_lag)
    pr(f"  lag={lag:3d}  IC(informed_flow_60, ret[t+{lag}]) = {ic:+.6f}")

# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL A+B COMBINED
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SIGNAL A+B: COMBINED ANALYSIS")
pr(BORDER)

# Correlation between A and B signals in train set
df_combo = train_df[["fund_exhaustion", "informed_flow_60",
                      "ret_1h", "ret_5m", "ret_8h"]].dropna()
rho_ab = sp_stats.spearmanr(df_combo["fund_exhaustion"],
                              df_combo["informed_flow_60"]).statistic
pr(f"\n[C1] Spearman correlation between Signal A and Signal B: {rho_ab:+.5f}")
pr(f"     (Low correlation = signals are complementary)")

# Combined signal: standardise both and average
for col in ["fund_exhaustion", "informed_flow_60"]:
    s = df_combo[col]
    df_combo[col + "_z"] = (s - s.mean()) / s.std()
df_combo["combo_signal"] = (df_combo["fund_exhaustion_z"] +
                             df_combo["informed_flow_60_z"]) / 2.0

pr("\n[C2] IC of combined signal vs returns (train set):")
for ret_col in ["ret_5m", "ret_1h", "ret_8h"]:
    ic_a    = spearman_ic(df_combo["fund_exhaustion"].values,
                          df_combo[ret_col].values)
    ic_b    = spearman_ic(df_combo["informed_flow_60"].values,
                          df_combo[ret_col].values)
    ic_ab   = spearman_ic(df_combo["combo_signal"].values,
                          df_combo[ret_col].values)
    pr(f"  {ret_col}: A={ic_a:+.5f}  B={ic_b:+.5f}  A+B={ic_ab:+.5f}")

# Breakeven analysis
pr(f"\n[C3] Breakeven IC analysis (taker costs = {TAKER.round_trip_cost()*100:.2f}%)")
for hz, ret_col in [("5m", "ret_5m"), ("15m", "ret_15m"), ("1h", "ret_1h"), ("4h", "ret_4h")]:
    sig_vals  = df[ret_col].dropna()
    sigma_ret = float(sig_vals.std())
    ez        = 1.4  # E[|z(signal)|] at 80th pct entry
    gross_edge_at_ic01 = 0.10 * sigma_ret * ez
    breakeven_ic = TAKER.round_trip_cost() / (sigma_ret * ez)
    pr(f"  horizon={hz:3s}  σ_ret={sigma_ret*100:.4f}%  "
       f"IC_breakeven={breakeven_ic:.4f}  "
       f"(need IC>{breakeven_ic:.4f} to profit after {TAKER.round_trip_cost()*100:.2f}% RT cost)")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
pr(f"\n{BORDER}")
pr("SUMMARY")
pr(BORDER)

pr("""
Signal A (Funding Rate Curvature / Exhaustion):
  Tests whether d²F/dt² — the acceleration of funding sentiment — predicts
  returns at the 8h settlement frequency. The 'exhaustion' signal
  (−level × d²F) encodes when extreme funding is starting to reverse.

Signal B (Informed Flow):
  Tests whether unusually large trades in a direction (trade_size_z × quote-OFI)
  predict short-term returns. This is a proxy for institutional/informed order
  flow that bypasses the noise in retail taker flow.

Combined:
  If A and B are uncorrelated, combining them may produce a signal with
  higher IC (closer to the breakeven threshold for profitable trading).
""")

Path("results/killed/signal_ab_exploration.txt").write_text(
    "\n".join(out_lines), encoding="utf-8")
pr("Saved: results/killed/signal_ab_exploration.txt")
