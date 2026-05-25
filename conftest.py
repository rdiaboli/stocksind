"""Ensures the repo root is on sys.path so ``import config`` and
``from src.screener import ...`` resolve when running pytest."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
