"""Computer-vision helpers: OCR (RapidOCR), green-banner and buy-button detection.

OCR language follows config game.locale (auto = latin model for multi-language UI).
The OCR engine loads lazily on first use so the watch loop starts instantly.
"""
from __future__ import annotations

import os
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from src.game_locale import confirm_banner_text, get_ui, ocr_lang_for_cfg


def _frozen_ocr_model_root() -> str | None:
    """Writable cache for OCR weights when running as MiniWarAFKBot.exe."""
    if not getattr(sys, "frozen", False):
        return None
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    root = Path(base) / "MiniWarAFKBot" / "ocr_models"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)

# RapidOCR logs an INFO line per model + a WARNING on every empty frame; quiet it.
logging.getLogger("RapidOCR").setLevel(logging.ERROR)


class Vision:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._ocr = None
        self._ocr_lang_key = ""
        self.reload_params()

    def reload_params(self):
        """Re-read HSV/threshold values from self.cfg without rebuilding the OCR engine."""
        c = self.cfg["colors"]
        self.banner_low = np.array(c["refill_green_hsv_low"], np.uint8)
        self.banner_high = np.array(c["refill_green_hsv_high"], np.uint8)
        self.banner_min_px = int(c.get("refill_min_pixels", 800))
        self.banner_max_fraction = float(c.get("refill_max_fraction", 0.7))
        lang_key = ocr_lang_for_cfg(self.cfg)
        if self._ocr is not None and lang_key != self._ocr_lang_key:
            self._ocr = None

    def _build_ocr(self):
        from rapidocr import RapidOCR, EngineType, LangRec, OCRVersion, ModelType

        lang_key = ocr_lang_for_cfg(self.cfg)
        self._ocr_lang_key = lang_key
        try:
            lang_enum = LangRec(lang_key)
        except ValueError:
            lang_enum = LangRec.EN if lang_key == "en" else LangRec.LATIN
        params = {
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Cls.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": lang_enum,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        }
        raw = self.cfg.get("ocr", {}).get("num_threads", 0)
        if isinstance(raw, str):
            raw = 0 if raw.strip().lower() in ("auto", "") else int(raw)
        n = int(raw)
        if n <= 0:
            cores = os.cpu_count() or 4
            n = max(2, min(8, cores // 2))
        params["EngineConfig.onnxruntime.intra_op_num_threads"] = n
        params["EngineConfig.onnxruntime.inter_op_num_threads"] = 1
        model_root = _frozen_ocr_model_root()
        if model_root:
            params["Global.model_root_dir"] = model_root
        self._ocr = RapidOCR(params=params)
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)

    # ---- OCR engine (lazy) ----------------------------------------------
    @property
    def ocr(self):
        if self._ocr is None:
            self._build_ocr()
        return self._ocr

    def warmup(self):
        """Force the model to load (downloads on first ever run)."""
        _ = self.ocr
        self.ocr(np.zeros((40, 120, 3), np.uint8))

    # ---- green refill banner --------------------------------------------
    def banner_score(self, img_bgr) -> int:
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.banner_low, self.banner_high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        return int(cv2.countNonZero(mask))

    def banner_present(self, img_bgr) -> bool:
        score = self.banner_score(img_bgr)
        total = img_bgr.shape[0] * img_bgr.shape[1]
        # Scale the pixel floor for narrow calibration strips (full-frame threshold
        # is too high for a tiny banner_text crop).
        ref_area = 1920 * 1080 * 0.4 * 0.06
        min_px = max(80, int(self.banner_min_px * min(1.0, total / max(ref_area, 1))))
        if score < min_px:
            return False
        # The banner is green text (partial fill); solid green filling the whole
        # region is scenery, not a banner.
        if total and (score / total) > self.banner_max_fraction:
            return False
        return True

    def banner_confirm_ocr(self, img_bgr, upscale: float | None = None) -> bool:
        return bool(self.banner_confirm_text(img_bgr, upscale=upscale))

    def banner_confirm_text(self, img_bgr, upscale: float | None = None) -> str | None:
        """Return OCR text when it matches the restock banner, else None."""
        if upscale is None:
            upscale = 4.0 if img_bgr.shape[0] > 120 else 3.0
        text = self.ocr_text(img_bgr, upscale=upscale)
        if not text.strip():
            return None
        if confirm_banner_text(text, get_ui(self.cfg)):
            return text.strip()
        return None

    # ---- green "buy" (money) button -------------------------------------
    def find_buy_button(self, frame_bgr, y_above, hsv_low, hsv_high,
                        right_frac=0.58, min_w_frac=0.10):
        """Find the green money button of the card whose name is at y_above.
        Searches only right of the card and below the name so the green "Stock"
        text / item icon don't match. Returns (cx, cy) in frame coords, or None."""
        h, w = frame_bgr.shape[:2]
        x0 = int(w * right_frac)
        roi = frame_bgr[:, x0:]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(hsv_low, np.uint8), np.array(hsv_high, np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < w * min_w_frac or bw < bh * 1.3:   # buttons are wide rectangles
                continue
            cy = y + bh // 2
            if cy <= y_above + 5:                      # must be below the name
                continue
            cx = x0 + x + bw // 2
            if best is None or cy < best[1]:
                best = (cx, cy)
        return best

    # ---- purchase verification --------------------------------------------
    def read_stock_at(self, frame_bgr, y_center, band_h=46):
        """OCR a narrow horizontal band around a card's name row so a purchase
        can be confirmed by checking the stock number actually dropped, instead
        of just assuming the click worked. Returns the raw OCR'd text, or None
        if the band is out of frame (e.g. the list scrolled/reflowed)."""
        h, w = frame_bgr.shape[:2]
        y0 = max(0, int(y_center) - 6)
        y1 = min(h, y0 + band_h)
        if y1 <= y0:
            return None
        band = frame_bgr[y0:y1, :]
        if band.size == 0:
            return None
        return self.ocr_text(band, upscale=2.5)

    # ---- disabled / unaffordable buy button --------------------------------
    def find_disabled_button(self, frame_bgr, y_above, hsv_low, hsv_high,
                             right_frac=0.58, min_w_frac=0.10):
        """Same shape-search as find_buy_button but against a *different* HSV
        range (grey/red = can't afford, rather than green = can buy). Lets the
        bot tell 'sold out' (no button-shaped region at all) apart from 'still
        there but disabled' (insufficient funds)."""
        return self.find_buy_button(frame_bgr, y_above, hsv_low, hsv_high,
                                    right_frac, min_w_frac)


    def _preprocess(self, img_bgr, scale):
        img = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def ocr_lines(self, img_bgr, upscale=None):
        """Return [{text, score, x, y, h, x0}] in original crop coordinates."""
        up = float(upscale) if upscale else float(self.cfg["ocr"].get("upscale", 3.0))
        pre = self._preprocess(img_bgr, up)
        res = self.ocr(pre)
        records = self._normalize_result(res)
        out = []
        min_conf = float(self.cfg["ocr"].get("min_confidence", 0.3))
        for txt, box, score in records:
            if score is not None and score < min_conf:
                continue
            pts = np.asarray(box, dtype=np.float32) / up
            out.append({
                "text": str(txt),
                "score": float(score) if score is not None else 1.0,
                "x": float(pts[:, 0].mean()),
                "y": float(pts[:, 1].mean()),
                "h": float(pts[:, 1].max() - pts[:, 1].min()),
                "x0": float(pts[:, 0].min()),
            })
        return out

    def ocr_text(self, img_bgr, upscale=None) -> str:
        return " ".join(l["text"] for l in self.ocr_lines(img_bgr, upscale))

    @staticmethod
    def _normalize_result(res):
        """Handle both the modern rapidocr object API and the legacy tuple API."""
        if res is None:
            return []
        # modern: object with .txts/.boxes/.scores (boxes/scores are ndarrays)
        txts = getattr(res, "txts", None)
        if txts is not None:
            n = len(txts)
            boxes = getattr(res, "boxes", None)
            scores = getattr(res, "scores", None)
            if boxes is None:
                boxes = [None] * n
            if scores is None:
                scores = [None] * n
            return list(zip(txts, boxes, scores))
        # legacy: (list_of_[box,text,score], elapse) or list_of_[box,text,score]
        data = res
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], (list, type(None))):
            data = res[0] or []
        out = []
        for item in (data or []):
            try:
                out.append((item[1], item[0], item[2]))
            except (IndexError, TypeError):
                continue
        return out
