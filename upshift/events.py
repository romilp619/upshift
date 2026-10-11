"""Structured run events - the source of truth for anything watching a run.

The agent's console output is for people. A dashboard needs something it can
rely on: one JSON object per line, appended and flushed as things happen, with a
sequence number so a reader that reconnects can resume exactly where it left
off. Disabled (a no-op) unless UPSHIFT_EVENTS names a file.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


class EventLog:
    def __init__(self, path: str | None):
        self.path = Path(path) if path else None
        self.seq = 0
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                # Resume numbering if the file already has events.
                for line in self.path.read_text().splitlines():
                    try:
                        self.seq = max(self.seq, int(json.loads(line).get("seq", 0)))
                    except (ValueError, json.JSONDecodeError):
                        continue

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def emit(self, type_: str, **data) -> None:
        if not self.path:
            return
        with self._lock:
            self.seq += 1
            record = {"seq": self.seq, "t": round(time.time(), 3), "type": type_, **data}
            with self.path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())


EVENTS = EventLog(os.environ.get("UPSHIFT_EVENTS"))
