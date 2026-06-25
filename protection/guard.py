"""
protection/guard.py
SHAHKAR Protection — Hard time block + gem crash exemption.
"""
import json, os
from datetime import datetime, date
import config
from utils.logger import log

STATE_FILE = "logs/protection_state.json"


class ProtectionGuard:
    def __init__(self):
        self._state = self._load_state()
        self._reset_if_new_day()

    def _load_state(self) -> dict:
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"date": str(date.today()), "daily_loss": 0.0, "halted": False}

    def _save_state(self):
        os.makedirs("logs", exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self._state, f, indent=2)

    def _reset_if_new_day(self):
        today = str(date.today())
        if self._state.get("date") != today:
            log.info("New day — resetting daily loss")
            self._state = {"date": today, "daily_loss": 0.0, "halted": False}
            self._save_state()

    # ── HARD time block ───────────────────────────────────────

    def is_trading_allowed(self) -> bool:
        """HARD BLOCK — if outside HOT_HOURS, stop scanning entirely."""
        hour = datetime.utcnow().hour
        if hour not in config.HOT_HOURS:
            log.info(f"HARD BLOCK — {hour} UTC outside trading hours (6-22)")
            return False
        return True

    # ── Daily loss ────────────────────────────────────────────

    def record_loss(self, amount: float):
        self._state["daily_loss"] += abs(amount)
        log.warning(f"Daily loss: ${self._state['daily_loss']:.2f}/${config.DAILY_LOSS_LIMIT}")
        if self._state["daily_loss"] >= config.DAILY_LOSS_LIMIT:
            self._state["halted"] = True
            log.error(f"DAILY LIMIT HIT — trading HALTED")
        self._save_state()

    def is_halted(self) -> bool:
        return self._state.get("halted", False)

    def daily_loss_used(self) -> float:
        return round(self._state.get("daily_loss", 0.0), 2)

    def should_reduce_size(self) -> bool:
        return self._state["daily_loss"] >= config.DAILY_LOSS_LIMIT * 0.5

    # ── Stop loss ─────────────────────────────────────────────

    def check_stop_loss(self, entry_price: float, current_price: float) -> bool:
        drop = (entry_price - current_price) / entry_price
        if drop >= config.STOP_LOSS_PCT:
            log.warning(f"STOP LOSS triggered — drop={drop*100:.2f}%")
            return True
        return False

    def check_trailing_stop(self, highest_price: float, current_price: float) -> bool:
        stop = round(highest_price * (1 - config.TRAILING_STOP_PCT), 8)
        if current_price <= stop:
            log.info(f"TRAILING STOP hit — highest={highest_price} stop={stop} current={current_price}")
            return True
        return False

    def calc_trailing_stop(self, highest_price: float) -> float:
        return round(highest_price * (1 - config.TRAILING_STOP_PCT), 8)

    # ── Crash detection with gem exemption ───────────────────

    def detect_crash(self, btc_change_5m: float, btc_change_1h: float) -> dict:
        if btc_change_5m < -3.0 or btc_change_1h < -7.0:
            log.error(f"CRASH DETECTED — 5m={btc_change_5m}% 1h={btc_change_1h}%")
            return {"crash": True, "level": "crash"}
        if btc_change_5m < -1.5 or btc_change_1h < -4.0:
            log.warning(f"CRASH WARNING — 5m={btc_change_5m}% 1h={btc_change_1h}%")
            return {"crash": False, "level": "warning"}
        return {"crash": False, "level": "safe"}

    def get_crash_close_list(self, open_trades: dict, crash_level: str) -> list[str]:
        """
        Returns list of symbols to close on crash.
        GEM_EXEMPT: gems are NOT closed — they might be pumping BECAUSE of BTC crash.
        """
        to_close = []
        for sym, trade in open_trades.items():
            if config.GEM_EXEMPT_FROM_CRASH and trade.get("is_gem"):
                log.info(f"[GEM EXEMPT] {sym} — keeping open during crash")
                continue
            to_close.append(sym)
        return to_close

    # ── News time block ───────────────────────────────────────

    def is_news_time(self, hour_utc: int, minute_utc: int) -> bool:
        news_hours = [(8, 30), (14, 0), (18, 0), (20, 30)]
        for (nh, nm) in news_hours:
            diff = abs((hour_utc * 60 + minute_utc) - (nh * 60 + nm))
            if diff <= 30:
                log.warning(f"NEWS BLOCK — near {nh:02d}:{nm:02d} UTC")
                return True
        return False

    # ── Master entry gate ─────────────────────────────────────

    def can_enter_trade(self, hour: int, minute: int,
                         btc_change_5m: float = 0.0,
                         btc_change_1h: float = 0.0) -> tuple[bool, str]:
        if self.is_halted():
            return False, "daily_loss_limit_hit"
        crash = self.detect_crash(btc_change_5m, btc_change_1h)
        if crash["crash"]:
            return False, "crash_detected"
        if self.is_news_time(hour, minute):
            return False, "news_time_blocked"
        return True, "ok"
