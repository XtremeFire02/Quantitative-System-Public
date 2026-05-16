"""
Download BTCUSDT 1m klines and perpetual funding history from Binance.
Saves to data/raw/ as parquet files.
"""
import time
import requests
import pandas as pd
from pathlib import Path
from tqdm import tqdm

RAW = Path(__file__).parent / "raw"
RAW.mkdir(parents=True, exist_ok=True)

SPOT_BASE = "https://api.binance.com"
PERP_BASE = "https://fapi.binance.com"

SYMBOL = "BTCUSDT"
# Approx 2 years of 1m data: 2023-01-01 to 2024-12-31
START_MS = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
END_MS   = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)

KLINE_LIMIT = 1500          # max per Binance request
FUNDING_LIMIT = 1000


def _get(url: str, params: dict, retries: int = 5) -> list:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt+1} after {wait}s — {exc}")
            time.sleep(wait)


# ── 1m klines (perpetual futures) ────────────────────────────────────────────
def download_klines(symbol: str = SYMBOL) -> pd.DataFrame:
    out_path = RAW / f"{symbol}_1m_klines.parquet"
    if out_path.exists():
        print(f"klines already downloaded → {out_path}")
        return pd.read_parquet(out_path)

    url = f"{PERP_BASE}/fapi/v1/klines"
    rows = []
    start = START_MS
    total_ms = END_MS - START_MS
    pbar = tqdm(total=total_ms, unit="ms", desc="klines", unit_scale=True)

    while start < END_MS:
        batch = _get(url, {
            "symbol": symbol,
            "interval": "1m",
            "startTime": start,
            "endTime": END_MS - 1,
            "limit": KLINE_LIMIT,
        })
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        pbar.update(last_open - start)
        start = last_open + 60_000  # next minute
        time.sleep(0.1)

    pbar.close()

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trade_count",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    for c in ["open", "high", "low", "close", "volume",
              "quote_volume", "taker_buy_base_volume", "taker_buy_quote_volume"]:
        df[c] = df[c].astype(float)
    df["trade_count"] = df["trade_count"].astype(int)
    df = df.drop(columns=["close_time", "ignore"])
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.to_parquet(out_path)
    print(f"saved {len(df):,} rows → {out_path}")
    return df


# ── Funding rate history (perpetual) ─────────────────────────────────────────
def download_funding(symbol: str = SYMBOL) -> pd.DataFrame:
    out_path = RAW / f"{symbol}_funding.parquet"
    if out_path.exists():
        print(f"funding already downloaded → {out_path}")
        return pd.read_parquet(out_path)

    url = f"{PERP_BASE}/fapi/v1/fundingRate"
    rows = []
    start = START_MS
    pbar = tqdm(desc="funding", unit=" records")

    while start < END_MS:
        batch = _get(url, {
            "symbol": symbol,
            "startTime": start,
            "endTime": END_MS - 1,
            "limit": FUNDING_LIMIT,
        })
        if not batch:
            break
        rows.extend(batch)
        pbar.update(len(batch))
        last_ts = int(batch[-1]["fundingTime"])
        if len(batch) < FUNDING_LIMIT:
            break
        start = last_ts + 1
        time.sleep(0.1)

    pbar.close()

    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.rename(columns={"fundingTime": "time"}).set_index("time")
    df = df[["fundingRate", "symbol"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.to_parquet(out_path)
    print(f"saved {len(df):,} funding records → {out_path}")
    return df


if __name__ == "__main__":
    print("=== downloading klines ===")
    klines = download_klines()
    print(klines.tail(3))

    print("\n=== downloading funding ===")
    funding = download_funding()
    print(funding.tail(3))
