"""H1 Regime Stability: 2022-2026 using premium index data.

Since ofi.parquet ends 2024-12-31 we cannot directly compute
  basis = (perp_close - 8h_mark) / 8h_mark
for 2025+.

Instead, we use prem.parquet (2022-01-01 to 2026-05-12) which has:
  mark_close   = 1m real-time mark price
  index_close  = 1m spot composite index
  basis_pct    = (mark_close - index_close) / index_close  [Signal J]

At settlement bars (every 8h: 00:00, 08:00, 16:00 UTC) this basis_pct
is the direct input to the funding rate calculation.  It is the cleanest
proxy for the H1 mechanism across years not covered by ofi.parquet.

Forward returns are computed from mark_close (≈ perp close to within
basis_pct ≈ 0.03% average drift).

This script answers:
  Q1: Does the settlement-bar J signal survive into 2025 and 2026?
  Q2: Was 2024 H1 (IC≈0) an anomaly or the new normal?
  Q3: Is regime stability good enough to justify execution modelling?
  Q4: H1+H2 style combination: basis_pct × funding sign at settlement.
"""
import sys, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.costs import TAKER

# ─── Data ────────────────────────────────────────────────────────────────────
prem = pd.read_parquet("data/raw/BTCUSDT_premium_index_1m.parquet")
fund_hist = pd.read_parquet("data/raw/BTCUSDT_funding.parquet")

# Align funding to minute index
fund_hist.index = fund_hist.index.floor("min")
fund_hist = fund_hist[~fund_hist.index.duplicated(keep="first")].sort_index()

print(f"Premium index : {prem.index[0].date()} to {prem.index[-1].date()}  ({len(prem):,} rows)")
print(f"Funding hist  : {fund_hist.index[0].date()} to {fund_hist.index[-1].date()}  ({len(fund_hist):,} rows)")
print()

# ─── Settlement timestamps ────────────────────────────────────────────────────
# Binance BTCUSDT settles at 00:00, 08:00, 16:00 UTC — synthetic generation
# for years not covered by the downloaded funding parquet.

settle_times_fund = fund_hist.index  # 2023-01-01 to 2024-12-31

# Generate synthetic settlements for full prem range
all_settle = pd.date_range(
    start=pd.Timestamp("2022-01-01", tz="UTC"),
    end=prem.index[-1],
    freq="8h",
)
# Only keep those present in prem index (guard against missing bars)
all_settle = all_settle[all_settle.isin(prem.index)]
print(f"Settlement bars in prem range: {len(all_settle):,}  "
      f"({all_settle[0].date()} to {all_settle[-1].date()})")

# ─── Signal and returns ───────────────────────────────────────────────────────
settle_df = prem.loc[all_settle].copy()

# Signal: basis_pct at settlement (mark vs index)
signal = settle_df["basis_pct"]

# Forward returns from mark_close (≈ perp close; error < 0.05% per period)
for h, label in [(60, "ret_1h"), (480, "ret_8h")]:
    fwd_prices = prem["mark_close"].reindex(settle_df.index + pd.Timedelta(minutes=h))
    fwd_prices.index = settle_df.index
    settle_df[label] = np.log(fwd_prices.values / settle_df["mark_close"].values)

# For comparison: in ofi period, attach actual funding rate
settle_df["funding_rate"] = fund_hist["fundingRate"].reindex(settle_df.index)
settle_df["fund_sign"]    = np.sign(settle_df["funding_rate"])

# ─── Helpers ─────────────────────────────────────────────────────────────────
MKR = TAKER.__class__(use_maker=True).round_trip_cost()

def ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    return float(sp_stats.spearmanr(x[m], y[m]).statistic)

def bk(sigma):
    return MKR / (sigma * np.sqrt(2 / np.pi))

# ─── Year-by-year IC ─────────────────────────────────────────────────────────
print("=== YEAR-BY-YEAR IC (basis_pct at settlement vs mark_close forward returns) ===")
print(f"{'Period':<20} {'n':>5}  {'IC_1h':>8}  {'ratio_1h':>9}  {'IC_8h':>8}  {'ratio_8h':>9}")
print("-" * 70)

periods = [
    ("2022",        "2022-01-01", "2023-01-01"),
    ("2023 (train)","2023-01-01", "2024-01-01"),
    ("2024-H1",     "2024-01-01", "2024-07-01"),
    ("2024-H2",     "2024-07-01", "2025-01-01"),
    ("2025-H1",     "2025-01-01", "2025-07-01"),
    ("2025-H2",     "2025-07-01", "2026-01-01"),
    ("2026 YTD",    "2026-01-01", "2027-01-01"),
]

annual_ics = {}
for label, start, end in periods:
    m = (settle_df.index >= pd.Timestamp(start, tz="UTC")) & \
        (settle_df.index <  pd.Timestamp(end,   tz="UTC"))
    sub = settle_df[m].dropna(subset=["ret_1h", "ret_8h"])
    if len(sub) < 20:
        print(f"  {label:<18} {'<20':>5}  (skip)")
        continue
    ic1  = ic(sub["basis_pct"].values, sub["ret_1h"].values)
    ic8  = ic(sub["basis_pct"].values, sub["ret_8h"].values)
    bk1  = bk(sub["ret_1h"].std())
    bk8  = bk(sub["ret_8h"].std())
    annual_ics[label] = (ic1, ic8, len(sub))
    print(f"  {label:<18} {len(sub):>5}  {ic1:>+8.4f}  {abs(ic1)/bk1:>9.3f}x  "
          f"{ic8:>+8.4f}  {abs(ic8)/bk8:>9.3f}x")
print()

# ─── Full OOS view ────────────────────────────────────────────────────────────
print("=== OOS STABILITY: train=2022-2023, OOS=2024+ ===")
print()

train = settle_df[settle_df.index < pd.Timestamp("2024-01-01", tz="UTC")]
oos   = settle_df[settle_df.index >= pd.Timestamp("2024-01-01", tz="UTC")]

ic_train = ic(train["basis_pct"].values, train["ret_1h"].values)
ic_oos   = ic(oos["basis_pct"].values,   oos["ret_1h"].values)
print(f"  Train (2022-2023): n={len(train)}  IC(1h)={ic_train:+.4f}")
print(f"  OOS   (2024+):     n={len(oos)}   IC(1h)={ic_oos:+.4f}")
print()

# ─── Walk-forward OOS (90-day windows) ───────────────────────────────────────
print("=== WALK-FORWARD OOS (90-day windows, 30-day step) on 2024+ ===")

WINDOW_S = 90 * 3   # 90 days × 3 settlements/day
STEP_S   = 30 * 3

oos_vals = oos.dropna(subset=["ret_1h"])
ics_wf   = []
dates_wf = []
for i in range(0, len(oos_vals) - WINDOW_S, STEP_S):
    w = oos_vals.iloc[i: i + WINDOW_S]
    v = ic(w["basis_pct"].values, w["ret_1h"].values)
    ics_wf.append(v)
    dates_wf.append(w.index[0].date())

ics_wf = np.array([v for v in ics_wf if np.isfinite(v)])
frac_neg = (ics_wf < 0).mean() * 100
print(f"  n={len(ics_wf)} windows  mean={ics_wf.mean():+.4f}  "
      f"std={ics_wf.std():.4f}  frac_neg={frac_neg:.0f}%")
for v, d in zip(ics_wf, dates_wf):
    print(f"    {d}:  IC={v:+.4f}")
print()

# ─── Funding-conditioned version (available only where funding data exists) ───
print("=== FUNDING SIGN CONDITIONING (2023-2024 only, where funding data available) ===")

sub_fund = settle_df.dropna(subset=["funding_rate", "ret_1h"])
for label, cond in [
    ("All",                         sub_fund["basis_pct"].notna()),
    ("fund_sign == basis_pct_sign", np.sign(sub_fund["basis_pct"]) == sub_fund["fund_sign"]),
    ("fund_sign != basis_pct_sign", np.sign(sub_fund["basis_pct"]) != sub_fund["fund_sign"]),
    ("|fund_rate| top 25%",         sub_fund["funding_rate"].abs() >
                                    sub_fund["funding_rate"].abs().quantile(0.75)),
]:
    c = cond if hasattr(cond, 'dtype') else cond
    subs = sub_fund[c]
    if len(subs) < 30:
        continue
    ic_v = ic(subs["basis_pct"].values, subs["ret_1h"].values)
    bk_v = bk(subs["ret_1h"].std())
    print(f"  {label:<40} n={len(subs):4d}  IC={ic_v:+.4f}  ratio={abs(ic_v)/bk_v:.3f}x maker")

print()
print("Done.")
