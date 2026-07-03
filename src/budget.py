"""Per-restock purchase budget.

The bot has no reliable way to OCR in-game currency prices off the shop
cards (parser.py only reads name/rarity/stock — see README if you want to
extend it), so "budget" here is a practical stand-in: a cap on the total
*number of purchase actions* (buy-button clicks) allowed in a single restock
cycle, shared across all categories. Combined with item priority, this lets
you say "buy at most N things per restock, favoring my top picks."

max_total_per_restock = 0 means unlimited (the old, uncapped behavior).
"""
from __future__ import annotations


class Budget:
    def __init__(self, cfg):
        buy_cfg = (cfg or {}).get("buy", {})
        self.limit = int(buy_cfg.get("max_total_per_restock", 0))
        self.spent = 0

    def reset(self):
        self.spent = 0

    def remaining(self):
        if self.limit <= 0:
            return None  # unlimited
        return max(0, self.limit - self.spent)

    def can_buy(self):
        return self.limit <= 0 or self.spent < self.limit

    def spend(self, n=1):
        self.spent += n
