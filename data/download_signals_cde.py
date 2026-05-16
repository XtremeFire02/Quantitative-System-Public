"""
Downloaders for Signals C, D, E
=================================
Run from project root:

  python data/download_signals_cde.py --signal c   # liquidation volume (Data Vision)
  python data/download_signals_cde.py --signal d   # open interest daily (Data Vision)
  python data/download_signals_cde.py --signal e   # premiumIndex mark+index (FAPI klines)
  python data/download_signals_cde.py --signal all # all three sequentially

All data saved to data/raw/ as parquet.

Signal C — Aggregate Liquidation Volume (daily, from Data Vision bulk files)
  Source : https://data.binance.vision/data/futures/um/daily/liquidationSnapshot/
           One zip per day; each CSV has individual liquidation events.
  Output : data/raw/BTCUSDT_liquidations_daily.parquet
           columns: liq_buy_vol, liq_sell_vol, liq_net_vol, liq_count per day

Signal D — Open Interest (daily, from Data Vision bulk metrics files)
  Source : https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/
           One zip per day; fields: create_time, sum_open_interest, etc.
  Output : data/raw/BTCUSDT_open_interest_daily.parquet
           columns: sum_open_interest, sum_open_interest_value, etc.

Signal E — Premium Index: Mark Price + Index Price (1m, from FAPI klines)
  Source : /fapi/v1/markPriceKlines  (symbol=BTCUSDT)
           /fapi/v1/indexPriceKlines (pair=BTCUSDT — NOTE: uses 'pair' not 'symbol')
  Output : data/raw/BTCUSDT_premium_index_1m.parquet
           columns: mark_close, index_close, basis_pct=(mark-index)/index
"""
from __future__ import annotations
import argparse
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

BASE   = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
RAW    = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

# Full dataset covers 2022-01-01 → present based on ofi.parquet
START_MS = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
END_MS   = int(pd.Timestamp("2026-05-13 23:59:00", tz="UTC").timestamp() * 1000)

DELAY    = 0.25   # seconds between requests (4 req/s, well within rate limit)


def get(endpoint: str, params: dict) -> list | dict:
    url = BASE + endpoint
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            wait = 2 ** attempt
            log.warning("Request failed (%s) — retry in %ds", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed after 5 attempts: {url} {params}")


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL C — LIQUIDATION VOLUME (1m buckets)
# ══════════════════════════════════════════════════════════════════════════════

DV_BASE = "https://data.binance.vision"


def _iter_dates(start: str, end: str):
    """Yield date strings YYYY-MM-DD from start to end inclusive."""
    d = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while d <= end_ts:
        yield d.strftime("%Y-%m-%d")
        d += pd.Timedelta(days=1)


def _download_dv_zip(url: str) -> pd.DataFrame | None:
    """Download a Data Vision daily zip and return its CSV as a DataFrame."""
    import io, zipfile
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None      # date not available
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        fname = z.namelist()[0]
        return pd.read_csv(z.open(fname))


def download_liquidations() -> pd.DataFrame:
    """
    Binance Data Vision: daily liquidationSnapshot CSV files.
    Each CSV contains individual liquidation events for that day.

    CSV columns: time, symbol, side, order_type, time_in_force,
                 original_quantity, price, average_price, order_status,
                 last_filled_quantity, filled_accumulated_quantity, last_trade_time
    side: BUY = short liquidation (exchange buys); SELL = long liquidation (exchange sells)
    """
    out_path = RAW / "BTCUSDT_liquidations_daily.parquet"
    base_url = f"{DV_BASE}/data/futures/um/daily/liquidationSnapshot/{SYMBOL}"

    daily_rows = []
    for date_str in _iter_dates("2022-01-01", "2026-05-12"):
        url = f"{base_url}/{SYMBOL}-liquidationSnapshot-{date_str}.zip"
        df  = _download_dv_zip(url)
        if df is None:
            continue
        df.columns = [c.strip() for c in df.columns]
        # Try common column name variants
        side_col = next((c for c in df.columns if "side" in c.lower()), None)
        qty_col  = next((c for c in df.columns if "filled" in c.lower() and "accum" in c.lower()), None)
        if qty_col is None:
            qty_col = next((c for c in df.columns if "quantity" in c.lower()), None)
        if side_col is None or qty_col is None:
            log.warning("  %s: unexpected columns %s", date_str, list(df.columns))
            continue
        df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
        buy_vol  = df.loc[df[side_col]=="BUY",  qty_col].sum()
        sell_vol = df.loc[df[side_col]=="SELL", qty_col].sum()
        daily_rows.append({
            "date":         pd.Timestamp(date_str, tz="UTC"),
            "liq_buy_vol":  buy_vol,
            "liq_sell_vol": sell_vol,
            "liq_net_vol":  buy_vol - sell_vol,
            "liq_count":    len(df),
        })
        time.sleep(DELAY)

    if not daily_rows:
        log.warning("No liquidation data downloaded.")
        return pd.DataFrame()

    out = pd.DataFrame(daily_rows).set_index("date").sort_index()
    out.index.name = "open_time"
    out.to_parquet(out_path)
    log.info("Saved %d daily rows to %s", len(out), out_path)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL D — OPEN INTEREST HISTORY (5m → forward-filled to 1m)
# ══════════════════════════════════════════════════════════════════════════════

def download_open_interest() -> pd.DataFrame:
    """
    Binance Data Vision: daily metrics CSV files.
    Fields include: create_time, sum_open_interest, sum_open_interest_value,
                    sum_taker_long_short_vol_ratio, etc.

    Note: Data Vision metrics files are daily snapshots, not 5m granularity.
    For daily-resolution OI signals this is sufficient.
    """
    out_path = RAW / "BTCUSDT_open_interest_daily.parquet"
    base_url = f"{DV_BASE}/data/futures/um/daily/metrics/{SYMBOL}"

    records = []
    for date_str in _iter_dates("2022-01-01", "2026-05-12"):
        url = f"{base_url}/{SYMBOL}-metrics-{date_str}.zip"
        df  = _download_dv_zip(url)
        if df is None:
            continue
        df.columns = [c.strip() for c in df.columns]
        # Take only the first row per day (or the end-of-day row)
        df = df.rename(columns={
            "create_time":                "open_time",
            "sum_open_interest":          "sum_open_interest",
            "sum_open_interest_value":    "sum_open_interest_value",
            "sum_taker_long_short_vol_ratio": "taker_ls_ratio",
        })
        if "open_time" not in df.columns:
            # try the first column
            df = df.rename(columns={df.columns[0]: "open_time"})
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True, errors="coerce")
        df = df.dropna(subset=["open_time"])
        if df.empty:
            continue
        # Take the last row of the day as end-of-day snapshot
        row = df.iloc[-1]
        records.append({
            "open_time":               row["open_time"],
            "sum_open_interest":       float(row.get("sum_open_interest", np.nan)),
            "sum_open_interest_value": float(row.get("sum_open_interest_value", np.nan)),
            "taker_ls_ratio":          float(row.get("taker_ls_ratio", np.nan)),
        })
        time.sleep(DELAY)

    if not records:
        log.warning("No OI data downloaded.")
        return pd.DataFrame()

    out = pd.DataFrame(records).set_index("open_time").sort_index()
    out.index = out.index.floor("D")
    out = out[~out.index.duplicated(keep="last")]
    out["oi_change"]     = out["sum_open_interest"].diff()
    out["oi_change_pct"] = out["sum_open_interest"].pct_change()
    out.index.name = "open_time"
    out.to_parquet(out_path)
    log.info("Saved %d daily rows to %s", len(out), out_path)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNAL E — PREMIUM INDEX KLINES (mark price + index price, 1m)
# ══════════════════════════════════════════════════════════════════════════════

def download_premium_index() -> pd.DataFrame:
    """
    /fapi/v1/premiumIndexKlines — 1m klines for the premiumIndex series.
    Each kline: [open_time, open, high, low, close, ignore, close_time, ...]
    where the values are the premiumIndex (= (mark - index) / index in %).

    We also need mark and index separately. Binance doesn't provide them
    in kline form individually, but we can derive:
      mark_price  : /fapi/v1/markPriceKlines  (1m)
      index_price : /fapi/v1/indexPriceKlines (1m)

    Both have the same kline format.
    """
    out_path = RAW / "BTCUSDT_premium_index_1m.parquet"

    def _fetch_klines(endpoint: str, label: str, use_pair: bool = False) -> pd.DataFrame:
        records = []
        t0      = START_MS
        limit   = 1500
        step    = limit * 60 * 1000   # limit × 1min in ms
        # indexPriceKlines uses 'pair' not 'symbol'
        sym_key = "pair" if use_pair else "symbol"

        log.info("Downloading %s klines...", label)
        while t0 < END_MS:
            t1   = min(t0 + step, END_MS)
            data = get(endpoint, {
                sym_key:     SYMBOL,
                "interval":  "1m",
                "limit":     limit,
                "startTime": t0,
                "endTime":   t1,
            })
            if data:
                records.extend(data)
            pct = (t0 - START_MS) / (END_MS - START_MS) * 100
            if len(records) % 50000 == 0:
                log.info("  %s  %.1f%%  (%d rows)", label,
                         pct, len(records))
            t0 = t1
            time.sleep(DELAY)

        df = pd.DataFrame(records, columns=[
            "open_time","open","high","low","close",
            "ignore","close_time","v1","v2","v3","v4","v5"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"].astype(int), unit="ms", utc=True)
        df = df.set_index("open_time").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        for c in ["open","high","low","close"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close"]]

    mark  = _fetch_klines("/fapi/v1/markPriceKlines",  "markPrice",  use_pair=False)
    index = _fetch_klines("/fapi/v1/indexPriceKlines", "indexPrice", use_pair=True)

    # Align on common timestamps
    common = mark.index.intersection(index.index)
    mark   = mark.loc[common]
    index  = index.loc[common]

    out = pd.DataFrame({
        "mark_open":   mark["open"],
        "mark_high":   mark["high"],
        "mark_low":    mark["low"],
        "mark_close":  mark["close"],
        "index_open":  index["open"],
        "index_high":  index["high"],
        "index_low":   index["low"],
        "index_close": index["close"],
    })
    out["basis_pct"] = (out["mark_close"] - out["index_close"]) / out["index_close"]
    out.index.name   = "open_time"

    out.to_parquet(out_path)
    log.info("Saved %d rows to %s", len(out), out_path)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", choices=["c","d","e","all"], default="all")
    args = parser.parse_args()

    if args.signal in ("c", "all"):
        log.info("=== Signal C: Liquidations ===")
        download_liquidations()

    if args.signal in ("d", "all"):
        log.info("=== Signal D: Open Interest ===")
        download_open_interest()

    if args.signal in ("e", "all"):
        log.info("=== Signal E: Premium Index ===")
        download_premium_index()

    log.info("Done.")


if __name__ == "__main__":
    main()
