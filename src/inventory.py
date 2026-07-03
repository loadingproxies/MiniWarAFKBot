"""Inventory snapshots and diff → structured events.

Keeps previous vs current OCR inventory so restock/item changes are detected
in the backend, independent of UI polling.
"""
from __future__ import annotations

import json
import os
import time

from src import appconfig
from src import botevents
from src import notify
from src.parser import normalize_name
from src.shop_tabs import catalog_names_for_shop_tab, wishlist_for_shop_tab

LOG_DIR = os.path.join(appconfig.ROOT, "logs")
SNAPSHOT_PATH = os.path.join(LOG_DIR, "inventory_snapshot.json")
DEBUG_PATH = os.path.join(LOG_DIR, "pipeline_debug.jsonl")


def _item_key(category: str, name: str) -> str:
    return f"{category}:{normalize_name(name)}"


def _norm_item(it: dict, category: str) -> dict:
    return {
        "category": category,
        "name": it.get("name", ""),
        "stock": it.get("stock"),
        "status": it.get("status"),
        "rarity": it.get("rarity"),
    }


def flatten(results: dict) -> dict[str, dict]:
    """{category: [items]} → {cat:normname: item_dict}."""
    flat: dict[str, dict] = {}
    for cat, items in (results or {}).items():
        for it in items or []:
            name = it.get("name")
            if not name:
                continue
            flat[_item_key(cat, name)] = _norm_item(it, cat)
    return flat


def load_previous() -> dict[str, dict]:
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        cur = data.get("current") or {}
        return cur if isinstance(cur, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_snapshot(flat: dict) -> None:
    prev = load_previous()
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": int(time.time()),
        "previous": prev,
        "current": flat,
    }
    tmp = SNAPSHOT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SNAPSHOT_PATH)


def _available(it: dict) -> bool:
    """True only when OCR saw clear in-stock evidence (not a name-only peek)."""
    if not it:
        return False
    if it.get("status") == "out":
        return False
    stock = it.get("stock")
    if stock is not None:
        return stock > 0
    return it.get("status") == "in"


def _is_restock_change(prev: dict | None, curr: dict | None) -> bool:
    """True when an item transitions from unavailable → available between scans."""
    if not prev or not curr:
        return False
    if not _available(curr):
        return False
    return not _available(prev)


def _stock_label(it: dict) -> str:
    if it.get("status") == "out":
        return "out"
    stock = it.get("stock")
    if stock is not None and stock <= 0:
        return "out"
    if stock is not None and stock > 0:
        return "in"
    if it.get("status") == "in":
        return "in"
    return "unknown"


def compute_diff(prev: dict[str, dict], curr: dict[str, dict]) -> list[dict]:
    """Compare snapshots → list of event payloads (without seq)."""
    events: list[dict] = []
    restock_items: list[str] = []
    first_scan = not prev
    all_keys = set(prev) | set(curr)

    for key in sorted(all_keys):
        p, c = prev.get(key), curr.get(key)
        cat = (c or p or {}).get("category", key.split(":", 1)[0])
        name = (c or p or {}).get("name", key)

        if p is None and c is not None:
            if not first_scan:
                events.append({
                    "type": "item_found",
                    "category": cat,
                    "name": name,
                    "stock": c.get("stock"),
                    "status": _stock_label(c),
                })
            continue

        if p is not None and c is None:
            events.append({
                "type": "item_state_changed",
                "category": cat,
                "name": name,
                "prev_status": _stock_label(p),
                "status": "missing",
                "prev_stock": p.get("stock"),
                "stock": None,
            })
            continue

        if not p or not c:
            continue

        prev_st, curr_st = _stock_label(p), _stock_label(c)
        changed = (
            prev_st != curr_st
            or p.get("stock") != c.get("stock")
        )
        if not changed:
            continue

        ev = {
            "type": "item_state_changed",
            "category": cat,
            "name": name,
            "prev_status": prev_st,
            "status": curr_st,
            "prev_stock": p.get("stock"),
            "stock": c.get("stock"),
        }
        if curr_st == "out":
            ev["type"] = "out_of_stock"
        events.append(ev)

        if _is_restock_change(p, c):
            restock_items.append(name)

    if restock_items and prev:
        events.insert(0, {
            "type": "restock_detected",
            "source": "inventory_diff",
            "items": restock_items[:20],
            "count": len(restock_items),
        })

    return events


def find_scanned_item(wish_name: str, items: list, *, require_stock_row: bool = False,
                     cfg: dict | None = None) -> dict | None:
    """Match a wishlist name to a parsed OCR item."""
    from src.parser import match_whitelist, parse_status
    from src.game_locale import get_ui

    ui = get_ui(cfg)

    def _ok(it: dict) -> bool:
        if not require_stock_row:
            return True
        return it.get("status") is not None or it.get("stock") is not None

    def _score(it: dict) -> int:
        raw = it.get("raw") or it.get("name", "")
        st = it.get("status") or parse_status(raw, it.get("stock"), ui)
        if st == "out":
            return 5
        stock = it.get("stock")
        if stock is not None and stock > 0:
            return 4
        if st == "in":
            return 3
        if stock is not None:
            return 2
        if st:
            return 1
        return 0

    key = normalize_name(wish_name)
    candidates: list[dict] = []
    names = [it.get("name", "") for it in items]
    for it in items:
        if not _ok(it):
            continue
        nk = normalize_name(it.get("name", ""))
        if nk == key or match_whitelist(it.get("name", ""), [wish_name], ui) == wish_name:
            candidates.append(it)
    if not candidates:
        canon = match_whitelist(wish_name, names, ui)
        if canon:
            for it in items:
                if it.get("name") == canon and _ok(it):
                    candidates.append(it)
    if not candidates:
        return None
    return max(candidates, key=_score)


def count_category_changes(prev: dict[str, dict], cat: str, items: list) -> int:
    """Count inventory changes for one category vs previous snapshot."""
    curr = flatten({cat: items})
    prefix = f"{cat}:"
    keys = {k for k in prev if k.startswith(prefix)} | set(curr)
    n = 0
    for k in keys:
        p, c = prev.get(k), curr.get(k)
        if p is None and c is not None:
            n += 1
        elif p is not None and c is None:
            n += 1
        elif p and c and (
            _stock_label(p) != _stock_label(c) or p.get("stock") != c.get("stock")
        ):
            n += 1
    return n


def build_tracked_matches(cfg: dict, cat: str, items: list, prev: dict[str, dict]) -> list[dict]:
    """Cross-check scan against wishlist + enabled category."""
    nav = set(cfg.get("navigation", {}).get("categories") or [])
    if cat not in nav:
        return []
    buy_list = wishlist_for_shop_tab(cfg, cat)
    catalog = catalog_names_for_shop_tab(cfg, cat)
    if not buy_list and not catalog:
        return []

    tracked: list[dict] = []
    for wish in buy_list:
        scanned = find_scanned_item(wish, items, require_stock_row=False, cfg=cfg)
        prev_item = prev.get(_item_key(cat, wish))
        if not scanned:
            tracked.append({"name": wish, "kind": "unseen"})
            continue
        norm = _norm_item(scanned, cat)
        st = _stock_label(norm)
        if st == "out":
            tracked.append({"name": wish, "kind": "missing", "stock": scanned.get("stock")})
        elif st == "unknown":
            tracked.append({"name": wish, "kind": "unknown", "stock": scanned.get("stock")})
        elif _is_restock_change(prev_item, norm):
            tracked.append({
                "name": wish, "kind": "newly_available",
                "stock": scanned.get("stock"),
            })
        else:
            tracked.append({
                "name": wish, "kind": "found",
                "stock": scanned.get("stock"),
            })
    return tracked


def emit_category_scan_result(cfg: dict, cat: str, items: list, prev: dict[str, dict]) -> None:
    """Single user-centric scan event (replaces noisy per-item feed entries)."""
    tracked = build_tracked_matches(cfg, cat, items, prev)
    changes = count_category_changes(prev, cat, items)
    items_scanned = len(items)
    botevents.emit(
        "scan_result",
        category=cat,
        items_scanned=items_scanned,
        changes_detected=changes,
        tracked=tracked,
    )
    notify.scan_result(cfg, cat, items_scanned, changes, tracked)


def lookup_item(items_map: dict[str, dict], category: str, display_name: str) -> dict | None:
    """Fuzzy lookup for UI — catalog name → live inventory row."""
    exact = _item_key(category, display_name)
    if exact in items_map:
        return items_map[exact]
    key = normalize_name(display_name)
    prefix = f"{category}:"
    for k, v in items_map.items():
        if not k.startswith(prefix):
            continue
        kn = k.split(":", 1)[1]
        if kn == key or key in kn or kn in key:
            return v
    # Stock may live under another tab (e.g. Special-tab items shown in Factory list).
    for k, v in items_map.items():
        kn = k.split(":", 1)[1]
        if kn == key or key in kn or kn in key:
            return v
    return None


def emit_diff_events(prev: dict[str, dict], curr: dict[str, dict]) -> list[dict]:
    """Compute diff, emit each event, return emitted list (with type)."""
    events = compute_diff(prev, curr)
    for ev in events:
        t = ev["type"]
        # Banner detection already emitted restock_detected; skip inventory diff
        # duplicate (was showing "Restock detected" twice + double sound/alert).
        if t == "restock_detected":
            continue
        payload = {k: v for k, v in ev.items() if k != "type"}
        botevents.emit(t, **payload)
    return events


def log_pipeline(*, reason: str, prev: dict, curr: dict, events: list,
                   raw_summary: str | None = None) -> None:
    """Debug log: parsed inventory, diff, emitted events."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        row = {
            "ts": int(time.time()),
            "reason": reason,
            "prev_count": len(prev),
            "curr_count": len(curr),
            "event_count": len(events),
            "events": events,
            "parsed_summary": raw_summary,
        }
        with open(DEBUG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_live_state() -> dict:
    """Current inventory for UI stock dots."""
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"ts": 0, "items": {}, "categories": {}}

    cur = data.get("current") or {}
    ts = int(data.get("ts", 0))
    items: dict[str, dict] = {}
    categories: dict[str, dict] = {}

    for key, it in cur.items():
        cat = it.get("category", "")
        entry = {
            "name": it.get("name"),
            "stock": it.get("stock"),
            "status": _stock_label(it),
            "ts": ts,
            "category": cat,
        }
        items[key] = entry
        # alias keys by normalized display name for catalog cross-lookup
        if cat and it.get("name"):
            alias = _item_key(cat, it["name"])
            if alias != key:
                items[alias] = entry
        if cat:
            c = categories.setdefault(cat, {"item_count": 0, "last_scan_ts": ts})
            c["item_count"] += 1

    return {"ts": ts, "items": items, "categories": categories}


def clear() -> None:
    try:
        os.remove(SNAPSHOT_PATH)
    except OSError:
        pass
