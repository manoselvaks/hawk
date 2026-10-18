"""Track OpenRouter spend in a log file and refuse to go past a cap.

Every paid call appends one JSON line to the log (``data/llm_spend.jsonl``) with the
cost OpenRouter reported for it (``usage.cost``, in US dollars) and the running total.
The log is committed with the repository, so the total carries across machines and
sessions: the API key has a hard lifetime limit, and the tracker is what keeps us
under it.

Before each call the tracker checks that ``spent + reserve`` stays under the cap,
where ``reserve`` is a generous upper bound on one call. Once the cap is reached
nothing more is sent until someone raises it on purpose (``--spend-cap`` or the
``HAWK_SPEND_CAP_USD`` environment variable).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

SPEND_LOG = Path("data/llm_spend.jsonl")
DEFAULT_CAP_USD = 4.0
DEFAULT_RESERVE_USD = 0.01


class BudgetExceededError(Exception):
    """Raised instead of making a call that could take spend past the cap."""


def default_cap() -> float:
    return float(os.environ.get("HAWK_SPEND_CAP_USD", DEFAULT_CAP_USD))


class SpendTracker:
    def __init__(
        self,
        log_path: Path = SPEND_LOG,
        cap_usd: float | None = None,
        reserve_usd: float = DEFAULT_RESERVE_USD,
    ) -> None:
        self.log_path = log_path
        self.cap_usd = default_cap() if cap_usd is None else cap_usd
        self.reserve_usd = reserve_usd
        self.spent_usd = self._read_total()
        self.session_usd = 0.0
        self._lock = threading.Lock()

    def _read_total(self) -> float:
        if not self.log_path.exists():
            return 0.0
        total = 0.0
        for line in self.log_path.read_text().splitlines():
            if line.strip():
                total += float(json.loads(line)["cost_usd"])
        return total

    def check(self) -> None:
        """Raise ``BudgetExceededError`` if one more call could break the cap."""
        with self._lock:
            self._check()

    def _check(self) -> None:
        if self.spent_usd + self.reserve_usd > self.cap_usd:
            raise BudgetExceededError(
                f"OpenRouter spend ${self.spent_usd:.4f} plus a ${self.reserve_usd:.2f} reserve "
                f"would exceed the ${self.cap_usd:.2f} cap; refusing to make another call"
            )

    def record(self, cost_usd: float, *, model: str, key: str) -> None:
        with self._lock:
            self._record(cost_usd, model, key)

    def _record(self, cost_usd: float, model: str, key: str) -> None:
        self.spent_usd += cost_usd
        self.session_usd += cost_usd
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": model,
            "key": key,
            "cost_usd": round(cost_usd, 8),
            "cumulative_usd": round(self.spent_usd, 8),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
