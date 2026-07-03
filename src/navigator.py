"""Shop-reading flow: open the shop, reach the vendor, press E, read all four tabs.

run_check() returns {"factory": [item, ...], "houses": [...], "military": [...], "special": [...]}
and raises NavigationError if it cannot reach the shop.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np

from src.parser import group_items, dedupe, normalize_name, match_whitelist, parse_stock, parse_status
from src.game_locale import get_ui, is_vendor_talk, shop_text_hits
from src import botstatus, botevents, inventory, botlogs
from src.shop_tabs import catalog_names_for_shop_tab, report_items_for_shop_tab, wishlist_for_shop_tab

CATEGORIES = ["factory", "houses", "military", "special"]
CAT_TAB_BUTTON = {
    "factory": "tab_factory",
    "houses": "tab_houses",
    "military": "tab_military",
    "special": "tab_special",
}


class NavigationError(RuntimeError):
    pass


class SkipCheck(Exception):
    """Non-error skip (e.g. vendor soft-focus — Roblox not in foreground)."""
    pass


class Navigator:
    def __init__(self, cfg, window, capture, vision, inp, root, log=print, budget=None):
        self.cfg = cfg
        self.window = window
        self.capture = capture
        self.vision = vision
        self.inp = inp
        self.root = root
        self.log = log
        self._dbg = 0
        self.budget = budget  # optional src.budget.Budget; None = unlimited

    # ---- helpers ---------------------------------------------------------
    def _btn_xy(self, name):
        frac = self.cfg["buttons"].get(name)
        if not frac:
            raise NavigationError(f"Button '{name}' is not calibrated (run calibrate.py)")
        return self.window.to_screen(frac[0], frac[1])

    def _region(self, name):
        frac = self.cfg["regions"].get(name)
        if not frac:
            return self.window.client_rect()
        return self.window.region_px(frac)

    def _click_btn(self, name):
        x, y = self._btn_xy(name)
        if not self.window.is_foreground():   # focus can be lost mid-run
            self.window.focus()
            time.sleep(0.3)
        self.inp.click(x, y)

    def _grab(self, region_name):
        return self.capture.grab(self._region(region_name))

    def _save_debug(self, img, tag):
        if not self.cfg.get("debug", {}).get("save_screenshots"):
            return
        d = os.path.join(self.root, self.cfg["debug"].get("dir", "debug"))
        os.makedirs(d, exist_ok=True)
        self._dbg += 1
        cv2.imwrite(os.path.join(d, f"{self._dbg:03d}_{tag}.png"), img)

    # ---- main flow -------------------------------------------------------
    def _ensure_foreground(self, timeout=3.0):
        """Bring Roblox to the foreground and confirm it got there; an inactive
        window consumes the first click just to activate itself."""
        end_at = time.monotonic() + timeout
        self.window.focus()
        while time.monotonic() < end_at:
            if self.window.is_foreground():
                return True
            self.window.focus()
            time.sleep(0.3)
        return self.window.is_foreground()

    def _focus_game_for_input(self):
        """Click the Roblox client so keyboard input (E) reaches the game."""
        try:
            box = self.window.client_rect()
            cx = box[0] + box[2] // 2
            cy = box[1] + box[3] // 2
            self.window.focus()
            time.sleep(0.25)
            self.inp.click(cx, cy, delay=0.08)
            time.sleep(0.2)
        except Exception:
            pass

    def _wait_shop_ready(self, timeout_sec: float = 3.5) -> bool:
        """Poll until the shop panel and item list look loaded."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self._shop_ready():
                return True
            if self.shop_open():
                time.sleep(0.35)
                if self._shop_ready():
                    return True
            time.sleep(0.25)
        return self._shop_ready()

    def _open_shop_at_vendor(self, *, focus_click: bool = True) -> bool:
        """Press E at the vendor NPC with retries until the shop UI opens."""
        t = self.cfg["timings"]
        nav = self.cfg.get("navigation", {})
        hold = t.get("e_press_hold_sec", 0.9)
        post = max(0.6, t.get("after_tab_sec", 1.0))
        retries = max(1, int(nav.get("e_retries", 3)))

        if self._shop_ready():
            self.log("-> shop UI already open")
            return True

        if focus_click:
            self._focus_game_for_input()

        for i in range(retries):
            self.log(f"-> pressing E (attempt {i + 1}/{retries})")
            self.inp.hold_key("e", hold)
            if self._wait_shop_ready(post + 2.5):
                return True
            time.sleep(0.4)
        return self._shop_ready()

    def run_check(self, *, from_banner: bool = False):
        t = self.cfg["timings"]
        nav = self.cfg.get("navigation", {})
        vendor = bool(nav.get("vendor_mode"))
        soft = bool(nav.get("vendor_soft_focus", True))

        # Confirmed restock banner on screen — always run (focus Roblox if needed).
        if vendor and soft and not from_banner:
            self.window.ensure()
            if not self.window.is_foreground():
                self.log("-> Roblox not focused — skipping check (soft focus)")
                raise SkipCheck("Click Roblox to check shop")
        elif not self._ensure_foreground():
            raise NavigationError(
                "Could not bring the Roblox window to the foreground. Click the game window and retry "
                "(or run the bot as administrator if Roblox runs as admin).")

        if vendor:
            botevents.emit("vendor_check")

        time.sleep(0.6 if vendor else 1.0)

        hold = t.get("e_press_hold_sec", 0.9)
        post = max(0.6, t.get("after_tab_sec", 1.0))
        if vendor:
            opened = self._open_shop_at_vendor(focus_click=from_banner or not soft)
        else:
            opened = self._shop_ready()
            if opened:
                self.log("-> shop UI already open")
            else:
                self.log("-> pressing E (at vendor)")
                self.inp.hold_key("e", hold)
                time.sleep(post)
                opened = self._shop_ready()

            if not opened:
                self.log("-> opening the shop (Buy)")
                self._click_btn("buy")
                time.sleep(float(nav.get("e_delay_after_buy_sec", 1.5)))
                for i in range(int(nav.get("e_retries", 3))):
                    self.log(f"-> pressing E (attempt {i + 1})")
                    self.inp.hold_key("e", hold)
                    time.sleep(post)
                    if self._shop_ready():
                        opened = True
                        break
        if not opened:
            if vendor:
                raise NavigationError(
                    "Shop did not open with E. Stand next to the shop vendor, click the Roblox "
                    "window once, and make sure Roblox is in Windowed mode.")
            raise NavigationError(
                'The shop did not open after E. Stand next to the shop vendor (or at your base so '
                'Buy can teleport you there), then retry.')

        cats = self.cfg.get("navigation", {}).get("categories") or CATEGORIES
        # Optional cross-category priority (e.g. spend the shared budget on Military
        # before Factory). Falls back to the configured/default category order.
        cat_priority = self.cfg.get("buy", {}).get("category_priority")
        if cat_priority:
            rank = {c: i for i, c in enumerate(cat_priority)}
            cats = sorted(cats, key=lambda c: rank.get(c, len(rank)))
        self.log(f"-> scan order: {', '.join(cats)}")
        results = {}
        purchases = []
        prev_flat = inventory.load_previous()
        for cat in cats:
            self.log(f"-> reading category: {cat}")
            botstatus.write("reading", f"Reading {cat.capitalize()}…", phase="scanning",
                            category=cat, event_seq=botevents.last_seq())
            time.sleep(0.4)                 # let any buffered scroll flush first
            self._click_btn(CAT_TAB_BUTTON[cat])
            time.sleep(t["after_tab_sec"])  # tab click resets the list to the top
            items, buys = self.read_and_buy(cat)
            results[cat] = items
            purchases.extend(buys)
            inventory.emit_category_scan_result(self.cfg, cat, items, prev_flat)
            self.log(f"   {cat}: {len(items)} items"
                     + (f", bought {len(buys)}" if buys else ""))
            # Debug: log OCR parse summary per category
            if items:
                sample = ", ".join(
                    f"{it['name']}(stock={it.get('stock')},st={it.get('status')})"
                    for it in items[:5]
                )
                self.log(f"   [pipeline] {cat} parsed: {sample}"
                         + ("…" if len(items) > 5 else ""))

        self.log("-> closing the shop")
        self._close_shop()
        return results, purchases

    # ---- shop open / close -----------------------------------------------
    def shop_open(self):
        """True when the shop panel/tab bar is visible (not the vendor overworld)."""
        ui = get_ui(self.cfg)
        img = self._grab("shop_window")
        text = self.vision.ocr_text(img, upscale=2.0)
        tab_hits, has_marker = shop_text_hits(text, ui)
        if tab_hits >= 2:
            return True
        return tab_hits >= 1 and has_marker

    def _shop_list_ready(self):
        """True when the item list shows shop cards, not the vendor / player names."""
        ui = get_ui(self.cfg)
        img = self._grab("item_list")
        text = self.vision.ocr_text(img, upscale=1.5)
        if is_vendor_talk(text, ui):
            _, has_marker = shop_text_hits(text, ui)
            if not has_marker:
                return False
        _, has_marker = shop_text_hits(text, ui)
        norm = text.lower()
        if "locked" in norm or any(k in norm for k in ui.locked):
            return True
        return has_marker

    def _shop_ready(self):
        """Shop panel open AND the item list looks like a real catalog."""
        return self.shop_open() and self._shop_list_ready()

    def _close_shop(self):
        closed = False
        for attempt in range(3):
            self._click_btn("close_x")
            time.sleep(0.7)
            if not self.shop_open():
                closed = True
                break
            if attempt < 2:
                self.log("   the shop did not close, trying again")
        if not closed:
            self.log("   !! could not close via the X button — check the close_x coordinate")
        nav = self.cfg.get("navigation", {})
        if nav.get("vendor_mode"):
            self.log("   vendor mode — staying at shop (no Country button)")
            return
        # optional post-check action to return to the map where the banner shows
        action = nav.get("post_check_action")
        if action:
            self._do_action(action)
            time.sleep(nav.get("return_settle_sec", 1.5))

    def _do_action(self, action):
        kind = action.get("type")
        val = action.get("value")
        if kind == "key":
            self.inp.tap(val)
        elif kind == "button":
            try:
                self._click_btn(val)
            except NavigationError:
                pass

    # ---- shop scrolling via the mouse wheel --------------------------------
    def _shop_focus(self):
        """Click a safe spot inside the item list (icon column, away from any buy button)
        so the shop's ScrollingFrame becomes the wheel target — without this first click
        the wheel scrolls the game camera, not the list."""
        box = self._region("item_list")
        fx = box[0] + int(box[2] * float(self.cfg.get("navigation", {}).get("focus_click_fx", 0.12)))
        fy = box[1] + int(box[3] * float(self.cfg.get("navigation", {}).get("focus_click_fy", 0.32)))
        self.inp.click(fx, fy)
        time.sleep(0.15)

    def _wheel_step(self, notches):
        """Hover the list centre and spin the wheel `notches` (negative = down) as
        individual 1-notch ticks so Roblox smooth-scrolls between them."""
        nav = self.cfg.get("navigation", {})
        notch_delay = float(nav.get("wheel_notch_delay_sec", 0.008))
        box = self._region("item_list")
        self.inp.move(box[0] + box[2] // 2, box[1] + box[3] // 2)
        time.sleep(0.02)
        n = int(notches)
        step = 1 if n >= 0 else -1
        for _ in range(abs(n) or 1):
            self.inp.scroll(step, delay=notch_delay)

    # ---- read + buy in one scroll pass -----------------------------------
    def read_and_buy(self, cat):
        """Single top-to-bottom scroll per category: read every card for the report and
        buy any selected item as soon as its green button is in view.
        Returns (deduped_items, purchases)."""
        nav = self.cfg.get("navigation", {})
        box = self._region("item_list")
        read_pause = float(nav.get("scroll_read_pause", 0.14))
        notches = int(nav.get("wheel_notches_read", 2))
        ocr_up = nav.get("scroll_ocr_upscale")
        ocr_upscale = float(ocr_up) if ocr_up is not None else None
        still_diff = float(nav.get("wheel_still_diff", 9.0))
        after_found = int(nav.get("scroll_after_found", 2))

        # early-stop: wishlist-only scroll stops once buy-list names are seen
        wishlist_only = bool(nav.get("wishlist_scroll_only", True))
        buy_cfg = self.cfg.get("buy", {})
        wish_names = wishlist_for_shop_tab(self.cfg, cat)
        buy_list = wish_names if buy_cfg.get("enabled") else None
        max_steps = int(nav.get("wheel_max_steps_merged", nav.get("wheel_max_steps", 120)))
        if wishlist_only and wish_names:
            max_steps = min(max_steps, int(nav.get("wheel_max_steps_wishlist", 35)))
        if wishlist_only and wish_names:
            targets = list(wish_names)
            target_keys = {normalize_name(x) for x in targets}
            self.log("   wishlist-only scroll: " + ", ".join(targets))
        else:
            targets = report_items_for_shop_tab(self.cfg, cat)
            target_keys = {normalize_name(x) for x in targets} if targets else None

        # buying is gated on the green button, not the OCR'd stock line; _do_buy
        # stops once the button disappears
        if buy_list:
            max_qty = int(buy_cfg.get("max_per_item", 0))
            per_item = max_qty if max_qty > 0 else int(buy_cfg.get("buy_until_soldout_max", 20))
            to_buy = {entry: per_item for entry in buy_list}
            names = list(to_buy.keys())
            # Priority: buy.items[] is already an ordered wishlist (first = most
            # wanted); an explicit buy.priority[cat] list, if present, overrides
            # that order. Used to break ties when two selected items are visible
            # in the same frame, and to decide who gets the last of the budget.
            explicit_priority = (buy_cfg.get("priority") or {}).get(cat)
            priority_order = explicit_priority if explicit_priority else names
            priority_rank = {entry: i for i, entry in enumerate(priority_order)}
            self.log("   to buy (priority order): "
                     + ", ".join(sorted(names, key=lambda n: priority_rank.get(n, 999))))
        else:
            to_buy, names, priority_rank = {}, [], {}
        hsv_low = buy_cfg.get("button_hsv_low", [40, 120, 180])
        hsv_high = buy_cfg.get("button_hsv_high", [75, 255, 255])
        right_frac = float(buy_cfg.get("right_fraction", 0.58))
        dry = bool(buy_cfg.get("dry_run", True))
        click_delay = float(buy_cfg.get("click_delay_sec", 0.5))
        verify = bool(buy_cfg.get("verify_purchases", False))
        verify_wait = float(buy_cfg.get("verify_wait_sec", 0.6))
        verify_poll = float(buy_cfg.get("verify_poll_sec", 0.4))
        verify_retries = max(1, int(buy_cfg.get("verify_retries", 5)))
        disabled_low = buy_cfg.get("button_disabled_hsv_low")
        disabled_high = buy_cfg.get("button_disabled_hsv_high")

        collected, purchases, done, seen_wishlist, ocr_times = [], [], set(), set(), []
        ui = get_ui(self.cfg)

        self._shop_focus()
        time.sleep(read_pause)
        # skip the low-rarity items at the top of each list (the catalog only offers
        # Epic+). `start_skip_notches` is a scalar or per-category dict (0 = off),
        # calibrated at `start_skip_ref_height`; Roblox scrolls fixed pixels per wheel
        # notch while the cards scale with the viewport, so scale the notch count by
        # the live client height.
        sk = nav.get("start_skip_notches", 0)
        skip = int(sk.get(cat, 0)) if isinstance(sk, dict) else int(sk)
        if skip > 0:
            ref_h = float(nav.get("start_skip_ref_height", 1009))
            try:
                ch = self.window.client_rect()[3]
                if ch > 0 and ref_h > 0:
                    skip = int(round(skip * ch / ref_h))
            except Exception:
                pass
        if skip > 0:
            self._wheel_step(-skip)
            time.sleep(read_pause)
        last_sig = None
        still = 0
        found_done = False
        extra = 0
        for idx in range(max_steps + 1):
            frame = self.capture.grab(box)
            self._save_debug(frame, f"{cat}_{idx}")
            t0 = time.perf_counter()
            lines = self.vision.ocr_lines(frame, upscale=ocr_upscale)
            ocr_times.append(time.perf_counter() - t0)
            items = group_items(lines, frame.shape[0], ui)
            collected.extend(items)
            if names:
                for it in items:
                    hit = match_whitelist(it["name"], names, ui)
                    if hit:
                        seen_wishlist.add(hit)

            # --- buy at most one item per frame; re-capture handles the list reflow ---
            bought = False
            if names and len(done) < len(names):
                # priority first, physical scroll position second (so within one
                # visible frame the higher-priority item wins the shared budget)
                for it in sorted(items, key=lambda i: (
                        priority_rank.get(match_whitelist(i["name"], names, ui), 999),
                        i.get("y") or 0.0)):
                    canon = match_whitelist(it["name"], names, ui)
                    if not canon or canon in done:
                        continue
                    y_name = it.get("y")
                    if y_name is None:
                        continue
                    if self.vision.find_buy_button(frame, y_name, hsv_low, hsv_high,
                                                   right_frac) is None:
                        continue          # button not in view yet — a later step reveals it
                    if not dry and self.budget is not None and not self.budget.can_buy():
                        done.add(canon)   # stop retrying this item; budget is spent
                        self.log(f"   !! budget cap reached — skipping {canon}")
                        try:
                            from src import notify
                            notify.budget_exhausted(self.cfg, canon)
                        except Exception:
                            pass
                        continue
                    qty = to_buy[canon]
                    clicked, confirmed, outcome, shot = self._do_buy(
                        box, y_name, qty, hsv_low, hsv_high, right_frac, click_delay, dry,
                        expected_stock=it.get("stock"), verify=verify,
                        verify_wait=verify_wait, verify_poll=verify_poll,
                        verify_retries=verify_retries,
                        disabled_hsv_low=disabled_low, disabled_hsv_high=disabled_high)
                    if not dry and self.budget is not None:
                        self.budget.spend(clicked)  # counts actual units clicked
                    done.add(canon)
                    if dry:
                        tag = "[test] would buy"
                    elif outcome == "insufficient_funds":
                        tag = "COULD NOT BUY (insufficient funds)"
                    elif verify and (confirmed or 0) < clicked:
                        tag = f"clicked but UNCONFIRMED ({confirmed}/{clicked} verified)"
                    else:
                        tag = "BOUGHT"
                    purchases.append({
                        "category": cat, "name": canon,
                        "qty": (qty if dry else clicked),
                        "confirmed": confirmed,          # None if verify=False (unchecked)
                        "outcome": outcome,               # "ok" | "sold_out" | "insufficient_funds"
                        "dry": dry, "image": shot, "tag": tag,
                    })
                    self.log(f"   {tag}: {canon} ×{qty if dry else clicked}")
                    botstatus.write("buying", f"{tag}: {canon} ×{qty if dry else clicked}",
                                    phase="matching", event_seq=botevents.last_seq())
                    botevents.emit("purchase_success", category=cat, name=canon,
                                   qty=qty if dry else clicked, dry=dry, tag=tag)
                    botlogs.log_purchase(
                        name=canon, category=cat, qty=qty if dry else clicked,
                        dry=dry, confirmed=confirmed, outcome=outcome, tag=tag,
                    )
                    bought = True
                    self._shop_focus()    # the buy click can defocus the list -> re-focus
                    break                 # one buy per frame; the frame is stale now — re-read
            if bought:
                last_sig = None           # the reflow changed the view -> reset bottom detect
                still = 0
                continue                  # re-read same spot (a neighbour may be buyable too)

            # Wishlist-only: mark confirmed-out items so we don't scroll forever
            if wishlist_only and names:
                for it in items:
                    canon = match_whitelist(it["name"], names, ui)
                    if not canon or canon in done:
                        continue
                    if it.get("status") == "out":
                        done.add(canon)
                    elif it.get("stock") is not None and it.get("stock") <= 0:
                        done.add(canon)

            # --- bottom / early-stop detection ---
            if not found_done and target_keys and self._found_all(
                    collected, targets, target_keys, ui=ui, names_only=wishlist_only):
                found_done = True
            all_bought = (not names) or (len(done) >= len(names))
            sig = self._frame_sig(frame)
            stop_after_found = found_done and (all_bought or wishlist_only)
            if stop_after_found:
                extra += 1
                if extra > after_found:
                    if wishlist_only and not all_bought:
                        self.log("   wishlist-only stop (items seen, none to buy)")
                    break
            elif last_sig is not None and float(np.abs(sig - last_sig).mean()) < still_diff:
                # a static frame can be the real bottom or a wheel step that didn't land
                # (focus lost); re-focus and require two static frames in a row
                still += 1
                self._shop_focus()
                if still >= 2:
                    break                 # genuinely static after a re-focus retry -> bottom
            else:
                still = 0
            last_sig = sig
            self._wheel_step(-notches)

        if ocr_times:
            self.log(f"   OCR: {len(ocr_times)} frames, "
                     f"~{1000 * sum(ocr_times) / len(ocr_times):.0f} ms/frame")
        missed = [n for n in names if n not in done]
        catalog = list(catalog_names_for_shop_tab(self.cfg, cat).keys())
        merge_names = list(dict.fromkeys(list(names) + catalog))
        merged = dedupe(collected, merge_names, ui)
        # Seen on screen but no green buy button → treat as out of stock (OCR often
        # splits the "Out of Stock!" label away from the item title).
        if missed and seen_wishlist:
            for it in merged:
                canon = match_whitelist(it["name"], names, ui)
                if not canon or canon not in missed or canon not in seen_wishlist:
                    continue
                stock = it.get("stock")
                if stock is not None and stock > 0:
                    continue
                if it.get("status") == "in":
                    continue
                it["status"] = "out"
        if missed:
            self.log("   !! did not buy: " + ", ".join(missed))
        return merged, purchases

    # ---- auto-buy --------------------------------------------------------
    @staticmethod
    def _png_bytes(frame):
        ok, buf = cv2.imencode(".png", frame)
        return buf.tobytes() if ok else None

    def _purchase_verified(self, frame, y_name, hsv_low, hsv_high, right_frac,
                           last_stock, disabled_low, disabled_high) -> bool:
        """True when OCR/button state shows the buy click worked."""
        ui = get_ui(self.cfg)
        text = self.vision.read_stock_at(frame, y_name)
        if text:
            new_stock = parse_stock(text, ui)
            new_status = parse_status(text, new_stock, ui)
            if last_stock is not None and new_stock is not None and new_stock < last_stock:
                return True
            if new_status == "out":
                return True
        btn = self.vision.find_buy_button(frame, y_name, hsv_low, hsv_high, right_frac)
        if btn is not None:
            return False
        if disabled_low and disabled_high:
            if self.vision.find_disabled_button(
                    frame, y_name, disabled_low, disabled_high, right_frac) is not None:
                return False
        return True

    def _do_buy(self, box, y_name, qty, hsv_low, hsv_high, right_frac, click_delay, dry,
                expected_stock=None, verify=False, verify_wait=0.6, verify_poll=0.4,
                verify_retries=5, disabled_hsv_low=None, disabled_hsv_high=None):
        """Click the buy button up to `qty` times.
        Returns (clicked, confirmed, outcome, shot):
          clicked   - how many times the button was pressed
          confirmed - how many of those clicks were OCR-verified (stock actually
                      dropped); None if verify=False (not checked, old behavior)
          outcome   - "ok" | "sold_out" | "insufficient_funds"
        """
        if dry:
            return qty, (qty if verify else None), "ok", self._png_bytes(self.capture.grab(box))
        ui = get_ui(self.cfg)
        clicked = 0
        confirmed = 0
        last_stock = expected_stock
        outcome = "ok"
        for _ in range(qty + 2):
            if clicked >= qty:
                break
            frame = self.capture.grab(box)
            btn = self.vision.find_buy_button(frame, y_name, hsv_low, hsv_high, right_frac)
            if btn is None:
                # The green button is gone. That's normally "sold out" - but if a
                # differently-colored (grey/red) button-shaped region is still
                # sitting right there, it's more likely "can't afford this."
                if disabled_hsv_low and disabled_hsv_high:
                    still_there = self.vision.find_disabled_button(
                        frame, y_name, disabled_hsv_low, disabled_hsv_high, right_frac)
                    if still_there is not None:
                        outcome = "insufficient_funds"
                    else:
                        outcome = "sold_out"
                else:
                    outcome = "sold_out"
                break
            self.inp.click(box[0] + btn[0], box[1] + btn[1])
            clicked += 1
            time.sleep(click_delay)
            if verify:
                time.sleep(verify_wait)
                for attempt in range(verify_retries):
                    if attempt > 0:
                        time.sleep(verify_poll)
                    frame2 = self.capture.grab(box)
                    if self._purchase_verified(
                            frame2, y_name, hsv_low, hsv_high, right_frac,
                            last_stock, disabled_hsv_low, disabled_hsv_high):
                        confirmed += 1
                        text = self.vision.read_stock_at(frame2, y_name)
                        new_stock = parse_stock(text, ui) if text else None
                        if new_stock is not None:
                            last_stock = new_stock
                        elif parse_status(text or "", None, ui) == "out":
                            last_stock = 0
                        break
        shot = self._png_bytes(self.capture.grab(box))
        return clicked, (confirmed if verify else None), outcome, shot

    @staticmethod
    def _frame_sig(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (48, 48)).astype(np.int32)

    @staticmethod
    def _sig_close(a, b):
        return float(np.abs(a - b).mean()) < 3.0

    @staticmethod
    def _found_all(collected, targets, target_keys, *, ui=None, names_only=False):
        got = set()
        for it in collected:
            if not names_only and it.get("status") is None and it.get("stock") is None:
                continue
            m = match_whitelist(it["name"], targets, ui)
            if m:
                got.add(normalize_name(m))
        return target_keys.issubset(got)
