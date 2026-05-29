"""
Position sizing engine.

Sizing modes (set via POSITION_SIZING_MODE env var):

  fixed (default) — always returns POSITION_NOTIONAL_USD.
      Backward-compatible with all existing paper-trade history.

  vol_target — scales notional so the position contributes a fixed
      annualized volatility equal to PORTFOLIO_VOL_TARGET × capital.
      Signal confidence (0–1) optionally weights the raw size down,
      and the result is clipped to POSITION_CONCENTRATION_CAP × equity
      and clamped to [POSITION_MIN_USD, POSITION_MAX_USD].

Vol-targeting formula:
    raw_notional   = (VOL_TARGET / asset_vol_ann) × available_capital
    signal_notional = raw_notional × _confidence_weight(signal_strength)
    notional       = clip(signal_notional, 0, capital × CONCENTRATION_CAP)
    notional       = clamp(notional, POSITION_MIN_USD, POSITION_MAX_USD)

Confidence weighting: maps signal_strength ∈ [0, 1] → weight ∈ [0.5, 1.0]
so even a low-confidence signal still deploys half the vol-targeted size.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import (
    PORTFOLIO_VOL_TARGET,
    POSITION_CONCENTRATION_CAP,
    POSITION_MAX_USD,
    POSITION_MIN_USD,
    POSITION_NOTIONAL_USD,
    POSITION_SIZING_MODE,
)


@dataclass
class SizingInput:
    signal_strength: float    # 0–1 confidence; 1.0 = maximum conviction
    asset_vol_ann: float      # annualized decimal vol (e.g. DVOL=54 → 0.54)
    available_capital: float  # current portfolio equity in USD
    strategy_name: str


@dataclass
class SizingOutput:
    notional_usd: float
    vol_target_raw: float | None        # vol-targeted notional before caps; None in fixed mode
    signal_weight: float                # confidence multiplier applied
    concentration_cap_applied: bool
    min_max_clipped: bool
    sizing_mode: str                    # "fixed" | "vol_target"


def compute_size(inp: SizingInput) -> SizingOutput:
    """
    Compute the notional USD size for a new position.

    In fixed mode this is always POSITION_NOTIONAL_USD regardless of
    signal_strength or volatility. Switch to vol_target via env var.
    """
    if POSITION_SIZING_MODE != "vol_target":
        return SizingOutput(
            notional_usd=POSITION_NOTIONAL_USD,
            vol_target_raw=None,
            signal_weight=1.0,
            concentration_cap_applied=False,
            min_max_clipped=False,
            sizing_mode="fixed",
        )

    asset_vol = max(inp.asset_vol_ann, 0.01)   # floor — avoid division by zero
    raw = (PORTFOLIO_VOL_TARGET / asset_vol) * inp.available_capital

    weight = _confidence_weight(inp.signal_strength)
    weighted = raw * weight

    cap_limit = inp.available_capital * POSITION_CONCENTRATION_CAP
    capped = min(weighted, cap_limit)

    final = max(POSITION_MIN_USD, min(capped, POSITION_MAX_USD))

    return SizingOutput(
        notional_usd=round(final, 2),
        vol_target_raw=round(raw, 2),
        signal_weight=round(weight, 4),
        concentration_cap_applied=weighted > cap_limit,
        min_max_clipped=(final != capped),
        sizing_mode="vol_target",
    )


def _confidence_weight(strength: float) -> float:
    """Map signal strength [0, 1] → position weight [0.5, 1.0]."""
    return 0.5 + 0.5 * max(0.0, min(1.0, strength))
