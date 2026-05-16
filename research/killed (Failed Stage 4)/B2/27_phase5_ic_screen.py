"""
Phase 5 -- IC Screen: Novel High-Frequency Inefficiencies
==========================================================

Three genuinely new signals, each from a different part of market structure.
None overlap mechanistically with N3, P3, or the killed Phase 1-4 signals.

S1  Realized Skewness Reversal
    5-day realized skewness of 1m returns. When the return distribution
    develops a fat left tail (persistent asymmetric selling), then rapidly
    normalises, it signals fear exhaustion before a bounce. Contrarian on
    skewness level; momentum on skewness velocity (rate of reversion).
    Academic backing: Harvey & Siddique (2000), Amaya et al. (2015),
    Neuberger (2012). Unused in killed phases. Data: existing 1m klines.

S2  Pre-Settlement Signed Flow
    At each 8h Binance funding settlement (00:00/08:00/16:00 UTC), longs
    paying a negative rate rush to exit in the 30-60 minutes prior. This
    creates measurable taker-sell pressure that exhausts AT settlement --
    post-settlement the selling stops and the market rebounds. Signal =
    pre-settlement net sell imbalance conditioned on negative funding.
    Different from killed H1 (basis at settlement, 30s window, infeasible)
    -- S2 uses a 30-min window and only trades AFTER settlement, not at it.
    Data: existing 1m klines + funding.

S3  Cross-Exchange Funding Divergence
    When Bybit or OKX funding rates diverge from Binance, different trader
    populations are expressing different directional views. The divergence
    predicts which market corrects toward the other. Not pure carry (which
    is arb'd) -- the DIFFERENCE between exchanges is structurally harder
    to arbitrage (requires simultaneous positions across venues).
    Academic backing: Makarov & Schoar (2020) on crypto exchange price
    differences. Data: Bybit + OKX funding (download_phase5.py).

Signal variants tested:
  S1a  Realised skewness level (contrarian: negative skew -> long)
  S1b  Skewness velocity (rate of change from negative: higher -> long)
  S2a  Pre-settlement sell flow * (-funding_rate): positive when selling into negative funding
  S2b  Pre-settlement sell flow alone (pure microstructure contrarian)
  S3a  Bybit - Binance divergence z-score
  S3b  OKX - Binance divergence z-score
  S3c  Max(Bybit, OKX) - Binance divergence (combined cross-exchange view)

Hold periods tested: 4h (high-frequency target), 8h, 24h.
Pass criteria: same gates as N3 / P3 / Q5c.

Run from repo root:
  python research/active/p5/27_phase5_ic_screen.py
"""
from __future__ import annotations
import sys, io, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.costs import CostModel

RAW       = Path("data/raw")
MAKER     = CostModel(use_maker=True)
MAKER_RT  = MAKER.round_trip_cost()   # 0.0006 = 6 bp
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_START = TRAIN_END
SEP       = "=" * 72

OOS_PERIODS = [
    ("OOS 2024-H1",  "2024-01-01", "2024-07-01"),
    ("OOS 2024-H2",  "2024-07-01", "2025-01-01"),
    ("OOS 2025-H1",  "2025-01-01", "2025-07-01"),
    ("OOS 2025-H2",  "2025-07-01", "2026-01-01"),
    ("OOS 2026-YTD", "2026-01-01", "2027-01-01"),
]


# ── Statistical helpers ───────────────────────────────────────────────────────

def ic_with_p(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return np.nan, np.nan, 0
    r, p = sp_stats.spearmanr(x[m], y[m])
    return float(r), float(p), int(m.sum())


def breakeven_ic(y, cost=None):
    if cost is None:
        cost = MAKER_RT
    s = float(np.nanstd(y))
    return cost / (s * np.sqrt(2.0 / np.pi)) if s > 0 else np.nan


def ic_ratio(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return np.nan, np.nan
    ic_v  = float(sp_stats.spearmanr(x[m], y[m]).statistic)
    bk    = breakeven_ic(y[m])
    ratio = abs(ic_v) / bk if (bk and bk > 0) else np.nan
    return ic_v, ratio


def block_bootstrap_p(x, y, n_boot=2000, block=21, seed=42):
    m = np.isfinite(x) & np.isfinite(y)
    xi, yi = x[m], y[m]
    n = len(xi)
    if n < block * 2:
        return np.nan
    obs      = float(sp_stats.spearmanr(xi, yi).statistic)
    rng      = np.random.default_rng(seed)
    n_blocks = (n // block) + 2
    null     = np.empty(n_boot)
    for i in range(n_boot):
        idx     = np.concatenate([
            np.arange(s, min(s + block, n))
            for s in rng.integers(0, n - block + 1, size=n_blocks)
        ])[:n]
        null[i] = float(sp_stats.spearmanr(xi[idx], yi).statistic)
    return float((null >= obs).mean())


def screen_signal(label, signal_col, daily, oos, n3z_col="n3z"):
    """Full IC screen: unfiltered, sub-period, DVOL-filtered, incremental."""
    print()
    print(SEP)
    print(f"=== {label} ===")
    print(SEP)

    x_oos = np.array(oos[signal_col])
    y_oos = np.array(oos["r24h_net"])

    # 1. Full OOS
    ic_v, ratio = ic_ratio(x_oos, y_oos)
    p_v = block_bootstrap_p(x_oos, y_oos)
    bk  = breakeven_ic(y_oos[np.isfinite(y_oos)])
    n   = np.sum(np.isfinite(x_oos) & np.isfinite(y_oos))
    dir_ok = ic_v is not None and ic_v > 0

    print()
    print(f"--- 1. FULL OOS IC (n={n}) ---")
    print(f"  IC          : {ic_v:+.4f}  (positive = expected direction)")
    print(f"  IC*         : {bk:+.4f}  (breakeven)")
    print(f"  Ratio       : {ratio:.3f}x")
    print(f"  Bootstrap p : {p_v:.4f}  (one-sided, B=2000, block=21d)")
    unfiltered_pass = dir_ok and ratio is not None and ratio > 0.5
    print(f"  Unfiltered  : {'PASS' if unfiltered_pass else 'FAIL'}")

    # 2. Sub-period stability
    print()
    print(f"--- 2. SUB-PERIOD IC TABLE ---")
    print(f"  {'Period':<18} {'n':>5}  {'IC':>8}  {'p':>8}  {'Ratio':>8}  Dir")
    print(f"  {'-'*60}")
    n_oos_correct = 0
    for per_label, s, e in [("Train 2023", "2023-01-01", "2024-01-01")] + [(l, s, e) for l, s, e in OOS_PERIODS]:
        sub = daily[(daily.index >= s) & (daily.index < e)][
            [signal_col, "r24h_net"]
        ].dropna()
        if len(sub) < 15:
            continue
        ic_s, ratio_s = ic_ratio(np.array(sub[signal_col]), np.array(sub["r24h_net"]))
        p_s = block_bootstrap_p(np.array(sub[signal_col]), np.array(sub["r24h_net"]), n_boot=1000)
        d = "OK" if ic_s is not None and ic_s > 0 else "XX"
        print(f"  {per_label:<18} {len(sub):>5}  {ic_s:>+8.4f}  {p_s:>8.4f}  {ratio_s:>7.3f}x  {d}")
        if "OOS" in per_label and ic_s is not None and ic_s > 0:
            n_oos_correct += 1
    print(f"  Direction stability: {n_oos_correct}/{len(OOS_PERIODS)} OOS periods correct")

    # 3. DVOL >= 54 filter
    print()
    print(f"--- 3. DVOL >= 54 REGIME FILTER ---")
    oos_f = oos[oos["dvol"] >= 54]
    if len(oos_f) >= 30:
        xf = np.array(oos_f[signal_col])
        yf = np.array(oos_f["r24h_net"])
        ic_f, ratio_f = ic_ratio(xf, yf)
        p_f = block_bootstrap_p(xf, yf)
        filtered_pass = (ic_f is not None and ic_f > 0 and
                         ratio_f is not None and ratio_f > 1.0 and
                         p_f <= 0.05)
        print(f"  n (DVOL>=54) : {len(oos_f)}")
        print(f"  IC (filtered): {ic_f:+.4f}")
        print(f"  Ratio        : {ratio_f:.3f}x")
        print(f"  p-boot       : {p_f:.4f}")
        print(f"  Filtered     : {'PASS' if filtered_pass else 'FAIL'}  (need IC>0, ratio>1.0, p<=0.05)")
    else:
        ic_f = ratio_f = p_f = np.nan
        filtered_pass = False
        print(f"  Too few obs in DVOL>=54 regime ({len(oos_f)})")

    # 4. Hold-period comparison (4h, 8h, 24h)
    print()
    print(f"--- 4. HOLD-PERIOD IC TABLE ---")
    print(f"  {'Hold':<6} {'IC':>8}  {'Ratio':>8}  {'p-boot':>8}")
    print(f"  {'-'*38}")
    for col, lbl in [("r4h_net", "4h"), ("r8h_net", "8h"), ("r24h_net", "24h")]:
        if col not in oos.columns:
            continue
        sub = oos[[signal_col, col]].dropna()
        if len(sub) < 15:
            continue
        ic_h, ratio_h = ic_ratio(np.array(sub[signal_col]), np.array(sub[col]))
        p_h = block_bootstrap_p(np.array(sub[signal_col]), np.array(sub[col]))
        print(f"  {lbl:<6} {ic_h:>+8.4f}  {ratio_h:>7.3f}x  {p_h:>8.4f}")

    # 5. Incremental IC vs N3z
    print()
    print(f"--- 5. INCREMENTAL IC (residualised on N3z, OOS) ---")
    m_both = np.isfinite(x_oos) & np.isfinite(oos[n3z_col].values)
    if m_both.sum() >= 20:
        from numpy.polynomial import polynomial as P
        sig_m   = x_oos[m_both]
        n3z_m   = oos[n3z_col].values[m_both]
        ret_m   = y_oos[m_both]
        coeffs  = np.polyfit(n3z_m, sig_m, 1)
        resid   = sig_m - (coeffs[0] * n3z_m + coeffs[1])
        ic_incr, ratio_incr = ic_ratio(resid, ret_m)
        corr_n3z = float(sp_stats.spearmanr(sig_m, n3z_m).statistic)
        ic_n3z, ratio_n3z   = ic_ratio(n3z_m, ret_m)
        print(f"  N3z IC         : {ic_n3z:+.4f}  ratio={ratio_n3z:.3f}x")
        print(f"  Signal IC      : {ic_v:+.4f}  ratio={ratio:.3f}x")
        print(f"  Incremental IC : {ic_incr:+.4f}  ratio={ratio_incr:.3f}x")
        print(f"  Corr w/ N3z    : {corr_n3z:+.3f}")
        print(f"  Independence   : {'INDEPENDENT' if abs(corr_n3z) < 0.5 else 'CORRELATED'}")

    # Verdict
    stability_pass = n_oos_correct >= 3
    all_pass = unfiltered_pass and filtered_pass and stability_pass
    verdict = "ADVANCE TO DEEP DIVE" if all_pass else "KILL"
    print()
    print(f"{'-'*72}")
    print(f"  VERDICT -- {label}")
    print(f"    Unfiltered ratio > 0.5         : {'PASS' if unfiltered_pass else 'FAIL'}")
    print(f"    Filtered ratio > 1.0, p <= 0.05: {'PASS' if filtered_pass else 'FAIL'}")
    print(f"    Sub-period stability >= 3/5     : {n_oos_correct}/{len(OOS_PERIODS)} -- {'PASS' if stability_pass else 'FAIL'}")
    print(f"    => {verdict}")
    print(f"{'-'*72}")

    return {
        "label":          label,
        "ic":             ic_v,
        "ratio":          ratio,
        "p_boot":         p_v,
        "ic_filtered":    ic_f,
        "ratio_filtered": ratio_f,
        "p_filtered":     p_f,
        "stability":      f"{n_oos_correct}/{len(OOS_PERIODS)}",
        "verdict":        verdict,
    }


# ── Load base data ────────────────────────────────────────────────────────────

print(SEP)
print("PHASE 5 -- IC SCREEN: S1 (REALIZED SKEWNESS), S2 (SETTLEMENT FLOW), S3 (FUNDING DIVERGENCE)")
print(SEP)
print()
print("Loading base data...")

klines   = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
dvol_raw = pd.read_parquet(RAW / "BTC_deribit_dvol_1h.parquet")[["close"]].rename(columns={"close": "dvol"})
fund     = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")

# 1m price frame
log_c = np.log(klines["close"])
df    = klines[["close", "volume", "taker_buy_base_volume"]].copy()

# Forward returns: 4h, 8h, 24h
for h in [4, 8, 24]:
    df[f"r{h}h"] = log_c.shift(-h * 60) - log_c

# Funding (resample to 1m via ffill)
fund_1m = fund[["fundingRate"]].resample("1min").ffill()
df = df.join(fund_1m["fundingRate"])

# BTC DVOL and N3z at 1m
dvol_raw["n3z"] = (
    (dvol_raw["dvol"] - dvol_raw["dvol"].rolling(720).mean())
    / dvol_raw["dvol"].rolling(720).std()
)
dvol_1m = dvol_raw[["dvol", "n3z"]].resample("1min").ffill()
df = df.join(dvol_1m, how="inner").dropna(subset=["dvol"])

# Net returns (subtract maker round-trip)
for h in [4, 8, 24]:
    df[f"r{h}h_net"] = df[f"r{h}h"] - MAKER_RT

print(f"  1m bars : {len(df):,}  ({df.index.min().date()} to {df.index.max().date()})")


# ── SIGNAL CONSTRUCTION ───────────────────────────────────────────────────────

print()
print(SEP)
print("CONSTRUCTING SIGNALS")
print(SEP)

# ── S1: Realized Skewness ─────────────────────────────────────────────────────

print()
print("[S1] Realized Skewness -- using 1m log returns, 5-day rolling window")

log_ret = log_c.diff()
W5 = 5 * 1440  # 5-day window in 1m bars

# Efficient rolling skewness via central moments
# skew = E[(X-mu)^3] / std^3
roll_mean = log_ret.rolling(W5).mean()
centered  = log_ret - roll_mean
roll_m3   = (centered ** 3).rolling(W5).mean()
roll_std  = log_ret.rolling(W5).std(ddof=0)
roll_skew = roll_m3 / (roll_std ** 3 + 1e-20)

df["skew_5d"] = roll_skew

# S1a: raw skewness (contrarian -- negative skew -> signal is positive)
df["s1a_skew_level"] = -df["skew_5d"]

# S1b: 1-day velocity of skewness (reversion from negative)
df["s1b_skew_velocity"] = df["skew_5d"].diff(1440)

print(f"  Skewness 5d: mean={df['skew_5d'].dropna().mean():.3f}  std={df['skew_5d'].dropna().std():.3f}")
print(f"  Pct negative skew days: {100*(df['skew_5d']<0).mean():.1f}%")

# ── S2: Pre-Settlement Signed Flow ────────────────────────────────────────────

print()
print("[S2] Pre-Settlement Signed Flow -- 30-bar window before 8h funding settlements")

# Signed taker imbalance: +1 = all taker buys, -1 = all taker sells
df["tob_frac"]    = df["taker_buy_base_volume"] / df["volume"].clip(lower=1e-8)
df["signed_flow"] = 2 * df["tob_frac"] - 1

# 30-bar rolling sum of signed flow (30-min pre-settlement window)
# At each midnight bar, this = signed flow from 23:31 to 00:00
df["presettl_flow_30m"] = df["signed_flow"].rolling(30).sum()

# S2a: pre-settlement sell flow * (-funding_rate)
# When funding < 0 (longs paying) AND pre-settlement selling is heavy -> bounce
df["s2a_flow_x_funding"] = df["presettl_flow_30m"] * (-df["fundingRate"])

# S2b: pure pre-settlement contrarian (net selling before settlement -> bounce)
df["s2b_flow_contrarian"] = -df["presettl_flow_30m"]

# Normalise to rolling z-score over 30-day window (720 daily obs -> use 720*1440)
for col in ["s2a_flow_x_funding", "s2b_flow_contrarian"]:
    W30 = 30 * 1440
    df[f"{col}_z"] = (
        (df[col] - df[col].rolling(W30).mean())
        / df[col].rolling(W30).std()
    )

print(f"  Pre-settlement flow: mean={df['presettl_flow_30m'].dropna().mean():.4f}  std={df['presettl_flow_30m'].dropna().std():.4f}")
print(f"  Funding negative %: {100*(df['fundingRate'] < 0).mean():.1f}%")

# ── S3: Cross-Exchange Funding Divergence ─────────────────────────────────────

print()
print("[S3] Cross-Exchange Funding Divergence (Bybit/OKX vs Binance)")

bybit_ok = (RAW / "BTCUSDT_bybit_funding.parquet").exists()
okx_ok   = (RAW / "BTCUSDT_okx_funding.parquet").exists()

if not bybit_ok and not okx_ok:
    print("  SKIP -- neither Bybit nor OKX funding data found.")
    print("  Run: python data/download_phase5.py")
    has_s3 = False
else:
    has_s3 = True
    # Binance funding at 8h resolution
    bin_8h = fund[["fundingRate"]].resample("8h").last().rename(columns={"fundingRate": "bin_rate"})

    if bybit_ok:
        bybit = pd.read_parquet(RAW / "BTCUSDT_bybit_funding.parquet")[["fundingRate"]].rename(
            columns={"fundingRate": "bybit_rate"}
        )
        bybit_8h = bybit.resample("8h").last()
        merged   = bin_8h.join(bybit_8h, how="inner")
        merged["bybit_div"] = merged["bybit_rate"] - merged["bin_rate"]
        W30_8h = 30 * 3   # 30 days at 8h resolution
        merged["s3a_bybit_div_z"] = (
            (merged["bybit_div"] - merged["bybit_div"].rolling(W30_8h).mean())
            / merged["bybit_div"].rolling(W30_8h).std()
        )
        print(f"  Bybit: {len(bybit_8h)} 8h obs, div mean={merged['bybit_div'].mean():.6f}")
    else:
        merged = bin_8h.copy()
        print("  Bybit data not available -- skipping S3a")

    if okx_ok:
        okx    = pd.read_parquet(RAW / "BTCUSDT_okx_funding.parquet")[["fundingRate"]].rename(
            columns={"fundingRate": "okx_rate"}
        )
        okx_8h = okx.resample("8h").last()
        merged = merged.join(okx_8h, how="left")
        merged["okx_div"] = merged["okx_rate"] - merged["bin_rate"]
        W30_8h = 30 * 3
        merged["s3b_okx_div_z"] = (
            (merged["okx_div"] - merged["okx_div"].rolling(W30_8h).mean())
            / merged["okx_div"].rolling(W30_8h).std()
        )
        print(f"  OKX: {len(okx_8h)} 8h obs, div mean={merged['okx_div'].mean():.6f}")
    else:
        print("  OKX data not available -- skipping S3b")

    # Resample divergence signals to 1m (ffill within 8h window)
    s3_cols = [c for c in ["s3a_bybit_div_z", "s3b_okx_div_z"] if c in merged.columns]
    if s3_cols:
        s3_1m = merged[s3_cols].resample("1min").ffill()
        df = df.join(s3_1m, how="left")
        print(f"  S3 signals joined to 1m frame: {s3_cols}")


# ── Daily non-overlapping observation frame ───────────────────────────────────

print()
print("Building daily observation frame (non-overlapping, sampled at 00:00 UTC)...")

signal_cols = [
    "s1a_skew_level", "s1b_skew_velocity",
    "s2a_flow_x_funding_z", "s2b_flow_contrarian_z",
]
if has_s3:
    for c in ["s3a_bybit_div_z", "s3b_okx_div_z"]:
        if c in df.columns:
            signal_cols.append(c)

keep_cols = ["dvol", "n3z", "r4h_net", "r8h_net", "r24h_net"] + signal_cols
daily = df[keep_cols].iloc[::1440].copy()
daily = daily.dropna(subset=["dvol", "n3z", "r24h_net"])

oos   = daily[daily.index >= OOS_START].copy()
train = daily[daily.index <  OOS_START].copy()

print(f"  Daily obs: {len(daily):,}  (train: {len(train)}, OOS: {len(oos)})")

# Quick signal availability check
print()
print("  Signal availability (OOS non-null %):  ", end="")
for col in signal_cols:
    pct = 100 * oos[col].notna().mean() if col in oos.columns else 0.0
    print(f"{col.split('_')[0]}={pct:.0f}%", end="  ")
print()


# ── RUN IC SCREEN ─────────────────────────────────────────────────────────────

results = []

for col in signal_cols:
    if col not in daily.columns or daily[col].notna().mean() < 0.1:
        print(f"\nSKIP {col}: insufficient data")
        continue
    label_map = {
        "s1a_skew_level":          "S1a: Realized skewness level (contrarian)",
        "s1b_skew_velocity":       "S1b: Skewness velocity (reversion speed)",
        "s2a_flow_x_funding_z":    "S2a: Pre-settlement flow x funding (z)",
        "s2b_flow_contrarian_z":   "S2b: Pre-settlement flow contrarian (z)",
        "s3a_bybit_div_z":         "S3a: Bybit-Binance funding divergence (z)",
        "s3b_okx_div_z":           "S3b: OKX-Binance funding divergence (z)",
    }
    label = label_map.get(col, col)
    r = screen_signal(label, col, daily, oos)
    results.append(r)


# ── SUMMARY TABLE ─────────────────────────────────────────────────────────────

print()
print(SEP)
print("PHASE 5 IC SCREEN -- SUMMARY")
print(SEP)

hdr  = f"  {'Signal':<42}  {'IC':>8}  {'Ratio':>7}  {'p-boot':>7}  {'IC(f)':>7}  {'R(f)':>6}  {'Stab':>5}  Verdict"
rule = "  " + "-" * (len(hdr) - 2)
print(hdr)
print(rule)

survivors = []
for r in results:
    ic_s   = f"{r['ic']:+.4f}" if r["ic"] is not None and np.isfinite(r["ic"]) else "   n/a"
    ratio  = f"{r['ratio']:.3f}x" if r["ratio"] is not None and np.isfinite(r["ratio"]) else "   n/a"
    p_b    = f"{r['p_boot']:.3f}" if r["p_boot"] is not None and np.isfinite(r["p_boot"]) else "   n/a"
    ic_f   = f"{r['ic_filtered']:+.4f}" if r["ic_filtered"] is not None and np.isfinite(r["ic_filtered"]) else "   n/a"
    r_f    = f"{r['ratio_filtered']:.3f}x" if r["ratio_filtered"] is not None and np.isfinite(r["ratio_filtered"]) else "   n/a"
    lbl    = r["label"][:42]
    print(f"  {lbl:<42}  {ic_s:>8}  {ratio:>7}  {p_b:>7}  {ic_f:>7}  {r_f:>6}  {r['stability']:>5}  {r['verdict']}")
    if r["verdict"] == "ADVANCE TO DEEP DIVE":
        survivors.append(r["label"])

print()
print(f"  Survivors: {len(survivors)}")
for s in survivors:
    print(f"    => {s}")

print()
print(SEP)
print("Done.")
print(SEP)
