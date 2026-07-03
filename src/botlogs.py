"""Structured append-only logs for purchases and restock timing."""
from __future__ import annotations

import json
import os
import time

from src import appconfig

LOG_DIR = os.path.join(appconfig.ROOT, "logs")
PURCHASES_PATH = os.path.join(LOG_DIR, "purchases.jsonl")
TIMELINE_PATH = os.path.join(LOG_DIR, "restock_timeline.jsonl")

# Wiped when the bot stops (see cleanup_on_stop).
_CLEAR_ON_STOP_DIRS = ("logs", "events", "debug", "timed")


def _append(path: str, row: dict) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        row = dict(row)
        row.setdefault("ts", int(time.time()))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_purchase(*, name: str, category: str, qty: int, dry: bool = False,
                 confirmed=None, outcome: str = "ok", tag: str = "") -> None:
    _append(PURCHASES_PATH, {
        "type": "purchase",
        "name": name,
        "category": category,
        "qty": qty,
        "dry": dry,
        "confirmed": confirmed,
        "outcome": outcome,
        "tag": tag,
    })


def log_timeline(phase: str, **extra) -> None:
    _append(TIMELINE_PATH, {"type": "timeline", "phase": phase, **extra})


def log_session(*, checks: int, buys: int, reason: str = "stopped") -> None:
    _append(TIMELINE_PATH, {
        "type": "session",
        "phase": reason,
        "checks": checks,
        "buys": buys,
    })


def _should_cleanup_on_stop(cfg: dict | None = None) -> bool:
    if cfg is None:
        try:
            cfg = appconfig.load()
        except Exception:
            return True
    return bool((cfg.get("logs") or {}).get("cleanup_on_stop", True))


def _remove_file(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _clear_dir_files(path: str) -> int:
    """Delete all files in a directory (not subdirs). Returns count removed."""
    n = 0
    try:
        names = os.listdir(path)
    except OSError:
        return 0
    for name in names:
        fp = os.path.join(path, name)
        if os.path.isfile(fp) and _remove_file(fp):
            n += 1
    return n


def cleanup_on_stop(root: str | None = None, *, cfg: dict | None = None) -> int:
    """Remove all log files when the bot stops. Returns the number of files removed."""
    if not _should_cleanup_on_stop(cfg):
        return 0
    root = root or appconfig.ROOT
    removed = 0
    for dirname in _CLEAR_ON_STOP_DIRS:
        removed += _clear_dir_files(os.path.join(root, dirname))
    return removed


def tail_jsonl(path: str, limit: int = 50) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-max(1, int(limit)):]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def format_purchase_rows(rows: list[dict]) -> list[str]:
    lines: list[str] = []
    for r in rows:
        if r.get("type") != "purchase":
            continue
        ts = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0)))
        mode = "TEST" if r.get("dry") else "LIVE"
        tag = r.get("tag") or r.get("outcome") or "ok"
        qty = r.get("qty", 0)
        name = r.get("name", "?")
        cat = r.get("category", "?")
        conf = r.get("confirmed")
        sfx = f" confirmed={conf}" if conf is not None else ""
        lines.append(f"[{ts}] [{mode}] {name} x{qty} ({cat}) - {tag}{sfx}")
    return lines or ["No purchases logged yet."]


def format_timeline_rows(rows: list[dict]) -> list[str]:
    lines: list[str] = []
    for r in rows:
        ts = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0)))
        kind = r.get("type", "?")
        if kind == "session":
            lines.append(
                f"[{ts}] SESSION {r.get('phase', '?')} - "
                f"{r.get('checks', 0)} checks, {r.get('buys', 0)} buys"
            )
            continue
        phase = r.get("phase", "?")
        parts = [f"[{ts}] {phase}"]
        if r.get("reason"):
            parts.append(f"reason={r['reason']}")
        if r.get("duration_ms") is not None:
            parts.append(f"{r['duration_ms']}ms")
        if r.get("items") is not None:
            parts.append(f"{r['items']} items")
        if r.get("purchases") is not None:
            parts.append(f"{r['purchases']} buys")
        if r.get("error"):
            parts.append(f"ERR: {r['error']}")
        lines.append(" - ".join(parts))
    return lines or ["No timeline events yet."]


def restock_timestamps(limit: int = 30) -> list[int]:
    """Unix timestamps of recent restock_detected events."""
    rows = tail_jsonl(TIMELINE_PATH, limit=200)
    out: list[int] = []
    for r in rows:
        if r.get("type") == "timeline" and r.get("phase") == "restock_detected":
            out.append(int(r.get("ts", 0)))
    return out[-limit:]


def restock_eta(default_avg_sec: int = 240) -> dict:
    """Estimate seconds until next restock from recent intervals."""
    times = restock_timestamps()
    if len(times) < 2:
        return {
            "avg_sec": default_avg_sec,
            "next_in_sec": None,
            "samples": max(0, len(times)),
            "last_ts": times[-1] if times else 0,
        }
    intervals = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    intervals = [x for x in intervals if 120 <= x <= 600]
    avg = int(sum(intervals) / len(intervals)) if intervals else default_avg_sec
    last = times[-1]
    next_in = max(0, int(avg - (time.time() - last)))
    return {
        "avg_sec": avg,
        "next_in_sec": next_in,
        "samples": len(intervals),
        "last_ts": last,
    }
