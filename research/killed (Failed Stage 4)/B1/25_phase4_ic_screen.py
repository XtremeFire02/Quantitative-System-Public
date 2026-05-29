"""
Phase 4 -- IC Screen: Three Genuinely New Signals
==================================================

Q4  Mark-Index Basis        -- perpetual premium/discount vs spot (data already in repo)
Q5  ETH-BTC Cross-DVOL     -- cross-asset implied vol spillover (requires ETH DVOL download)
Q6  Liquidation Exhaustion  -- daily long-liquidation surge as capitulation (requires liq download)

Design decisions:
  - Daily non-overlapping observations (sample every 1440 1m bars).
  - Block bootstrap: block = 21 days (captures monthly autocorrelation).
  - Breakeven IC (IC*) computed from maker round-trip cost and observed return sigma.
  - Regime filter: DVOL >= threshold tested as an overlay (following N3 and P3 precedent).
  - Independence check: incremental IC of each signal residualised on N3z.
  - Missing data files cause that signal to be skipped with a clear message.

Run (from repo root, after running download_phase4.py):
  python research/active/p4/25_phase4_ic_screen.py

Pass criterion (same gate used in P3):
  Unfiltered:  IC* ratio > 0.5   (IC exceeds half the breakeven threshold)
  Filtered:    IC* ratio > 1.0   AND block-bootstrap p <= 0.05
  Sub-period:  IC same-sign in >= 3 of 5 OOS half-years
"""
from __future__ import annotations
import sys, io, warnings
import numpy as np
import os
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.costs import CostModel

# DVOL regime filter threshold — loaded from env; see paper_trading/.env.example.
_DVOL_TH = float(os.getenv("DVOL_THRESHOLD", "0"))

RAW       = Path("data/raw")
MAKER     = CostModel(use_maker=True)
MAKER_RT  = MAKER.round_trip_cost()   # 0.0006  (6 bp round-trip)
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")

SEP = "=" * 72

PERIODS = [
    ("Train 2023",   "2023-01-01", "2024-01-01"),
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


def breakeven_ic(sigma, cost=None):
    if cost is None:
        cost = MAKER_RT
    return cost / (sigma * np.sqrt(2.0 / np.pi)) if sigma > 0 else np.nan


def ic_ratio(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return np.nan, np.nan
    ic_v = float(sp_stats.spearmanr(x[m], y[m]).statistic)
    sigma = float(np.nanstd(y[m]))
    ratio = abs(ic_v) / breakeven_ic(sigma) if sigma > 0 else np.nan
    return ic_v, ratio


def block_bootstrap_p(x, y, n_boot=2000, block_size=21, seed=42, direction=1):
    """One-sided block-bootstrap p-value. direction=+1 tests H1: IC > 0."""
    m = np.isfinite(x) & np.isfinite(y)
    xi, yi = x[m], y[m]
    n = len(xi)
    if n < block_size * 3:
        return np.nan
    rng = np.random.default_rng(seed)
    obs = float(sp_stats.spearmanr(xi, yi).statistic)
    n_blocks = max(1, n // block_size)
    null = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        null[i] = sp_stats.spearmanr(xi[rng.permutation(idx)], yi[idx]).statistic
    return float((null >= obs).mean()) if direction >= 0 else float((null <= obs).mean())


def incremental_ic(signal, control, ret):
    """IC of signal after projecting out control (incremental over control)."""
    m = np.isfinite(signal) & np.isfinite(control) & np.isfinite(ret)
    if m.sum() < 20:
        return np.nan, np.nan
    s, c, r = signal[m], control[m], ret[m]
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(c)), c])
    b, _, _, _ = lstsq(X, s, rcond=None)
    resid = s - X @ b
    return ic_ratio(resid, r)


# ── Full signal screen ────────────────────────────────────────────────────────

def screen_signal(label, daily, sig_col, ret_col, direction=1, n3z_col="n3_z"):
    """Run full IC screen for one signal. Returns result dict."""
    oos = daily[daily.index >= TRAIN_END].copy()
    sub = oos.dropna(subset=[sig_col, ret_col])

    print(f"\n{SEP}")
    print(f"=== {label} ===")
    print(SEP)

    if len(sub) < 30:
        print(f"  [SKIP] insufficient OOS data: {len(sub)} obs")
        return {"label": label, "verdict": "INSUFFICIENT DATA"}

    # 1. Full OOS IC
    ic_v, ratio = ic_ratio(sub[sig_col].values, sub[ret_col].values)
    p_boot = block_bootstrap_p(sub[sig_col].values, sub[ret_col].values, direction=direction)
    sigma  = np.nanstd(sub[ret_col].values)
    ic_star = breakeven_ic(sigma)
    n = len(sub)

    dir_ok = np.isfinite(ic_v) and np.sign(ic_v) == direction

    print(f"\n--- 1. FULL OOS IC (non-overlapping daily, {ret_col}, n={n}) ---")
    print(f"  IC          : {ic_v:>+.4f}  (expected direction: {'positive' if direction > 0 else 'negative'})")
    print(f"  IC*         : {ic_star:>+.4f}  (breakeven at maker cost)")
    print(f"  Ratio       : {ratio:>7.3f}x  (IC / IC*)")
    print(f"  Bootstrap p : {p_boot:.4f}  (one-sided, B=2000, block=21d)")
    verdict_unfiltered = dir_ok and ratio > 0.5
    print(f"  Unfiltered  : {'PASS' if verdict_unfiltered else 'FAIL'}  (need correct direction + ratio > 0.5)")

    # 2. Sub-period stability
    print(f"\n--- 2. SUB-PERIOD IC TABLE ---")
    print(f"  {'Period':<15}  {'n':>5}  {'IC':>8}  {'p':>7}  {'Ratio':>8}  {'Dir':>5}")
    same_sign = 0
    oos_periods = 0
    for lbl, s, e in PERIODS:
        mask = (
            (daily.index >= pd.Timestamp(s, tz="UTC")) &
            (daily.index <  pd.Timestamp(e, tz="UTC"))
        )
        sl = daily[mask].dropna(subset=[sig_col, ret_col])
        if len(sl) < 10:
            print(f"  {lbl:<15}  {'<10':>5}")
            continue
        ic_p, p_p, n_p = ic_with_p(sl[sig_col].values, sl[ret_col].values)
        _, ratio_p = ic_ratio(sl[sig_col].values, sl[ret_col].values)
        dir_flag = "OK" if np.sign(ic_p) == direction else "XX"
        if s >= "2024-01-01":
            oos_periods += 1
            same_sign += (np.sign(ic_p) == direction)
        print(f"  {lbl:<15}  {n_p:>5}  {ic_p:>+8.4f}  {p_p:>7.4f}  {ratio_p:>8.3f}x  {dir_flag:>5}")
    stability = f"{same_sign}/{oos_periods}"
    stability_flag = same_sign >= 3
    print(f"  Direction stability: {stability} OOS periods correct")

    # 3. DVOL regime filter (threshold from env — see .env.example)
    print(f"\n--- 3. DVOL REGIME FILTER ---")
    dvol_filt = sub[sub["dvol"] >= _DVOL_TH].copy()
    ic_filt = ratio_filt = p_filt = np.nan
    verdict_filtered = False
    if len(dvol_filt) < 20:
        print(f"  Insufficient obs in high-DVOL regime ({len(dvol_filt)})")
    else:
        ic_filt, ratio_filt = ic_ratio(dvol_filt[sig_col].values, dvol_filt[ret_col].values)
        p_filt = block_bootstrap_p(dvol_filt[sig_col].values, dvol_filt[ret_col].values,
                                   direction=direction)
        verdict_filtered = (np.isfinite(ic_filt) and np.sign(ic_filt) == direction
                            and ratio_filt > 1.0 and p_filt < 0.05)
        print(f"  n (DVOL >= filter): {len(dvol_filt)}")
        print(f"  IC (filtered)    : {ic_filt:>+.4f}")
        print(f"  Ratio (filtered) : {ratio_filt:>7.3f}x")
        print(f"  p-boot (filtered): {p_filt:.4f}")
        print(f"  Filtered verdict : {'PASS' if verdict_filtered else 'FAIL'}  (need ratio > 1.0, p < 0.05)")

    # 4. Quintile returns
    print(f"\n--- 4. QUINTILE RETURNS (net of maker cost, OOS) ---")
    qt = sub.copy()
    try:
        qt["q5"] = pd.qcut(qt[sig_col], 5, labels=False, duplicates="drop")
    except ValueError:
        print("  [SKIP] qcut failed (too many duplicate values)")
    else:
        print(f"  {'Q':>3}  {'n':>5}  {'Mean signal':>12}  {'Gross(bp)':>10}  {'Net maker(bp)':>14}")
        for q in sorted(qt["q5"].dropna().unique()):
            sl = qt[qt["q5"] == q]
            gross = sl[ret_col].mean()
            net   = gross - MAKER_RT
            print(f"  Q{int(q)+1:>1}   {len(sl):>5}  {sl[sig_col].mean():>+12.4f}"
                  f"  {gross*1e4:>+10.1f}  {net*1e4:>+14.1f}")
        q_lo = qt[qt["q5"] == qt["q5"].min()][ret_col].mean()
        q_hi = qt[qt["q5"] == qt["q5"].max()][ret_col].mean()
        print(f"  Q5-Q1 spread: {(q_hi - q_lo)*1e4:+.1f}bp gross, "
              f"{(q_hi - q_lo - 2*MAKER_RT)*1e4:+.1f}bp net maker")

    # 5. Incremental IC over N3z
    print(f"\n--- 5. INCREMENTAL IC (residualised on N3z, OOS) ---")
    both = oos.dropna(subset=[sig_col, n3z_col, ret_col])
    ic_incr = ratio_incr = corr_with_n3 = np.nan
    if len(both) >= 20:
        ic_n3, ratio_n3 = ic_ratio(both[n3z_col].values, both[ret_col].values)
        ic_sig, ratio_sig = ic_ratio(both[sig_col].values, both[ret_col].values)
        ic_incr, ratio_incr = incremental_ic(
            both[sig_col].values, both[n3z_col].values, both[ret_col].values)
        corr_with_n3 = float(sp_stats.spearmanr(
            both[sig_col].values, both[n3z_col].values).statistic)
        print(f"  N3z IC         : {ic_n3:>+.4f}  ratio={ratio_n3:.3f}x")
        print(f"  {sig_col} IC   : {ic_sig:>+.4f}  ratio={ratio_sig:.3f}x")
        print(f"  Incremental IC : {ic_incr:>+.4f}  ratio={ratio_incr:.3f}x")
        print(f"  Corr w/ N3z    : {corr_with_n3:>+.3f}")
        independence = "INDEPENDENT" if abs(corr_with_n3) < 0.5 else "CORRELATED"
        print(f"  Independence   : {independence}  (|corr| < 0.5 threshold)")
    else:
        print("  Insufficient overlap for incremental IC")

    # Verdict
    all_pass = verdict_unfiltered and verdict_filtered and stability_flag
    print(f"\n{'-'*72}")
    print(f"  VERDICT -- {label}")
    print(f"    Unfiltered ratio > 0.5        : {'PASS' if verdict_unfiltered else 'FAIL'}")
    print(f"    Filtered ratio > 1.0, p < 0.05: {'PASS' if verdict_filtered else 'FAIL'}")
    print(f"    Sub-period stability           : {stability} -- {'PASS' if stability_flag else 'FAIL'}")
    print(f"    => {'ADVANCE TO DEEP DIVE' if all_pass else 'KILL'}")
    print(f"{'-'*72}")

    return {
        "label":       label,
        "ic":          ic_v,
        "ratio":       ratio,
        "p_boot":      p_boot,
        "ic_filt":     ic_filt,
        "ratio_filt":  ratio_filt,
        "p_filt":      p_filt,
        "stability":   stability,
        "verdict":     "ADVANCE" if all_pass else "KILL",
    }


# ==============================================================================
# LOAD SHARED DATA
# ==============================================================================

print(SEP)
print("PHASE 4 -- IC SCREEN: Q4, Q5, Q6")
print(SEP)
print("\nLoading shared data...")

klines   = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
dvol_raw = pd.read_parquet(RAW / "BTC_deribit_dvol_1h.parquet")[["close"]].rename(
    columns={"close": "dvol"}
)
fund = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")

# 1m price frame
df = klines[["close"]].copy()
log_c = np.log(df["close"])
for h in [24, 48]:
    df[f"r{h}h"] = log_c.shift(-h * 60) - log_c

# 24h total-PnL for a long: price return minus funding paid
fund_1m = fund[["fundingRate"]].resample("1min").ffill()
fund_1m["fund_per_min"] = fund_1m["fundingRate"] / 480.0
fund_1m["fund_24h"]     = fund_1m["fund_per_min"].rolling(1440).sum().shift(-1440)
df["r24h_net"] = df["r24h"] - fund_1m["fund_24h"].reindex(df.index)

# BTC DVOL and N3z at 1m resolution
dvol_raw["n3_z"] = (
    (dvol_raw["dvol"] - dvol_raw["dvol"].rolling(30 * 24).mean())
    / dvol_raw["dvol"].rolling(30 * 24).std()
)
dvol1m = dvol_raw.resample("1min").ffill()
df = df.join(dvol1m[["dvol", "n3_z"]], how="inner").dropna(subset=["dvol"])

# Non-overlapping daily frame (sample at bar 0 of each day)
daily = df.iloc[::1440].copy().sort_index()
print(f"  Daily obs : {len(daily)} ({daily.index[0].date()} to {daily.index[-1].date()})")
print(f"  OOS range : {daily[daily.index >= TRAIN_END].index[0].date()} onward")


# ==============================================================================
# Q4: MARK-INDEX BASIS
# ==============================================================================

print(f"\n{SEP}")
print("CONSTRUCTING SIGNALS")
print(SEP)

basis_path = RAW / "BTCUSDT_premium_index_1m.parquet"
if not basis_path.exists():
    print("\n[Q4] SKIP -- data/raw/BTCUSDT_premium_index_1m.parquet not found.")
    print("  Run: python data/download_signals_cde.py --signal e")
    q4_available = False
else:
    basis_raw = pd.read_parquet(basis_path)[["basis_pct"]]
    # Daily close of basis
    basis_daily = basis_raw["basis_pct"].resample("1D").last()
    daily["basis"] = basis_daily.reindex(daily.index, method="nearest")

    # 30-day rolling z-score
    daily["q4_basis_z"] = (
        (daily["basis"] - daily["basis"].rolling(30).mean())
        / daily["basis"].rolling(30).std()
    )
    # Test BOTH directions -- first run revealed positive basis predicts positive returns
    # q4_momentum:      HIGH when basis very positive (perp premium) -> momentum LONG
    # q4_contrarian:    HIGH when basis very negative (perp discount) -> squeeze LONG
    daily["q4_momentum"]   =  daily["q4_basis_z"]   # positive basis -> long
    daily["q4_contrarian"] = -daily["q4_basis_z"]   # negative basis -> long

    q4_available = True
    n_q4 = daily["q4_momentum"].notna().sum()
    print(f"\n[Q4] Mark-Index Basis -- {n_q4} daily obs with signal")
    print(f"  Basis stats: mean={daily['basis'].mean()*1e4:.2f}bp  "
          f"std={daily['basis'].std()*1e4:.2f}bp  "
          f"min={daily['basis'].min()*1e4:.2f}bp  max={daily['basis'].max()*1e4:.2f}bp")
    print("  Testing Q4a (momentum: high basis -> long) AND Q4b (contrarian: low basis -> long)")


# ==============================================================================
# Q5: ETH-BTC CROSS-DVOL
# ==============================================================================

eth_dvol_path = RAW / "ETH_deribit_dvol_1h.parquet"
if not eth_dvol_path.exists():
    print(f"\n[Q5] SKIP -- {eth_dvol_path} not found.")
    print("  Run: python data/download_phase4.py --eth-dvol")
    q5_available = False
else:
    eth_dvol_raw = pd.read_parquet(eth_dvol_path)[["close"]].rename(
        columns={"close": "eth_dvol"}
    )
    eth_dvol_raw["eth_n3z"] = (
        (eth_dvol_raw["eth_dvol"] - eth_dvol_raw["eth_dvol"].rolling(30 * 24).mean())
        / eth_dvol_raw["eth_dvol"].rolling(30 * 24).std()
    )
    eth_daily = eth_dvol_raw.resample("1D").last()
    daily["eth_dvol"] = eth_daily["eth_dvol"].reindex(daily.index, method="ffill")
    daily["eth_n3z"]  = eth_daily["eth_n3z"].reindex(daily.index, method="ffill")

    # Signal variants
    daily["q5_eth_z"]    = daily["eth_n3z"]                          # ETH z-score alone
    daily["q5_product"]  = daily["n3_z"] * daily["eth_n3z"]          # joint confirmation
    daily["q5_btc_only"] = daily["n3_z"] - daily["eth_n3z"]          # BTC-specific excess

    q5_available = True
    n_q5 = daily["q5_eth_z"].notna().sum()
    btc_eth_corr = daily[["n3_z", "eth_n3z"]].dropna().corr().iloc[0, 1]
    print(f"\n[Q5] ETH-BTC Cross-DVOL -- {n_q5} daily obs with signal")
    print(f"  ETH DVOL range : {eth_dvol_raw.index[0].date()} to {eth_dvol_raw.index[-1].date()}")
    print(f"  Corr(BTC_n3z, ETH_n3z): {btc_eth_corr:.3f}")
    print("  Testing Q5a (ETH N3z alone), Q5b (BTC x ETH product), Q5c (BTC excess over ETH)")


# ==============================================================================
# Q6: LIQUIDATION EXHAUSTION
# ==============================================================================

liq_path = RAW / "BTCUSDT_liquidations_daily.parquet"
if not liq_path.exists():
    print(f"\n[Q6] SKIP -- {liq_path} not found.")
    print("  Binance Data Vision liquidation endpoint returned no data (HTTP 404 on all dates).")
    print("  Q6 is not testable without an alternative data source.")
    q6_available = False
else:
    liq_raw = pd.read_parquet(liq_path)
    liq_daily = liq_raw.reindex(
        pd.date_range(liq_raw.index[0], daily.index[-1], freq="D", tz="UTC"),
        fill_value=0,
    )
    liq_sell = liq_daily["liq_sell_notional"].clip(lower=0)
    liq_buy  = liq_daily["liq_buy_notional"].clip(lower=0)
    liq_sell_log = np.log1p(liq_sell)
    liq_buy_log  = np.log1p(liq_buy)
    for col, src in [("q6_sell_z", liq_sell_log), ("q6_buy_z", liq_buy_log)]:
        roll_mean = src.rolling(30).mean()
        roll_std  = src.rolling(30).std()
        daily[col] = ((src - roll_mean) / roll_std).reindex(daily.index, method="ffill")
    liq_net_log = liq_sell_log - liq_buy_log
    roll_m = liq_net_log.rolling(30).mean()
    roll_s = liq_net_log.rolling(30).std()
    daily["q6_net_z"] = ((liq_net_log - roll_m) / roll_s).reindex(daily.index, method="ffill")
    q6_available = True
    n_q6 = daily["q6_sell_z"].notna().sum()
    print(f"\n[Q6] Liquidation Exhaustion -- {n_q6} daily obs with signal")


# ==============================================================================
# RUN IC SCREENS
# ==============================================================================

results = []

if q4_available:
    res_q4a = screen_signal("Q4a: Basis momentum (high basis -> long)", daily,
                            "q4_momentum",   "r24h_net", direction=+1)
    res_q4b = screen_signal("Q4b: Basis contrarian (low basis -> long)", daily,
                            "q4_contrarian", "r24h_net", direction=+1)
    results += [res_q4a, res_q4b]

if q5_available:
    res_q5a = screen_signal("Q5a: ETH N3z alone",             daily,
                            "q5_eth_z",   "r24h_net", direction=+1)
    res_q5b = screen_signal("Q5b: BTC x ETH N3z (product)",   daily,
                            "q5_product", "r24h_net", direction=+1)
    res_q5c = screen_signal("Q5c: BTC-excess N3z (BTC-ETH)",  daily,
                            "q5_btc_only","r24h_net", direction=+1)
    results += [res_q5a, res_q5b, res_q5c]

if q6_available:
    res_q6a = screen_signal("Q6a: Long-liq surge z-score",    daily,
                            "q6_sell_z",  "r24h_net", direction=+1)
    res_q6b = screen_signal("Q6b: Long-liq excess z-score",   daily,
                            "q6_net_z",   "r24h_net", direction=+1)
    results += [res_q6a, res_q6b]


# ==============================================================================
# SUMMARY TABLE
# ==============================================================================

print(f"\n{SEP}")
print("PHASE 4 IC SCREEN -- SUMMARY")
print(SEP)
hdr = (f"  {'Signal':<40}  {'IC':>8}  {'Ratio':>7}  {'p-boot':>7}"
       f"  {'IC(f)':>7}  {'R(f)':>7}  {'Stab':>6}  {'Verdict':>8}")
print(hdr)
print("  " + "-" * (len(hdr) - 2))
for r in results:
    if "ic" not in r:
        print(f"  {r['label']:<40}  {'SKIP':>8}")
        continue
    ic_s  = f"{r['ic']:>+8.4f}"      if np.isfinite(r.get('ic', np.nan))        else f"{'n/a':>8}"
    rt_s  = f"{r['ratio']:>7.3f}x"   if np.isfinite(r.get('ratio', np.nan))     else f"{'n/a':>7}"
    p_s   = f"{r['p_boot']:>7.3f}"   if np.isfinite(r.get('p_boot', np.nan))    else f"{'n/a':>7}"
    icf_s = f"{r['ic_filt']:>+7.4f}" if np.isfinite(r.get('ic_filt', np.nan))   else f"{'n/a':>7}"
    rf_s  = f"{r['ratio_filt']:>7.3f}x" if np.isfinite(r.get('ratio_filt',np.nan)) else f"{'n/a':>7}"
    st_s  = f"{r.get('stability', '--'):>6}"
    vd_s  = f"{r.get('verdict', '--'):>8}"
    print(f"  {r['label']:<40}  {ic_s}  {rt_s}  {p_s}  {icf_s}  {rf_s}  {st_s}  {vd_s}")

survivors = [r["label"] for r in results if r.get("verdict") == "ADVANCE"]
print(f"\n  Survivors: {len(survivors)}")
for s in survivors:
    print(f"    => {s}")

if not survivors:
    print("\n  No signals passed all three gates.")
    print("  Next steps:")
    print("    1. Check for partial passes (ratio > 0.5 but filtered gate failed)")
    print("    2. Try combining Q4/Q5 with N3 as a filter overlay")
    print("    3. Update kill log for failed signals")

print(f"\n{SEP}")
print("Done.")
print(SEP)
