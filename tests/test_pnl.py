"""Tests for the PnL calculator (pure functions, no DB dependency)."""
import math
import pytest
from app.trading.pnl import calculate_pnl, calculate_unrealised_pnl
from app.config import ONE_WAY_COST


# ── Basic long trade scenarios ────────────────────────────────────────────────

def test_long_positive_return():
    result = calculate_pnl(
        side="long",
        entry_price=50000.0,
        exit_price=51000.0,
        funding_rates=[],
    )
    gross = math.log(51000.0 / 50000.0)
    assert result["gross_price_return"] == pytest.approx(gross, rel=1e-6)
    assert result["net_pnl"] < result["gross_price_return"]  # fees reduce PnL
    assert result["net_pnl"] > 0


def test_long_negative_return():
    result = calculate_pnl(
        side="long",
        entry_price=50000.0,
        exit_price=49000.0,
        funding_rates=[],
    )
    assert result["gross_price_return"] < 0
    assert result["net_pnl"] < result["gross_price_return"]  # fees make it worse


def test_long_breakeven_return():
    # When price return exactly covers fees, net PnL ~= 0
    round_trip = 2 * ONE_WAY_COST
    exit_price = 50000.0 * math.exp(round_trip)
    result = calculate_pnl(
        side="long",
        entry_price=50000.0,
        exit_price=exit_price,
        funding_rates=[],
    )
    assert result["net_pnl"] == pytest.approx(0.0, abs=1e-8)


# ── Fees ──────────────────────────────────────────────────────────────────────

def test_fees_equal_two_one_way_costs():
    result = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[])
    assert result["fees"] == pytest.approx(2 * ONE_WAY_COST, rel=1e-9)


def test_net_pnl_equals_gross_minus_funding_minus_fees():
    funding = [0.001, -0.0005]  # two 8h settlements
    result = calculate_pnl("long", 50000.0, 51000.0, funding_rates=funding)
    expected_net = (
        result["gross_price_return"]
        + result["funding_pnl"]
        - result["fees"]
    )
    assert result["net_pnl"] == pytest.approx(expected_net, rel=1e-9)


# ── Funding ───────────────────────────────────────────────────────────────────

def test_positive_funding_rate_hurts_long():
    # Positive funding rate: longs pay shorts
    result_with_funding = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[0.001])
    result_no_funding = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[])
    assert result_with_funding["net_pnl"] < result_no_funding["net_pnl"]


def test_negative_funding_rate_helps_long():
    # Negative funding rate: shorts pay longs
    result_with_funding = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[-0.001])
    result_no_funding = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[])
    assert result_with_funding["net_pnl"] > result_no_funding["net_pnl"]


def test_funding_pnl_sums_all_settlements():
    funding = [0.0005, -0.0002, 0.0003]
    result = calculate_pnl("long", 50000.0, 50000.0, funding_rates=funding)
    # Long pays positive net funding
    expected_funding_pnl = -(0.0005 - 0.0002 + 0.0003)
    assert result["funding_pnl"] == pytest.approx(expected_funding_pnl, rel=1e-9)


def test_empty_funding_is_zero():
    result = calculate_pnl("long", 50000.0, 50000.0, funding_rates=[])
    assert result["funding_pnl"] == pytest.approx(0.0)


# ── Basis points conversion ───────────────────────────────────────────────────

def test_net_pnl_bp_is_net_pnl_times_10000():
    result = calculate_pnl("long", 50000.0, 51000.0, funding_rates=[])
    assert result["net_pnl_bp"] == pytest.approx(result["net_pnl"] * 10000, rel=1e-9)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_zero_entry_price_returns_zero_gross():
    result = calculate_pnl("long", 0.0, 50000.0, funding_rates=[])
    assert result["gross_price_return"] == 0.0


def test_zero_exit_price_returns_zero_gross():
    result = calculate_pnl("long", 50000.0, 0.0, funding_rates=[])
    assert result["gross_price_return"] == 0.0


# ── Unrealised PnL ────────────────────────────────────────────────────────────

def test_unrealised_pnl_positive_when_price_rises():
    upnl = calculate_unrealised_pnl("long", entry_price=50000.0, current_price=51000.0)
    assert upnl > 0


def test_unrealised_pnl_negative_when_price_falls():
    upnl = calculate_unrealised_pnl("long", entry_price=50000.0, current_price=49000.0)
    assert upnl < 0


def test_unrealised_pnl_zero_at_entry():
    upnl = calculate_unrealised_pnl("long", entry_price=50000.0, current_price=50000.0)
    assert upnl == pytest.approx(0.0, abs=1e-10)
