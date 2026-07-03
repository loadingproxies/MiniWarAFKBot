"""Discord webhook notifications — restock alerts, purchase summaries, errors.

Best-effort and non-blocking: every call fires a short-lived thread so a slow
or unreachable webhook can never stall the bot's watch/buy loop. All errors
are swallowed (matches the rest of the codebase's "never crash the bot"
style, e.g. src/botstatus.py).

Enable it in config.json:

  "discord": {
    "enabled": true,
    "webhook_url": "https://discord.com/api/webhooks/...",
    "notify_restock": true,
    "notify_buy": true,
    "notify_error": true,
    "notify_scan": true,
    "mention": ""            // optional, e.g. "<@123456789012345678>"
  }
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

try:
    import requests
except ImportError:  # pragma: no cover - requests is in requirements.txt
    requests = None

_TIMEOUT = 8
_FOOTER = {"text": "MiniWar AFK Bot"}


def _cfg(cfg):
    return cfg.get("discord", {}) if cfg else {}


def _discord_log(msg: str) -> None:
    try:
        import os
        import time
        from src import appconfig
        path = os.path.join(appconfig.ROOT, "logs", "discord_notify.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _fire(webhook_url, payload, files=None):
    def _send():
        try:
            if files:
                r = requests.post(webhook_url, data=payload, files=files, timeout=_TIMEOUT)
            else:
                r = requests.post(webhook_url, json=payload, timeout=_TIMEOUT)
            if r.status_code >= 400:
                _discord_log(f"HTTP {r.status_code}: {(r.text or '')[:200]}")
            else:
                kind = "embed" if payload.get("embeds") else "message"
                _discord_log(f"sent {kind} OK")
        except Exception as e:
            _discord_log(f"send failed: {e!r}")

    threading.Thread(target=_send, daemon=True).start()


def _send(cfg, content, image_bytes=None, image_name="shot.png"):
    d = _cfg(cfg)
    if requests is None:
        _discord_log("message: skipped (requests not installed)")
        return
    if not d.get("enabled"):
        _discord_log("message: skipped (discord disabled)")
        return
    url = d.get("webhook_url")
    if not url:
        _discord_log("message: skipped (no webhook URL)")
        return
    mention = d.get("mention", "")
    text = f"{mention} {content}".strip() if mention else content
    if image_bytes:
        _fire(url, {"content": text}, files={"file": (image_name, image_bytes, "image/png")})
    else:
        _fire(url, {"content": text})


def _send_embed(cfg, embed: dict):
    d = _cfg(cfg)
    if requests is None:
        _discord_log("embed: skipped (requests not installed)")
        return
    if not d.get("enabled"):
        _discord_log("embed: skipped (discord disabled)")
        return
    url = d.get("webhook_url")
    if not url:
        _discord_log("embed: skipped (no webhook URL)")
        return
    payload: dict = {"embeds": [embed]}
    mention = d.get("mention", "")
    if mention:
        payload["content"] = mention
    _fire(url, payload)


def _wishlist_in_stock_only(cfg) -> bool:
    return bool(_cfg(cfg).get("notify_wishlist_in_stock_only", False))


def _tracked_in_stock(tracked: list) -> list:
    return [t for t in (tracked or []) if t.get("kind") in ("found", "newly_available")]


def build_scan_embed(category: str, items_scanned: int, changes_detected: int,
                     tracked: list) -> dict:
    """Build Discord embed dict for a category scan (testable without sending)."""
    tracked = tracked or []
    if not tracked:
        color = 0x95A5A6
    elif any(t.get("kind") != "missing" for t in tracked):
        color = 0x2ECC71
    else:
        color = 0xE67E22

    fields = []
    for t in tracked:
        kind = t.get("kind", "missing")
        name = t.get("name", "?")
        stock = t.get("stock")
        if kind == "found":
            val = f"✅ In Stock (x{stock})" if stock else "✅ In Stock"
            fields.append({"name": name, "value": val, "inline": True})
        elif kind == "newly_available":
            val = (f"✅ Just Restocked (x{stock})" if stock else "✅ Just Restocked")
            fields.append({"name": f"🆕 {name}", "value": val, "inline": True})
        elif kind == "unknown":
            fields.append({"name": name, "value": "❓ Stock unclear", "inline": True})
        elif kind == "unseen":
            fields.append({"name": name, "value": "— Not seen in scan", "inline": True})
        else:
            fields.append({"name": name, "value": "❌ Out of Stock", "inline": True})

    desc = f"{items_scanned} items scanned"
    if changes_detected:
        desc += f" · {changes_detected} changes"

    return {
        "title": f"🔍 {category.title()} Scan",
        "description": desc,
        "color": color,
        "fields": fields,
        "footer": _FOOTER,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scan_result(cfg, category: str, items_scanned: int, changes_detected: int, tracked: list):
    """Post wishlist stock snapshot for one category scan."""
    if not _cfg(cfg).get("notify_scan", True):
        _discord_log(f"scan {category}: skipped (notify_scan off)")
        return
    tracked = tracked or []
    if _wishlist_in_stock_only(cfg):
        in_stock = _tracked_in_stock(tracked)
        if not in_stock:
            _discord_log(f"scan {category}: skipped (wishlist in-stock only, all OOS)")
            return
        tracked = in_stock
    embed = build_scan_embed(category, items_scanned, changes_detected, tracked)
    if _wishlist_in_stock_only(cfg):
        embed["title"] = f"🎯 {category.title()} — Wishlist in stock!"
        embed["color"] = 0x2ECC71
    _send_embed(cfg, embed)


def restock_detected(cfg):
    if _wishlist_in_stock_only(cfg):
        _discord_log("restock: skipped (wishlist in-stock only)")
        return
    if _cfg(cfg).get("notify_restock", True):
        _send(cfg, "🔔 **Shop restocked!** Opening the shop and checking your items…")


def purchases_summary(cfg, purchases):
    """purchases: list of {"category", "name", "qty", "dry", "image",
    "confirmed", "outcome"} from Navigator."""
    if not _cfg(cfg).get("notify_buy", True) or not purchases:
        return
    lines = []
    last_image = None
    for p in purchases:
        outcome = p.get("outcome", "ok")
        confirmed = p.get("confirmed")
        qty = p.get("qty", 0)
        if p.get("dry"):
            tag = "[TEST] would buy"
        elif outcome == "insufficient_funds":
            tag = "⚠️ could NOT buy (insufficient funds)"
        elif confirmed is not None and confirmed >= qty and qty > 0:
            tag = "✅ bought (confirmed)"
        elif confirmed is not None and 0 < confirmed < qty:
            tag = f"⚠️ partly confirmed ({confirmed}/{qty})"
        elif confirmed is not None and confirmed < qty:
            tag = f"⚠️ clicked but unconfirmed ({confirmed}/{qty})"
        else:
            tag = "bought"
        lines.append(f"• {tag} **{p['name']}** ×{qty} ({p['category']})")
        # Attach screenshot for confirmed buys (shows Out of Stock after a x1 purchase).
        if p.get("image") and (confirmed is None or confirmed >= qty or p.get("dry")):
            last_image = p["image"]
    header = "🛒 **Purchase report**"
    note = ""
    if last_image and any(
            not p.get("dry")
            and p.get("qty", 0) > 0
            and (p.get("confirmed") if p.get("confirmed") is not None else p.get("qty", 0))
            >= p.get("qty", 0)
            for p in purchases
    ):
        note = "\n_Screenshot: item after purchase (Out of Stock = success for single stock)._"
    _send(cfg, header + "\n" + "\n".join(lines) + note, image_bytes=last_image)


def budget_exhausted(cfg, item_name):
    if _cfg(cfg).get("notify_buy", True):
        _send(cfg, f"⚠️ Budget cap reached — skipped buying **{item_name}**.")


def error(cfg, message):
    if _cfg(cfg).get("notify_error", True):
        _send(cfg, f"❌ **Bot error:** {message}")
