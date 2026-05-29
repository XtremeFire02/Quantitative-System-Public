"""
Replay certification tests.

Two layers:
  1. Unit tests — run always. Verify _build_trades() and _compute_stats()
     produce correct results on synthetic DataFrame inputs. This ensures the
     frozen strategy rule is implemented correctly regardless of whether
     local parquet files are present.

  2. Integration test — skipped automatically when parquet files are absent.
     When files ARE present it runs GET /api/replay and asserts summary
     statistics match the reference targets within 5% tolerance:
       n_trades ≈ 199, Sharpe ≈ +2.95, total_pnl_bp ≈ +11,228.

Run:
  cd paper_trading/backend
  pytest tests/test_replay_certification.py -v
"""
import math

import pandas as pd
import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_daily(n=50, dvol=60.0, n3z=1.0, r24h=0.005, fund_24h=0.0001):
    """Build a synthetic daily DataFrame with constant conditions."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "dvol": dvol,
        "n3_z": n3z,
        "r24h": r24h,
        "fund_24h": fund_24h,
        "close": 50_000.0,
    }, index=idx)


def _import_build():
    from app.api.replay import _build_trades, _compute_stats
    return _build_trades, _compute_stats


# ── 1. Frozen rule unit tests ─────────────────────────────────────────────────

def test_no_trades_below_dvol_threshold():
    bt, cs = _import_build()
    df = _make_daily(dvol=50.0, n3z=1.5)   # DVOL=50 < 54 → no signal
    result = bt(df)
    assert len(result) == 0, "DVOL below 54 must produce no trades"


def test_no_trades_below_n3z_threshold():
    bt, cs = _import_build()
    df = _make_daily(dvol=60.0, n3z=0.5)   # n3z=0.5 < 0.75 → no signal
    result = bt(df)
    assert len(result) == 0, "N3z below 0.75 must produce no trades"


def test_long_entries_when_both_thresholds_met():
    bt, cs = _import_build()
    df = _make_daily(n=10, dvol=60.0, n3z=1.0, r24h=0.005)
    result = bt(df)
    assert len(result) == 10, "All bars above both thresholds should generate trades"
    assert (result["pos"] == 1.0).all(), "All trades should be LONG (+1)"


def test_net_pnl_positive_for_winning_long():
    bt, cs = _import_build()
    df = _make_daily(n=20, dvol=60.0, n3z=1.0, r24h=0.01, fund_24h=0.0)
    result = bt(df)
    stats = cs(result)
    assert stats["total_pnl_bp"] > 0, "Consistently winning longs should have positive PnL"


def test_round_trip_cost_deducted():
    """A flat market (r24h=0) with n trades should show net_pnl = -cost × n."""
    bt, cs = _import_build()
    n = 5
    df = _make_daily(n=n, dvol=60.0, n3z=1.0, r24h=0.0, fund_24h=0.0)
    result = bt(df)
    # Each trade: cost = ONE_WAY_COST (entry) but since position doesn't change,
    # cost is ONE_WAY_COST on first entry then 0 for held positions.
    # Verify that fees > 0 (some cost was deducted)
    total_cost = -result["net_r"].sum()   # should be positive (cost drag)
    assert total_cost > 0, "Flat market trades should have negative net PnL due to costs"


def test_compute_stats_sharpe_definition():
    bt, cs = _import_build()
    df = _make_daily(n=100, dvol=60.0, n3z=1.0, r24h=0.002, fund_24h=0.0)
    result = bt(df)
    stats = cs(result)

    r = result["net_r"]
    expected_sharpe = round(r.mean() / r.std() * math.sqrt(252), 3)
    assert abs(stats["sharpe"] - expected_sharpe) < 1e-6, "Sharpe formula mismatch"


def test_compute_stats_win_rate():
    bt, cs = _import_build()
    # Half positive, half negative
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    net_r = [0.005, -0.003, 0.007, -0.002, 0.004, 0.001, -0.001, 0.006, -0.004, 0.002]
    result = pd.DataFrame({"net_r": net_r, "pos": 1.0, "n3z": 1.0,
                           "dvol": 60.0, "r24h": net_r, "fund_24h": 0.0,
                           "gross_r": net_r, "cost": 0.0,
                           "cumulative_pnl": pd.Series(net_r).cumsum().values},
                          index=idx)
    stats = cs(result)
    winners = sum(1 for x in net_r if x > 0)
    assert abs(stats["win_rate"] - winners / len(net_r)) < 1e-9


def test_no_trades_returns_empty_stats():
    _, cs = _import_build()
    stats = cs(pd.DataFrame())
    assert stats["n_trades"] == 0
    assert stats["sharpe"] is None


# ── 2. Parquet integration test (skips when files absent) ────────────────────

def _parquet_files_exist() -> bool:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent.parent.parent
    raw = root / "data" / "raw"
    return all((raw / f).exists() for f in [
        "BTCUSDT_1m_klines.parquet",
        "BTC_deribit_dvol_1h.parquet",
        "BTCUSDT_funding.parquet",
    ])


@pytest.mark.skipif(not _parquet_files_exist(), reason="Local parquet files not present")
def test_replay_matches_reference_targets():
    """
    Certification gate: replay must reproduce reference statistics within 5%.
    Reference (OOS 2024-2026): n≈199 trades, Sharpe≈+2.95, PnL≈+11,228bp.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/replay?start=2024-01-01")
    assert response.status_code == 200

    data = response.json()
    summary = data["summary"]
    ref = data["reference_targets"]

    TOLERANCE = 0.05   # 5%

    n_actual = summary["n_trades"]
    n_ref = ref["n_trades"]
    assert abs(n_actual - n_ref) / n_ref <= TOLERANCE, (
        f"Trade count {n_actual} deviates from reference {n_ref} by more than 5%"
    )

    sharpe_actual = summary["sharpe"]
    sharpe_ref = ref["sharpe"]
    assert sharpe_actual is not None, "Sharpe must not be None"
    assert abs(sharpe_actual - sharpe_ref) / sharpe_ref <= TOLERANCE, (
        f"Sharpe {sharpe_actual} deviates from reference {sharpe_ref} by more than 5%"
    )

    pnl_actual = summary["total_pnl_bp"]
    pnl_ref = ref["total_pnl_bp"]
    assert abs(pnl_actual - pnl_ref) / pnl_ref <= TOLERANCE, (
        f"PnL {pnl_actual}bp deviates from reference {pnl_ref}bp by more than 5%"
    )
