"""
protection/risk_manager.py
SHAHKAR — Perfect Risk Management
Position sizing, drawdown control, win rate based sizing
"""
import json, os
from utils.logger import log

RISK_FILE = "logs/risk_state.json"


class RiskManager:
    def __init__(self):
        self.state = self._load()

    def _load(self) -> dict:
        try:
            if os.path.exists(RISK_FILE):
                with open(RISK_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "consecutive_losses": 0,
            "consecutive_wins":   0,
            "peak_portfolio":     1000.0,
            "current_portfolio":  1000.0,
        }

    def _save(self):
        os.makedirs("logs", exist_ok=True)
        with open(RISK_FILE, "w") as f:
            json.dump(self.state, f, indent=2)

    def calculate_position_size(self, base_capital: float, win_rate: float,
                                 score: int, daily_loss_used: float,
                                 daily_loss_limit: float) -> float:
        """
        Kelly Criterion based position sizing.
        Higher win rate + higher score = bigger position.
        """
        capital = base_capital

        # Reduce after consecutive losses
        consec_losses = self.state.get("consecutive_losses", 0)
        if consec_losses >= 3:
            capital *= 0.5
            log.warning(f"RISK  3 consecutive losses — reducing size to ${capital:.2f}")
        elif consec_losses >= 2:
            capital *= 0.7

        # Increase after consecutive wins
        consec_wins = self.state.get("consecutive_wins", 0)
        if consec_wins >= 3 and win_rate >= 65:
            capital *= 1.2
            log.info(f"RISK  3 consecutive wins — increasing size to ${capital:.2f}")

        # Score-based adjustment
        if score >= 90:
            capital *= 1.1
        elif score < 75:
            capital *= 0.8

        # Daily loss protection
        remaining = daily_loss_limit - daily_loss_used
        if remaining < daily_loss_limit * 0.3:
            capital *= 0.5
            log.warning(f"RISK  Near daily limit — reducing size to ${capital:.2f}")

        # Never go below $1 or above $50
        capital = max(1.0, min(50.0, capital))
        return round(capital, 2)

    def record_win(self, pnl: float):
        self.state["consecutive_losses"] = 0
        self.state["consecutive_wins"]   = self.state.get("consecutive_wins", 0) + 1
        self.state["current_portfolio"]  = self.state.get("current_portfolio", 1000) + pnl
        peak = self.state.get("peak_portfolio", 1000)
        if self.state["current_portfolio"] > peak:
            self.state["peak_portfolio"] = self.state["current_portfolio"]
        self._save()
        log.info(f"RISK  WIN recorded — consecutive_wins={self.state['consecutive_wins']}")

    def record_loss(self, pnl: float):
        self.state["consecutive_wins"]   = 0
        self.state["consecutive_losses"] = self.state.get("consecutive_losses", 0) + 1
        self.state["current_portfolio"]  = self.state.get("current_portfolio", 1000) + pnl
        self._save()
        log.warning(f"RISK  LOSS recorded — consecutive_losses={self.state['consecutive_losses']}")

    def get_drawdown(self) -> float:
        peak = self.state.get("peak_portfolio", 1000)
        curr = self.state.get("current_portfolio", 1000)
        if peak == 0:
            return 0
        return round((peak - curr) / peak * 100, 2)

    def should_stop_trading(self) -> tuple[bool, str]:
        """Stop trading if drawdown too high."""
        dd = self.get_drawdown()
        if dd >= 20:
            return True, f"Max drawdown hit: {dd}%"
        if self.state.get("consecutive_losses", 0) >= 5:
            return True, "5 consecutive losses — cooling down"
        return False, "ok"
