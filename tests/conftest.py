"""Lets the tests import modules from src/ (for example: from parse import ...)."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))