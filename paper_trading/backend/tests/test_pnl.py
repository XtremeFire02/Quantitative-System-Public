"""
Unit tests for PnL calculation.

Tests calculate_pnl() from app.trading.pnl.
All tests are deterministic — no database or external I/O required.

Run:
  cd paper_trading/backend
  pytest tests/test_pnl.py -v
"""
from __future__ import annotations

import math

import pytest

from app.config import ONE_WAY_COST
from app.trading.pnl import calculate_pnl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FEES_RT = ONE_WAY_COST * 2   # round-trip fee constant


def _pnl(
    side: str = "long",
    entry_price: float = 50_000.0,
    exit_price: float = 51_000.0,
    funding_rates: list[float] | None = None,
    notional_usd: float = 10_000.0,
) -> dict:
    return calculate_pnl(
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        funding_rates=funding_rates if funding_rates is not None else [],
        notional_usd=notional_usd,
    )


# ---------------------------------------------------------------------------
# Basic long/short PnL sign tests
# ---------------------------------------------------------------------------

def test_long_winner_positive_net_pnl():
    """Long trade: exit > entry → net_pnl > 0 (after fees)."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0)

    assert result["net_pnl"] > 0.0


def test_long_loser_negative_net_pnl():
    """Long trade: exit < entry → net_pnl < 0."""
    result = _pnl(side="long", entry_price=51_000.0, exit_price=50_000.0)

    assert result["net_pnl"] < 0.0


def test_short_winner_positive_net_pnl():
    """Short trade: exit < entry → positive net_pnl (price fell, short profits)."""
    result = _pnl(side="short", entry_price=51_000.0, exit_price=50_000.0)

    assert result["net_pnl"] > 0.0


def test_short_loser_negative_net_pnl():
    """Short trade: exit > entry → negative net_pnl (price rose, short loses)."""
    result = _pnl(side="short", entry_price=50_000.0, exit_price=51_000.0)

    assert result["net_pnl"] < 0.0


# ---------------------------------------------------------------------------
# Gross price return — log-return formula
# ---------------------------------------------------------------------------

def test_gross_price_return_long_formula():
    """Long gross_price_return = log(exit/entry)."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0)

    expected = math.log(51_000.0 / 50_000.0)
    assert result["gross_price_return"] == pytest.approx(expected, rel=1e-9)


def test_gross_price_return_short_formula():
    """Short gross_price_return = -log(exit/entry) (direction flipped)."""
    result = _pnl(side="short", entry_price=51_000.0, exit_price=50_000.0)

    expected = -math.log(50_000.0 / 51_000.0)
    assert result["gross_price_return"] == pytest.approx(expected, rel=1e-9)


def test_large_move_2x_price_long():
    """2× price move gives log(2) gross return for a long."""
    result = _pnl(side="long", entry_price=30_000.0, exit_price=60_000.0)

    assert result["gross_price_return"] == pytest.approx(math.log(2.0), rel=1e-9)


def test_large_move_2x_price_short():
    """Price halving gives log(2) gross return for a short (price fell 50%)."""
    result = _pnl(side="short", entry_price=60_000.0, exit_price=30_000.0)

    assert result["gross_price_return"] == pytest.approx(math.log(2.0), rel=1e-9)


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------

def test_fees_equal_one_way_cost_times_two():
    """fees must always equal ONE_WAY_COST × 2, regardless of trade outcome."""
    for entry, exit_p, side in [
        (50_000.0, 51_000.0, "long"),
        (51_000.0, 50_000.0, "long"),
        (51_000.0, 50_000.0, "short"),
    ]:
        result = _pnl(side=side, entry_price=entry, exit_price=exit_p)
        assert result["fees"] == pytest.approx(FEES_RT, abs=1e-12)


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------

def test_slippage_is_always_zero():
    """slippage must always be 0 (included in ONE_WAY_COST per spec)."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0)

    assert result["slippage"] == 0.0


# ---------------------------------------------------------------------------
# net_pnl_bp
# ---------------------------------------------------------------------------

def test_net_pnl_bp_equals_net_pnl_times_10000():
    """net_pnl_bp = net_pnl × 10_000."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0)

    assert result["net_pnl_bp"] == pytest.approx(result["net_pnl"] * 10_000.0, rel=1e-9)


def test_net_pnl_bp_is_positive_for_long_winner():
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0)
    assert result["net_pnl_bp"] > 0.0


def test_net_pnl_bp_is_negative_for_long_loser():
    result = _pnl(side="long", entry_price=51_000.0, exit_price=50_000.0)
    assert result["net_pnl_bp"] < 0.0


# ---------------------------------------------------------------------------
# Funding PnL
# ---------------------------------------------------------------------------

def test_positive_funding_rates_reduce_long_net_pnl():
    """Positive funding rates mean longs pay → reduces long net_pnl."""
    result_no_fund = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0, funding_rates=[])
    result_funding = _pnl(
        side="long",
        entry_price=50_000.0,
        exit_price=51_000.0,
        funding_rates=[0.0001, 0.0001],
    )

    assert result_funding["net_pnl"] < result_no_fund["net_pnl"]


def test_positive_funding_rates_funding_pnl_is_negative_for_long():
    """Longs pay positive funding rates → funding_pnl < 0."""
    result = _pnl(
        side="long",
        entry_price=50_000.0,
        exit_price=51_000.0,
        funding_rates=[0.0001, 0.0002],
    )

    assert result["funding_pnl"] < 0.0


def test_negative_funding_rates_benefit_longs():
    """Negative funding rates mean longs receive payment → increases net_pnl."""
    result_no_fund = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0, funding_rates=[])
    result_funding = _pnl(
        side="long",
        entry_price=50_000.0,
        exit_price=51_000.0,
        funding_rates=[-0.0002, -0.0001],
    )

    assert result_funding["net_pnl"] > result_no_fund["net_pnl"]


def test_positive_funding_rates_reduce_short_net_pnl():
    """Shorts receive positive funding rates (direction=-1 × -sum) → funding_pnl > 0 for shorts.
    But shorts paying negative funding means negative_funding_rates reduce short net_pnl."""
    # For a short, funding_pnl = -1 × (-sum(rates)) = sum(rates)
    # Positive rates → shorts receive → funding_pnl > 0
    result = _pnl(
        side="short",
        entry_price=51_000.0,
        exit_price=50_000.0,
        funding_rates=[0.0001, 0.0001],
    )

    assert result["funding_pnl"] > 0.0


def test_negative_funding_rates_shorts_pay():
    """Negative funding rates → shorts pay → funding_pnl < 0 for short."""
    result = _pnl(
        side="short",
        entry_price=51_000.0,
        exit_price=50_000.0,
        funding_rates=[-0.0002, -0.0002],
    )

    assert result["funding_pnl"] < 0.0


def test_funding_pnl_formula_long():
    """Spot-check: direction=1, rates=[0.0001, 0.0002] → funding_pnl = -(0.0001+0.0002) = -0.0003."""
    result = _pnl(
        side="long",
        entry_price=50_000.0,
        exit_price=51_000.0,
        funding_rates=[0.0001, 0.0002],
    )

    assert result["funding_pnl"] == pytest.approx(-0.0003, abs=1e-10)


def test_funding_pnl_formula_short():
    """Spot-check: direction=-1, rates=[0.0001, 0.0002] → funding_pnl = -(-1)(0.0003) = 0.0003."""
    result = _pnl(
        side="short",
        entry_price=51_000.0,
        exit_price=50_000.0,
        funding_rates=[0.0001, 0.0002],
    )

    assert result["funding_pnl"] == pytest.approx(0.0003, abs=1e-10)


def test_empty_funding_rates_yields_zero_funding_pnl():
    """No funding settlements → funding_pnl == 0.0."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=51_000.0, funding_rates=[])

    assert result["funding_pnl"] == 0.0


# ---------------------------------------------------------------------------
# Zero price edge case
# ---------------------------------------------------------------------------

def test_zero_entry_price_no_crash():
    """Zero entry price must not raise; gross_price_return should be 0."""
    result = _pnl(side="long", entry_price=0.0, exit_price=51_000.0)

    assert result["gross_price_return"] == 0.0


def test_zero_exit_price_no_crash():
    """Zero exit price must not raise; gross_price_return should be 0."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=0.0)

    assert result["gross_price_return"] == 0.0


def test_both_zero_prices_no_crash():
    """Both prices zero must not raise; gross_price_return should be 0."""
    result = _pnl(side="long", entry_price=0.0, exit_price=0.0)

    assert result["gross_price_return"] == 0.0


# ---------------------------------------------------------------------------
# Round-trip flat trade (entry == exit, no funding)
# ---------------------------------------------------------------------------

def test_flat_trade_net_pnl_bp_is_negative_due_to_fees():
    """entry == exit, no funding → gross=0, net_pnl = -fees < 0."""
    result = _pnl(side="long", entry_price=50_000.0, exit_price=50_000.0, funding_rates=[])

    assert result["gross_price_return"] == pytest.approx(0.0, abs=1e-12)
    assert result["net_pnl"] == pytest.approx(-FEES_RT, abs=1e-12)
    assert result["net_pnl_bp"] < 0.0


# ---------------------------------------------------------------------------
# Net PnL decomposition identity
# ---------------------------------------------------------------------------

def test_net_pnl_equals_gross_plus_funding_minus_fees():
    """net_pnl = gross_price_return + funding_pnl - slippage - fees."""
    funding_rates = [0.0001, -0.00005]
    result = _pnl(
        side="long",
        entry_price=50_000.0,
        exit_price=50_500.0,
        funding_rates=funding_rates,
    )

    expected_net = (
        result["gross_price_return"]
        + result["funding_pnl"]
        - result["slippage"]
        - result["fees"]
    )
    assert result["net_pnl"] == pytest.approx(expected_net, rel=1e-9)


def test_net_pnl_decomposition_short_with_funding():
    """Same identity holds for a short trade with funding."""
    funding_rates = [0.0002, 0.0001]
    result = _pnl(
        side="short",
        entry_price=51_000.0,
        exit_price=50_000.0,
        funding_rates=funding_rates,
    )

    expected_net = (
        result["gross_price_return"]
        + result["funding_pnl"]
        - result["slippage"]
        - result["fees"]
    )
    assert result["net_pnl"] == pytest.approx(expected_net, rel=1e-9)


# ---------------------------------------------------------------------------
# Return dict keys
# ---------------------------------------------------------------------------

def test_return_dict_has_all_required_keys():
    """calculate_pnl() must return all six attribution keys."""
    result = _pnl()
    required = {"gross_price_return", "funding_pnl", "slippage", "fees", "net_pnl", "net_pnl_bp"}
    missing = required - set(result.keys())
    assert not missing, f"Missing keys: {missing}"
