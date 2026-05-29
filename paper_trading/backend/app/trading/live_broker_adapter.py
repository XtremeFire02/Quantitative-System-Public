"""
Live Binance Futures broker adapter.

Implements the BrokerAdapter protocol using real Binance FAPI calls.
ONLY active when LIVE_TRADING_ENABLED=true and both API credentials are set.
All order attempts are logged to SystemLog via the supplied SQLAlchemy session.

Safety contract
---------------
- Every public method calls _check_enabled() first; if live trading is not
  configured the method raises LiveTradingNotEnabled before touching anything.
- All exceptions from the exchange or OMS transitions are caught and surfaced
  as a FillResult(status="rejected"), never propagated raw to the caller.
- Only MARKET orders are placed — no limit, no stop.

State machine (same as paper path)
-----------------------------------
  submit_order → acknowledge_order → [reject | fill]_order
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.database import SystemLog
from app.trading import oms
from app.trading.paper_broker import open_trade

# FillResult is imported lazily at call-time to avoid a circular import
# (broker_adapter imports this module at the bottom for re-export).
# TYPE_CHECKING guard satisfies static analysis without a runtime import.
if TYPE_CHECKING:
    from app.trading.broker_adapter import FillResult


class LiveTradingNotEnabled(Exception):
    """Raised when a live broker method is called without proper configuration."""


def _sign(params: dict, secret: str) -> str:
    """Compute HMAC-SHA256 signature over the URL-encoded parameter string."""
    query = urlencode(params)
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=query.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _log(db: Session, level: str, component: str, message: str) -> None:
    db.add(SystemLog(level=level, component=component, message=message))
    db.commit()


class LiveBrokerAdapter:
    """
    Live Binance Futures broker adapter.

    Only active when LIVE_TRADING_ENABLED=true and both API keys are set.
    Uses MARKET orders only. No partial fills are expected for market orders.
    """

    def __init__(self) -> None:
        self._enabled: bool = (
            os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
        )
        self._api_key: str = os.getenv("BINANCE_API_KEY", "")
        self._api_secret: str = os.getenv("BINANCE_API_SECRET", "")
        self._base_url: str = os.getenv(
            "BINANCE_FAPI_BASE", "https://fapi.binance.com"
        )

    # ── Guard ─────────────────────────────────────────────────────────────────

    def _check_enabled(self) -> None:
        if not self._enabled:
            raise LiveTradingNotEnabled(
                "Set LIVE_TRADING_ENABLED=true to use live trading"
            )
        if not self._api_key or not self._api_secret:
            raise LiveTradingNotEnabled(
                "BINANCE_API_KEY and BINANCE_API_SECRET are required for live trading"
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    async def _get_mark_price(self, client: httpx.AsyncClient, symbol: str) -> float:
        """Fetch current Binance mark price for *symbol* (no auth required)."""
        resp = await client.get(
            f"{self._base_url}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=10.0,
        )
        resp.raise_for_status()
        return float(resp.json()["markPrice"])

    def _build_signed_params(self, extra: dict) -> dict:
        """Return params dict with timestamp + signature appended."""
        params = {**extra, "timestamp": int(time.time() * 1000)}
        params["signature"] = _sign(params, self._api_secret)
        return params

    # ── BrokerAdapter protocol ────────────────────────────────────────────────

    async def submit(self, db: Session, request) -> "FillResult":
        """
        Submit a market order to Binance Futures.

        Flow:
          1. Guard: raises LiveTradingNotEnabled if not configured.
          2. Persist order through OMS (submitted → acknowledged).
          3. Fetch mark price to compute quantity.
          4. Reject locally if quantity < 0.001 BTC.
          5. POST market order to Binance.
          6. On exchange fill: create Trade row via open_trade(), then fill OMS order.
          7. On any error: reject OMS order, return FillResult(rejected).
        """
        from app.trading.broker_adapter import FillResult  # lazy — avoids circular import
        self._check_enabled()

        # -- OMS: persist the order before touching the exchange ---------------
        order = oms.submit_order(
            db=db,
            market=request.market,
            strategy_name=request.strategy_name,
            side=request.side,
            notional_usd=request.notional_usd,
            requested_price=request.signal_price,
        )
        oms.acknowledge_order(db, order.id)

        _log(
            db, "INFO", "live_broker",
            f"Order #{order.id} acknowledged — sending MARKET {request.side.upper()} "
            f"{request.market} notional=${request.notional_usd:,.0f} to Binance",
        )

        try:
            async with httpx.AsyncClient() as client:
                # -- Step 1: get mark price to size the order ------------------
                try:
                    mark_price = await self._get_mark_price(client, request.market)
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to fetch mark price for {request.market}: {exc}"
                    ) from exc

                # -- Step 2: compute quantity (round DOWN to 3 decimal places) -
                quantity = math.floor(
                    request.notional_usd / mark_price * 1000
                ) / 1000

                if quantity < 0.001:
                    reason = (
                        f"Quantity too small: {quantity} BTC "
                        f"(notional=${request.notional_usd:.2f}, mark={mark_price:.2f})"
                    )
                    _log(db, "WARNING", "live_broker",
                         f"Order #{order.id} rejected — {reason}")
                    # Order is already 'acknowledged'; OMS only allows cancel from this state.
                    oms.cancel_order(db, order.id, reason=reason)
                    return FillResult(
                        order_id=order.id,
                        trade_id=None,
                        status="rejected",
                        fill_price=None,
                        fill_type=None,
                        fill_quantity_pct=0.0,
                        message=reason,
                    )

                # -- Step 3: map side ------------------------------------------
                binance_side = "BUY" if request.side == "long" else "SELL"

                # -- Step 4: build signed params and POST order ----------------
                raw_params = {
                    "symbol": request.market,
                    "side": binance_side,
                    "type": "MARKET",
                    "quantity": f"{quantity:.3f}",
                }
                signed_params = self._build_signed_params(raw_params)

                _log(
                    db, "INFO", "live_broker",
                    f"Order #{order.id} — POST MARKET {binance_side} "
                    f"{quantity:.3f} {request.market} @ mark={mark_price:.4f}",
                )

                try:
                    resp = await client.post(
                        f"{self._base_url}/fapi/v1/order",
                        params=signed_params,
                        headers=self._headers(),
                        timeout=10.0,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    error_body = exc.response.text
                    reason = (
                        f"Binance HTTP {exc.response.status_code}: {error_body}"
                    )
                    _log(db, "ERROR", "live_broker",
                         f"Order #{order.id} exchange error — {reason}")
                    # Order is already 'acknowledged'; OMS only allows cancel from this state.
                    oms.cancel_order(db, order.id, reason=reason)
                    return FillResult(
                        order_id=order.id,
                        trade_id=None,
                        status="rejected",
                        fill_price=None,
                        fill_type=None,
                        fill_quantity_pct=0.0,
                        message=reason,
                    )

                # -- Step 5: parse exchange response ---------------------------
                data = resp.json()
                exchange_order_id: int = data["orderId"]
                exchange_status: str = data.get("status", "UNKNOWN")
                avg_price_str: str = data.get("avgPrice", "0")
                executed_qty_str: str = data.get("executedQty", "0")

                # Persist exchange reference on the Order row
                order_row = oms.get_order(db, order.id)
                if order_row is not None:
                    order_row.exchange_ref = str(exchange_order_id)
                    db.commit()

                _log(
                    db, "INFO", "live_broker",
                    f"Order #{order.id} exchange response — "
                    f"binanceId={exchange_order_id} status={exchange_status} "
                    f"avgPrice={avg_price_str} executedQty={executed_qty_str}",
                )

                if exchange_status != "FILLED":
                    reason = f"Exchange status: {exchange_status}"
                    _log(db, "WARNING", "live_broker",
                         f"Order #{order.id} not filled — {reason}")
                    # Order is already 'acknowledged'; OMS only allows cancel from this state.
                    oms.cancel_order(db, order.id, reason=reason)
                    return FillResult(
                        order_id=order.id,
                        trade_id=None,
                        status="rejected",
                        fill_price=None,
                        fill_type=None,
                        fill_quantity_pct=0.0,
                        message=reason,
                    )

                # -- Step 6: create Trade row using the live fill price --------
                avg_price = float(avg_price_str)

                trade = open_trade(
                    db=db,
                    market=request.market,
                    strategy_name=request.strategy_name,
                    side=request.side,
                    entry_price=avg_price,        # actual exchange fill price
                    hold_hours=request.hold_hours,
                    entry_reason=request.entry_reason,
                    entry_dvol=request.entry_dvol,
                    entry_n3_z=request.entry_n3_z,
                    notional_usd=request.notional_usd,
                    exec_estimate=None,            # no simulation needed; real fill
                )

                oms.fill_order(
                    db=db,
                    order_id=order.id,
                    fill_price=avg_price,
                    fill_type="taker",             # MARKET orders are always taker
                    trade_id=trade.id,
                    fill_quantity_pct=1.0,
                )

                _log(
                    db, "INFO", "live_broker",
                    f"Order #{order.id} filled — trade #{trade.id} "
                    f"{request.side.upper()} {request.market} "
                    f"@ {avg_price:.4f} qty={executed_qty_str} "
                    f"notional=${request.notional_usd:,.0f}",
                )

                return FillResult(
                    order_id=order.id,
                    trade_id=trade.id,
                    status="filled",
                    fill_price=avg_price,
                    fill_type="taker",
                    fill_quantity_pct=1.0,
                    message=(
                        f"Filled @ {avg_price:.4f} [taker] "
                        f"qty={executed_qty_str} binanceId={exchange_order_id}"
                    ),
                )

        except LiveTradingNotEnabled:
            raise
        except Exception as exc:
            # Catch-all: cancel the OMS order and return a safe FillResult.
            # After acknowledge_order() the state is 'acknowledged'; cancel_order()
            # is the correct terminal transition (reject_order() only works from
            # 'submitted').  We silently ignore any further OMS failure since the
            # order may already be in a terminal state (filled, cancelled, etc.).
            reason = f"Unexpected error: {exc}"
            _log(db, "ERROR", "live_broker",
                 f"Order #{order.id} failed — {reason}")
            try:
                oms.cancel_order(db, order.id, reason=reason)
            except Exception:
                pass  # order may already be in a terminal state
            return FillResult(
                order_id=order.id,
                trade_id=None,
                status="rejected",
                fill_price=None,
                fill_type=None,
                fill_quantity_pct=0.0,
                message=reason,
            )

    async def cancel(self, db: Session, order_id: int, reason: str = "") -> bool:
        """
        Cancel an open order on Binance Futures, then update OMS.

        Looks up the exchange_ref on the Order row, issues DELETE /fapi/v1/order,
        and on success drives the OMS order to 'cancelled'.
        Returns True on success, False on any failure.
        """
        self._check_enabled()

        order = oms.get_order(db, order_id)
        if order is None:
            _log(db, "WARNING", "live_broker",
                 f"cancel() called for unknown order #{order_id}")
            return False

        exchange_ref = order.exchange_ref
        if not exchange_ref:
            _log(db, "WARNING", "live_broker",
                 f"Order #{order_id} has no exchange_ref; cannot cancel on Binance")
            return False

        try:
            raw_params = {
                "symbol": order.market,
                "orderId": exchange_ref,
            }
            signed_params = self._build_signed_params(raw_params)

            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{self._base_url}/fapi/v1/order",
                    params=signed_params,
                    headers=self._headers(),
                    timeout=10.0,
                )
                resp.raise_for_status()

            _log(
                db, "INFO", "live_broker",
                f"Order #{order_id} (binanceId={exchange_ref}) cancelled on exchange",
            )
            oms.cancel_order(db, order_id, reason=reason)
            return True

        except Exception as exc:
            _log(
                db, "ERROR", "live_broker",
                f"Order #{order_id} cancel failed — {exc}",
            )
            return False

    def get_order_status(self, db: Session, order_id: int) -> str | None:
        """Return the current OMS status string for an order, or None if not found."""
        order = oms.get_order(db, order_id)
        return order.status if order else None


_live_adapter = LiveBrokerAdapter()


def get_live_adapter() -> LiveBrokerAdapter:
    """Get the singleton live trading adapter.

    Raises LiveTradingNotEnabled on first method call if LIVE_TRADING_ENABLED
    is not true or API credentials are absent.
    """
    return _live_adapter
