"""In-process daily fetch health snapshot.

Low-cost production visibility: scheduler writes the latest daily_fetch outcome
here, and dashboard/health endpoints can read it. No DB schema change, no
external alerting system.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.utils.date_helper import cn_now

_LAST_DAILY_FETCH: dict[str, Any] = {
    "status": "never_run",
    "ok": False,
    "last_run_at": None,
    "errors": [],
    "stats": None,
}


def record_fetch_result(stats: dict[str, Any]) -> None:
    """Record fetch_and_store_today stats from scheduler."""
    errors = list(stats.get("errors") or [])
    status = "ok" if not errors else "partial_failure"
    _LAST_DAILY_FETCH.update({
        "status": status,
        "ok": not errors,
        "last_run_at": cn_now(),
        "errors": errors,
        "stats": deepcopy(stats),
    })


def record_fetch_exception(exc: Exception) -> None:
    """Record a scheduler-level exception from daily_fetch."""
    msg = f"{type(exc).__name__}: {exc}"
    _LAST_DAILY_FETCH.update({
        "status": "failed",
        "ok": False,
        "last_run_at": cn_now(),
        "errors": [msg],
        "stats": None,
    })


def get_fetch_health() -> dict[str, Any]:
    """Return a copy suitable for API serialization."""
    return deepcopy(_LAST_DAILY_FETCH)
