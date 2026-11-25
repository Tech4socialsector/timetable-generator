"""The CP-SAT solver from ``src/solver.py`` (the original engine), used unchanged."""

from ._upstream import load

_solver = load("solver")

TimetableSolver = _solver.TimetableSolver
SolutionProgressTracker = _solver.SolutionProgressTracker
