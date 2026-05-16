"""Phase 2 mechanism-based signal quick screen.

Pass criteria (ANY horizon must clear both):
  |IC| / IC*_maker  > 0.5
  permutation p     < 0.10  (relaxed for first pass; tighten to 0.05 if passing)

Signals tested:
  D1  OI velocity              dOI_5m
  D2  OI acceleration          d2OI_5m
  D3  OI-price divergence      ret_5m × sign(dOI)  (squeeze/flush detector)
  D4  OI-funding combo         funding_rate × dOI_8h
  K1  Liquidation imbalance    (liq_sell - liq_buy) / total, 5m rolling
  K2  Liquidation Z-score      rolling z-score of total liquidation notional
  L1  Cross-exchange funding d  Binance_rate - Bybit_rate at settlement
  L2  Cross-exchange funding d  Binance_rate - OKX_rate at settlement
  N1  DVOL level               raw 1h DVOL close
  N2  DVOL slope               DVOL_t - DVOL_{t-8h}  (term structure proxy)
  N3  DVOL z-score             30d rolling z-score of DVOL

Horizons tested: 5m, 15m, 1h, 4h, 8h (where data resolution allows).
All tests use OOS period (2024-01-01 onward) where possible.
"""
import sys, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from framework.costs import TAKER

RAW        = Path("data/raw")
TRAIN_END  = pd.Timestamp("2024-01-01", tz="UTC")
IC_BK_PASS = 0.50   # first-pass hurdle on |IC|/IC*_maker
P_PASS     = 0.10   # relaxed p-value for first pass

# ─── Helpers ─────────────────────────────────────────────────────────────────
MKR = TAKER.__class__(use_maker=True).round_trip_cost()

def ic(x, y, max_n: int = 100_000):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return np.nan
    xi, yi = x[m], y[m]
    if len(xi) > max_n:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(xi), max_n, replace=False)
        xi, yi = xi[idx], yi[idx]
    return float(sp_stats.spearmanr(xi, yi).statistic)

def perm_p(x, y, B: int = 1000, max_n: int = 50_000, seed: int = 0):
    rng = np.random.default_rng(seed)
    m = np.isfinite(x) & np.isfinite(y)
    xi, yi = x[m], y[m]
    if len(xi) > max_n:
        idx = rng.choice(len(xi), max_n, replace=False)
        xi, yi = xi[idx], yi[idx]
    obs  = float(sp_stats.spearmanr(xi, yi).statistic)
    null = [float(sp_stats.spearmanr(rng.permutation(xi), yi).statistic)
            for _ in range(B)]
    return obs, (np.abs(null) >= np.abs(obs)).mean()

def bk(sigma):
    return MKR / (sigma * np.sqrt(2 / np.pi))

def screen(label: str, sig: np.ndarray, rets: dict[str, np.ndarray]) -> bool:
    """Test one signal against multiple return horizons. Returns True if passes."""
    best_ratio, best_hz, best_p = 0.0, None, 1.0
    for hz, ret in rets.items():
        ic_v = ic(sig, ret)
        if not np.isfinite(ic_v):
            continue
        sigma = np.nanstd(ret[np.isfinite(ret)])
        if sigma == 0:
            continue
        ratio = abs(ic_v) / bk(sigma)
        if ratio > best_ratio:
            best_ratio, best_hz = ratio, hz
            _, best_p = perm_p(sig, ret, B=500)
    passes = best_ratio > IC_BK_PASS and best_p < P_PASS
    flag   = "  PASS" if passes else "  fail"
    print(f"  {label:<28} best={best_hz:<5} ratio={best_ratio:.3f}x  p={best_p:.3f}{flag}")
    return passes

# ─── Load base data ───────────────────────────────────────────────────────────
print("Loading base data...")
ofi = pd.read_parquet("data/processed/ofi.parquet")
kl  = pd.read_parquet(RAW / "BTCUSDT_1m_klines.parquet")
fund = pd.read_parquet(RAW / "BTCUSDT_funding.parquet")

# Forward returns on 1m grid (reuse columns if available)
for h_bars, col in [(5,"r5m"), (15,"r15m"), (60,"r1h"), (240,"r4h"), (480,"r8h")]:
    if col not in ofi.columns:
        ofi[col] = np.log(ofi["close"].shift(-h_bars) / ofi["close"])

ofi_oos = ofi[ofi.index >= TRAIN_END]
print(f"  OFI OOS  : {len(ofi_oos):,} 1m bars")

# ─── Signal D: Open Interest Velocity ────────────────────────────────────────
print("\n=== SIGNAL D: OPEN INTEREST VELOCITY ===")
oi_path = RAW / "BTCUSDT_oi_5m.parquet"
if not oi_path.exists():
    print("  [SKIP] BTCUSDT_oi_5m.parquet not found — run download_phase2.py --oi")
else:
    oi5 = pd.read_parquet(oi_path)
    oi5 = oi5[["sumOpenInterest"]].rename(columns={"sumOpenInterest": "oi"})
    oi5["oi"] = oi5["oi"].astype(float)

    # Upsample to 1m (forward-fill within each 5m bar)
    oi1m = oi5.resample("1min").ffill()

    # Signals
    oi1m["d1_oi"]   = oi5["oi"].diff().reindex(oi1m.index, method="ffill")
    oi1m["d2_oi"]   = oi1m["d1_oi"].diff()
    oi1m["d1_oi_z"] = (oi1m["d1_oi"] - oi1m["d1_oi"].rolling(480).mean()) / \
                       oi1m["d1_oi"].rolling(480).std()

    # Merge with OFI returns
    merged = ofi_oos.join(oi1m[["d1_oi","d2_oi","d1_oi_z"]], how="inner")
    merged = merged.dropna(subset=["d1_oi"])
    rets   = {hz: merged[c].values for hz, c in
              [("5m","r5m"),("15m","r15m"),("1h","r1h"),("4h","r4h")] if c in merged}

    # D4: OI-funding combo (at 8h settlement bars)
    settle = fund[fund.index.isin(merged.index)]
    m_s    = merged.loc[merged.index.isin(settle.index)].copy()
    m_s    = m_s.join(fund[["fundingRate"]], how="inner")
    m_s["d4"] = m_s["fundingRate"] * m_s["d1_oi_z"]

    print(f"  OI data: {len(oi5):,} 5m bars ({oi5.index[0].date()} to {oi5.index[-1].date()})")
    print(f"  Merged with OFI OOS: {len(merged):,} bars")

    passed = []
    passed.append(screen("D1 dOI (5m, z-scored)",   merged["d1_oi_z"].values, rets))
    passed.append(screen("D2 d2OI (acceleration)",  merged["d2_oi"].values,   rets))

    if len(m_s) > 100:
        rets_s = {hz: m_s[c].values for hz, c in
                  [("1h","r1h"),("4h","r4h"),("8h","r8h")] if c in m_s}
        passed.append(screen("D4 funding×dOI (settle)", m_s["d4"].values, rets_s))

# ─── Signal K: Liquidation Cascade ───────────────────────────────────────────
print("\n=== SIGNAL K: LIQUIDATION CASCADE ===")
liq_path = RAW / "BTCUSDT_liquidations_1m.parquet"
if not liq_path.exists():
    print("  [SKIP] liquidations_1m.parquet not found — run download_phase2.py --liq")
    # Fallback: volume-spike liquidation proxy from existing klines
    print("  Using volume-spike proxy from 1m klines (buy/sell imbalance on large bars)")
    kl_oos = kl[kl.index >= TRAIN_END].copy()
    kl_oos["vol_z"]    = (kl_oos["volume"] - kl_oos["volume"].rolling(60).mean()) / \
                          kl_oos["volume"].rolling(60).std()
    kl_oos["sell_frac"] = 1 - (kl_oos["taker_buy_base_volume"] / kl_oos["volume"])
    kl_oos["k_proxy"]  = kl_oos["vol_z"] * (kl_oos["sell_frac"] - 0.5)
    kl_oos = kl_oos.join(ofi_oos[["r5m","r15m","r1h","r4h"]], how="inner")
    rets   = {hz: kl_oos[c].values for hz, c in
              [("5m","r5m"),("15m","r15m"),("1h","r1h"),("4h","r4h")] if c in kl_oos}
    screen("K_proxy vol-imbalance spike", kl_oos["k_proxy"].values, rets)
else:
    liq = pd.read_parquet(liq_path).fillna(0)
    liq["liq_net"]    = liq["liq_sell_notional"] - liq["liq_buy_notional"]
    liq["liq_total"]  = liq["liq_sell_notional"] + liq["liq_buy_notional"]
    liq["k1_imbal"]   = liq["liq_net"] / (liq["liq_total"] + 1)
    liq["k2_z"]       = (liq["liq_total"] - liq["liq_total"].rolling(60).mean()) / \
                         liq["liq_total"].rolling(60).std()

    merged = ofi_oos.join(liq[["k1_imbal","k2_z"]], how="inner")
    merged = merged.dropna(subset=["k1_imbal"])
    rets   = {hz: merged[c].values for hz, c in
              [("5m","r5m"),("15m","r15m"),("1h","r1h"),("4h","r4h")] if c in merged}
    print(f"  Liquidation data: {len(liq):,} 1m bars")
    screen("K1 liq imbalance",   merged["k1_imbal"].values, rets)
    screen("K2 liq total z",     merged["k2_z"].values,     rets)

# ─── Signal L: Cross-exchange funding dispersion ──────────────────────────────
print("\n=== SIGNAL L: CROSS-EXCHANGE FUNDING DISPERSION ===")
bybit_path = RAW / "BTCUSDT_bybit_funding.parquet"
okx_path   = RAW / "BTCUSDT_okx_funding.parquet"

bnb_fund = fund[fund.index >= TRAIN_END]["fundingRate"].rename("bnb")

for name, path in [("Bybit", bybit_path), ("OKX", okx_path)]:
    if not path.exists():
        print(f"  [SKIP] {path.name} not found — run download_phase2.py --bybit/--okx")
        continue
    other = pd.read_parquet(path)
    other.index = other.index.floor("min")
    other = other[~other.index.duplicated()]
    other_fund = other["fundingRate"].rename("other")

    # Align on settlement timestamps
    disp = pd.concat([bnb_fund, other_fund], axis=1, join="inner").dropna()
    disp["l_disp"] = disp["bnb"] - disp["other"]

    # Forward returns for Binance from ofi
    disp = disp.join(ofi_oos[["r1h","r4h","r8h"]], how="inner")
    if len(disp) < 30:
        print(f"  {name}: too few aligned rows ({len(disp)})")
        continue
    rets = {hz: disp[c].values for hz, c in [("1h","r1h"),("4h","r4h"),("8h","r8h")]
            if c in disp}
    print(f"  {name}: {len(disp)} aligned funding events")
    screen(f"L1 Binance-{name} dfunding", disp["l_disp"].values, rets)

# ─── Signal N: Options volatility regime (Deribit DVOL) ─────────────────────
print("\n=== SIGNAL N: OPTIONS VOLATILITY REGIME (DERIBIT DVOL) ===")
dvol_path = RAW / "BTC_deribit_dvol_1h.parquet"
if not dvol_path.exists():
    print("  [SKIP] BTC_deribit_dvol_1h.parquet not found — run download_phase2.py --dvol")
else:
    dvol = pd.read_parquet(dvol_path)[["close"]].rename(columns={"close": "dvol"})

    # N1: raw DVOL level (1h, forward-filled to 1m)
    dvol["n2_slope"] = dvol["dvol"] - dvol["dvol"].shift(8)   # 8h slope
    dvol["n3_z"]     = (dvol["dvol"] - dvol["dvol"].rolling(30*24).mean()) / \
                        dvol["dvol"].rolling(30*24).std()      # 30d z-score

    dvol1m = dvol.resample("1min").ffill()
    merged = ofi_oos.join(dvol1m[["dvol","n2_slope","n3_z"]], how="inner").dropna(subset=["dvol"])
    rets   = {hz: merged[c].values for hz, c in
              [("1h","r1h"),("4h","r4h"),("8h","r8h")] if c in merged}

    print(f"  DVOL data: {len(dvol):,} 1h bars ({dvol.index[0].date()} to {dvol.index[-1].date()})")
    screen("N1 DVOL level",      merged["dvol"].values,     rets)
    screen("N2 DVOL 8h slope",   merged["n2_slope"].values, rets)
    screen("N3 DVOL 30d z-score",merged["n3_z"].values,     rets)

# ─── Summary ─────────────────────────────────────────────────────────────────
print("\n=== PASS CRITERIA ===")
print(f"  |IC|/IC*_maker > {IC_BK_PASS}x  AND  permutation p < {P_PASS}")
print("  Signals passing first screen warrant full OOS + block bootstrap.")
print("Done.")
