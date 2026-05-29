"""Maps strategy_name strings to signal evaluator instances."""
import os

from app.signals.base import SignalEvaluator
from app.signals.cvd_divergence import CvdDivergenceEvaluator
from app.signals.execution_test import ExecutionTestEvaluator
from app.signals.funding_carry import FundingCarryEvaluator
from app.signals.n3_signal import N3DvolEvaluator
from app.signals.p3_oipd_signal import P3OIPDEvaluator

# Entry thresholds are loaded from environment variables; see .env.example.
# Specific parameter values are not published in this repository.
_N3Z_TH   = float(os.getenv("N3Z_THRESHOLD",   "0"))
_DVOL_TH  = float(os.getenv("DVOL_THRESHOLD",  "0"))
_DVOL_TH2 = float(os.getenv("DVOL_THRESHOLD_2", "0"))
_DVOL_TH3 = float(os.getenv("DVOL_THRESHOLD_3", "0"))

_REGISTRY: dict[str, SignalEvaluator] = {
    # ── Official validated strategy ────────────────────────────────────────────
    "N3_DVOL_LONG":      N3DvolEvaluator(strategy_name="N3_DVOL_LONG",      long_only=True),

    # ── Experimental variants ──────────────────────────────────────────────────
    "N3_DVOL_LONGSHORT": N3DvolEvaluator(strategy_name="N3_DVOL_LONGSHORT", long_only=False),

    # ── Shadow research variants (threshold sensitivity) ───────────────────────
    "N3_SHADOW_A":  N3DvolEvaluator(strategy_name="N3_SHADOW_A",  long_only=True,
                                    n3z_threshold=_N3Z_TH,  dvol_threshold=_DVOL_TH),
    "N3_SHADOW_B":  N3DvolEvaluator(strategy_name="N3_SHADOW_B",  long_only=True,
                                    n3z_threshold=_N3Z_TH,  dvol_threshold=_DVOL_TH2),
    "N3_SHADOW_C":  N3DvolEvaluator(strategy_name="N3_SHADOW_C",  long_only=True,
                                    n3z_threshold=_N3Z_TH,  dvol_threshold=_DVOL_TH3),

    # ── P3 OI-Price Divergence shadow ──────────────────────────────────────────
    "P3_OIPD_DD":    P3OIPDEvaluator(strategy_name="P3_OIPD_DD"),
    "P3_OIPD_DD_57": P3OIPDEvaluator(strategy_name="P3_OIPD_DD_57", dvol_threshold=_DVOL_TH2),
    "P3_OIPD_DD_60": P3OIPDEvaluator(strategy_name="P3_OIPD_DD_60", dvol_threshold=_DVOL_TH3),

    # ── Experimental ──────────────────────────────────────────────────────────
    "FUNDING_CARRY":  FundingCarryEvaluator(strategy_name="FUNDING_CARRY"),

    # ── Utility ───────────────────────────────────────────────────────────────
    "EXECUTION_TEST": ExecutionTestEvaluator(strategy_name="EXECUTION_TEST"),

    # ── Stubs ─────────────────────────────────────────────────────────────────
    "CVD_DIVERGENCE": CvdDivergenceEvaluator(strategy_name="CVD_DIVERGENCE"),
}


def get_evaluator(strategy_name: str) -> SignalEvaluator:
    if strategy_name not in _REGISTRY:
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[strategy_name]
