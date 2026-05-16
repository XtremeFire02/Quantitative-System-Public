"""
Experiment registry — loads all YAML files from experiments/ and provides
a structured query interface. Single source of truth for signal metadata.

Usage:
    from framework.registry import load_all, get, validated, killed
    exps = load_all()
    a1   = get("A1")
    live = validated()
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not installed — run: pip install pyyaml")

_ROOT = Path(__file__).resolve().parents[1]
_EXP_DIR = _ROOT / "experiments"


def _load_file(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data.setdefault("_path", str(path.relative_to(_ROOT)))
    return data


def load_all() -> dict[str, dict[str, Any]]:
    """Return all experiments keyed by id (e.g. 'A1', 'B2')."""
    if not _EXP_DIR.exists():
        raise FileNotFoundError(f"experiments/ directory not found at {_EXP_DIR}")
    return {
        d["id"]: d
        for path in sorted(_EXP_DIR.glob("*.yaml"))
        if (d := _load_file(path)) and "id" in d
    }


def get(exp_id: str) -> dict[str, Any]:
    """Load a single experiment by id. Raises KeyError if not found."""
    exps = load_all()
    if exp_id not in exps:
        raise KeyError(f"Experiment '{exp_id}' not found. Available: {list(exps)}")
    return exps[exp_id]


def validated() -> list[dict[str, Any]]:
    """All experiments with status == 'validated'."""
    return [e for e in load_all().values() if e.get("status") == "validated"]


def killed() -> list[dict[str, Any]]:
    """All experiments with status == 'killed'."""
    return [e for e in load_all().values() if e.get("status") == "killed"]


def in_progress() -> list[dict[str, Any]]:
    """All experiments with status == 'in_progress'."""
    return [e for e in load_all().values() if e.get("status") == "in_progress"]


def summary() -> None:
    """Print a one-line summary of every registered experiment."""
    exps = load_all()
    status_icon = {"validated": "[+]", "killed": "[-]", "in_progress": "[~]"}
    print(f"{'ID':<6} {'Status':<12} {'Stage':>5}  Name")
    print("-" * 60)
    for exp in sorted(exps.values(), key=lambda e: e["id"]):
        icon = status_icon.get(exp.get("status", ""), "?")
        print(
            f"{exp['id']:<6} "
            f"{icon} {exp.get('status', '?'):<10} "
            f"{exp.get('stage_reached', '?'):>5}  "
            f"{exp.get('name', '')}"
        )


if __name__ == "__main__":
    summary()
