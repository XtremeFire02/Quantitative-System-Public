# Research

All hypothesis-testing scripts live here, organised by outcome and depth of investigation.

---

## Quantitative Research Pipeline

Every signal passes through this 7-stage pipeline. A signal is killed the moment it fails a pre-specified threshold at any stage. No stage is skipped.

```
Stage 1 — Generate Hypothesis
         Form a hypothesis about why a signal should predict returns.
         State the proposed mechanism, the expected direction, and the
         holding period. No data is touched at this stage.
         (e.g. elevated DVOL z-score predicts positive 24h returns via
          fear-resolution; positioning deterioration predicts reversal)

Stage 2 — Initial Statistical Screen
         Apply a fast, low-cost quantitative filter on in-sample data to
         determine whether the signal has any measurable predictive content.
         Signals that fail here are killed immediately before further
         research time is invested.
         (e.g. Spearman IC vs. breakeven IC threshold, t-test on mean returns,
          hit rate vs. random baseline, in-sample Sharpe)

Stage 3 — Out-of-Sample Validation
         Test the signal on data it has never seen, using a methodology that
         controls for the statistical properties of financial returns:
         serial dependence, non-normality, and multiple comparisons.
         Must achieve a pre-specified significance threshold.
         (e.g. non-overlapping daily returns, one-sided block bootstrap p ≤ 0.05,
          walk-forward cross-validation, permutation tests)

Stage 4 — Stress Testing of signal
         Deliberately attempt to invalidate the signal. Extend the evaluation
         window, stress-test across market regimes, and apply the most
         unfavourable assumptions about costs and execution. If the edge
         is fragile, it is killed here.`
         (e.g. extended OOS kill attempt, bear/bull/sideways regime splits,
          taker-cost stress test, parameter sensitivity analysis)

Stage 5 — Regime Conditioning
         Identify the structural conditions under which the signal has edge
         and those under which it does not. Apply filters to concentrate
         capital into the high-edge environment and avoid the low-edge one.
         (e.g. volatility regime filter, market microstructure conditions,
          time-of-day or funding-cycle filters, liquidity screens)

Stage 6 — Cost-Adjusted Backtest
         Simulate the strategy at the position level with realistic transaction
         costs, market impact, and carry. Evaluate risk-adjusted performance
         and capacity. The signal must generate sufficient gross edge to
         remain profitable net of all costs.
         (e.g. maker/taker fees, funding payments, slippage, Sharpe, max
          drawdown, win rate, exposure, turnover)

Stage 7 — Forward Validation
         Deploy the frozen, unmodified rule to a live or paper trading
         environment. Forward performance is compared against the backtest
         to verify implementation fidelity and detect distribution shift.
         No parameter changes are permitted during this stage.
         (e.g. paper trading with replay certification, live trading on
          reduced size, minimum 3-month observation window before promotion)
```

---

## Directory Structure

```
research/
├── validated reports/
│   ├── A1/    Validated volatility-regime signal — passed all 7 stages
│   └── A2/    Shadow positioning-regime signal — passed stages 1–6, in stage 7
│
├── killed reports/
│   ├── B1/    Phase 4 signals — passed stages 1–3, killed at stage 4–5
│   └── B2/    Phase 5 signals — passed stages 1–3, killed at stage 4–5
│
└── killed/    Phase 1 signals — killed at stage 2 (IC screen)
               Scripts as run — never modified post-kill
```

---

## Workflow

New scripts are numbered sequentially. Once a verdict is reached the script moves to the appropriate directory. No script stays at the root level permanently.

---

## Experiment Registry

Every experiment is recorded in a YAML file under `experiments/`. This is the canonical source of metadata — hypothesis, status, stage reached, key metrics, and file pointers.

```
experiments/
├── A1.yaml    Conditional DVOL Signal (N3) — validated, stage 7
├── A2.yaml    Phase 3 signals (P3 validated, P1/P2 killed)
├── B1.yaml    Phase 4 signals — killed at stage 4
└── B2.yaml    Phase 5 signals — killed at stage 4
```

**Required fields** in every experiment YAML:

| Field | Description |
|---|---|
| `id` | Matches the filename (A1, B2, …) |
| `status` | `validated` \| `killed` \| `in_progress` |
| `stage_reached` | Last pipeline stage completed (1–7) |
| `dataset.splits` | Must be `framework.splits` — never hardcode dates |
| `report` | Path to `.tex` report relative to project root |
| `scripts` | Ordered list of `.py` files that produced the results |

Query the registry from Python:

```python
from framework.registry import load_all, validated, summary
summary()          # print one-line status per experiment
validated()        # list of validated-experiment dicts
```

---

## Split Sync

All split boundaries live in `framework/splits.py` — the single source of truth. Research scripts must import from there; hardcoding dates creates silent drift if splits are ever adjusted.

**Check for drift at any time:**

```
python scripts/check_sync.py
```

This reports:
- Hardcoded split dates in active research/backtest/strategies/live scripts
- Registry YAML entries pointing to files that no longer exist

Killed scripts are excluded — they are frozen post-verdict records and are never modified.
