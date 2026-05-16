"""
Build the merged funding + premium dataset.

Outputs:
  data/processed/funding_premium.parquet  — 1m bars with funding/premium features
  data/processed/funding_8h.parquet       — 8h funding events with forward returns

Columns added:
  funding_rate       — latest funding rate valid at each 1m bar (forward-filled)
  funding_annualised — funding_rate * 3 * 365 (annualised %)
  mark_price         — mark price at funding event (forward-filled)
  basis              — (close - mark_price) / mark_price  [spot premium proxy on perp]
  funding_cum_8h     — cumulative funding since last settlement (running sum, reset every 8h)
  funding_zscore     — rolling 30-day z-score of 8h funding rate
  funding_pct_rank   — rolling 30-day percentile rank of 8h funding
  ret_1m / ret_5m / ret_15m / ret_1h / ret_4h / ret_8h  — forward log-returns on perp close
"""
import pandas as pd
import numpy as np
from pathlib import Path

RAW = Path("data/raw")
PROC = Path("data/processed")
PROC.mkdir(parents=True, exist_ok=True)


# ── Load raw data ─────────────────────────────────────────────────────────────
print("loading klines …")
klines = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")

print("loading funding …")
funding = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")
funding = funding[["fundingRate", "markPrice"]].copy()
funding.columns = ["funding_rate", "mark_price"]


# ── Merge: forward-fill 8h funding events onto 1m bars ───────────────────────
# reindex funding onto 1m index, then ffill
df = klines.copy()
df = df.join(funding.reindex(df.index).ffill(), how="left")

# annualise: 3 settlements per day × 365
df["funding_annualised"] = df["funding_rate"] * 3 * 365

# basis = (perp_close - mark) / mark
df["basis"] = (df["close"] - df["mark_price"]) / df["mark_price"]


# ── Cumulative intra-8h funding (resets at each settlement) ──────────────────
# identify settlement times (funding index in 1m bar timestamps)
settlement_times = set(funding.index)

def _cum_funding_8h(df_: pd.DataFrame) -> pd.Series:
    rates = df_["funding_rate"].values
    is_settle = df_.index.isin(settlement_times)
    cum = np.zeros(len(df_))
    running = 0.0
    for i in range(len(df_)):
        if is_settle[i]:
            running = rates[i]
        else:
            running += 0.0   # funding doesn't accrue per-minute; just carry the last
        cum[i] = running
    return pd.Series(cum, index=df_.index)

df["funding_cum_8h"] = _cum_funding_8h(df)


# ── Rolling z-score and percentile rank of 8h funding ────────────────────────
# work on 8h funding events, then merge back
f8 = funding.copy()

LOOKBACK = 30 * 3  # 30 days × 3 settlements/day = 90 observations
f8["funding_zscore"]   = (
    (f8["funding_rate"] - f8["funding_rate"].rolling(LOOKBACK).mean())
    / f8["funding_rate"].rolling(LOOKBACK).std()
)
f8["funding_pct_rank"] = f8["funding_rate"].rolling(LOOKBACK).rank(pct=True)

# merge z-score / pct-rank onto 1m bars (ffill from settlement times)
df = df.join(
    f8[["funding_zscore", "funding_pct_rank"]].reindex(df.index).ffill(),
    how="left",
)


# ── Forward log-returns ───────────────────────────────────────────────────────
log_close = np.log(df["close"])
for label, bars in [("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240), ("8h", 480)]:
    df[f"ret_{label}"] = log_close.shift(-bars) - log_close


# ── Save 1m dataset ──────────────────────────────────────────────────────────
out_1m = PROC / "funding_premium.parquet"
df.to_parquet(out_1m)
print(f"saved 1m dataset: {out_1m}  ({len(df):,} rows)")
print(df[["close", "funding_rate", "funding_annualised", "basis",
          "funding_zscore", "funding_pct_rank", "ret_1h"]].tail(3))


# ── 8h funding event dataset with forward returns ────────────────────────────
# at each 8h settlement, attach forward returns from the 1m bar at that time
f8_out = f8.copy()
for label in ["1m", "5m", "15m", "1h", "4h", "8h"]:
    f8_out[f"ret_{label}"] = df[f"ret_{label}"].reindex(f8_out.index)

out_8h = PROC / "funding_8h.parquet"
f8_out.to_parquet(out_8h)
print(f"\nsaved 8h dataset: {out_8h}  ({len(f8_out):,} rows)")
print(f8_out[["funding_rate", "funding_zscore", "funding_pct_rank", "ret_8h"]].tail(5))
