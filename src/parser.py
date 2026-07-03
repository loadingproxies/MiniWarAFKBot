"""Turn raw OCR lines (from Vision.ocr_lines) into structured shop items.

Cards are anchored on the item name (tallest token); every other token attaches
to the nearest name above it. Status labels ("Out of Stock!", "Stock xN",
"Locked") are not names — they become the item's stock status. Names are
normalized so OCR variants of the same item merge.
"""
from __future__ import annotations

import re

from src.game_locale import RARITIES, GameUi, fold_accents, get_ui

# Common OCR digit confusions.
_DIGIT_HOMO = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "i": "1"})

_DIGITS_ONLY = re.compile(r"^[\d\s.,xX×]+$")


def _norm_letters(s: str) -> str:
    """Lowercase, keep only ascii letters (for status/rarity keyword tests)."""
    return re.sub(r"[^a-z]", "", fold_accents(s).lower())


def normalize_name(name: str) -> str:
    """Dedup key: lowercase, keep letters and digits only (names like 'Area 51')."""
    return re.sub(r"[^a-z0-9]", "", fold_accents(name).lower())


def clean_display(name: str) -> str:
    """Tidy a name for display: collapse spaces, trim stray punctuation."""
    return re.sub(r"\s+", " ", name).strip(" .,-_!")


def _alias_candidates(whitelist, ui: GameUi | None):
    for e in whitelist:
        yield e
        if ui:
            for alias in ui.item_aliases.get(e, ()):
                yield alias


def match_whitelist(name, whitelist, ui: GameUi | None = None):
    """Return the canonical whitelist entry this name matches, else None."""
    if ui is None:
        ui = get_ui()
    key = normalize_name(name)
    if not key:
        return None
    name_words = set(re.findall(r"[a-z0-9]+", fold_accents(name).lower()))
    for e in whitelist:
        for cand in _alias_candidates([e], ui):
            ne = normalize_name(cand)
            if not ne:
                continue
            if key == ne:
                return e
            if len(ne) >= 5 and key.startswith(ne):
                return e
            if ne in key and len(key) <= len(ne) * 1.35:
                return e
            if key in ne and len(ne) <= len(key) * 1.35:
                return e
            ew = re.findall(r"[a-z0-9]+", fold_accents(cand).lower())
            if len(ew) >= 2 and all(w in name_words for w in ew):
                return e
            try:
                from rapidfuzz import fuzz
                if fuzz.ratio(key, ne) >= 86:
                    return e
            except Exception:
                pass
    return None


def parse_stock(text: str, ui: GameUi | None = None):
    """'Stock x3' / localized equivalent -> 3."""
    if ui is None:
        ui = get_ui()
    for kw in ui.stock_keywords:
        m = re.search(
            rf"(?i){re.escape(kw)}\s*[xX×]?\s*([0-9OolIi]+)", text, re.I
        )
        if m:
            digits = re.sub(r"\D", "", m.group(1).translate(_DIGIT_HOMO))
            if digits:
                return int(digits)
    m = re.search(r"(?i)stock\s*[xX]?\s*([0-9OolIi]+)", text)
    if m:
        digits = re.sub(r"\D", "", m.group(1).translate(_DIGIT_HOMO))
        if digits:
            return int(digits)
    m = re.search(r"(?i)[xX×]\s*([0-9OolIi]{1,4})\b", text)
    if m:
        digits = re.sub(r"\D", "", m.group(1).translate(_DIGIT_HOMO))
        if digits:
            return int(digits)
    return None


def parse_status(text: str, stock, ui: GameUi | None = None):
    """-> 'in' | 'out' | 'locked' | None for a card's joined text."""
    if ui is None:
        ui = get_ui()
    n = _norm_letters(text)
    for frag in ui.stock_out:
        if frag in n:
            return "out"
    if re.search(r"outofst", n):
        return "out"
    if re.search(r"out\s*of\s*st[o0][ck]", fold_accents(text), re.I):
        return "out"
    for frag in ui.locked:
        if frag in n:
            return "locked"
    if stock is not None:
        return "in"
    return None


def match_rarity(text: str, ui: GameUi | None = None):
    if ui is None:
        ui = get_ui()
    n = _norm_letters(text)
    if "secret" in n or "ecret" in n:
        return "Secret"
    for frag, canon in sorted(ui.rarity_map.items(), key=lambda x: -len(x[0])):
        if frag in n:
            return canon
    t = fold_accents(text).lower()
    for r in sorted(RARITIES, key=len, reverse=True):
        if r.lower() in t:
            return r
    try:
        from rapidfuzz import process, fuzz
        res = process.extractOne(
            _norm_letters(text),
            list(ui.rarity_map.keys()),
            scorer=fuzz.ratio,
        )
        if res and res[1] >= 88:
            return ui.rarity_map.get(res[0])
    except Exception:
        pass
    return None


def _looks_like_name(text: str, ui: GameUi | None = None) -> bool:
    if ui is None:
        ui = get_ui()
    t = text.strip()
    if not t or _DIGITS_ONLY.match(t):
        return False
    if _norm_letters(t) in ui.stoplist:
        return False
    n = _norm_letters(t)
    if any(bad in n for bad in ui.bad_name_substr):
        return False
    if match_rarity(t, ui) is not None and len(t.split()) <= 1:
        return False
    if len(t.split()) >= 2 and t == t.lower() and not any(c.isdigit() for c in t):
        return False
    return len(n) >= 3


def _make_item(name: str, joined: str, y=None, ui: GameUi | None = None) -> dict:
    stock = parse_stock(joined, ui)
    return {
        "name": name,
        "rarity": match_rarity(joined, ui),
        "stock": stock,
        "status": parse_status(joined, stock, ui),
        "raw": joined,
        "y": y,
    }


def _gap_cluster(lines, crop_h, ui: GameUi | None = None):
    lines = sorted(lines, key=lambda l: l["y"])
    heights = sorted(l["h"] for l in lines)
    med_h = heights[len(heights) // 2] or 10.0
    gap_thr = max(med_h * 1.9, crop_h * 0.05)
    clusters = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        if cur["y"] - prev["y"] > gap_thr:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    items = []
    for cl in clusters:
        joined = " ".join(l["text"] for l in cl)
        names = [l for l in cl if _looks_like_name(l["text"], ui)]
        if not names:
            continue
        name = " ".join(n["text"].strip() for n in sorted(names, key=lambda l: l["x0"]))
        items.append(_make_item(name.strip(), joined, min(n["y"] for n in names), ui))
    return items


def group_items(lines, crop_h: float, ui: GameUi | None = None):
    if ui is None:
        ui = get_ui()
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return []

    namelike = [l for l in lines if _looks_like_name(l["text"], ui)]
    if not namelike:
        return _gap_cluster(lines, crop_h, ui)

    max_h = max(l["h"] for l in namelike)
    anchors = sorted([l for l in namelike if l["h"] >= 0.62 * max_h], key=lambda l: l["y"])
    if not anchors:
        return _gap_cluster(lines, crop_h, ui)

    pad = 0.4 * max_h
    items = []
    for i, a in enumerate(anchors):
        y_lo = a["y"] - pad
        y_hi = (anchors[i + 1]["y"] - pad) if i + 1 < len(anchors) else float("inf")
        members = [l for l in lines if y_lo <= l["y"] < y_hi]
        joined = " ".join(l["text"] for l in members)

        name_tokens = [
            l for l in members
            if _looks_like_name(l["text"], ui) and l["h"] >= 0.62 * max_h
            and abs(l["y"] - a["y"]) <= 0.7 * max_h
        ]
        if a not in name_tokens:
            name_tokens.append(a)
        name = " ".join(
            t["text"].strip()
            for t in sorted(name_tokens, key=lambda l: (round(l["y"] / 8), l["x0"]))
        ).strip()
        if not name:
            continue
        items.append(_make_item(name, joined, a["y"], ui))
    return items


def _merge_item_fields(cur: dict, it: dict) -> None:
    if cur.get("rarity") is None and it.get("rarity"):
        cur["rarity"] = it["rarity"]
    if it.get("status") == "out":
        cur["status"] = "out"
    elif cur.get("status") is None and it.get("status"):
        cur["status"] = it["status"]
    if cur.get("stock") is None and it.get("stock") is not None:
        cur["stock"] = it["stock"]
    elif it.get("stock") is not None and (cur.get("stock") is None or it["stock"] > cur["stock"]):
        cur["stock"] = it["stock"]
    if it["name"].count(" ") > cur["name"].count(" "):
        cur["name"] = it["name"]


def dedupe(items, whitelist: list | None = None, ui: GameUi | None = None):
    if ui is None:
        ui = get_ui()
    seen = {}
    for it in items:
        key = normalize_name(it["name"])
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(it)
            continue
        _merge_item_fields(seen[key], it)
    merged = list(seen.values())
    if whitelist:
        by_canon: dict[str, dict] = {}
        for it in merged:
            canon = match_whitelist(it["name"], whitelist, ui) or it["name"]
            ck = normalize_name(canon)
            if ck not in by_canon:
                row = dict(it)
                if match_whitelist(it["name"], whitelist, ui):
                    row["name"] = canon
                by_canon[ck] = row
            else:
                _merge_item_fields(by_canon[ck], it)
                if match_whitelist(it["name"], whitelist, ui):
                    by_canon[ck]["name"] = canon
        merged = list(by_canon.values())
    for it in merged:
        if it.get("stock") is not None and it.get("status") is None:
            it["status"] = "in"
    return merged
