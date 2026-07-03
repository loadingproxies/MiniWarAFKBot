"""Verify scan_result Discord embed + Activity feed formatting.

Run:  python tools/verify_scan_notify.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.notify import build_scan_embed


def format_tracked_item(t):
    """Mirror of tools/launcher.py formatTrackedItem()."""
    kind = t.get("kind", "missing")
    name = t.get("name", "?")
    stock = t.get("stock")
    if kind == "missing":
        return {"icon": "⚠", "cls": "missing", "msg": f"{name} — Out of Stock"}
    if kind == "newly_available":
        sfx = f" (x{stock})" if stock else ""
        return {"icon": "✨", "cls": "new", "msg": f"{name} — Just Restocked{sfx}"}
    sfx = f" (x{stock})" if stock else ""
    return {"icon": "✔", "cls": "found", "msg": f"{name} — In Stock{sfx}"}


def build_scan_block(ev, time="12:00:00"):
    cat = (ev.get("category") or "").title()
    matches = [format_tracked_item(t) for t in (ev.get("tracked") or [])]
    return {
        "title": f"{cat} Scan",
        "summary": f"{ev.get('items_scanned', 0)} items scanned · {ev.get('changes_detected', 0)} changes",
        "matches": matches,
    }


def assert_eq(label, got, expected):
    if got != expected:
        raise AssertionError(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  OK  {label}")


def main():
    print("=== Discord embed: repeat scan, still out of stock (orange) ===")
    tracked_oos = [{"name": "Quantum Core Generator", "kind": "missing", "stock": None}]
    embed = build_scan_embed("factory", 30, 0, tracked_oos)
    print(json.dumps(embed, indent=2))
    assert_eq("color orange", embed["color"], 0xE67E22)
    assert_eq("field value", embed["fields"][0]["value"], "❌ Out of Stock")
    assert_eq("title", embed["title"], "🔍 Factory Scan")

    print("\n=== Discord embed: in stock (green) ===")
    tracked_in = [
        {"name": "Artillery Depot", "kind": "found", "stock": 1},
        {"name": "Rocket Bunker", "kind": "missing", "stock": None},
    ]
    embed2 = build_scan_embed("military", 33, 2, tracked_in)
    print(json.dumps(embed2, indent=2))
    assert_eq("color green", embed2["color"], 0x2ECC71)
    assert_eq("found field", embed2["fields"][0]["value"], "✅ In Stock (x1)")
    assert_eq("newly_available name prefix",
               build_scan_embed("m", 1, 1, [{"name": "X", "kind": "newly_available", "stock": 3}])["fields"][0]["name"],
               "🆕 X")

    print("\n=== Discord embed: empty wishlist (grey) ===")
    embed3 = build_scan_embed("special", 0, 0, [])
    assert_eq("color grey", embed3["color"], 0x95A5A6)
    assert_eq("no fields", embed3["fields"], [])

    print("\n=== Activity feed: repeat scan shows full tracked (changes=0) ===")
    ev_repeat = {
        "category": "factory",
        "items_scanned": 30,
        "changes_detected": 0,
        "tracked": tracked_oos,
    }
    block = build_scan_block(ev_repeat)
    print(json.dumps(block, indent=2))
    assert_eq("match count", len(block["matches"]), 1)
    assert_eq("match msg", block["matches"][0]["msg"], "Quantum Core Generator — Out of Stock")
    assert_eq("match class", block["matches"][0]["cls"], "missing")

    print("\n=== Activity feed: newly_available stays distinct ===")
    ev_new = {
        "category": "military",
        "items_scanned": 35,
        "changes_detected": 1,
        "tracked": [{"name": "Air Fortress", "kind": "newly_available", "stock": 2}],
    }
    block2 = build_scan_block(ev_new)
    assert_eq("new class", block2["matches"][0]["cls"], "new")
    assert_eq("new msg", block2["matches"][0]["msg"], "Air Fortress — Just Restocked (x2)")

    print("\n=== Live events.jsonl spot-check (if present) ===")
    events_path = os.path.join(HERE, "logs", "events.jsonl")
    if os.path.isfile(events_path):
        scan_results = []
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("type") == "scan_result":
                    scan_results.append(row)
        if scan_results:
            last = scan_results[-1]
            b = build_scan_block(last)
            print(f"  Last scan_result seq={last.get('seq')}: {len(b['matches'])} tracked line(s)")
            for m in b["matches"]:
                print(f"    {m['icon']} [{m['cls']}] {m['msg']}")
        else:
            print("  (no scan_result rows in events.jsonl)")
    else:
        print("  (no events.jsonl)")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
