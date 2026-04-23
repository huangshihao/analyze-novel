"""Entry point for both `python src/main.py` and the PyInstaller-bundled exe."""

import sys
from pathlib import Path

# Make sibling modules importable without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui import launch


if __name__ == "__main__":
    launch()
