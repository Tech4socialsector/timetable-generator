"""Load the scheduling engine from this repository's ``src/`` package.

``src/`` (domain.py, solver.py, data_loader.py) is the original engine used by
``main.py``. The Frappe app uses the very same code, so a change to ``src/``
reaches both the command line and the web app. Nothing in ``src/`` is copied
or modified by the app.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # <repo>/timetable_app/engine/_upstream.py
SRC_DIR = REPO_ROOT / "src"


def load(module: str):
	"""Import ``src.<module>`` from this repository and verify it is the right ``src``."""
	if not (SRC_DIR / "solver.py").exists():
		raise ImportError(f"Engine not found: expected {SRC_DIR}/solver.py next to the timetable_app package.")
	if str(REPO_ROOT) not in sys.path:
		sys.path.append(str(REPO_ROOT))
	pkg = importlib.import_module("src")
	found = Path(getattr(pkg, "__file__", "") or "").resolve().parent
	if found != SRC_DIR.resolve():
		raise ImportError(f"A different 'src' package ({found}) shadows the timetable engine at {SRC_DIR}.")
	return importlib.import_module(f"src.{module}")
