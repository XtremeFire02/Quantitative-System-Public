"""
Deribit options data — IV surface, options chain.
Uses get_book_summary_by_currency for a single batch call covering all options.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from app.config import DERIBIT_BASE
from app.data.retry import async_retry


def _now() -> datetime:
    return datetime.now(timezone.utc)


@async_retry(max_attempts=3, base_delay=1.0)
async def fetch_options_summary(currency: str = "BTC") -> list[dict]:
    """
    All listed options for a currency via get_book_summary_by_currency.

    Returns a flat list of option records with IV, bid/ask, OI, volume.
    One HTTP request covers all expiries and strikes.
    """
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(
            f"{DERIBIT_BASE}/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
        )
        r.raise_for_status()
        results = r.json().get("result", [])

    out = []
    for d in results:
        inst = d.get("instrument_name", "")
        parts = inst.split("-")
        if len(parts) < 4:
            continue
        # Format: BTC-28MAR25-100000-C
        expiry = parts[1]
        try:
            strike = float(parts[2])
        except ValueError:
            continue
        opt_type = parts[3]  # "C" or "P"

        out.append({
            "instrument": inst,
            "currency": currency,
            "expiry": expiry,
            "strike": strike,
            "type": opt_type,
            "iv": d.get("mark_iv"),
            "bid_iv": d.get("bid_iv"),
            "ask_iv": d.get("ask_iv"),
            "mark_price": d.get("mark_price"),
            "bid": d.get("best_bid_price"),
            "ask": d.get("best_ask_price"),
            "volume_usd": d.get("volume_usd"),
            "open_interest": d.get("open_interest"),
            "underlying_price": d.get("underlying_price"),
        })

    return out


async def fetch_options_expiries(currency: str = "BTC") -> list[str]:
    """Unique expiry labels sorted chronologically."""
    data = await fetch_options_summary(currency)
    return sorted(set(d["expiry"] for d in data), key=_expiry_sort_key)


async def fetch_options_chain(currency: str = "BTC", expiry: str | None = None) -> list[dict]:
    """
    Options chain for one expiry, sorted by strike.
    If expiry is None, uses the nearest expiry.
    Returns per-strike rows: {strike, call_iv, call_bid, call_ask, call_oi, put_iv, ...}
    """
    data = await fetch_options_summary(currency)
    expiries = sorted(set(d["expiry"] for d in data), key=_expiry_sort_key)
    if not expiries:
        return []
    target = expiry if expiry in expiries else expiries[0]

    chain: dict[float, dict] = {}
    for d in data:
        if d["expiry"] != target:
            continue
        strike = d["strike"]
        if strike not in chain:
            chain[strike] = {
                "strike": strike,
                "underlying_price": d["underlying_price"],
            }
        iv_dec = (d["iv"] / 100.0) if d["iv"] else None
        spot   = d["underlying_price"]
        T      = _expiry_to_years(target)
        greeks = (
            bs_greeks(spot, strike, T, iv_dec, d["type"])
            if (iv_dec and spot and T > 0)
            else {"delta": None, "gamma": None, "theta_daily": None, "vega": None, "rho": None}
        )

        prefix = "call_" if d["type"] == "C" else "put_"
        chain[strike][prefix + "iv"] = d["iv"]
        chain[strike][prefix + "bid_iv"] = d["bid_iv"]
        chain[strike][prefix + "ask_iv"] = d["ask_iv"]
        chain[strike][prefix + "bid"] = d["bid"]
        chain[strike][prefix + "ask"] = d["ask"]
        chain[strike][prefix + "oi"] = d["open_interest"]
        chain[strike][prefix + "volume"] = d["volume_usd"]
        chain[strike][prefix + "delta"] = greeks["delta"]
        chain[strike][prefix + "gamma"] = greeks["gamma"]
        chain[strike][prefix + "theta"] = greeks["theta_daily"]
        chain[strike][prefix + "vega"]  = greeks["vega"]

    return sorted(chain.values(), key=lambda x: x["strike"])


async def fetch_iv_surface(currency: str = "BTC") -> list[dict]:
    """
    IV surface data: for each (expiry, strike) pair, call and put IV.
    Returns records sorted by expiry then strike.
    """
    data = await fetch_options_summary(currency)
    surface: dict[tuple[str, float], dict] = {}
    for d in data:
        key = (d["expiry"], d["strike"])
        if key not in surface:
            surface[key] = {
                "expiry": d["expiry"],
                "strike": d["strike"],
                "underlying_price": d["underlying_price"],
            }
        if d["type"] == "C":
            surface[key]["call_iv"] = d["iv"]
        else:
            surface[key]["put_iv"] = d["iv"]

    return sorted(
        surface.values(),
        key=lambda x: (_expiry_sort_key(x["expiry"]), x["strike"]),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _expiry_sort_key(label: str) -> tuple:
    """Convert Deribit expiry label like '28MAR25' into a sortable tuple."""
    try:
        day = int(label[:2])
        month = _MONTH_MAP.get(label[2:5].upper(), 0)
        year = 2000 + int(label[5:])
        return (year, month, day)
    except Exception:
        return (9999, 99, 99)


def _expiry_to_years(label: str) -> float:
    """Time to expiry in years (Deribit settles at 08:00 UTC)."""
    key = _expiry_sort_key(label)
    if key[0] == 9999:
        return 0.0
    settle = datetime(key[0], key[1], key[2], 8, 0, tzinfo=timezone.utc)
    secs = max(0.0, (settle - _now()).total_seconds())
    return secs / (365.25 * 86400)


# ── Black-Scholes Greeks ─────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf (exact)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(
    S: float,
    K: float,
    T: float,
    sigma: float,
    opt_type: str = "C",
    r: float = 0.0,
) -> dict:
    """
    Black-Scholes delta, gamma, theta (daily), vega (per 1% IV move), rho.
    S=spot, K=strike, T=years to expiry, sigma=IV as decimal (0.70 = 70%).
    Returns None for all Greeks when inputs are degenerate.
    """
    if T <= 1e-6 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": None, "gamma": None, "theta_daily": None, "vega": None, "rho": None}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    pdf_d1 = _norm_pdf(d1)
    nd1    = _norm_cdf(d1)
    nd2    = _norm_cdf(d2)
    nd2_m  = _norm_cdf(-d2)

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    vega  = S * pdf_d1 * sqrt_T / 100.0  # per 1% IV

    if opt_type.upper() == "C":
        delta = nd1
        theta = (-(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
                 - r * K * math.exp(-r * T) * nd2) / 365.25
        rho   = K * T * math.exp(-r * T) * nd2 / 100.0
    else:
        delta = nd1 - 1.0
        theta = (-(S * pdf_d1 * sigma) / (2.0 * sqrt_T)
                 + r * K * math.exp(-r * T) * nd2_m) / 365.25
        rho   = -K * T * math.exp(-r * T) * nd2_m / 100.0

    return {
        "delta":       round(delta, 4),
        "gamma":       round(gamma, 6),
        "theta_daily": round(theta, 4),
        "vega":        round(vega, 4),
        "rho":         round(rho, 4),
    }
