"""
Pytest configuration for the paper trading backend tests.

sys.path entries:
  [0] paper_trading/backend  — enables `from app.xxx import yyy`
  [1] repo root              — enables `from framework.costs import ...`
                               and `from strategies.base import ...`
"""
import sys
from pathlib import Path

ROOT_DIR    = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "paper_trading" / "backend"

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(1, str(ROOT_DIR))
