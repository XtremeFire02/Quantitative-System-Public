"""
Extend BTCUSDT 1m klines and funding parquets from their current end date
to today. Appends new data in-place to the existing raw parquets.
"""
import time
import requests
import pandas as pd
from pathlib import Path
from tqdm import tqdm

RAW = Path(__file__).parent / "raw"
PERP_BASE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
KLINE_LIMIT = 1500
FUNDING_LIMIT = 1000


def _get(url: str, params: dict, retries: int = 5) -> list:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt+1} after {wait}s — {exc}")
            time.sleep(wait)


def extend_klines() -> pd.DataFrame:
    out_path = RAW / f"{SYMBOL}_1m_klines.parquet"
    existing = pd.read_parquet(out_path)
    # start one minute after the last bar
    start_ts = existing.index.max() + pd.Timedelta(minutes=1)
    # end at current minute boundary (leave 1 bar buffer)
    end_ts = pd.Timestamp("now", tz="UTC").floor("1min") - pd.Timedelta(minutes=2)

    print(f"Existing klines: {existing.index.min().date()} to {existing.index.max().date()} ({len(existing):,} bars)")
    if start_ts >= end_ts:
        print("Already up to date.")
        return existing
    print(f"Downloading klines {start_ts.date()} to {end_ts.date()} ...")

    start_ms = int(start_ts.timestamp() * 1000)
    end_ms   = int(end_ts.timestamp() * 1000)
    url = f"{PERP_BASE}/fapi/v1/klines"

    rows = []
    cur  = start_ms
    pbar = tqdm(total=end_ms - start_ms, unit="ms", desc="klines", unit_scale=True)

    while cur < end_ms:
        batch = _get(url, {
            "symbol": SYMBOL, "interval": "1m",
            "startTime": cur, "endTime": end_ms - 1,
            "limit": KLINE_LIMIT,
        })
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        pbar.update(last_open - cur)
        cur = last_open + 60_000
        if len(batch) < KLINE_LIMIT:
            break
        time.sleep(0.05)

    pbar.close()

    if not rows:
        print("No new kline data fetched.")
        return existing

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trade_count",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
    ]
    new = pd.DataFrame(rows, columns=cols)
    new["open_time"] = pd.to_datetime(new["open_time"], unit="ms", utc=True)
    new = new.set_index("open_time")
    for c in ["open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_base_volume", "taker_buy_quote_volume"]:
        new[c] = new[c].astype(float)
    new["trade_count"] = new["trade_count"].astype(int)
    new = new.drop(columns=["close_time", "ignore"])

    combined = pd.concat([existing, new]).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.to_parquet(out_path)
    print(f"Saved klines: {combined.index.min().date()} to {combined.index.max().date()} ({len(combined):,} bars)")
    return combined


def extend_funding() -> pd.DataFrame:
    out_path = RAW / f"{SYMBOL}_funding.parquet"
    existing = pd.read_parquet(out_path)
    start_ts = existing.index.max() + pd.Timedelta(hours=8)
    end_ts   = pd.Timestamp("now", tz="UTC")

    print(f"\nExisting funding: {existing.index.min().date()} to {existing.index.max().date()} ({len(existing):,} records)")
    if start_ts >= end_ts:
        print("Already up to date.")
        return existing
    print(f"Downloading funding {start_ts.date()} to {end_ts.date()} ...")

    start_ms = int(start_ts.timestamp() * 1000)
    end_ms   = int(end_ts.timestamp() * 1000)
    url = f"{PERP_BASE}/fapi/v1/fundingRate"

    rows = []
    cur  = start_ms
    pbar = tqdm(desc="funding", unit=" records")

    while cur < end_ms:
        batch = _get(url, {
            "symbol": SYMBOL,
            "startTime": cur, "endTime": end_ms - 1,
            "limit": FUNDING_LIMIT,
        })
        if not batch:
            break
        rows.extend(batch)
        pbar.update(len(batch))
        last_ts = int(batch[-1]["fundingTime"])
        if len(batch) < FUNDING_LIMIT:
            break
        cur = last_ts + 1
        time.sleep(0.1)

    pbar.close()

    if not rows:
        print("No new funding data fetched.")
        return existing

    new = pd.DataFrame(rows)
    new["fundingTime"] = pd.to_datetime(new["fundingTime"], unit="ms", utc=True)
    new["fundingRate"] = new["fundingRate"].astype(float)
    new = new.rename(columns={"fundingTime": "time"}).set_index("time")
    # keep whichever columns the API returned
    keep_cols = [c for c in ["fundingRate", "markPrice", "symbol"] if c in new.columns]
    if "markPrice" in new.columns:
        new["markPrice"] = new["markPrice"].astype(float)
    new = new[keep_cols]

    combined = pd.concat([existing, new]).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]
    combined.to_parquet(out_path)
    print(f"Saved funding: {combined.index.min().date()} to {combined.index.max().date()} ({len(combined):,} records)")
    return combined


if __name__ == "__main__":
    print("=== Extending klines ===")
    klines = extend_klines()

    print("\n=== Extending funding ===")
    funding = extend_funding()

    print("\nDone.")
