"""
intelligence/whale_onchain.py
On-chain whale tracking via Etherscan/BSCScan free tier.
10-minute cache to avoid rate limits.
Max bonus reduced to +10 (on-chain is slow/delayed).
"""
import requests, json, os, time
from datetime import datetime
from utils.logger import log

WHALE_FILE = "logs/whale_onchain.json"
CACHE_TTL  = 600   # 10 minutes


class UltimateWhaleTracker:
    def __init__(self):
        self.etherscan_key = os.getenv("ETHERSCAN_API_KEY", "")
        self.bscscan_key   = os.getenv("BSCSCAN_API_KEY", "")
        self._cache        = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(WHALE_FILE):
                with open(WHALE_FILE) as f:
                    data = json.load(f)
                    self._cache = data.get("cache", {})
        except Exception:
            pass

    def _save(self):
        os.makedirs("logs", exist_ok=True)
        try:
            with open(WHALE_FILE, "w") as f:
                json.dump({"cache": self._cache, "updated": datetime.utcnow().isoformat()}, f, indent=2)
        except Exception:
            pass

    def _cached(self, key: str):
        entry = self._cache.get(key)
        if entry and time.time() - entry.get("t", 0) < CACHE_TTL:
            return entry.get("v")
        return None

    def _set_cache(self, key: str, value):
        self._cache[key] = {"v": value, "t": time.time()}
        self._save()

    def get_exchange_flow(self) -> dict:
        """
        Check Binance wallet inflow/outflow on BSC.
        10 min cache — free tier safe.
        """
        cache_key = "exchange_flow"
        cached = self._cached(cache_key)
        if cached:
            return cached

        try:
            binance_wallet = "0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8"
            params = {
                "module":  "account",
                "action":  "txlist",
                "address": binance_wallet,
                "sort":    "desc",
                "apikey":  self.bscscan_key or "YourApiKeyToken",
                "page":    1,
                "offset":  20,
            }
            r = requests.get("https://api.bscscan.com/api", params=params, timeout=8)
            if r.status_code == 200:
                txs     = r.json().get("result", [])
                if not isinstance(txs, list):
                    result = {"signal": "neutral", "score": 0, "ok": False}
                    self._set_cache(cache_key, result)
                    return result

                inflow  = sum(1 for tx in txs if tx.get("to","").lower() == binance_wallet.lower())
                outflow = sum(1 for tx in txs if tx.get("from","").lower() == binance_wallet.lower())

                if inflow > outflow * 1.5:
                    signal, score = "selling_pressure", -8
                elif outflow > inflow * 1.5:
                    signal, score = "accumulation", 10
                else:
                    signal, score = "neutral", 0

                result = {"inflow": inflow, "outflow": outflow, "signal": signal, "score": score, "ok": True}
                self._set_cache(cache_key, result)
                log.info(f"WHALE ONCHAIN  {signal}  in={inflow}  out={outflow}")
                return result
        except Exception as e:
            log.debug(f"BSCScan failed: {e}")

        result = {"signal": "neutral", "score": 0, "ok": False}
        self._set_cache(cache_key, result)
        return result

    def get_ultimate_whale_signal(self, symbol: str = "BTCUSDT") -> dict:
        flow  = self.get_exchange_flow()
        score = flow.get("score", 0)
        # Cap at +10 — on-chain is delayed, don't over-weight
        score = max(-10, min(10, score))
        signal = "accumulation" if score > 0 else "distribution" if score < 0 else "neutral"
        return {"signal": signal, "score": score, "ok": flow.get("ok", False)}

    def get_score_bonus(self, symbol: str = "BTCUSDT") -> float:
        result = self.get_ultimate_whale_signal(symbol)
        return float(result.get("score", 0))
