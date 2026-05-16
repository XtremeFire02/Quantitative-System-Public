"""Phase 2 data downloads.

Fetches all data needed for mechanism-based signal screening:
  --oi          Binance FAPI open interest history (5m bars, 2022-2026)
  --bybit       Bybit BTCUSDT perpetual funding history
  --okx         OKX BTC-USDT-SWAP funding history
  --dvol        Deribit BTC DVOL volatility index (1h bars)
  --liq         Binance liquidation snapshots daily (data.binance.vision)
  --all         All of the above

Usage:
  python data/download_phase2.py --all
  python data/download_phase2.py --oi --bybit
"""
from __future__ import annotations
import argparse
import io
import logging
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

RAW = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2022-01-01", tz="UTC")
END   = pd.Timestamp("2026-05-13", tz="UTC")

def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)

def _get(url: str, params: dict, retries: int = 5, sleep: float = 0.3) -> dict | list:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            time.sleep(sleep)
            return r.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning(f"retry {attempt+1} after {wait}s — {exc}")
            time.sleep(wait)


# ── Binance OI 5m ─────────────────────────────────────────────────────────────
def download_oi_5m(symbol: str = "BTCUSDT") -> None:
    """Download 5-minute OI from data.binance.vision daily metric zips.
    URL pattern: https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-YYYY-MM-DD.zip
    CSV columns: create_time, open_time, symbol, sum_open_interest,
                 sum_open_interest_value, count_toptrader_long_short_ratio, ...
    """
    out = RAW / f"{symbol}_oi_5m.parquet"
    if out.exists():
        existing  = pd.read_parquet(out)
        start_day = existing.index[-1].date()
        all_dfs   = [existing]
        log.info(f"OI 5m: extending from {start_day}")
    else:
        start_day = START.date()
        all_dfs   = []

    base  = f"https://data.binance.vision/data/futures/um/daily/metrics/{symbol}"
    dates = pd.date_range(start_day, END.date(), freq="D")
    found = 0

    for d in dates:
        url = f"{base}/{symbol}-metrics-{d.strftime('%Y-%m-%d')}.zip"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                continue
            r.raise_for_status()
        except Exception as e:
            log.debug(f"  {d.date()}: {e}")
            continue

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            fname = z.namelist()[0]
            with z.open(fname) as f:
                raw = pd.read_csv(f)

        # Normalize column names (some zips use camelCase, some snake_case)
        raw.columns = [c.strip().lower() for c in raw.columns]
        ts_col = next((c for c in raw.columns if "create_time" in c or "open_time" in c), None)
        oi_col = next((c for c in raw.columns if "sum_open_interest" in c
                       and "value" not in c), None)
        iv_col = next((c for c in raw.columns if "sum_open_interest_value" in c), None)
        if ts_col is None or oi_col is None:
            continue

        raw["ts"] = pd.to_datetime(raw[ts_col], unit="ms", utc=True)
        raw = raw.set_index("ts").sort_index()
        keep = {oi_col: "sumOpenInterest"}
        if iv_col:
            keep[iv_col] = "sumOpenInterestValue"
        raw = raw[list(keep)].rename(columns=keep).astype(float)
        all_dfs.append(raw)
        found += 1
        time.sleep(0.05)

    if not all_dfs:
        log.warning("OI 5m: no data downloaded")
        return
    df = pd.concat(all_dfs).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(out)
    log.info(f"OI 5m saved: {len(df):,} bars "
             f"({df.index[0].date()} to {df.index[-1].date()}) — {found} new days → {out}")


# ── Bybit funding history ──────────────────────────────────────────────────────
def download_bybit_funding(symbol: str = "BTCUSDT") -> None:
    out = RAW / f"{symbol}_bybit_funding.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        last_ts  = existing.index[-1]
        if last_ts >= END - pd.Timedelta(days=1):
            log.info(f"Bybit funding already up to date ({last_ts.date()}) → {out}")
            return
        start = last_ts + pd.Timedelta(minutes=1)
    else:
        start = START

    url  = "https://api.bybit.com/v5/market/funding/history"
    rows = []
    cur  = start
    while cur < END:
        end_window = min(cur + pd.Timedelta(days=200), END)
        data = _get(url, {
            "category":  "linear",
            "symbol":    symbol,
            "startTime": _ms(cur),
            "endTime":   _ms(end_window),
            "limit":     200,
        })
        if data.get("retCode") != 0:
            log.error(f"Bybit API error: {data}")
            break
        batch = data["result"]["list"]
        if not batch:
            cur = end_window + pd.Timedelta(minutes=1)
            continue
        rows.extend(batch)
        last = pd.Timestamp(int(batch[-1]["fundingRateTimestamp"]), unit="ms", tz="UTC")
        cur  = last + pd.Timedelta(minutes=1)
        if len(batch) < 200:
            cur = end_window + pd.Timedelta(minutes=1)

    if not rows:
        log.warning("Bybit: no data returned")
        return
    df = pd.DataFrame(rows)
    df["timestamp"]   = pd.to_datetime(df["fundingRateTimestamp"].astype(int), unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.set_index("timestamp")[["fundingRate", "symbol"]].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(out)
    log.info(f"Bybit funding saved: {len(df):,} rows → {out}")


# ── OKX funding history ────────────────────────────────────────────────────────
def download_okx_funding(inst_id: str = "BTC-USDT-SWAP") -> None:
    symbol = "BTCUSDT"
    out = RAW / f"{symbol}_okx_funding.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        last_ts  = existing.index[-1]
        if last_ts >= END - pd.Timedelta(days=1):
            log.info(f"OKX funding already up to date ({last_ts.date()}) → {out}")
            return
        start = last_ts + pd.Timedelta(minutes=1)
    else:
        start = START

    url  = "https://www.okx.com/api/v5/public/funding-rate-history"
    rows = []
    # OKX pagination: 'after=X' returns records with fundingTime < X (older than X).
    # Paginate backward from END to start.
    after = _ms(END) + 1
    stop  = _ms(start)
    while after > stop:
        data = _get(url, {"instId": inst_id, "after": after, "limit": 100}, sleep=0.5)
        if data.get("code") != "0" or not data.get("data"):
            break
        batch = data["data"]
        rows.extend(batch)
        oldest = int(batch[-1]["fundingTime"])
        if oldest <= stop or len(batch) < 100:
            break
        after = oldest  # next page: records older than this

    if not rows:
        log.warning("OKX: no data returned")
        return
    df = pd.DataFrame(rows)
    df["timestamp"]   = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.set_index("timestamp")[["fundingRate", "realizedRate"]].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[df.index >= START]
    df.to_parquet(out)
    log.info(f"OKX funding saved: {len(df):,} rows → {out}")


# ── Deribit BTC DVOL (1h) ─────────────────────────────────────────────────────
def download_deribit_dvol(currency: str = "BTC") -> None:
    out = RAW / f"{currency}_deribit_dvol_1h.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        last_ts  = existing.index[-1]
        if last_ts >= END - pd.Timedelta(hours=2):
            log.info(f"Deribit DVOL already up to date ({last_ts.date()}) → {out}")
            return
        start = last_ts + pd.Timedelta(hours=1)
    else:
        start = START

    url  = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    rows = []
    cur  = start
    # Deribit caps at 1000 bars per request (returns the LAST 1000 if window > 1000h).
    # Use 40-day windows (960 bars) to guarantee complete 1h coverage.
    while cur < END:
        end_window = min(cur + pd.Timedelta(days=40), END)
        data = _get(url, {
            "currency":        currency,
            "start_timestamp": _ms(cur),
            "end_timestamp":   _ms(end_window),
            "resolution":      3600,
        }, sleep=0.4)
        if "result" not in data:
            log.error(f"Deribit error: {data}")
            break
        result = data["result"]
        batch  = result.get("data", [])
        if not batch:
            cur = end_window + pd.Timedelta(hours=1)
            continue
        rows.extend(batch)
        last = pd.Timestamp(batch[-1][0], unit="ms", tz="UTC")
        cur  = last + pd.Timedelta(hours=1)
        if len(batch) < 10:
            cur = end_window + pd.Timedelta(hours=1)

    if not rows:
        log.warning("Deribit DVOL: no data returned")
        return
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").astype(float).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(out)
    log.info(f"Deribit DVOL saved: {len(df):,} bars → {out}")


# ── Binance liquidation snapshots (data.binance.vision) ───────────────────────
def download_liquidations() -> None:
    out = RAW / "BTCUSDT_liquidations_1m.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        last_day = existing.index[-1].date()
        log.info(f"Liquidations: existing data to {last_day}")
        start_date = existing.index[-1].date()
        existing_rows = existing
    else:
        start_date = START.date()
        existing_rows = None

    BASE  = "https://data.binance.vision/data/futures/um/daily/liquidationSnapshot/BTCUSDT"
    dates = pd.date_range(start_date, END.date(), freq="D")
    new_dfs = []

    for d in dates:
        url = f"{BASE}/BTCUSDT-liquidationSnapshot-{d.strftime('%Y-%m-%d')}.zip"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                continue
            r.raise_for_status()
        except Exception as e:
            log.debug(f"  {d.date()}: {e}")
            continue

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            fname = z.namelist()[0]
            with z.open(fname) as f:
                raw = pd.read_csv(f, header=None,
                                  names=["symbol","side","order_type","time_in_force",
                                         "orig_qty","price","avg_price","order_status",
                                         "last_fill_qty","cum_fill_qty","liq_time"])
        if raw.empty:
            continue
        raw["liq_time"] = pd.to_datetime(raw["liq_time"], unit="ms", utc=True).dt.floor("min")
        raw["notional"] = raw["avg_price"] * raw["cum_fill_qty"]
        grp = raw.groupby("liq_time").apply(lambda x: pd.Series({
            "liq_buy_notional":  x.loc[x["side"]=="BUY",  "notional"].sum(),
            "liq_sell_notional": x.loc[x["side"]=="SELL", "notional"].sum(),
            "liq_count":         len(x),
        }))
        new_dfs.append(grp)
        time.sleep(0.1)

    if not new_dfs and existing_rows is None:
        log.warning("Liquidations: no data downloaded")
        return
    all_parts = ([existing_rows] if existing_rows is not None else []) + new_dfs
    df = pd.concat(all_parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(out)
    log.info(f"Liquidations saved: {len(df):,} 1m bars → {out}")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--oi",    action="store_true")
    p.add_argument("--bybit", action="store_true")
    p.add_argument("--okx",   action="store_true")
    p.add_argument("--dvol",  action="store_true")
    p.add_argument("--liq",   action="store_true")
    p.add_argument("--all",   action="store_true")
    args = p.parse_args()

    if args.all or args.oi:
        log.info("=== Binance OI 5m ===")
        download_oi_5m()
    if args.all or args.bybit:
        log.info("=== Bybit funding ===")
        download_bybit_funding()
    if args.all or args.okx:
        log.info("=== OKX funding ===")
        download_okx_funding()
    if args.all or args.dvol:
        log.info("=== Deribit DVOL ===")
        download_deribit_dvol()
    if args.all or args.liq:
        log.info("=== Liquidations ===")
        download_liquidations()
