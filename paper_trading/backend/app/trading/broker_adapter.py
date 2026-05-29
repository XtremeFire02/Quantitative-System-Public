"""
Broker abstraction — stable interface for paper and live execution.

The BrokerAdapter Protocol defines the contract that any execution venue
must satisfy. PaperBrokerAdapter implements it by wrapping the OMS +
paper_broker stack, recording every order through persistent state
transitions before delegating fill simulation to paper_broker.open_trade().

Switching from paper to live requires only:
  1. Implement BrokerAdapter on a live exchange client
  2. Replace get_paper_adapter() call-site with get_live_adapter()

Both adapters produce identical FillResult objects; the rest of the
daily signal job is venue-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session


@dataclass
class OrderRequest:
    market: str
    strategy_name: str
    side: str                   # "long" | "short"
    notional_usd: float
    signal_price: float         # evaluation price at signal time
    entry_reason: str
    hold_hours: int
    exec_estimate: object | None = None   # ExecutionEstimate from execution_sim
    entry_dvol: float | None = None
    entry_n3_z: float | None = None


@dataclass
class FillResult:
    order_id: int
    trade_id: int | None
    status: str                 # "filled" | "partially_filled" | "rejected"
    fill_price: float | None
    fill_type: str | None       # "maker" | "taker"
    fill_quantity_pct: float    # 0.0 – 1.0
    message: str


@runtime_checkable
class BrokerAdapter(Protocol):
    async def submit(self, db: Session, request: OrderRequest) -> FillResult:
        """Submit a new order and return the fill result."""
        ...

    async def cancel(self, db: Session, order_id: int, reason: str) -> bool:
        """Cancel an open order. Returns True if successfully cancelled."""
        ...

    def get_order_status(self, db: Session, order_id: int) -> str | None:
        """Return the current status string for an order, or None if not found."""
        ...


class PaperBrokerAdapter:
    """
    Paper broker adapter.

    Routes every entry through the OMS state machine so orders are
    durably persisted before any fill simulation occurs. All transitions
    fire synchronously (paper trading has no exchange round-trip latency).

    Rejection path: if paper_broker.open_trade() raises (e.g. a risk
    check that slipped through), the order is moved to REJECTED and a
    FillResult with status="rejected" is returned — the caller never sees
    a raw exception.
    """

    async def submit(self, db: Session, request: OrderRequest) -> FillResult:
        from app.trading import oms
        from app.trading.paper_broker import open_trade

        order = oms.submit_order(
            db=db,
            market=request.market,
            strategy_name=request.strategy_name,
            side=request.side,
            notional_usd=request.notional_usd,
            requested_price=request.signal_price,
        )

        # Paper: acknowledge immediately (no exchange round-trip)
        oms.acknowledge_order(db, order.id)

        try:
            trade = open_trade(
                db=db,
                market=request.market,
                strategy_name=request.strategy_name,
                side=request.side,
                entry_price=request.signal_price,
                hold_hours=request.hold_hours,
                entry_reason=request.entry_reason,
                entry_dvol=request.entry_dvol,
                entry_n3_z=request.entry_n3_z,
                notional_usd=request.notional_usd,
                exec_estimate=request.exec_estimate,
            )
            oms.fill_order(
                db=db,
                order_id=order.id,
                fill_price=trade.entry_price,
                fill_type=trade.fill_type or "maker",
                trade_id=trade.id,
                fill_quantity_pct=1.0,
            )
            return FillResult(
                order_id=order.id,
                trade_id=trade.id,
                status="filled",
                fill_price=trade.entry_price,
                fill_type=trade.fill_type,
                fill_quantity_pct=1.0,
                message=f"Filled @ {trade.entry_price:.4f} [{trade.fill_type or 'maker'}]",
            )
        except Exception as exc:
            oms.reject_order(db, order.id, reason=str(exc))
            return FillResult(
                order_id=order.id,
                trade_id=None,
                status="rejected",
                fill_price=None,
                fill_type=None,
                fill_quantity_pct=0.0,
                message=str(exc),
            )

    async def cancel(self, db: Session, order_id: int, reason: str = "") -> bool:
        from app.trading import oms
        try:
            oms.cancel_order(db, order_id, reason=reason)
            return True
        except Exception:
            return False

    def get_order_status(self, db: Session, order_id: int) -> str | None:
        from app.trading import oms
        order = oms.get_order(db, order_id)
        return order.status if order else None


_paper_adapter = PaperBrokerAdapter()


def get_paper_adapter() -> PaperBrokerAdapter:
    return _paper_adapter


# Live adapter — imported here so callers can reach LiveTradingNotEnabled
# from the same broker_adapter namespace without knowing the implementation module.
from app.trading.live_broker_adapter import (  # noqa: E402
    LiveBrokerAdapter,
    LiveTradingNotEnabled,
    get_live_adapter,
)

__all__ = [
    "BrokerAdapter",
    "FillResult",
    "OrderRequest",
    "PaperBrokerAdapter",
    "get_paper_adapter",
    "LiveBrokerAdapter",
    "LiveTradingNotEnabled",
    "get_live_adapter",
]
