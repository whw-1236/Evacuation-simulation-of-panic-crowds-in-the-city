# -*- coding: utf-8 -*-
"""In-memory snapshot helpers for decision.forward_evaluate.

The decision module needs a save/restore boundary while it simulates candidate
actions.  Keep this module intentionally small: it snapshots the simulation
object in memory and restores the same object in place, so callers keep their
existing references.
"""

from __future__ import annotations

import copy
from typing import Any, Dict


Snapshot = Dict[str, Any]


def save_snapshot(sim: Any) -> Snapshot:
    """Return a deep-copy snapshot of a simulation object's state."""
    return copy.deepcopy(sim.__dict__)


def load_snapshot(sim: Any, snapshot: Snapshot) -> Any:
    """Restore a simulation object's state from ``save_snapshot`` output."""
    sim.__dict__.clear()
    sim.__dict__.update(copy.deepcopy(snapshot))
    return sim
