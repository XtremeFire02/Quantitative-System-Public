"""
Split-sync checker.

Detects two classes of drift:
  1. Hardcoded split dates in research scripts that bypass framework/splits.py
  2. Experiment YAML files referencing scripts or reports that no longer exist

Run from the project root:
    python scripts/check_sync.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from framework.registry import load_all
from framework.splits import TRAIN_END, VAL_END

# Canonical date strings derived from framework/splits.py
_CANONICAL = {
    TRAIN_END.strftime("%Y-%m-%d"),  # "2024-01-01"
    VAL_END.strftime("%Y-%m-%d"),    # "2024-07-01"
}

# Pattern: an ISO date string appearing as a literal, NOT inside framework/splits.py
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

_FRAMEWORK_SPLITS = _ROOT / "framework" / "splits.py"
# Killed scripts are frozen records — never modify post-kill, so exclude them.
# Only active code must import from framework.splits.
_ACTIVE_DIRS = [
    _ROOT / "research" / "validated",
    _ROOT / "backtest",
    _ROOT / "strategies",
    _ROOT / "live",
]


def _check_hardcoded_dates() -> list[str]:
    issues: list[str] = []
    for base in _ACTIVE_DIRS:
        if not base.exists():
            continue
        for py in sorted(base.rglob("*.py")):
            if py.resolve() == _FRAMEWORK_SPLITS.resolve():
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if "framework.splits" in line or "from framework" in line:
                    continue
                for m in _DATE_RE.finditer(line):
                    if m.group(1) in _CANONICAL:
                        rel = py.relative_to(_ROOT)
                        issues.append(
                            f"  {rel}:{lineno}  hardcoded split date {m.group(1)!r}"
                            "  — import from framework.splits instead"
                        )
    return issues


def _check_registry_files() -> list[str]:
    issues: list[str] = []
    exps = load_all()
    for exp_id, exp in exps.items():
        report = exp.get("report")
        if report and not (_ROOT / report).exists():
            issues.append(f"  [{exp_id}] report not found: {report}")
        for script in exp.get("scripts", []):
            if not (_ROOT / script).exists():
                issues.append(f"  [{exp_id}] script not found: {script}")
        splits_ref = (exp.get("dataset") or {}).get("splits", "")
        if splits_ref != "framework.splits":
            issues.append(
                f"  [{exp_id}] dataset.splits should be 'framework.splits', "
                f"got: {splits_ref!r}"
            )
    return issues


def main() -> int:
    print("=" * 60)
    print("Split-sync check")
    print(f"Canonical TRAIN_END : {TRAIN_END.date()}")
    print(f"Canonical VAL_END   : {VAL_END.date()}")
    print("=" * 60)

    date_issues = _check_hardcoded_dates()
    reg_issues = _check_registry_files()

    if date_issues:
        print(f"\n[WARN] Hardcoded split dates found ({len(date_issues)}):")
        print("\n".join(date_issues))
    else:
        print("\n[OK] No hardcoded split dates in research/backtest/strategies/live")

    if reg_issues:
        print(f"\n[WARN] Registry file issues ({len(reg_issues)}):")
        print("\n".join(reg_issues))
    else:
        print("[OK] All registry paths resolve")

    total = len(date_issues) + len(reg_issues)
    print(f"\n{'PASS' if total == 0 else 'FAIL'} — {total} issue(s) found")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
