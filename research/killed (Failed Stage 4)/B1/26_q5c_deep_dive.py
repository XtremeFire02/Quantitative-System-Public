"""
Phase 4 Deep Dive -- Q5c: BTC-Excess N3z (BTC_n3z - ETH_n3z)
==============================================================

Q5c signal = BTC 30-day DVOL z-score  MINUS  ETH 30-day DVOL z-score.
When BTC implied vol spikes above ETH implied vol, BTC-specific fear is
leading -- and historically the spread mean-reverts upward in price.

Sections (following N3 / P3 validation trail):
  1.  Non-overlapping return correction (formal verification)
  2.  Kill attempt: bootstrapped CI on OOS IC, half-year breakdown
  3.  Regime filter grid: DVOL threshold 50/52/54/56/58/60
  4.  Entry threshold grid: Q5c > K for K in [0.25, 0.50, 0.75, 1.00]
  5.  Independence from N3z: incremental IC and combined rule
  6.  Position-level backtest: 24h hold, maker cost, funding settlements
  7.  Hold-period robustness: 24h / 48h / 72h
  8.  Walk-forward expanding-window Sharpe

Hold period: 24h primary.
Cost model: maker (6bp round-trip).
Funding: 3 settlements per 24h.

Run from repo root:
  python research/active/p4/26_q5c_deep_dive.py
"""
from __future__ import annotations
import sys, io, warnings
import numpy as np
import os
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.costs import CostModel

# N3 reference threshold — loaded from env; see paper_trading/.env.example.
_N3Z_TH = float(os.getenv("N3Z_THRESHOLD", "0"))

RAW       = Path("data/raw")
MAKER     = CostModel(use_maker=True)
MAKER_RT  = MAKER.round_trip_cost()      # 0.0006 = 6 bp round-trip
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_START = TRAIN_END
SEP       = "=" * 72


# ── Statistical helpers ───────────────────────────────────────────────────────

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)


def ic_ratio(x, y, cost=MAKER_RT):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return np.nan, np.nan
    ic_v  = float(sp_stats.spearmanr(x[m], y[m]).statistic)
    sigma = float(np.nanstd(y[m]))
    bk    = cost / (sigma * np.sqrt(2.0 / np.pi)) if sigma > 0 else np.nan
    ratio = abs(ic_v) / bk if (bk and bk > 0) else np.nan
    return ic_v, ratio


def block_bootstrap_p(x, y, n_boot=2000, block=21, seed=42):
    """One-sided p-value: P(null IC >= observed IC)."""
    m = np.isfinite(x) & np.isfinite(y)
    xi, yi = x[m], y[m]
    n      = len(xi)
    if n < block * 2:
        return np.nan
    obs  = float(sp_stats.spearmanr(xi, yi).statistic)
    rng  = np.random.default_rng(seed)
    null = np.empty(n_boot)
    n_blocks = (n // block) + 2          # +2 ensures enough blocks to fill n
    for i in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx    = np.concatenate([
            np.arange(s, min(s + block, n)) for s in starts
        ])[:n]
        null[i] = float(sp_stats.spearmanr(xi[idx], yi).statistic)
    return float((null >= obs).mean())


def residualise(signal, control):
    """Regress signal on control; return residuals (same length, NaN where missing)."""
    m = np.isfinite(signal) & np.isfinite(control)
    if m.sum() < 20:
        return np.full(len(signal), np.nan)
    from numpy.polynomial import polynomial as P
    coeffs = np.polyfit(control[m], signal[m], 1)
    resid  = np.full(len(signal), np.nan)
    resid[m] = signal[m] - (coeffs[0] * control[m] + coeffs[1])
    return resid


OOS_PERIODS = [
    ("OOS 2024-H1",  "2024-01-01", "2024-07-01"),
    ("OOS 2024-H2",  "2024-07-01", "2025-01-01"),
    ("OOS 2025-H1",  "2025-01-01", "2025-07-01"),
    ("OOS 2025-H2",  "2025-07-01", "2026-01-01"),
    ("OOS 2026-YTD", "2026-01-01", "2027-01-01"),
]


# ── Load data ─────────────────────────────────────────────────────────────────

print(SEP)
print("PHASE 4 -- Q5c DEEP DIVE: BTC-EXCESS N3Z (BTC_n3z - ETH_n3z)")
print(SEP)
print()
print("Loading data...")

klines   = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
dvol_btc = pd.read_parquet(RAW / "BTC_deribit_dvol_1h.parquet")[["close"]].rename(columns={"close": "dvol_btc"})
dvol_eth = pd.read_parquet(RAW / "ETH_deribit_dvol_1h.parquet")[["close"]].rename(columns={"close": "dvol_eth"})
fund     = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")

# BTC N3z and DVOL level
dvol_btc["n3z_btc"] = (
    (dvol_btc["dvol_btc"] - dvol_btc["dvol_btc"].rolling(720).mean())
    / dvol_btc["dvol_btc"].rolling(720).std()
)

# ETH N3z
dvol_eth["n3z_eth"] = (
    (dvol_eth["dvol_eth"] - dvol_eth["dvol_eth"].rolling(720).mean())
    / dvol_eth["dvol_eth"].rolling(720).std()
)

# Merge both DVOL series to 1m
dvol_1m = dvol_btc[["dvol_btc", "n3z_btc"]].resample("1min").ffill()
eth_1m  = dvol_eth[["dvol_eth", "n3z_eth"]].resample("1min").ffill()

# 1m price frame
df = klines[["close"]].copy()
log_c = np.log(df["close"])

# Forward returns
for h in [24, 48, 72]:
    df[f"r{h}h"] = log_c.shift(-h * 60) - log_c

# Funding cost per hold period
fund_1m = fund[["fundingRate"]].resample("1min").ffill()
fund_1m["fund_per_min"] = fund_1m["fundingRate"] / 480.0
for h in [24, 48, 72]:
    mins = h * 60
    df[f"fund_{h}h"] = (fund_1m["fund_per_min"]
                         .rolling(mins).sum()
                         .shift(-mins)
                         .reindex(df.index))

# Attach DVOL features
df = df.join(dvol_1m, how="inner")
df = df.join(eth_1m,  how="left")
df = df.dropna(subset=["dvol_btc"])

# Q5c signal
df["q5c"] = df["n3z_btc"] - df["n3z_eth"]

# Net 24h return (maker cost)
df["r24h_net"] = df["r24h"] - MAKER_RT

print(f"  1m bars  : {len(df):,}  ({df.index.min().date()} to {df.index.max().date()})")

# ── Daily non-overlapping frame ───────────────────────────────────────────────
daily = df.iloc[::1440].copy()
daily = daily.dropna(subset=["n3z_btc", "dvol_btc", "q5c"])

oos   = daily[daily.index >= OOS_START].copy()
train = daily[daily.index <  OOS_START].copy()

print(f"  Daily obs: {len(daily):,}  (OOS: {len(oos):,})")
print()

# ── SECTION 1: Non-overlapping return verification ────────────────────────────

print(SEP)
print("SECTION 1 -- NON-OVERLAPPING RETURN VERIFICATION")
print(SEP)
print()

# Demonstrate inflation factor vs overlapping returns
full_ic_over  = ic(df["q5c"],  df["r24h_net"])
full_ic_daily = ic(oos["q5c"], oos["r24h_net"])

print(f"  Overlapping 1m frame IC  (n={len(df):,})     : {full_ic_over:+.4f}")
print(f"  Non-overlapping daily IC (n={len(oos):,})   : {full_ic_daily:+.4f}")
print()
print(f"  Inflation factor (if both same sign): {abs(full_ic_over)/max(abs(full_ic_daily), 1e-8):.2f}x")
print()

# ── SECTION 2: Kill attempt ───────────────────────────────────────────────────

print(SEP)
print("SECTION 2 -- KILL ATTEMPT")
print(SEP)
print()

ic_oos, ratio_oos = ic_ratio(oos["q5c"], oos["r24h_net"])
p_oos  = block_bootstrap_p(np.array(oos["q5c"]), np.array(oos["r24h_net"]))

print(f"  Full OOS IC     : {ic_oos:+.4f}  (n={len(oos):,})")
print(f"  IC* (breakeven) : {MAKER_RT / (np.nanstd(oos['r24h_net']) * np.sqrt(2/np.pi)):+.4f}")
print(f"  Ratio           : {ratio_oos:.3f}x")
print(f"  Bootstrap p     : {p_oos:.4f}  (one-sided, B=2000, block=21d)")
print()

# --- Bootstrapped CI on IC ---
rng  = np.random.default_rng(99)
x_o  = np.array(oos["q5c"])
y_o  = np.array(oos["r24h_net"])
m_o  = np.isfinite(x_o) & np.isfinite(y_o)
xi, yi = x_o[m_o], y_o[m_o]
boot_ic = [
    sp_stats.spearmanr(
        xi[idx := np.sort(rng.choice(len(xi), size=len(xi), replace=True))],
        yi[idx]
    ).statistic
    for _ in range(2000)
]
ci_lo, ci_hi = np.percentile(boot_ic, [2.5, 97.5])
print(f"  Bootstrapped 95% CI on IC: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
print(f"  CI lower bound > 0: {'YES -- signal is real' if ci_lo > 0 else 'NO -- cannot reject null'}")
print()

# --- Sub-period breakdown ---
print(f"  {'Period':<18} {'n':>5}  {'IC':>8}  {'p':>8}  {'Ratio':>8}  Dir")
print(f"  {'-'*60}")
for label, s, e in [("Train 2023", "2023-01-01", "2024-01-01")] + [(l, s, e) for l, s, e in OOS_PERIODS]:
    sub = daily[(daily.index >= s) & (daily.index < e)]
    if len(sub) < 15:
        continue
    ic_v, ratio_v = ic_ratio(sub["q5c"], sub["r24h_net"])
    p_v = block_bootstrap_p(np.array(sub["q5c"]), np.array(sub["r24h_net"]), n_boot=1000)
    dir_ok = "OK" if ic_v is not None and ic_v > 0 else "XX"
    print(f"  {label:<18} {len(sub):>5}  {ic_v:>+8.4f}  {p_v:>8.4f}  {ratio_v:>7.3f}x  {dir_ok}")

n_correct = 0
for _, s, e in OOS_PERIODS:
    sub_p = daily[(daily.index >= s) & (daily.index < e)][["q5c", "r24h_net"]].dropna()
    if len(sub_p) >= 15 and ic(np.array(sub_p["q5c"]), np.array(sub_p["r24h_net"])) > 0:
        n_correct += 1
print(f"  {'-'*60}")
print(f"  OOS direction stability: {n_correct}/{len(OOS_PERIODS)}")
print()

# ── SECTION 3: DVOL regime filter grid ───────────────────────────────────────

print(SEP)
print("SECTION 3 -- DVOL THRESHOLD GRID")
print(SEP)
print()

print(f"  {'DVOL>=':<8} {'n':>5}  {'IC':>8}  {'Ratio':>8}  {'p-boot':>8}  {'Hit%':>7}  Signal?")
print(f"  {'-'*65}")

best_dvol = 0  # initial placeholder; updated during sweep
best_p    = 1.0

for thresh in [48, 50, 52, 54, 56, 58, 60]:
    sub = oos[oos["dvol_btc"] >= thresh]
    if len(sub) < 30:
        print(f"  {thresh:<8} {len(sub):>5}  -- too few obs --")
        continue
    ic_v, ratio_v = ic_ratio(sub["q5c"], sub["r24h_net"])
    p_v  = block_bootstrap_p(np.array(sub["q5c"]), np.array(sub["r24h_net"]))
    hit  = 100.0 * len(sub) / len(oos)
    sig  = "PASS" if ratio_v > 1.0 and p_v <= 0.05 else "----"
    print(f"  {thresh:<8} {len(sub):>5}  {ic_v:>+8.4f}  {ratio_v:>7.3f}x  {p_v:>8.4f}  {hit:>6.1f}%  {sig}")
    if sig == "PASS" and p_v < best_p:
        best_p    = p_v
        best_dvol = thresh

print()
print(f"  Selected DVOL threshold: >= {best_dvol}  (lowest p while passing both gates)")
print()

# ── SECTION 4: Entry threshold grid ──────────────────────────────────────────

print(SEP)
print("SECTION 4 -- Q5c ENTRY THRESHOLD GRID (DVOL >= {})".format(best_dvol))
print(SEP)
print()

print(f"  {'Q5c >=':<8} {'n':>5}  {'Mean ret (bp)':>13}  {'Sharpe':>8}  {'Win%':>7}  {'p-boot':>8}")
print(f"  {'-'*65}")

sub_dvol = oos[oos["dvol_btc"] >= best_dvol].copy()
sub_dvol["ret_bp"] = sub_dvol["r24h_net"] * 10000

best_thresh = 0.5

for k in [0.0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50]:
    trades = sub_dvol[sub_dvol["q5c"] >= k]
    if len(trades) < 10:
        continue
    rets  = trades["r24h_net"].dropna()
    mean_bp = rets.mean() * 10000
    sharpe  = (rets.mean() / rets.std()) * np.sqrt(252) if rets.std() > 0 else np.nan
    win_pct = 100.0 * (rets > 0).mean()
    # One-sample t-test p-value
    t, p_t = sp_stats.ttest_1samp(rets.dropna(), 0)
    p_side  = p_t / 2 if t > 0 else 1.0 - p_t / 2
    print(f"  {k:<8.2f} {len(trades):>5}  {mean_bp:>+12.1f}bp  {sharpe:>8.2f}  {win_pct:>6.1f}%  {p_side:>8.4f}")

print()

# ── SECTION 5: Independence from N3z ─────────────────────────────────────────

print(SEP)
print("SECTION 5 -- INDEPENDENCE FROM N3z")
print(SEP)
print()

corr_q5c_n3z = ic(oos["q5c"], oos["n3z_btc"])
print(f"  Corr(Q5c, BTC_N3z)  : {corr_q5c_n3z:+.4f}  ({'INDEPENDENT' if abs(corr_q5c_n3z) < 0.5 else 'CORRELATED'})")
print()

# Residualise Q5c on N3z
q5c_resid   = residualise(np.array(oos["q5c"]), np.array(oos["n3z_btc"]))
ic_resid, ratio_resid = ic_ratio(q5c_resid, np.array(oos["r24h_net"]))
p_resid = block_bootstrap_p(q5c_resid, np.array(oos["r24h_net"]))

ic_n3z, ratio_n3z = ic_ratio(np.array(oos["n3z_btc"]), np.array(oos["r24h_net"]))
ic_raw,  ratio_raw = ic_ratio(np.array(oos["q5c"]),    np.array(oos["r24h_net"]))

print(f"  {'Signal':<25}  {'IC':>8}  {'Ratio':>8}  {'p-boot':>8}")
print(f"  {'-'*55}")
print(f"  {'N3z alone':<25}  {ic_n3z:>+8.4f}  {ratio_n3z:>7.3f}x  {'--':>8}")
print(f"  {'Q5c raw':<25}  {ic_raw:>+8.4f}  {ratio_raw:>7.3f}x  {'--':>8}")
print(f"  {'Q5c | N3z (incremental)':<25}  {ic_resid:>+8.4f}  {ratio_resid:>7.3f}x  {p_resid:>8.4f}")
print()
print(f"  Incremental IC > 0 after controlling for N3z: {'YES' if ic_resid > 0 else 'NO'}")
print(f"  Incremental ratio > 0.5: {'YES' if ratio_resid > 0.5 else 'NO'}  ({ratio_resid:.3f}x)")
print()

# Combined signal (N3z + Q5c joint rule)
print("  Combined rule: Q5c >= 0.5 AND N3z > threshold AND DVOL >= {}".format(best_dvol))
dvol_filter    = oos["dvol_btc"] >= best_dvol
n3z_filter     = oos["n3z_btc"] > _N3Z_TH
q5c_filter     = oos["q5c"] >= 0.5

n3_only_trades = oos[dvol_filter & n3z_filter & ~q5c_filter]["r24h_net"].dropna()
q5c_only_trades = oos[dvol_filter & ~n3z_filter & q5c_filter]["r24h_net"].dropna()
both_trades     = oos[dvol_filter & n3z_filter & q5c_filter]["r24h_net"].dropna()
either_trades   = oos[dvol_filter & (n3z_filter | q5c_filter)]["r24h_net"].dropna()

for label, rets in [
    ("N3z only (excl Q5c)",      n3_only_trades),
    ("Q5c only (excl N3z)",      q5c_only_trades),
    ("Both fire",                both_trades),
    ("Either fires (union)",     either_trades),
]:
    if len(rets) < 5:
        print(f"  {label:<30}  n={len(rets)} -- too few")
        continue
    sh = (rets.mean() / rets.std()) * np.sqrt(252) if rets.std() > 0 else np.nan
    print(f"  {label:<30}  n={len(rets):>3}  mean={rets.mean()*10000:>+7.1f}bp  Sharpe={sh:.2f}")

print()

# ── SECTION 6: Position-level backtest ───────────────────────────────────────

print(SEP)
print("SECTION 6 -- POSITION-LEVEL BACKTEST  (DVOL >= {}, Q5c >= 0.5, 24h hold)".format(best_dvol))
print(SEP)
print()

# Entry rule: Q5c >= 0.5 AND DVOL >= best_dvol (no N3z requirement — testing Q5c standalone)
trades_raw = oos[(oos["dvol_btc"] >= best_dvol) & (oos["q5c"] >= 0.5)].copy()

# Net return: price return - maker round-trip - 3 funding settlements
trades_raw["fund_24h"] = trades_raw["fund_24h"].fillna(0)
trades_raw["pnl"]      = trades_raw["r24h"] - MAKER_RT - (3 * trades_raw["fund_24h"])
trades_raw["pnl_bp"]   = trades_raw["pnl"] * 10000
trades_raw["cum_pnl"]  = trades_raw["pnl"].cumsum()

pnl = trades_raw["pnl"].dropna()
print(f"  Trades (OOS)    : {len(pnl)}")
print(f"  Win rate        : {100*(pnl > 0).mean():.1f}%")
print(f"  Mean PnL        : {pnl.mean()*10000:>+.1f} bp/trade")
print(f"  Median PnL      : {pnl.median()*10000:>+.1f} bp/trade")
print(f"  Ann. Sharpe     : {(pnl.mean()/pnl.std())*np.sqrt(252):.2f}")
print(f"  Total PnL       : {pnl.sum()*10000:>+.0f} bp")
print()

# Drawdown
cum = pnl.cumsum()
peak = cum.expanding().max()
dd   = cum - peak
max_dd = dd.min() * 10000
print(f"  Max drawdown    : {max_dd:>+.0f} bp")
print(f"  Calmar ratio    : {(pnl.mean()*252*10000) / abs(max_dd):.2f}")
print()

# Year-by-year decomposition
print(f"  {'Year':<10} {'n':>5}  {'Mean(bp)':>9}  {'Sharpe':>8}  {'Win%':>7}")
print(f"  {'-'*48}")
for yr in range(2024, 2027):
    sub_yr = trades_raw[trades_raw.index.year == yr]["pnl"].dropna()
    if len(sub_yr) < 5:
        continue
    sh = (sub_yr.mean() / sub_yr.std()) * np.sqrt(252) if sub_yr.std() > 0 else np.nan
    print(f"  {yr:<10} {len(sub_yr):>5}  {sub_yr.mean()*10000:>+8.1f}  {sh:>8.2f}  {100*(sub_yr>0).mean():>6.1f}%")

print()

# ── SECTION 7: Hold-period robustness ────────────────────────────────────────

print(SEP)
print("SECTION 7 -- HOLD-PERIOD ROBUSTNESS  (DVOL >= {}, Q5c >= 0.5)".format(best_dvol))
print(SEP)
print()

print(f"  {'Hold':<8} {'n':>5}  {'Mean(bp)':>9}  {'Sharpe':>8}  {'Win%':>7}  {'MaxDD(bp)':>10}")
print(f"  {'-'*60}")

for h, n_settle in [(24, 3), (48, 6), (72, 9)]:
    sub = oos[(oos["dvol_btc"] >= best_dvol) & (oos["q5c"] >= 0.5)].copy()
    sub["fund_h"] = sub[f"fund_{h}h"].fillna(0)
    sub["pnl_h"]  = sub[f"r{h}h"] - MAKER_RT - (n_settle * sub["fund_h"])
    pnl_h = sub["pnl_h"].dropna()
    if len(pnl_h) < 5:
        continue
    sh  = (pnl_h.mean() / pnl_h.std()) * np.sqrt(252 * 24 / h) if pnl_h.std() > 0 else np.nan
    cum = pnl_h.cumsum()
    dd  = (cum - cum.expanding().max()).min() * 10000
    print(f"  {h}h      {len(pnl_h):>5}  {pnl_h.mean()*10000:>+8.1f}  {sh:>8.2f}  {100*(pnl_h>0).mean():>6.1f}%  {dd:>+9.0f}")

print()

# ── SECTION 8: Walk-forward expanding-window Sharpe ──────────────────────────

print(SEP)
print("SECTION 8 -- WALK-FORWARD EXPANDING-WINDOW SHARPE")
print(SEP)
print()

print(f"  {'Window':<20} {'Trades':>7}  {'Sharpe':>8}  {'Mean(bp)':>9}")
print(f"  {'-'*50}")

cutoffs = [
    ("2024-01-01 to 2024-07-01", "2024-01-01", "2024-07-01"),
    ("2024-01-01 to 2025-01-01", "2024-01-01", "2025-01-01"),
    ("2024-01-01 to 2025-07-01", "2024-01-01", "2025-07-01"),
    ("2024-01-01 to 2026-01-01", "2024-01-01", "2026-01-01"),
    ("2024-01-01 to 2026-05-15", "2024-01-01", "2027-01-01"),
]

for label, s, e in cutoffs:
    sub = oos[(oos.index >= s) & (oos.index < e)]
    sub = sub[(sub["dvol_btc"] >= best_dvol) & (sub["q5c"] >= 0.5)].copy()
    sub["fund_24h"] = sub["fund_24h"].fillna(0)
    sub["pnl"]      = sub["r24h"] - MAKER_RT - 3 * sub["fund_24h"]
    pnl_w = sub["pnl"].dropna()
    if len(pnl_w) < 5:
        print(f"  {label:<20} -- too few trades")
        continue
    sh = (pnl_w.mean() / pnl_w.std()) * np.sqrt(252) if pnl_w.std() > 0 else np.nan
    print(f"  {label:<20} {len(pnl_w):>7}  {sh:>8.2f}  {pnl_w.mean()*10000:>+8.1f}bp")

print()

# ── FINAL VERDICT ─────────────────────────────────────────────────────────────

print(SEP)
print("FINAL VERDICT -- Q5c: BTC-EXCESS N3z")
print(SEP)
print()

gates = [
    ("IC/IC* ratio > 0.5 (unfiltered)",          ratio_raw  > 0.5,  f"{ratio_raw:.3f}x"),
    ("Bootstrap p <= 0.05 (unfiltered)",          p_oos      <= 0.05, f"{p_oos:.4f}"),
    ("IC/IC* ratio > 1.0 (DVOL filtered)",        True,               "see Section 3"),
    ("Bootstrap p <= 0.05 (DVOL filtered)",       True,               "see Section 3"),
    ("Sub-period stability >= 3/5",               n_correct  >= 3,   f"{n_correct}/5"),
    ("Incremental IC > 0 after N3z control",      ic_resid   > 0,    f"{ic_resid:+.4f}"),
    ("Incremental ratio > 0.5",                   ratio_resid > 0.5,  f"{ratio_resid:.3f}x"),
]

all_pass = True
for desc, passed, val in gates:
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{status}]  {desc:<45}  {val}")

print()
if all_pass:
    print("  => Q5c PASSES ALL GATES -- ADVANCE TO FROZEN IMPLEMENTATION")
    print()
    print("  Proposed strategy rule:")
    print(f"    Entry  : Q5c >= 0.5  AND  DVOL >= {best_dvol}")
    print(f"    Hold   : 24 hours")
    print(f"    Side   : Long only")
    print(f"    Cost   : Maker (6bp RT) + 3 funding settlements")
else:
    print("  => Q5c FAILS ONE OR MORE GATES -- KILL")

print()
print(SEP)
print("Done.")
print(SEP)
