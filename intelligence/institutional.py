"""
intelligence/institutional.py
SHAHKAR Institutional Intelligence — FREE only.
Sources: Fear & Greed (alternative.me) + Deribit P/C ratio.
No Glassnode. No CoinGlass. No paid APIs.
"""
import requests
import json
import os
import time
import threading
from datetime import datetime
from utils.logger import log

INST_FILE = "logs/institutional_data.json"


class InstitutionalIntelligence:
    def __init__(self):
        self.data     = self._load()
        self._lock    = threading.Lock()
        self._running = False

    def _load(self) -> dict:
        try:
            if os.path.exists(INST_FILE):
                with open(INST_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self):
        os.makedirs("logs", exist_ok=True)
        try:
            with open(INST_FILE, "w") as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception:
            pass

    # ── 1. Fear & Greed ───────────────────────────────────────

    def get_fear_greed(self) -> dict:
        """Always free — no API key needed."""
        try:
            r = requests.get(
                "https://api.alternative.me/fng/?limit=2",
                timeout=8,
                headers={"User-Agent": "SHAHKAR-Bot/1.0"}
            )
            if r.status_code == 200:
                data    = r.json().get("data", [])
                if not data:
                    return self._fg_neutral()
                current = int(data[0].get("value", 50))
                label   = data[0].get("value_classification", "Neutral")

                if current <= 20:
                    signal, score = "extreme_fear_buy", 25
                elif current <= 35:
                    signal, score = "fear_buy", 12
                elif current >= 80:
                    signal, score = "extreme_greed_sell", -20
                elif current >= 65:
                    signal, score = "greed_caution", -8
                else:
                    signal, score = "neutral", 0

                log.info(f"FEAR/GREED  {current}/100  {label}  score={score:+d}")
                return {"value": current, "label": label, "signal": signal, "score": score, "ok": True}
        except Exception as e:
            log.debug(f"Fear/Greed failed: {e}")
        return self._fg_neutral()

    def _fg_neutral(self) -> dict:
        return {"value": 50, "label": "Neutral", "signal": "neutral", "score": 0, "ok": False}

    # ── 2. Deribit Put/Call ratio ─────────────────────────────

    def get_options_sentiment(self) -> dict:
        """Free public Deribit API — no key needed."""
        try:
            r = requests.get(
                "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
                params={"currency": "BTC", "kind": "option"},
                timeout=10,
                headers={"User-Agent": "SHAHKAR-Bot/1.0"}
            )
            if r.status_code == 200:
                data     = r.json().get("result", [])
                call_vol = sum(float(x.get("volume", 0)) for x in data if x.get("instrument_name","").endswith("C"))
                put_vol  = sum(float(x.get("volume", 0)) for x in data if x.get("instrument_name","").endswith("P"))

                if call_vol + put_vol == 0:
                    return {"pc_ratio": 1.0, "signal": "neutral", "score": 0, "ok": False}

                pc = put_vol / call_vol if call_vol > 0 else 1.0

                if pc < 0.5:
                    signal, score = "institutional_bullish", 18
                elif pc < 0.7:
                    signal, score = "slightly_bullish", 8
                elif pc > 1.5:
                    signal, score = "institutional_bearish", -15
                elif pc > 1.0:
                    signal, score = "slightly_bearish", -5
                else:
                    signal, score = "neutral", 0

                log.info(f"OPTIONS P/C={pc:.2f}  signal={signal}  score={score:+d}")
                return {"pc_ratio": round(pc, 3), "signal": signal, "score": score, "ok": True}
        except Exception as e:
            log.debug(f"Deribit failed: {e}")
        return {"pc_ratio": 1.0, "signal": "neutral", "score": 0, "ok": False}

    # ── Combined signal ───────────────────────────────────────

    def get_institutional_signal(self) -> dict:
        fg  = self.get_fear_greed()
        opt = self.get_options_sentiment()
        total = fg.get("score", 0) + opt.get("score", 0)

        if total >= 35:    final = "strong_buy"
        elif total >= 15:  final = "accumulation"
        elif total >= 0:   final = "mild_bullish"
        elif total >= -15: final = "mild_bearish"
        else:              final = "distribution"

        result = {
            "signal":      final,
            "total_score": total,
            "fear_greed":  fg,
            "options":     opt,
            "timestamp":   datetime.utcnow().isoformat(),
        }

        if abs(total) >= 15:
            log.info(f"INSTITUTIONAL  {final}  total={total:+d}  fg={fg.get('value',50)}  pc={opt.get('pc_ratio',1):.2f}")

        with self._lock:
            self.data = result
            self._save()
        return result

    def get_score_bonus(self) -> float:
        with self._lock:
            score = self.data.get("total_score", 0)
        return max(-20.0, min(20.0, score * 0.4))

    def start_background(self):
        self._running = True
        def loop():
            while self._running:
                try:
                    self.get_institutional_signal()
                    time.sleep(300)
                except Exception as e:
                    log.error(f"Institutional update error: {e}")
                    time.sleep(60)
        threading.Thread(target=loop, daemon=True).start()
        log.info("INSTITUTIONAL INTELLIGENCE started (Fear/Greed + Deribit)")

    def stop(self):
        self._running = False
