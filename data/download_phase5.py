"""
Phase 5 data downloads — cross-exchange funding rates.

S3 Cross-Exchange Funding Divergence requires:
  Bybit:  data/raw/BTCUSDT_bybit_funding.parquet   (8h, back to 2022)
  OKX:    data/raw/BTCUSDT_okx_funding.parquet     (8h, ~90 day API limit)

S1 (Realized Skewness) and S2 (Pre-Settlement Flow) use existing 1m klines.

Usage (from repo root):
  python data/download_phase5.py
  python data/download_phase5.py --bybit
  python data/download_phase5.py --okx
"""
from __future__ import annotations
import argparse
import logging
import time
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


def _get(url: str, params: dict, retries: int = 5, sleep: float = 0.35) -> dict:
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
            log.warning("retry %d after %ds -- %s", attempt + 1, wait, exc)
            time.sleep(wait)


# ── Bybit funding rates ───────────────────────────────────────────────────────

def download_bybit_funding() -> None:
    """
    Bybit v5 public: /v5/market/funding/history
    Max 200 per call, descending order. Iterates forward in 60-day windows.
    Bybit has full history back to contract launch (2020).

    Output columns: fundingRate (float), indexed by UTC settlement timestamp.
    """
    out = RAW / "BTCUSDT_bybit_funding.parquet"
    url = "https://api.bybit.com/v5/market/funding/history"
    rows: list[dict] = []

    cur = START
    while cur < END:
        win_end = min(cur + pd.Timedelta(days=60), END)
        data = _get(url, {
            "category":  "linear",
            "symbol":    "BTCUSDT",
            "startTime": _ms(cur),
            "endTime":   _ms(win_end),
            "limit":     200,
        })

        if data.get("retCode", -1) != 0:
            log.error("Bybit error: %s", data)
            break

        records = data.get("result", {}).get("list", [])
        if not records:
            cur = win_end + pd.Timedelta(hours=8)
            continue

        for r in records:
            rows.append({
                "ts":          pd.Timestamp(int(r["fundingRateTimestamp"]), unit="ms", tz="UTC"),
                "fundingRate": float(r["fundingRate"]),
            })

        newest = max(int(r["fundingRateTimestamp"]) for r in records)
        cur    = pd.Timestamp(newest, unit="ms", tz="UTC") + pd.Timedelta(hours=8)
        log.info("  Bybit fetched to %s  (%d rows)", cur.date(), len(rows))

    if not rows:
        log.warning("Bybit: no data returned")
        return

    df = (
        pd.DataFrame(rows)
        .drop_duplicates("ts")
        .set_index("ts")
        .sort_index()[["fundingRate"]]
    )
    df.index.name = None
    df.to_parquet(out)
    log.info(
        "Bybit saved: %d rows (%s to %s) -> %s",
        len(df), df.index[0].date(), df.index[-1].date(), out,
    )


# ── OKX funding rates ─────────────────────────────────────────────────────────

def download_okx_funding() -> None:
    """
    OKX v5 public: /api/v5/public/funding-rate-history
    Max 100 per call, descending. Cursor-based via `after` (records older than cursor).
    Note: OKX API retains only ~90 days of funding history on this endpoint.

    Output columns: fundingRate (float), indexed by UTC settlement timestamp.
    """
    out  = RAW / "BTCUSDT_okx_funding.parquet"
    url  = "https://www.okx.com/api/v5/public/funding-rate-history"
    rows: list[dict] = []

    # Paginate backward from END
    cursor = str(_ms(END) + 1)

    while True:
        data = _get(url, {
            "instId": "BTC-USDT-SWAP",
            "limit":  "100",
            "after":  cursor,
        })

        if data.get("code", "-1") != "0":
            log.error("OKX error: %s", data)
            break

        records = data.get("data", [])
        if not records:
            break

        for r in records:
            rows.append({
                "ts":          pd.Timestamp(int(r["fundingTime"]), unit="ms", tz="UTC"),
                "fundingRate": float(r["fundingRate"]),
            })

        oldest    = min(int(r["fundingTime"]) for r in records)
        oldest_ts = pd.Timestamp(oldest, unit="ms", tz="UTC")
        log.info("  OKX fetched to %s  (%d rows)", oldest_ts.date(), len(rows))

        if oldest_ts <= START:
            break
        cursor = str(oldest)

    if not rows:
        log.warning("OKX: no data returned")
        return

    df = (
        pd.DataFrame(rows)
        .drop_duplicates("ts")
        .set_index("ts")
        .sort_index()[["fundingRate"]]
    )
    df.index.name = None
    df = df[df.index >= START]
    df.to_parquet(out)
    log.info(
        "OKX saved: %d rows (%s to %s) -> %s  (API limit: ~90 days)",
        len(df), df.index[0].date(), df.index[-1].date(), out,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bybit", action="store_true")
    p.add_argument("--okx",   action="store_true")
    args = p.parse_args()
    if not any([args.bybit, args.okx]):
        args.bybit = args.okx = True

    if args.bybit:
        log.info("=== Bybit BTCUSDT funding rates ===")
        download_bybit_funding()

    if args.okx:
        log.info("=== OKX BTC-USDT-SWAP funding rates ===")
        download_okx_funding()

    log.info("Done.")
