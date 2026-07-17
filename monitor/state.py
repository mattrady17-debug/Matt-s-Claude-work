"""Anti-duplication memory: a JSON file recording every event already alerted on."""

import json
from datetime import date, timedelta
from pathlib import Path

RETENTION_DAYS = 120


class State:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, str] = {}  # event_id -> ISO date first alerted
        if path.exists():
            self._data = json.loads(path.read_text()).get("alerted_events", {})

    def already_alerted(self, event_id: str) -> bool:
        return event_id in self._data

    def record(self, event_id: str, on: date) -> None:
        self._data.setdefault(event_id, on.isoformat())

    def prune(self, today: date) -> None:
        cutoff = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        self._data = {k: v for k, v in self._data.items() if v >= cutoff}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"alerted_events": dict(sorted(self._data.items()))}, indent=2) + "\n"
        )
