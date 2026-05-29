"""
Order Management System — persistent order lifecycle for the paper trading stack.

State machine:
    submitted → acknowledged → partially_filled → filled
                              ↘ cancelled
              ↘ rejected

In paper trading all transitions fire synchronously (zero round-trip latency).
A live exchange adapter would drive the same state machine via webhook or poll,
making the transition from paper to live a drop-in swap in broker_adapter.py.

Usage:
    order = oms.submit_order(db, market="BTCUSDT", ...)
    oms.acknowledge_order(db, order.id)
    oms.fill_order(db, order.id, fill_price=..., fill_type="maker", trade_id=42)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import Order, SystemLog


class InvalidTransition(Exception):
    pass


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "submitted":       {"acknowledged", "rejected"},
    "acknowledged":    {"partially_filled", "filled", "cancelled"},
    "partially_filled": {"filled", "cancelled"},
    "filled":          set(),
    "cancelled":       set(),
    "rejected":        set(),
}


def submit_order(
    db: Session,
    market: str,
    strategy_name: str,
    side: str,
    notional_usd: float,
    requested_price: float,
    run_ref: str | None = None,
    order_type: str = "market",
    time_in_force: str = "IOC",
) -> Order:
    """Create a new order in SUBMITTED state and persist it."""
    order = Order(
        order_ref=str(uuid.uuid4()),
        run_ref=run_ref,
        market=market,
        strategy_name=strategy_name,
        side=side,
        notional_usd=notional_usd,
        requested_price=requested_price,
        status="submitted",
        fill_quantity_pct=0.0,
        order_type=order_type,
        time_in_force=time_in_force,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    _log(db, "INFO", "oms",
         f"Order #{order.id} submitted: {side} {market}/{strategy_name} "
         f"@ {requested_price:.2f} notional=${notional_usd:,.0f}")
    return order


def acknowledge_order(db: Session, order_id: int) -> Order:
    """submitted → acknowledged."""
    order = _get_and_validate(db, order_id, "acknowledged")
    order.status = "acknowledged"
    order.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order


def fill_order(
    db: Session,
    order_id: int,
    fill_price: float,
    fill_type: str,
    trade_id: int,
    fill_quantity_pct: float = 1.0,
) -> Order:
    """acknowledged/partially_filled → partially_filled | filled."""
    target = "partially_filled" if fill_quantity_pct < 1.0 else "filled"
    order = _get_and_validate(db, order_id, target)
    order.status = target
    order.fill_price = fill_price
    order.fill_type = fill_type
    order.fill_quantity_pct = fill_quantity_pct
    order.trade_id = trade_id
    order.filled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    _log(db, "INFO", "oms",
         f"Order #{order.id} {target}: fill @ {fill_price:.2f} [{fill_type}] "
         f"qty={fill_quantity_pct:.0%} trade=#{trade_id}")
    return order


def cancel_order(db: Session, order_id: int, reason: str = "") -> Order:
    """acknowledged/partially_filled → cancelled."""
    order = _get_and_validate(db, order_id, "cancelled")
    order.status = "cancelled"
    order.rejection_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    _log(db, "WARNING", "oms", f"Order #{order.id} cancelled: {reason or 'no reason'}")
    return order


def reject_order(db: Session, order_id: int, reason: str = "") -> Order:
    """submitted → rejected."""
    order = _get_and_validate(db, order_id, "rejected")
    order.status = "rejected"
    order.rejection_reason = reason
    order.rejected_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    _log(db, "WARNING", "oms", f"Order #{order.id} rejected: {reason or 'no reason'}")
    return order


def get_order(db: Session, order_id: int) -> Order | None:
    return db.query(Order).filter(Order.id == order_id).first()


def get_orders_for_trade(db: Session, trade_id: int) -> list[Order]:
    return db.query(Order).filter(Order.trade_id == trade_id).all()


def _get_and_validate(db: Session, order_id: int, target: str) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise ValueError(f"Order #{order_id} not found")
    allowed = _VALID_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise InvalidTransition(
            f"Order #{order_id}: cannot transition {order.status!r} → {target!r}. "
            f"Allowed from {order.status!r}: {allowed or '(terminal)'}."
        )
    return order


def _log(db: Session, level: str, component: str, message: str) -> None:
    db.add(SystemLog(level=level, component=component, message=message))
    db.commit()
