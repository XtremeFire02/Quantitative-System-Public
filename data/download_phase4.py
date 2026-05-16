"""
Phase 4 data downloads.

Two new data sources required for the Phase 4 signal screen:

  --eth-dvol    Deribit ETH DVOL (1h bars, 2022-2026)
                → data/raw/ETH_deribit_dvol_1h.parquet
                Same API as BTC DVOL, currency=ETH.

  --liq         Binance daily long-liquidation notional (Data Vision)
                → data/raw/BTCUSDT_liquidations_daily.parquet
                Each day: liq_buy_notional (short liq) + liq_sell_notional (long liq).

  --all         Both of the above (default if no flag given)

Usage (from repo root):
  python data/download_phase4.py --all
  python data/download_phase4.py --eth-dvol
  python data/download_phase4.py --liq
"""
from __future__ import annotations
import argparse
import io
import logging
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAW   = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2022-01-01", tz="UTC")
END   = pd.Timestamp("2026-05-15", tz="UTC")


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def _get(url: str, params: dict, retries: int = 5, sleep: float = 0.4) -> dict | list:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(sleep)
            return r.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("retry %d after %ds — %s", attempt + 1, wait, exc)
            time.sleep(wait)


# ── ETH DVOL (Deribit, 1h) ────────────────────────────────────────────────────

def download_eth_dvol() -> None:
    """
    Fetch Deribit ETH DVOL 1h bars via the same endpoint used for BTC DVOL,
    with currency='ETH'.  Saves to data/raw/ETH_deribit_dvol_1h.parquet.

    Deribit caps at 1000 bars per request; we use 40-day windows (960 bars)
    for complete 1h coverage.
    """
    out = RAW / "ETH_deribit_dvol_1h.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        last_ts  = existing.index[-1]
        if last_ts >= END - pd.Timedelta(hours=2):
            log.info("ETH DVOL already up to date (%s) → %s", last_ts.date(), out)
            return
        start = last_ts + pd.Timedelta(hours=1)
    else:
        start = START

    url  = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    rows = []
    cur  = start
    while cur < END:
        end_window = min(cur + pd.Timedelta(days=40), END)
        data = _get(url, {
            "currency":        "ETH",
            "start_timestamp": _ms(cur),
            "end_timestamp":   _ms(end_window),
            "resolution":      3600,
        })
        if "result" not in data:
            log.error("Deribit ETH DVOL error: %s", data)
            break
        batch = data["result"].get("data", [])
        if not batch:
            cur = end_window + pd.Timedelta(hours=1)
            continue
        rows.extend(batch)
        last = pd.Timestamp(batch[-1][0], unit="ms", tz="UTC")
        cur  = last + pd.Timedelta(hours=1)
        if len(batch) < 10:
            cur = end_window + pd.Timedelta(hours=1)
        log.info("  ETH DVOL fetched to %s  (%d rows total)", last.date(), len(rows))

    if not rows:
        log.warning("ETH DVOL: no data returned")
        return

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").astype(float).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    if out.exists():
        old = pd.read_parquet(out)
        df  = pd.concat([old, df]).sort_index()
        df  = df[~df.index.duplicated(keep="last")]

    df.to_parquet(out)
    log.info(
        "ETH DVOL saved: %d bars (%s to %s) → %s",
        len(df), df.index[0].date(), df.index[-1].date(), out,
    )


# ── Daily liquidation notional (Binance Data Vision) ─────────────────────────

def download_liquidations() -> None:
    """
    Binance Data Vision daily liquidationSnapshot zips.
    Each zip has per-event rows; we aggregate to daily notional totals.

    Columns in output:
      liq_buy_notional   — notional of SHORT positions liquidated
                           (exchange bought to close shorts)
      liq_sell_notional  — notional of LONG positions liquidated
                           (exchange sold to close longs)
      liq_net_notional   — buy - sell (positive = more short liq)
      liq_count          — total liquidation events

    For the FEAR EXHAUSTION signal we use liq_sell_notional (long liquidations):
    an unusual spike in forced long selling signals capitulation, which has
    historically preceded positive 24h returns in the N3 high-DVOL regime.
    """
    out = RAW / "BTCUSDT_liquidations_daily.parquet"
    if out.exists():
        existing   = pd.read_parquet(out)
        start_date = existing.index[-1].date()
        log.info("Liquidations: extending from %s", start_date)
        all_rows = list(existing.reset_index().to_dict("records"))
    else:
        start_date = START.date()
        all_rows   = []

    base  = "https://data.binance.vision/data/futures/um/daily/liquidationSnapshot/BTCUSDT"
    dates = pd.date_range(start_date, END.date(), freq="D")
    found = 0

    for d in dates:
        url = f"{base}/BTCUSDT-liquidationSnapshot-{d.strftime('%Y-%m-%d')}.zip"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                continue
            r.raise_for_status()
        except Exception as e:
            log.debug("  %s: %s", d.date(), e)
            continue

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            fname = z.namelist()[0]
            raw   = pd.read_csv(z.open(fname), header=None)

        # Column layout varies by date; detect by count
        # Standard layout: symbol, side, order_type, time_in_force,
        #   orig_qty, price, avg_price, order_status,
        #   last_fill_qty, cum_fill_qty, liq_time
        if raw.shape[1] >= 11:
            raw.columns = [
                "symbol", "side", "order_type", "time_in_force",
                "orig_qty", "price", "avg_price", "order_status",
                "last_fill_qty", "cum_fill_qty", "liq_time",
            ] + [f"extra_{i}" for i in range(raw.shape[1] - 11)]
        else:
            log.warning("  %s: unexpected column count %d, skipping", d.date(), raw.shape[1])
            continue

        raw["avg_price"]    = pd.to_numeric(raw["avg_price"],    errors="coerce")
        raw["cum_fill_qty"] = pd.to_numeric(raw["cum_fill_qty"], errors="coerce")
        raw["notional"]     = raw["avg_price"] * raw["cum_fill_qty"]
        raw                 = raw.dropna(subset=["notional"])

        buy_not  = raw.loc[raw["side"] == "BUY",  "notional"].sum()
        sell_not = raw.loc[raw["side"] == "SELL", "notional"].sum()
        all_rows.append({
            "date":               pd.Timestamp(d, tz="UTC"),
            "liq_buy_notional":   buy_not,
            "liq_sell_notional":  sell_not,
            "liq_net_notional":   buy_not - sell_not,
            "liq_count":          len(raw),
        })
        found += 1
        time.sleep(0.1)

    if not all_rows:
        log.warning("Liquidations: no data downloaded")
        return

    df = (
        pd.DataFrame(all_rows)
        .rename(columns={"date": "open_time"})
        .set_index("open_time")
        .sort_index()
    )
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(out)
    log.info(
        "Liquidations saved: %d daily rows (%s to %s), %d new days → %s",
        len(df), df.index[0].date(), df.index[-1].date(), found, out,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Phase 4 data downloads")
    p.add_argument("--eth-dvol", action="store_true", help="Deribit ETH DVOL 1h bars")
    p.add_argument("--liq",      action="store_true", help="Binance daily liquidation notional")
    p.add_argument("--all",      action="store_true", help="Download everything")
    args = p.parse_args()

    if not any([args.eth_dvol, args.liq, args.all]):
        args.all = True   # default: download everything

    if args.all or args.eth_dvol:
        log.info("=== Deribit ETH DVOL ===")
        download_eth_dvol()

    if args.all or args.liq:
        log.info("=== Binance daily liquidations ===")
        download_liquidations()

    log.info("Done.")
