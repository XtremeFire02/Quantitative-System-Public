"""
Options API — chain, IV surface, expiry list.
GET /api/options/expiries?currency=BTC
GET /api/options/chain?currency=BTC&expiry=28MAR25
GET /api/options/surface?currency=BTC
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data.deribit_options import (
    fetch_iv_surface,
    fetch_options_chain,
    fetch_options_expiries,
)

router = APIRouter()


@router.get("/options/expiries")
async def get_expiries(
    currency: str = Query("BTC", description="Currency: BTC or ETH"),
):
    """Available expiry dates for an options currency."""
    cur = currency.upper()
    if cur not in ("BTC", "ETH"):
        raise HTTPException(status_code=400, detail="currency must be BTC or ETH")
    try:
        expiries = await fetch_options_expiries(cur)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deribit error: {exc}")
    return {"currency": cur, "expiries": expiries}


@router.get("/options/chain")
async def get_options_chain(
    currency: str = Query("BTC"),
    expiry: str = Query(None, description="Expiry label, e.g. 28MAR25. Defaults to nearest expiry."),
):
    """
    Options chain for a specific expiry.
    Each row covers one strike with call and put columns.
    """
    cur = currency.upper()
    if cur not in ("BTC", "ETH"):
        raise HTTPException(status_code=400, detail="currency must be BTC or ETH")
    try:
        chain = await fetch_options_chain(cur, expiry)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deribit error: {exc}")
    return {"currency": cur, "expiry": expiry, "rows": chain}


@router.get("/options/surface")
async def get_iv_surface(
    currency: str = Query("BTC"),
):
    """
    IV surface: all (expiry, strike) pairs with call_iv and put_iv.
    Suitable for rendering a heatmap or 3D surface.
    """
    cur = currency.upper()
    if cur not in ("BTC", "ETH"):
        raise HTTPException(status_code=400, detail="currency must be BTC or ETH")
    try:
        surface = await fetch_iv_surface(cur)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deribit error: {exc}")

    # Derive unique axes for the heatmap
    expiries = sorted(set(r["expiry"] for r in surface))
    strikes = sorted(set(r["strike"] for r in surface))

    return {
        "currency": cur,
        "expiries": expiries,
        "strikes": strikes,
        "surface": surface,
    }
