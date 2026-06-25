"""
intelligence/memory.py
SHAHKAR Self-Learning Engine.
Reads trade history, adjusts indicator weights, recognizes win patterns.
"""
import json, os
import config
from utils.logger import log

MEMORY_FILE  = "logs/trade_history.json"
WEIGHTS_FILE = "logs/learned_weights.json"


class MemoryEngine:
    def __init__(self):
        self.history = self._load_history()
        self.weights = self._load_weights()

    def _load_history(self) -> list:
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _load_weights(self) -> dict:
        if os.path.exists(WEIGHTS_FILE):
            try:
                with open(WEIGHTS_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return dict(config.INDICATOR_WEIGHTS)

    def _save_weights(self):
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(self.weights, f, indent=2)

    def total_trades(self) -> int:
        return len(self.history)

    def win_rate(self) -> float:
        if not self.history:
            return 0.0
        wins = sum(1 for t in self.history if t.get("win"))
        return round(wins / len(self.history) * 100, 1)

    def avg_win_pct(self) -> float:
        wins = [t["pnl_pct"] for t in self.history if t.get("win") and "pnl_pct" in t]
        return round(sum(wins) / len(wins), 2) if wins else 0.0

    def avg_loss_pct(self) -> float:
        losses = [t["pnl_pct"] for t in self.history if not t.get("win") and "pnl_pct" in t]
        return round(sum(losses) / len(losses), 2) if losses else 0.0

    def learn(self):
        """
        After each trade, adjust weights based on what worked.
        Winning trades with high volume spike → boost volume_spike weight.
        """
        if len(self.history) < 10:
            return   # not enough data yet

        wins   = [t for t in self.history if t.get("win")]
        losses = [t for t in self.history if not t.get("win")]

        if not wins:
            return

        # Boost weights that appear in winners
        for t in wins[-20:]:   # look at last 20 wins
            bd = t.get("breakdown", {})
            for key in self.weights:
                if key in bd and bd[key].get("pass"):
                    self.weights[key] = min(25.0, self.weights[key] * 1.01)

        # Penalize weights that appear in losses
        for t in losses[-10:]:
            bd = t.get("breakdown", {})
            for key in self.weights:
                if key in bd and bd[key].get("pass"):
                    self.weights[key] = max(1.0, self.weights[key] * 0.99)

        self._save_weights()

        # Push updated weights back to config
        config.INDICATOR_WEIGHTS.update(self.weights)

        log.info(f"LEARNING  trades={self.total_trades()}  win_rate={self.win_rate()}%  "
                 f"avg_win={self.avg_win_pct()}%  avg_loss={self.avg_loss_pct()}%")

    def summary(self) -> dict:
        return {
            "total_trades": self.total_trades(),
            "win_rate":     self.win_rate(),
            "avg_win_pct":  self.avg_win_pct(),
            "avg_loss_pct": self.avg_loss_pct(),
            "weights":      self.weights,
        }
