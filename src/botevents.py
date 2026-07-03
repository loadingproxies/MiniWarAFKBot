"""Append-only event queue between the bot and launcher UI.

Events are the single source of truth for the activity feed — the UI must not
infer activity from coarse status strings alone.
"""
from __future__ import annotations

import json
import os
import time

from src import appconfig

LOG_DIR = os.path.join(appconfig.ROOT, "logs")
EVENTS_PATH = os.path.join(LOG_DIR, "events.jsonl")
SEQ_PATH = os.path.join(LOG_DIR, "event_seq.txt")


def _next_seq() -> int:
    try:
        with open(SEQ_PATH, encoding="utf-8") as f:
            return int(f.read().strip() or "0") + 1
    except (OSError, ValueError):
        return 1


def _write_seq(n: int) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = SEQ_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(n))
    os.replace(tmp, SEQ_PATH)


def emit(event_type: str, **payload) -> int:
    """Append one event. Returns monotonic sequence number."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        seq = _next_seq()
        row = {"seq": seq, "ts": int(time.time()), "type": event_type}
        row.update(payload)
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _write_seq(seq)
        return seq
    except Exception:
        return 0


def read_since(since_seq: int = 0, *, tail_lines: int = 400) -> list[dict]:
    """Return events with seq > since_seq (reads only the file tail for speed)."""
    out: list[dict] = []
    try:
        with open(EVENTS_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-max(1, int(tail_lines)):]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(row.get("seq", 0)) > since_seq:
                out.append(row)
    except OSError:
        pass
    return out


def last_seq() -> int:
    try:
        with open(SEQ_PATH, encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def clear() -> None:
    for path in (EVENTS_PATH, SEQ_PATH):
        try:
            os.remove(path)
        except OSError:
            pass
