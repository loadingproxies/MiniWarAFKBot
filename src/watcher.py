"""Main loop: watch for the green "Shop has been restocked!" banner, then run a check.

When the banner is detected the bot opens the shop, OCR-reads each category, and buys any
item you selected in config.json (buy.items). A single non-blocking lock guards the shop
read/buy flow so nothing fights over the mouse or the (single) OCR engine.
"""
from __future__ import annotations

import os
import time
import threading
from datetime import datetime

import cv2

from src import appconfig, botstatus, notify, botevents, inventory, botlogs
from src.window import RobloxWindow, RobloxWindowError
from src.capture import ScreenCapture
from src.vision import Vision
from src.input_control import InputController
from src.navigator import Navigator, NavigationError, SkipCheck
from src.budget import Budget


def _prune_dir(path, keep):
    """Keep only the newest `keep` files in `path` by mtime (0 = delete all). Best-effort."""
    try:
        files = [os.path.join(path, f) for f in os.listdir(path)]
        files = [f for f in files if os.path.isfile(f)]
    except OSError:
        return
    if len(files) <= keep:
        return
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    for f in files[keep:]:
        try:
            os.remove(f)
        except OSError:
            pass


class Watcher:
    def __init__(self):
        self.root = appconfig.ROOT
        self.cfg = appconfig.load()

        w = self.cfg["window"]
        self.window = RobloxWindow(w.get("title_contains", "Roblox"),
                                   w.get("class_name", "WINDOWSCLIENT"))
        self.capture = ScreenCapture()
        self.banner_capture = ScreenCapture()
        self.vision = Vision(self.cfg)
        self.inp = InputController()
        self.budget = Budget(self.cfg)
        self.navigator = Navigator(self.cfg, self.window, self.capture,
                                   self.vision, self.inp, self.root, log=self._log,
                                   budget=self.budget)

        self._check_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_results = None
        self._last_time = "not yet"
        self._last_error = None
        self._checks = 0
        self._pending_banner: tuple[str, str, float] | None = None  # region, ocr snippet, monotonic
        self._buys = 0
        self._roblox_ok = None

        try:
            logdir = os.path.join(self.root, "logs")
            os.makedirs(logdir, exist_ok=True)
            self._logpath = os.path.join(logdir, datetime.now().strftime("bot_%Y%m%d_%H%M%S.log"))
        except Exception:
            self._logpath = None

    # ---- logging ---------------------------------------------------------
    def _log(self, msg):
        line = time.strftime("[%H:%M:%S] ") + str(msg)
        if getattr(self, "_logpath", None):
            try:
                with open(self._logpath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            # Launcher runs the bot with a cp1252 stdout pipe; unicode arrows crash print().
            try:
                safe = line.encode("ascii", errors="backslashreplace").decode("ascii")
                print(safe, flush=True)
            except Exception:
                pass
        except Exception:
            pass

    # ---- the actual check ------------------------------------------------
    @staticmethod
    def _summarize(results):
        parts = []
        for cat, items in results.items():
            names = [it["name"] + (f" x{it['stock']}" if it.get("stock") else "") for it in items]
            if names:
                parts.append(f"{cat}: " + ", ".join(names))
        return " | ".join(parts) if parts else "nothing notable"

    def _resume_watching(self, action: str, *, checks: int | None = None, buys: int | None = None):
        """Return to the idle watch state after a check (success or failure)."""
        if self._is_vendor_mode() and "at vendor" not in action.lower():
            if " items read - " in action and "watching for restock" in action.lower():
                action = action.replace(
                    "watching for restock", "at vendor, watching for restock", 1
                )
            elif "watching for restock" in action.lower():
                action = "At vendor — watching for restock..."
            elif "still watching" in action.lower():
                action = "Check failed — at vendor, still watching..."
        cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 30))
        kwargs = {
            "checks": self._checks if checks is None else checks,
            "buys": self._buys if buys is None else buys,
            "cooldown_sec": cooldown,
            "countdown_reset": int(time.time()),
            "phase": "watching",
            "event_seq": botevents.last_seq(),
        }
        botstatus.write("watching", action, **kwargs)

    def _reload_cfg(self):
        """Pick up launcher Settings saves (scan order, wishlist, etc.)."""
        self.cfg = appconfig.load()
        self.navigator.cfg = self.cfg
        self.budget = Budget(self.cfg)
        self.navigator.budget = self.budget

    def _do_check(self, reason, *, from_banner: bool = False):
        """Runs under _check_lock. Reads the shop and buys selected items."""
        self._reload_cfg()
        self._log(f"=== CHECK ({reason}) ===")
        botlogs.log_timeline("check_started", reason=reason)
        t0 = time.monotonic()
        try:
            try:
                self.capture.reset()   # a long-lived mss handle can return frozen frames
            except Exception as e:
                self._log(f"   capture reset failed (continuing): {e!r}")
            self.budget.reset()    # fresh purchase budget for this restock cycle
            results, purchases = self.navigator.run_check(from_banner=from_banner)
        except NavigationError as e:
            self._last_error = str(e)
            self._log(f"!!! navigation: {e}")
            notify.error(self.cfg, str(e))
            botlogs.log_timeline("check_failed", reason=reason, error=str(e),
                                 duration_ms=int((time.monotonic() - t0) * 1000))
            self._resume_watching(f"Check failed - {e}")
            botevents.emit("check_failed", reason=reason, error=str(e))
            return False
        except SkipCheck as e:
            raise
        except Exception as e:
            self._last_error = str(e)
            self._log(f"!!! error: {e!r}")
            notify.error(self.cfg, repr(e))
            botlogs.log_timeline("check_failed", reason=reason, error=repr(e),
                                 duration_ms=int((time.monotonic() - t0) * 1000))
            self._resume_watching("Check failed - still watching...")
            botevents.emit("check_failed", reason=reason, error=repr(e))
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_results = results
        self._last_time = ts
        self._last_error = None
        total = sum(len(v) for v in results.values())
        self._log(f"=== DONE: {total} items === {self._summarize(results)}")

        prev_snap = inventory.load_previous()
        flat = inventory.flatten(results)
        diff_events = inventory.emit_diff_events(prev_snap, flat)
        inventory.save_snapshot(flat)
        inventory.log_pipeline(
            reason=reason,
            prev=prev_snap,
            curr=flat,
            events=diff_events,
            raw_summary=self._summarize(results),
        )
        self._log(f"[pipeline] parsed {len(flat)} items, diff -> {len(diff_events)} events")
        for ev in diff_events:
            self._log(f"[event] {ev.get('type', '?')}: {ev}")

        self._checks += 1
        self._buys += len(purchases)
        self._resume_watching(
            f"{total} items read - watching for restock...",
            checks=self._checks,
            buys=self._buys,
        )
        for p in purchases:
            tag = p.get("tag") or ("would buy" if p.get("dry") else "BOUGHT")
            self._log(f"{tag}: {p['name']} x{p['qty']} ({p['category']})")
        notify.purchases_summary(self.cfg, purchases)
        duration_ms = int((time.monotonic() - t0) * 1000)
        botlogs.log_timeline(
            "check_completed",
            reason=reason,
            duration_ms=duration_ms,
            items=total,
            purchases=len(purchases),
        )
        return True

    def _housekeeping(self):
        """Purge debug frames when debug is off; cap the event/timed screenshot dirs."""
        dbg = self.cfg.get("debug", {})
        if not dbg.get("save_screenshots"):
            _prune_dir(os.path.join(self.root, dbg.get("dir", "debug")), 0)
        ev = self.cfg.get("events", {})
        _prune_dir(os.path.join(self.root, ev.get("dir", "events")), int(ev.get("keep", 50)))
        ts = self.cfg.get("timed_screenshots", {})
        _prune_dir(os.path.join(self.root, ts.get("dir", "timed")), int(ts.get("keep", 50)))
        _prune_dir(os.path.join(self.root, "logs"), 40)

    def _save_event_screenshot(self):
        ev = self.cfg.get("events", {})
        if not ev.get("enabled", True):
            return
        try:
            full = self.banner_capture.grab(self.window.client_rect())
            d = os.path.join(self.root, ev.get("dir", "events"))
            os.makedirs(d, exist_ok=True)
            fn = os.path.join(d, datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
            cv2.imwrite(fn, full)
            _prune_dir(d, int(ev.get("keep", 50)))
            self._log(f"screenshot saved: {fn}")
        except Exception as e:
            self._log(f"screenshot failed: {e!r}")

    def _start_timed_screenshots(self):
        ts = self.cfg.get("timed_screenshots", {})
        if not ts.get("enabled"):
            return
        threading.Thread(target=self._timed_loop, args=(ts,), daemon=True).start()

    def _timed_loop(self, ts):
        cap = ScreenCapture()
        d = os.path.join(self.root, ts.get("dir", "timed"))
        os.makedirs(d, exist_ok=True)
        period = float(ts.get("period_sec", 270))
        extra = float(ts.get("extra_offset_sec", 30))
        offsets = [0.0] if extra <= 0 else [0.0, extra]
        t0 = time.monotonic()
        n = 1
        while not self._stop.is_set():
            for off in offsets:
                wait = t0 + period * n + off - time.monotonic()
                if wait > 0 and self._stop.wait(wait):
                    return
                try:
                    full = cap.grab(self.window.client_rect())
                    fn = os.path.join(d, datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
                    cv2.imwrite(fn, full)
                except Exception as e:
                    self._log(f"timed-shot failed: {e!r}")
            n += 1

    def _is_vendor_mode(self) -> bool:
        return bool(self.cfg.get("navigation", {}).get("vendor_mode"))

    def _vendor_fallback_poll_sec(self) -> float | None:
        """Optional slow timer poll; None = banner-only (same speed as normal mode)."""
        nav = self.cfg.get("navigation", {}) or {}
        if nav.get("vendor_poll_sec") is None:
            return None
        return max(5.0, float(nav["vendor_poll_sec"]))

    def _tick_heartbeat(self, last_mono: float) -> float:
        """Log + status ping every ~60s so the launcher knows the bot is alive."""
        now = time.monotonic()
        if now - last_mono < 60.0:
            return last_mono
        watch_msg = (
            "At vendor — watching for restock..."
            if self._is_vendor_mode()
            else "Watching for restock..."
        )
        self._log("Still watching (heartbeat)")
        st = botstatus.read() or {}
        botstatus.write(
            "watching",
            st.get("action") or watch_msg,
            heartbeat_ts=int(time.time()),
            checks=self._checks,
            buys=self._buys,
            phase="watching",
            ocr_ready=True,
            roblox_ok=self._roblox_ok if self._roblox_ok is not None else True,
            cooldown_sec=float(self.cfg["timings"].get("cooldown_after_check_sec", 30)),
        )
        return now

    def _banner_region_list(self) -> list[tuple[str, list]]:
        """Regions to scan each poll — center stack first (country view), then calibrated strips."""
        regions = dict(self.cfg.get("regions") or {})
        defaults = {
            "banner_center": [0.12, 0.22, 0.76, 0.38],
            "banner_stack": [0.18, 0.28, 0.64, 0.28],
            "refill_banner": [0.3, 0.15, 0.4, 0.2],
            "banner_text": [0.3, 0.17, 0.4, 0.06],
        }
        for key, frac in defaults.items():
            regions.setdefault(key, frac)
        order = ["banner_center", "banner_stack", "refill_banner", "banner_text"]
        out: list[tuple[str, list]] = []
        seen: set[tuple] = set()
        for key in order:
            frac = regions.get(key)
            if not frac:
                continue
            sig = tuple(float(x) for x in frac)
            if sig in seen:
                continue
            seen.add(sig)
            out.append((key, list(frac)))
        return out

    def _grab_banner_frames(self) -> list[tuple[str, object]]:
        frames: list[tuple[str, object]] = []
        for name, frac in self._banner_region_list():
            try:
                box = self.window.region_px(frac)
                frames.append((name, self.banner_capture.grab(box)))
            except Exception:
                pass
        return frames

    # Narrow crops first — banner_stack is large and can false-positive on timers/UI.
    _BANNER_TRIGGER_REGIONS = frozenset({"banner_text", "refill_banner", "banner_center"})

    def _try_restock_from_banner(
        self,
        frames: list[tuple[str, object]],
        *,
        cooldown: float,
        last_fire: float,
        last_confirm: float,
        poll_gap: float,
        last_skip_log: float,
    ) -> tuple[float, float, float]:
        """OCR-confirm restock banner and run a check. Returns updated fire/confirm/skip times."""
        now = time.monotonic()
        present = [(n, im) for n, im in frames if self.vision.banner_present(im)]
        if not present:
            self._pending_banner = None
            return last_fire, last_confirm, last_skip_log
        confirm_interval = float(self.cfg["timings"].get("banner_confirm_interval_sec", 1.5))
        if self._pending_banner and (now - self._pending_banner[2]) > confirm_interval * 2.5:
            self._pending_banner = None
        if (now - last_fire) <= cooldown or (now - last_confirm) <= poll_gap:
            return last_fire, last_confirm, last_skip_log

        if not self._check_lock.acquire(blocking=False):
            if now - last_skip_log > 15:
                self._log("Banner visible but a check is already running - skipping.")
                return last_fire, last_confirm, now
            return last_fire, last_confirm, last_skip_log

        last_confirm = time.monotonic()
        try:
            hit = None
            ocr_snip = ""
            for name, img in present:
                if name not in self._BANNER_TRIGGER_REGIONS:
                    continue
                text = self.vision.banner_confirm_text(img)
                if not text:
                    continue
                now = time.monotonic()
                pending = self._pending_banner
                if (
                    pending
                    and pending[0] == name
                    and (now - pending[2]) >= min(0.8, confirm_interval * 0.5)
                    and (now - pending[2]) <= confirm_interval * 2.5
                ):
                    hit = name
                    ocr_snip = text[:120]
                    self._pending_banner = None
                    break
                self._pending_banner = (name, text[:120], now)
                break
            if hit:
                self._log(f"Detected restock banner ({hit}): {ocr_snip!r}")
                cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 30))
                botevents.emit("restock_detected", source="banner")
                botlogs.log_timeline("restock_detected", source="banner")
                botstatus.write(
                    "restock",
                    "Shop restocked — opening (E)...",
                    phase="scanning",
                    countdown_reset=int(time.time()),
                    cooldown_sec=cooldown,
                    event_seq=botevents.last_seq(),
                )
                notify.restock_detected(self.cfg)
                self._save_event_screenshot()
                last_fire = time.monotonic()
                try:
                    self._do_check("shop restocked", from_banner=True)
                except SkipCheck as e:
                    msg = str(e) or "Click Roblox to check shop"
                    self._log(f"   skip: {msg}")
                    botstatus.write(
                        "watching", msg, phase="watching",
                        checks=self._checks, buys=self._buys,
                    )
                except Exception as e:
                    self._log(f"!!! check escaped: {e!r}")
                    self._resume_watching("Check failed — still watching...")
            elif now - last_skip_log > 30:
                names = ", ".join(n for n, _ in present)
                self._log(f"Green text in [{names}] — not a restock banner (OCR)")
                last_skip_log = now
        finally:
            self._check_lock.release()
        return last_fire, last_confirm, last_skip_log

    def _run_vendor_loop(self, interval: float):
        """At shop NPC: watch restock banner (fast) then E → scan → X close."""
        last_fallback = 0.0
        last_fire = 0.0
        last_confirm = 0.0
        last_skip_log = 0.0
        last_reset = 0.0
        first_poll = True
        warned_no_window = False
        last_heartbeat = 0.0
        capture_reset = float(self.cfg["timings"].get("capture_reset_sec", 10))
        cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 25))
        confirm_interval = float(self.cfg["timings"].get("banner_confirm_interval_sec", 1.5))

        self._log("Vendor mode — at shop, watching for restock banner (E/X flow).")
        botstatus.write(
            "watching",
            "At vendor — watching for restock...",
            checks=0, buys=0,
            cooldown_sec=cooldown,
            phase="watching",
            ocr_ready=True,
            roblox_ok=self._roblox_ok,
        )
        try:
            while not self._stop.is_set():
                self._reload_cfg()
                cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 25))
                confirm_interval = float(self.cfg["timings"].get("banner_confirm_interval_sec", 1.5))
                fallback_poll = self._vendor_fallback_poll_sec()

                try:
                    if not self._banner_region_list():
                        self._log("Banner region not calibrated - run tools/calibrate.py")
                        time.sleep(5)
                        continue
                    if self._roblox_ok is not True:
                        self._roblox_ok = True
                        st = botstatus.read() or {}
                        botstatus.write(
                            st.get("state", "watching"),
                            st.get("action", "At vendor — watching for restock..."),
                            ocr_ready=True, roblox_ok=True,
                            checks=st.get("checks", 0), buys=st.get("buys", 0),
                        )
                    warned_no_window = False
                except RobloxWindowError:
                    if not warned_no_window:
                        self._log("Roblox window not found, waiting...")
                        warned_no_window = True
                    if self._roblox_ok is not False:
                        self._roblox_ok = False
                        botstatus.write(
                            "watching",
                            "Roblox window not found — waiting...",
                            ocr_ready=True, roblox_ok=False,
                        )
                    time.sleep(2)
                    continue

                mono = time.monotonic()
                if mono - last_reset > capture_reset:
                    self.banner_capture.reset()
                    last_reset = mono

                frames = self._grab_banner_frames()
                if not frames:
                    time.sleep(2)
                    continue
                poll_gap = 0.0 if first_poll else confirm_interval
                first_poll = False
                last_fire, last_confirm, last_skip_log = self._try_restock_from_banner(
                    frames,
                    cooldown=cooldown,
                    last_fire=last_fire,
                    last_confirm=last_confirm,
                    poll_gap=poll_gap,
                    last_skip_log=last_skip_log,
                )

                now = time.monotonic()
                if fallback_poll is not None and (now - last_fallback) >= fallback_poll:
                    if self._check_lock.acquire(blocking=False):
                        try:
                            botstatus.write(
                                "reading",
                                "Opening shop (E)...",
                                phase="scanning",
                                event_seq=botevents.last_seq(),
                            )
                            self._do_check("vendor poll")
                            last_fallback = time.monotonic()
                        except SkipCheck as e:
                            msg = str(e) or "Click Roblox to check shop"
                            self._log(f"   skip: {msg}")
                            botstatus.write(
                                "watching", msg, phase="watching",
                                checks=self._checks, buys=self._buys,
                            )
                            last_fallback = now - max(0.0, fallback_poll - 5.0)
                        except Exception as e:
                            self._log(f"!!! vendor check escaped: {e!r}")
                            self._resume_watching("Check failed — retrying at vendor...")
                            last_fallback = time.monotonic()
                        finally:
                            self._check_lock.release()

                last_heartbeat = self._tick_heartbeat(last_heartbeat)
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log("Stopped (Ctrl+C)")

    # ---- run -------------------------------------------------------------
    def run(self):
        self._housekeeping()
        self._log("Starting. Warming up OCR (first run downloads the model — needs internet)...")
        ocr_ok = False
        ocr_err = ""
        try:
            self.vision.warmup()
            self._log("OCR ready.")
            ocr_ok = True
            botevents.emit("ocr_ready", ok=True)
        except Exception as e:
            ocr_err = repr(e)
            self._log(f"OCR warmup failed: {ocr_err} (check rapidocr/onnxruntime install)")
            botevents.emit("ocr_ready", ok=False, error=ocr_err)

        if not ocr_ok:
            botstatus.write("stopped", f"OCR failed: {ocr_err}",
                            phase="stopped", ocr_ready=False, roblox_ok=False)
            return

        self._reload_cfg()
        botstatus.write(
            "watching",
            "At vendor — waiting..." if self._is_vendor_mode() else "Watching for restock...",
            checks=0, buys=0,
            cooldown_sec=float(self.cfg["timings"].get("cooldown_after_check_sec", 30)),
            phase="watching",
            ocr_ready=True,
            roblox_ok=False,
        )

        interval = float(self.cfg["timings"].get("watch_interval_sec", 0.5))
        cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 25))
        confirm_interval = float(self.cfg["timings"].get("banner_confirm_interval_sec", 1.5))
        last_fire = 0.0
        last_confirm = 0.0
        last_skip_log = 0.0
        last_reset = 0.0
        capture_reset = float(self.cfg["timings"].get("capture_reset_sec", 10))
        warned_no_window = False
        last_heartbeat = 0.0

        self._start_timed_screenshots()
        try:
            if self._is_vendor_mode():
                self._run_vendor_loop(interval)
            else:
                self._log("Watching the shop...  (Ctrl+C to quit)")
                first_poll = True
                while not self._stop.is_set():
                    try:
                        if not self._banner_region_list():
                            self._log("Banner region not calibrated - run tools/calibrate.py")
                            time.sleep(5)
                            continue
                        if self._roblox_ok is not True:
                            self._roblox_ok = True
                            st = botstatus.read() or {}
                            botstatus.write(
                                st.get("state", "watching"),
                                st.get("action", "Watching for restock..."),
                                ocr_ready=True, roblox_ok=True,
                                checks=st.get("checks", 0), buys=st.get("buys", 0),
                            )
                        warned_no_window = False
                    except RobloxWindowError:
                        if not warned_no_window:
                            self._log("Roblox window not found, waiting...")
                            warned_no_window = True
                        if self._roblox_ok is not False:
                            self._roblox_ok = False
                            st = botstatus.read() or {}
                            botstatus.write(
                                st.get("state", "watching"),
                                "Roblox window not found — waiting...",
                                ocr_ready=True, roblox_ok=False,
                                checks=st.get("checks", 0), buys=st.get("buys", 0),
                            )
                        time.sleep(2)
                        continue

                    # A long-lived mss handle can silently start returning frozen frames,
                    # so recreate it every capture_reset seconds.
                    mono = time.monotonic()
                    if mono - last_reset > capture_reset:
                        self.banner_capture.reset()
                        last_reset = mono

                    frames = self._grab_banner_frames()
                    if not frames:
                        time.sleep(2)
                        continue
                    poll_gap = 0.0 if first_poll else confirm_interval
                    first_poll = False
                    last_fire, last_confirm, last_skip_log = self._try_restock_from_banner(
                        frames,
                        cooldown=cooldown,
                        last_fire=last_fire,
                        last_confirm=last_confirm,
                        poll_gap=poll_gap,
                        last_skip_log=last_skip_log,
                    )

                    last_heartbeat = self._tick_heartbeat(last_heartbeat)
                    time.sleep(interval)
        except KeyboardInterrupt:
            self._log("Stopped (Ctrl+C)")
        finally:
            self._stop.set()
            botlogs.log_session(checks=self._checks, buys=self._buys, reason="stopped")
            botstatus.write("stopped", "Stopped")
            botlogs.cleanup_on_stop(self.root, cfg=self.cfg)


if __name__ == "__main__":
    Watcher().run()
