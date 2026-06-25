"""
utils/state.py
File-based state with Redis fallback.
Works identically whether Redis is available or not.
"""
import json, os, time
from utils.logger import log

class StateManager:
    def __init__(self):
        self.redis     = None
        self.use_redis = False
        self._file     = "shahkar_state.json"
        self._mem      = {}   # in-memory fallback
        self._connect_redis()

    def _connect_redis(self):
        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            log.info("STATE  No Redis URL — using file storage")
            return
        try:
            import redis as _redis
            self.redis = _redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
            self.use_redis = True
            log.info("STATE  Redis connected!")
        except Exception as e:
            log.warning(f"STATE  Redis failed ({e}) — using file storage")

    # ── File helpers ──────────────────────────────────────────
    def _read_file(self) -> dict:
        try:
            if os.path.exists(self._file):
                with open(self._file, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_file(self, data: dict):
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            log.error(f"STATE file write error: {e}")

    # ── Public API ────────────────────────────────────────────
    def set(self, key: str, value, expiry: int = 3600):
        try:
            if self.use_redis:
                self.redis.setex(key, expiry, json.dumps(value, default=str))
            else:
                data = self._read_file()
                data[key] = {"v": value, "t": time.time(), "ttl": expiry}
                self._write_file(data)
                self._mem[key] = value
        except Exception as e:
            log.error(f"STATE set error: {e}")

    def get(self, key: str):
        try:
            if self.use_redis:
                v = self.redis.get(key)
                return json.loads(v) if v else None
            else:
                # Try memory first
                if key in self._mem:
                    return self._mem[key]
                data = self._read_file()
                entry = data.get(key)
                if entry:
                    # Check TTL
                    if time.time() - entry["t"] < entry["ttl"]:
                        self._mem[key] = entry["v"]
                        return entry["v"]
        except Exception as e:
            log.error(f"STATE get error: {e}")
        return None

    def delete(self, key: str):
        try:
            if self.use_redis:
                self.redis.delete(key)
            else:
                data = self._read_file()
                data.pop(key, None)
                self._write_file(data)
                self._mem.pop(key, None)
        except Exception as e:
            log.error(f"STATE delete error: {e}")

    # ── Convenience wrappers ──────────────────────────────────
    def update_btc(self, d):        self.set("btc", d, 60)
    def update_stats(self, d):      self.set("stats", d, 300)
    def update_trades(self, d):     self.set("trades", d, 300)
    def update_news(self, d):       self.set("news", d, 300)
    def update_logs(self, d):       self.set("logs", d, 300)
    def update_weights(self, d):    self.set("weights", d, 3600)

    def get_all_dashboard_data(self) -> dict:
        from datetime import datetime
        return {
            "btc":        self.get("btc")        or {},
            "stats":      self.get("stats")      or {},
            "trades":     self.get("trades")     or {},
            "news":       self.get("news")        or {},
            "logs":       self.get("logs")        or [],
            "weights":    self.get("weights")    or {},
            "history":    self.get("history")    or [],
            "protection": self.get("protection") or {},
            "timestamp":  datetime.utcnow().strftime("%H:%M:%S UTC"),
        }

state = StateManager()
