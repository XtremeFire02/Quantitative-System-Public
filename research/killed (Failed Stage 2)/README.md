# Killed Hypotheses

Scripts in this directory tested signals that **did not pass** the validation bar
and were formally retired. They are kept for reference and reproducibility —
the exact code that was tested is preserved unchanged.

**The validation bar:**  OOS block-bootstrap p ≤ 0.05 AND annualised Sharpe > 1.5
on a held-out test set that was never used during development.

---

## Kill Log

| Script | Signal / Hypothesis | Why Killed | Verdict date |
|--------|---------------------|------------|--------------|
| `01_build_dataset.py` | Dataset construction utility | Not a signal — prerequisite step only | — |
| `06_hypothesis_testing.py` | Signal C (CVD Divergence) + Signal E (VPIN) | CVD: IC insignificant in block-bootstrap (p > 0.10). VPIN: regime detection noise, no edge > RT cost | 2024 |
| `07_signal_ab_exploration.py` | Signal A (Funding Rate Curvature) + Signal B (Informed Flow) | Both failed IC screen: |IC| below breakeven threshold. No further development warranted | 2024 |
| `08_signal_f_vpin_asymmetry.py` | Signal F (Directional VPIN Asymmetry) | Regime classifier precision/recall insufficient for trading. IC decays to zero by lag 5 | 2024 |
| `09_mechanism_signals.py` | H1 Basis Dislocation mechanism | Positive IC but execution infeasible — signal fires at settlement bars with < 30s to act | 2024 |
| `10_basis_rigorous.py` | H1 Basis (rigorous OOS test) | OOS 2024 regime shift: basis mean-reversion accelerated, signal decayed | 2024 |
| `11_signal_e_premium_index.py` | Signal E Premium Index (1m continuous) | IC positive in-sample but decays sharply in OOS; not robust to 2024-2026 period | 2024 |
| `12_h1_execution_study.py` | H1 execution feasibility | Even with conditional entry, slippage + adverse selection consumes the edge entirely | 2024 |
| `13_h1_2025_oos.py` | H1 extended OOS 2022–2026 | IC negative in 2025 period; regime died. Formally killed | 2025 |
| `14_h1_h2_oos_combination.py` | H1 + H2 (funding carry) combination | H1 dead weight drags H2 performance; combination worse than H2 alone | 2025 |
| `15_h1_execution_feasibility.py` | H1 selective entry thresholds | Multiple threshold combinations tested — none achieve p ≤ 0.05 in OOS | 2025 |
| `16_phase2_quick_screen.py` | Phase 2 OI signals (D1, D2, D3) screen | D1, D2 failed IC screen. D3 marginal (became P3 after refinement → see `research/active/p3/`) | 2025 |
| `25_du_short.py` | DU Regime SHORT (price down + OI up) | **Formally killed.** OOS Sharpe −0.44, block-bootstrap p = 1.000 (n=57). Zero edge | 2026-05-14 |
| `25_phase4_ic_screen.py` (Q4a) | Basis momentum (high basis → long) | Unfiltered IC passes (ratio 3.79x, p≈0), but DVOL≥δ filter p=0.061 fails the 0.05 gate. Direction correct (5/5). Borderline — killed per pre-committed criteria | 2026-05-15 |
| `25_phase4_ic_screen.py` (Q4b) | Basis contrarian (low basis → long) | Wrong direction (IC=−0.113). The momentum direction (Q4a) is correct, not contrarian. 0/5 OOS sub-periods correct | 2026-05-15 |
| `25_phase4_ic_screen.py` (Q5a) | ETH N3z alone → BTC returns | Wrong direction in OOS (IC=−0.067). Signal reversed after 2024-H1. 1/5 stability. ETH vol alone is not a reliable BTC predictor | 2026-05-15 |
| `25_phase4_ic_screen.py` (Q5b) | BTC×ETH N3z product | Near-zero IC (−0.015, ratio 0.52x). Combining BTC and ETH z-scores multiplicatively adds noise. 2/5 stability | 2026-05-15 |
| `25_phase4_ic_screen.py` (Q6) | Liquidation Exhaustion (long-liq spike) | **Data unavailable.** Binance Data Vision liquidation snapshot endpoint returned HTTP 404 for all dates 2022–2026. Cannot be tested without an alternative source | 2026-05-15 |

| `27_phase5_ic_screen.py` (S1b) | Skewness velocity (rate of change) | Wrong direction in OOS (IC=-0.019), 2/5 stability. Speed of skewness reversion adds no information | 2026-05-15 |
| `27_phase5_ic_screen.py` (S2a) | Pre-settlement flow × funding | Near-zero IC (+0.001), 3/5 stability only. The settlement-timing mechanism exists but is too weak and inconsistent to trade | 2026-05-15 |
| `27_phase5_ic_screen.py` (S2b) | Pre-settlement flow contrarian | IC=+0.014 (below 0.5x unfiltered threshold). DVOL-filtered FAILS completely (ratio 0.017x). No edge in the raw microstructure | 2026-05-15 |
| `27_phase5_ic_screen.py` (S3a) | Bybit-Binance funding divergence | IC=-0.034, wrong direction, 2/5 stability. Divergence does not reliably predict Binance price direction; too much noise | 2026-05-15 |
| `27_phase5_ic_screen.py` (S3b) | OKX-Binance funding divergence | OKX API retains only ~90 days of history. Insufficient OOS data for IC screen (7% coverage) — untestable | 2026-05-15 |
| `28_s1a_deep_dive.py` (S1a) | Realized skewness level (contrarian) | Passed IC screen (6/7 gates) but killed in deep dive: CI lower bound -0.0076 (cannot confirm signal is real). Standalone Sharpe 1.55 vs N3's 3.30. Critically: S1a ALONE loses money (Sh=-2.26); its IC is entirely driven by overlap with N3 regime. Does NOT increase trade frequency (0.7/wk vs N3's 1.2/wk) | 2026-05-15 |

---

## Notes

- Scripts are numbered in the order they were run. Gaps in numbering reflect
  scripts that graduated to `research/active/` rather than being killed.
- `backtest/run.py` tested the CVD and VPIN implementations against held-out
  data and its results also belong to this kill record (see `results/killed/`).
- Archive implementations of CVD and VPIN live in `archive/strategies/` —
  their code is preserved but they are not used in production.
