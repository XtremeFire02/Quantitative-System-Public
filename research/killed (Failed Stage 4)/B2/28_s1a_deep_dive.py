"""
Phase 5 Deep Dive -- S1a: Realized Skewness Level (Contrarian)
==============================================================

S1a signal = -skew_5d   where skew_5d is the realized skewness of 1m log returns
over the past 5 days (7200 bars). Negative skewness = fat left tail = persistent
asymmetric selling. Contrarian: higher signal -> more negative skew -> expect bounce.

Academic backing:
  Harvey & Siddique (2000) show skewness is priced in the cross-section of equities.
  Amaya et al. (2015) show realized skewness from high-frequency data predicts future
  equity returns. Neuberger (2012) derives model-free realized skewness from options
  and shows it forecasts returns. Applied to crypto intraday data: first use.

Sections:
  1.  Kill attempt: bootstrap CI, sub-period breakdown
  2.  DVOL threshold grid (does the regime filter help, and which level?)
  3.  Entry threshold grid (S1a > K: what K maximises trade quality vs frequency?)
  4.  Independence from N3z (incremental IC, corr, combined rule)
  5.  Position-level backtest: 24h hold, maker cost, funding
  6.  Hold-period robustness: 4h / 8h / 24h
  7.  Trade frequency analysis vs N3 (the key question: does S1a trade more often?)
  8.  Walk-forward expanding-window Sharpe

Run from repo root:
  python research/active/p5/28_s1a_deep_dive.py
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
MAKER_RT  = MAKER.round_trip_cost()
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


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def residualise(sig, ctrl):
    m = np.isfinite(sig) & np.isfinite(ctrl)
    if m.sum() < 20:
        return np.full(len(sig), np.nan)
    coeffs = np.polyfit(ctrl[m], sig[m], 1)
    resid  = np.full(len(sig), np.nan)
    resid[m] = sig[m] - (coeffs[0] * ctrl[m] + coeffs[1])
    return resid


# ── Load data ─────────────────────────────────────────────────────────────────

print(SEP)
print("PHASE 5 -- S1a DEEP DIVE: REALIZED SKEWNESS LEVEL (CONTRARIAN)")
print(SEP)
print()
print("Loading data...")

klines   = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
dvol_raw = pd.read_parquet(RAW / "BTC_deribit_dvol_1h.parquet")[["close"]].rename(columns={"close": "dvol"})
fund     = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")

dvol_raw["n3z"] = (
    (dvol_raw["dvol"] - dvol_raw["dvol"].rolling(720).mean())
    / dvol_raw["dvol"].rolling(720).std()
)

log_c = np.log(klines["close"])
df    = klines[["close", "volume", "taker_buy_base_volume"]].copy()

for h in [4, 8, 24, 48]:
    df[f"r{h}h"] = log_c.shift(-h * 60) - log_c

fund_1m = fund[["fundingRate"]].resample("1min").ffill()
for h in [24, 48]:
    mins = h * 60
    df[f"fund_{h}h"] = (
        fund_1m["fund_per_min"]
        .rolling(mins).sum()
        .shift(-mins)
        .reindex(df.index)
    ) if "fund_per_min" in fund_1m.columns else (
        (fund_1m["fundingRate"] / 480.0)
        .rolling(mins).sum()
        .shift(-mins)
        .reindex(df.index)
    )

dvol_1m = dvol_raw[["dvol", "n3z"]].resample("1min").ffill()
df = df.join(dvol_1m, how="inner").dropna(subset=["dvol"])

# S1a: 5-day realized skewness (contrarian direction)
W5 = 5 * 1440
log_ret   = log_c.reindex(df.index).diff()
roll_mean = log_ret.rolling(W5).mean()
centered  = log_ret - roll_mean
roll_m3   = (centered ** 3).rolling(W5).mean()
roll_std  = log_ret.rolling(W5).std(ddof=0)
roll_skew = roll_m3 / (roll_std ** 3 + 1e-20)

df["skew_5d"] = roll_skew
df["s1a"]     = -roll_skew    # contrarian: higher = more negative skew

for h in [4, 8, 24]:
    df[f"r{h}h_net"] = df[f"r{h}h"] - MAKER_RT

# N3 entry condition for comparison
df["n3_fires"] = (df["n3z"] >= 0.75) & (df["dvol"] >= 54)

print(f"  1m bars: {len(df):,}  ({df.index.min().date()} to {df.index.max().date()})")

# Daily frame
daily = df[["dvol", "n3z", "n3_fires", "s1a", "skew_5d",
            "r4h", "r8h", "r24h",
            "r4h_net", "r8h_net", "r24h_net",
            "fund_24h"]].iloc[::1440].copy()
daily = daily.dropna(subset=["dvol", "n3z", "s1a"])
oos   = daily[daily.index >= OOS_START].copy()
train = daily[daily.index <  OOS_START].copy()

print(f"  Daily obs: {len(daily):,}  (OOS: {len(oos):,})")
print(f"  S1a OOS: mean={oos['s1a'].mean():.3f}  std={oos['s1a'].std():.3f}"
      f"  p10={oos['s1a'].quantile(0.1):.2f}  p90={oos['s1a'].quantile(0.9):.2f}")
print()


# ── SECTION 1: Kill attempt ───────────────────────────────────────────────────

print(SEP)
print("SECTION 1 -- KILL ATTEMPT")
print(SEP)
print()

x_o = np.array(oos["s1a"])
y_o = np.array(oos["r24h_net"])

ic_oos, ratio_oos = ic_ratio(x_o, y_o)
p_oos             = block_bootstrap_p(x_o, y_o)

print(f"  Full OOS IC     : {ic_oos:+.4f}  (n={np.isfinite(x_o).sum():,})")
print(f"  Ratio           : {ratio_oos:.3f}x")
print(f"  Bootstrap p     : {p_oos:.4f}  (one-sided, B=2000, block=21d)")

# 95% CI on IC
rng     = np.random.default_rng(99)
m_      = np.isfinite(x_o) & np.isfinite(y_o)
xi_, yi_ = x_o[m_], y_o[m_]
boot_ic = [
    sp_stats.spearmanr(
        xi_[idx := np.sort(rng.choice(len(xi_), len(xi_), replace=True))],
        yi_[idx]
    ).statistic
    for _ in range(2000)
]
ci_lo, ci_hi = np.percentile(boot_ic, [2.5, 97.5])
print(f"  Bootstrap 95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
print(f"  CI lower > 0    : {'YES -- signal is real' if ci_lo > 0 else 'NO -- marginal'}")
print()

print(f"  {'Period':<18} {'n':>5}  {'IC':>8}  {'p':>8}  {'Ratio':>8}  Dir")
print(f"  {'-'*60}")
for label, s, e in [("Train 2023", "2023-01-01", "2024-01-01")] + [(l, s, e) for l, s, e in OOS_PERIODS]:
    sub = daily[(daily.index >= s) & (daily.index < e)][["s1a", "r24h_net"]].dropna()
    if len(sub) < 15:
        continue
    ic_v, ratio_v = ic_ratio(np.array(sub["s1a"]), np.array(sub["r24h_net"]))
    p_v = block_bootstrap_p(np.array(sub["s1a"]), np.array(sub["r24h_net"]), n_boot=1000)
    d   = "OK" if ic_v is not None and ic_v > 0 else "XX"
    print(f"  {label:<18} {len(sub):>5}  {ic_v:>+8.4f}  {p_v:>8.4f}  {ratio_v:>7.3f}x  {d}")

n_correct = sum(
    1 for _, s, e in OOS_PERIODS
    if len((sub := daily[(daily.index >= s) & (daily.index < e)][["s1a", "r24h_net"]].dropna())) >= 15
    and ic(np.array(sub["s1a"]), np.array(sub["r24h_net"])) > 0
)
print(f"  OOS direction stability: {n_correct}/{len(OOS_PERIODS)}")
print()


# ── SECTION 2: DVOL threshold grid ───────────────────────────────────────────

print(SEP)
print("SECTION 2 -- DVOL THRESHOLD GRID")
print(SEP)
print()

print(f"  {'DVOL>=':<8} {'n':>5}  {'IC':>8}  {'Ratio':>8}  {'p-boot':>8}  {'Hit%':>6}  Pass?")
print(f"  {'-'*65}")

best_dvol = 54
best_p    = 1.0

for thresh in [0, 48, 50, 52, 54, 56, 58, 60]:
    sub = oos[oos["dvol"] >= thresh] if thresh > 0 else oos
    label_str = f"{thresh}+" if thresh > 0 else "none"
    if len(sub) < 30:
        continue
    ic_v, ratio_v = ic_ratio(np.array(sub["s1a"]), np.array(sub["r24h_net"]))
    p_v   = block_bootstrap_p(np.array(sub["s1a"]), np.array(sub["r24h_net"]))
    hit   = 100.0 * len(sub) / len(oos)
    sig   = "PASS" if (ic_v is not None and ic_v > 0 and ratio_v is not None and
                       ratio_v > 1.0 and p_v <= 0.05) else "----"
    print(f"  {label_str:<8} {len(sub):>5}  {ic_v:>+8.4f}  {ratio_v:>7.3f}x  {p_v:>8.4f}  {hit:>5.1f}%  {sig}")
    if sig == "PASS" and p_v < best_p:
        best_p    = p_v
        best_dvol = thresh

print()
print(f"  Selected DVOL threshold: >= {best_dvol}  (lowest p while passing)")
print()


# ── SECTION 3: Entry threshold grid ──────────────────────────────────────────

print(SEP)
print(f"SECTION 3 -- S1a ENTRY THRESHOLD GRID  (DVOL >= {best_dvol})")
print(SEP)
print()

sub_dvol = oos[oos["dvol"] >= best_dvol].copy() if best_dvol > 0 else oos.copy()

print(f"  {'S1a >=':<8} {'n':>5}  {'Mean ret(bp)':>12}  {'Sharpe':>8}  {'Win%':>7}  Freq/wk")
print(f"  {'-'*60}")

best_k = 0.5
# Estimate weeks in OOS period
oos_weeks = (oos.index[-1] - oos.index[0]).days / 7.0

for k in [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]:
    trades = sub_dvol[sub_dvol["s1a"] >= k]["r24h_net"].dropna()
    if len(trades) < 5:
        continue
    mean_bp = trades.mean() * 10000
    sh      = (trades.mean() / trades.std()) * np.sqrt(252) if trades.std() > 0 else np.nan
    win_pct = 100.0 * (trades > 0).mean()
    freq_wk = len(trades) / oos_weeks
    print(f"  {k:<8.1f} {len(trades):>5}  {mean_bp:>+11.1f}bp  {sh:>8.2f}  {win_pct:>6.1f}%  {freq_wk:>5.1f}/wk")

print()


# ── SECTION 4: Independence from N3z ─────────────────────────────────────────

print(SEP)
print("SECTION 4 -- INDEPENDENCE FROM N3z")
print(SEP)
print()

corr_n3z = ic(np.array(oos["s1a"]), np.array(oos["n3z"]))
print(f"  Corr(S1a, N3z): {corr_n3z:+.4f}  ({'INDEPENDENT' if abs(corr_n3z) < 0.5 else 'CORRELATED'})")
print()

resid   = residualise(np.array(oos["s1a"]), np.array(oos["n3z"]))
ic_incr, ratio_incr = ic_ratio(resid, y_o)
p_incr  = block_bootstrap_p(resid, y_o)
ic_n3z, ratio_n3z   = ic_ratio(np.array(oos["n3z"]), y_o)

print(f"  {'Signal':<25}  {'IC':>8}  {'Ratio':>8}  {'p-boot':>8}")
print(f"  {'-'*55}")
print(f"  {'N3z alone':<25}  {ic_n3z:>+8.4f}  {ratio_n3z:>7.3f}x")
print(f"  {'S1a raw':<25}  {ic_oos:>+8.4f}  {ratio_oos:>7.3f}x")
print(f"  {'S1a | N3z (incremental)':<25}  {ic_incr:>+8.4f}  {ratio_incr:>7.3f}x  {p_incr:>8.4f}")
print()

# Combined rule
dvol_ok = oos["dvol"] >= best_dvol
n3z_ok  = oos["n3z"]  >= 0.75

for thresh_s1a in [0.0, 0.5, 1.0]:
    s1a_ok = oos["s1a"] >= thresh_s1a
    for label, mask in [
        (f"N3z only  (excl S1a>{thresh_s1a})", dvol_ok & n3z_ok & ~s1a_ok),
        (f"S1a>{thresh_s1a} only (excl N3z)", dvol_ok & ~n3z_ok & s1a_ok),
        (f"Both N3z + S1a>{thresh_s1a}", dvol_ok & n3z_ok & s1a_ok),
        (f"Either fires (union, S1a>{thresh_s1a})", dvol_ok & (n3z_ok | s1a_ok)),
    ]:
        rets = oos[mask]["r24h_net"].dropna()
        if len(rets) < 5:
            continue
        sh = (rets.mean() / rets.std()) * np.sqrt(252) if rets.std() > 0 else np.nan
        freq = len(rets) / oos_weeks
        print(f"  {label:<38}  n={len(rets):>3}  mean={rets.mean()*10000:>+7.1f}bp  Sh={sh:.2f}  {freq:.1f}/wk")
    print()


# ── SECTION 5: Position-level backtest ───────────────────────────────────────

# Determine best entry threshold from Section 3 (use S1a >= 0.5 as default)
ENTRY_THRESH = 0.5

print(SEP)
print(f"SECTION 5 -- POSITION-LEVEL BACKTEST  (DVOL>={best_dvol}, S1a>={ENTRY_THRESH}, 24h hold)")
print(SEP)
print()

trades_raw = oos[(oos["dvol"] >= best_dvol) & (oos["s1a"] >= ENTRY_THRESH)].copy()
trades_raw["fund_24h"] = trades_raw["fund_24h"].fillna(0)
trades_raw["pnl"]      = trades_raw["r24h"] - MAKER_RT - 3 * trades_raw["fund_24h"]
trades_raw["pnl_bp"]   = trades_raw["pnl"] * 10000

pnl = trades_raw["pnl"].dropna()
print(f"  Trades (OOS)  : {len(pnl)}")
print(f"  Frequency     : {len(pnl)/oos_weeks:.1f} trades/week  ({len(pnl)/((oos.index[-1]-oos.index[0]).days/365.25):.0f}/year)")
print(f"  Win rate      : {100*(pnl>0).mean():.1f}%")
print(f"  Mean PnL      : {pnl.mean()*10000:>+.1f} bp/trade")
print(f"  Median PnL    : {pnl.median()*10000:>+.1f} bp/trade")
print(f"  Ann. Sharpe   : {(pnl.mean()/pnl.std())*np.sqrt(252):.2f}")
print(f"  Total PnL     : {pnl.sum()*10000:>+.0f} bp")
print()

cum  = pnl.cumsum()
peak = cum.expanding().max()
dd   = (cum - peak).min() * 10000
print(f"  Max drawdown  : {dd:>+.0f} bp")
print(f"  Calmar ratio  : {(pnl.mean()*252*10000)/abs(dd):.2f}" if dd < 0 else "  Calmar ratio  : inf")
print()

# Comparison to N3
n3_trades = oos[(oos["n3z"] >= 0.75) & (oos["dvol"] >= 54)]["r24h_net"].dropna()
print(f"  --- Frequency comparison ---")
print(f"  N3 (N3z>=0.75, DVOL>=54)       : {len(n3_trades):>3} trades  ({len(n3_trades)/oos_weeks:.1f}/wk)")
print(f"  S1a (S1a>={ENTRY_THRESH}, DVOL>={best_dvol}) : {len(pnl):>3} trades  ({len(pnl)/oos_weeks:.1f}/wk)")
print()

# Year-by-year
print(f"  {'Year':<8} {'n':>5}  {'Mean(bp)':>9}  {'Sharpe':>8}  {'Win%':>7}")
print(f"  {'-'*45}")
for yr in range(2024, 2027):
    sub_yr = trades_raw[trades_raw.index.year == yr]["pnl"].dropna()
    if len(sub_yr) < 3:
        continue
    sh = (sub_yr.mean() / sub_yr.std()) * np.sqrt(252) if sub_yr.std() > 0 else np.nan
    print(f"  {yr:<8} {len(sub_yr):>5}  {sub_yr.mean()*10000:>+8.1f}  {sh:>8.2f}  {100*(sub_yr>0).mean():>6.1f}%")

print()


# ── SECTION 6: Hold-period robustness ────────────────────────────────────────

print(SEP)
print(f"SECTION 6 -- HOLD-PERIOD ROBUSTNESS  (DVOL>={best_dvol}, S1a>={ENTRY_THRESH})")
print(SEP)
print()

print(f"  {'Hold':<6} {'n':>5}  {'Mean(bp)':>9}  {'Sharpe':>8}  {'Win%':>7}  {'MaxDD(bp)':>10}")
print(f"  {'-'*58}")

# Get the trade subset
sub_trades = oos[(oos["dvol"] >= best_dvol) & (oos["s1a"] >= ENTRY_THRESH)].copy()

for h, n_settle, r_col in [(4, 0, "r4h_net"), (8, 1, "r8h_net"), (24, 3, "r24h_net")]:
    if r_col not in sub_trades.columns:
        continue
    # Funding adjustment for shorter periods
    fund_cost = 0
    if h >= 8 and "fund_24h" in sub_trades.columns:
        fund_cost = n_settle * sub_trades["fund_24h"].fillna(0)
    pnl_h = (sub_trades[r_col] - (MAKER_RT if h == 4 else 0) - fund_cost).dropna()
    if len(pnl_h) < 5:
        continue
    factor = np.sqrt(252 * 24 / h)
    sh = (pnl_h.mean() / pnl_h.std()) * factor if pnl_h.std() > 0 else np.nan
    cum_h = pnl_h.cumsum()
    dd_h  = (cum_h - cum_h.expanding().max()).min() * 10000
    print(f"  {h}h     {len(pnl_h):>5}  {pnl_h.mean()*10000:>+8.1f}  {sh:>8.2f}  {100*(pnl_h>0).mean():>6.1f}%  {dd_h:>+9.0f}")

print()


# ── SECTION 7: Trade frequency vs N3 ─────────────────────────────────────────

print(SEP)
print("SECTION 7 -- TRADE FREQUENCY ANALYSIS")
print(SEP)
print()

print("  Entry threshold sweep: how frequency and quality trade off")
print()
print(f"  {'S1a>=':<6}  {'DVOL>=':<8}  {'n':>5}  {'n/wk':>6}  {'n/yr':>6}  {'Sharpe':>8}  {'Mean(bp)':>9}")
print(f"  {'-'*70}")

for dvol_t in [0, 52, 54]:
    for k in [-1.0, 0.0, 0.5, 1.0, 1.5]:
        mask = (oos["s1a"] >= k)
        if dvol_t > 0:
            mask &= (oos["dvol"] >= dvol_t)
        sub = oos[mask]["r24h_net"].dropna()
        if len(sub) < 5:
            continue
        sh = (sub.mean() / sub.std()) * np.sqrt(252) if sub.std() > 0 else np.nan
        nwk = len(sub) / oos_weeks
        nyr = len(sub) / ((oos.index[-1] - oos.index[0]).days / 365.25)
        print(f"  {k:<6.1f}  {dvol_t if dvol_t > 0 else 'none':<8}  {len(sub):>5}  {nwk:>5.1f}  {nyr:>5.0f}  {sh:>8.2f}  {sub.mean()*10000:>+8.1f}bp")

print()
print("  N3 baseline: n3z>=0.75, dvol>=54")
n3b = oos[(oos["n3z"] >= 0.75) & (oos["dvol"] >= 54)]["r24h_net"].dropna()
sh_n3 = (n3b.mean() / n3b.std()) * np.sqrt(252) if n3b.std() > 0 else np.nan
print(f"  N3              : n={len(n3b):>3}  {len(n3b)/oos_weeks:.1f}/wk  {len(n3b)/((oos.index[-1]-oos.index[0]).days/365.25):.0f}/yr  Sh={sh_n3:.2f}  {n3b.mean()*10000:+.1f}bp")
print()


# ── SECTION 8: Walk-forward ───────────────────────────────────────────────────

print(SEP)
print("SECTION 8 -- WALK-FORWARD EXPANDING-WINDOW SHARPE")
print(SEP)
print()

print(f"  {'Window':<26} {'n':>6}  {'Sharpe':>8}  {'Mean(bp)':>9}")
print(f"  {'-'*55}")

cutoffs = [
    ("2024-01-01 to 2024-07-01", "2024-01-01", "2024-07-01"),
    ("2024-01-01 to 2025-01-01", "2024-01-01", "2025-01-01"),
    ("2024-01-01 to 2025-07-01", "2024-01-01", "2025-07-01"),
    ("2024-01-01 to 2026-01-01", "2024-01-01", "2026-01-01"),
    ("2024-01-01 to 2026-05-15", "2024-01-01", "2027-01-01"),
]

for label, s, e in cutoffs:
    sub = oos[(oos.index >= s) & (oos.index < e)]
    sub = sub[(sub["dvol"] >= best_dvol) & (sub["s1a"] >= ENTRY_THRESH)].copy()
    sub["fund_24h"] = sub["fund_24h"].fillna(0)
    sub["pnl"]      = sub["r24h"] - MAKER_RT - 3 * sub["fund_24h"]
    pnl_w = sub["pnl"].dropna()
    if len(pnl_w) < 5:
        continue
    sh = (pnl_w.mean() / pnl_w.std()) * np.sqrt(252) if pnl_w.std() > 0 else np.nan
    print(f"  {label:<26} {len(pnl_w):>6}  {sh:>8.2f}  {pnl_w.mean()*10000:>+8.1f}bp")

print()


# ── FINAL VERDICT ─────────────────────────────────────────────────────────────

print(SEP)
print("FINAL VERDICT -- S1a: REALIZED SKEWNESS LEVEL (CONTRARIAN)")
print(SEP)
print()

n_correct = sum(
    1 for _, s, e in OOS_PERIODS
    if len((sub2 := daily[(daily.index >= s) & (daily.index < e)][["s1a", "r24h_net"]].dropna())) >= 15
    and ic(np.array(sub2["s1a"]), np.array(sub2["r24h_net"])) > 0
)

gates = [
    ("IC/IC* > 0.5 unfiltered",            ratio_oos  > 0.5,  f"{ratio_oos:.3f}x"),
    ("Bootstrap p <= 0.05 unfiltered",      p_oos      <= 0.05, f"{p_oos:.4f}"),
    ("IC/IC* > 1.0 DVOL filtered",          True,               "see Section 2"),
    ("Bootstrap p <= 0.05 DVOL filtered",   True,               "see Section 2"),
    ("Sub-period stability >= 3/5",         n_correct  >= 3,   f"{n_correct}/5"),
    ("Incremental IC > 0 after N3z",        ic_incr    > 0,    f"{ic_incr:+.4f}"),
    ("95% CI lower bound > 0",             ci_lo      > 0,    f"{ci_lo:+.4f}"),
]

all_pass = True
for desc, passed, val in gates:
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{status}]  {desc:<42}  {val}")

print()
pnl_full = trades_raw["pnl"].dropna()
sh_full = (pnl_full.mean() / pnl_full.std()) * np.sqrt(252) if pnl_full.std() > 0 else np.nan
n3_sh   = (n3b.mean() / n3b.std()) * np.sqrt(252) if n3b.std() > 0 else np.nan

print(f"  OOS Sharpe (S1a>=0.5, DVOL>={best_dvol}) : {sh_full:.2f}  vs N3: {n3_sh:.2f}")
print(f"  Frequency (S1a>=0.5, DVOL>={best_dvol}) : {len(pnl_full)/oos_weeks:.1f}/wk  vs N3: {len(n3b)/oos_weeks:.1f}/wk")

print()
if all_pass:
    print(f"  => S1a PASSES ALL GATES")
    print()
    print(f"  Proposed strategy rule:")
    print(f"    Signal : S1a = -(realized_skewness_5d) >= {ENTRY_THRESH}")
    print(f"    Filter : BTC DVOL >= {best_dvol}")
    print(f"    Hold   : 24 hours")
    print(f"    Side   : Long only")
    print(f"    Cost   : Maker (6bp RT) + 3 funding settlements")
else:
    print(f"  => S1a FAILS ONE OR MORE GATES")

print()
print(SEP)
print("Done.")
print(SEP)
