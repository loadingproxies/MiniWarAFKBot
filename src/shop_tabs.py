"""Shop tab helpers for the launcher and navigator.

UI categories (Factory / Houses / Military) match in-game shop tabs one-to-one.
Divine items (Quantum Core, Supernova) are listed under Factory in the UI and
scanned on the Factory tab in-game — no hidden Special-tab pass.
"""
from __future__ import annotations

UI_CATEGORIES = ("factory", "houses", "military")


def bot_scan_categories(ui_enabled: list[str], buy_items: dict) -> list[str]:
    """Navigation order: UI-enabled categories only (never auto-add special)."""
    allowed = set(UI_CATEGORIES)
    return [c for c in ui_enabled if c in allowed]


def wishlist_for_shop_tab(cfg: dict, shop_cat: str) -> list[str]:
    """Buy-list entries handled on this in-game shop tab."""
    buy_items = (cfg.get("buy") or {}).get("items") or {}
    return list(buy_items.get(shop_cat) or [])


def catalog_names_for_shop_tab(cfg: dict, shop_cat: str) -> dict[str, str]:
    """Catalog entries to report when scanning a shop tab."""
    return dict((cfg.get("catalog") or {}).get(shop_cat) or {})


def report_items_for_shop_tab(cfg: dict, shop_cat: str) -> list[str] | None:
    rep = ((cfg.get("report") or {}).get("items") or {}).get(shop_cat)
    return rep or None
