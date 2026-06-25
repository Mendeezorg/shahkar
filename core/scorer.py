"""
core/scorer.py
SHAHKAR Score Engine v3
New weights: max base = 92
Simple pattern replaces ML (higher highs, bullish engulfing, rising volume)
"""
import config
from utils.logger import log


class ScoreEngine:

    def score(self, symbol: str, candidate: dict, btc_trend: str,
              whale_signal: str = "neutral", is_gem: bool = False,
              hour_utc: int = 12, ob_bonus: float = 0.0) -> dict:

        klines = candidate.get("klines", [])
        breakdown = {}
        total = 0.0

        # ── 1. Volume Spike ────────────────────────────────────
        vol_ratio = candidate.get("vol_ratio", 1.0)
        if vol_ratio >= 4.0:
            pts = config.INDICATOR_WEIGHTS["volume_spike"]
        elif vol_ratio >= config.MIN_VOLUME_SPIKE:
            pts = config.INDICATOR_WEIGHTS["volume_spike"] * 0.7
        elif vol_ratio >= 1.5:
            pts = config.INDICATOR_WEIGHTS["volume_spike"] * 0.3
        else:
            pts = 0
        breakdown["volume_spike"] = {"value": round(vol_ratio, 2), "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 2. RSI ─────────────────────────────────────────────
        rsi = self._calc_rsi(klines) if klines else 50.0
        if 35 <= rsi <= 65:
            pts = config.INDICATOR_WEIGHTS["rsi"]
        elif 30 <= rsi <= 70:
            pts = config.INDICATOR_WEIGHTS["rsi"] * 0.5
        else:
            pts = 0
        breakdown["rsi"] = {"value": round(rsi, 1), "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 3. MACD ────────────────────────────────────────────
        macd_result = self._calc_macd(klines) if klines else {}
        if macd_result.get("cross_up"):
            pts = config.INDICATOR_WEIGHTS["macd"]
        elif macd_result.get("hist", 0) > 0:
            pts = config.INDICATOR_WEIGHTS["macd"] * 0.5
        else:
            pts = 0
        breakdown["macd"] = {"value": macd_result.get("cross_up", False), "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 4. Whale / Dark Pool ───────────────────────────────
        if whale_signal == "accumulation":
            pts = config.INDICATOR_WEIGHTS["whale_dark_pool"]
        elif whale_signal == "neutral":
            pts = config.INDICATOR_WEIGHTS["whale_dark_pool"] * 0.25
        else:
            pts = -5.0
        breakdown["whale"] = {"value": whale_signal, "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 5. BTC Trend ───────────────────────────────────────
        if btc_trend == "up":
            pts = config.INDICATOR_WEIGHTS["btc_trend"]
        elif btc_trend == "sideways":
            pts = config.INDICATOR_WEIGHTS["btc_trend"] * 0.5
        elif is_gem:
            pts = config.INDICATOR_WEIGHTS["btc_trend"] * 0.4   # Gem survives BTC down
        else:
            pts = 0
        breakdown["btc_trend"] = {"value": btc_trend, "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 6. Momentum ────────────────────────────────────────
        mom = candidate.get("momentum_3", 0)
        if mom > 2.0:
            pts = config.INDICATOR_WEIGHTS["momentum"]
        elif mom > 0.5:
            pts = config.INDICATOR_WEIGHTS["momentum"] * 0.5
        else:
            pts = 0
        breakdown["momentum"] = {"value": round(mom, 2), "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── 7. Simple Pattern ──────────────────────────────────
        pattern = self._simple_pattern(klines) if klines else {}
        pts = config.INDICATOR_WEIGHTS["simple_pattern"] * pattern.get("strength", 0)
        breakdown["pattern"] = {"value": pattern.get("name", "none"), "pts": round(pts, 1), "pass": pts > 0}
        total += pts

        # ── Bonuses ────────────────────────────────────────────
        if is_gem:
            total += 25
            breakdown["gem_bonus"] = {"pts": 25, "pass": True}

        # Order book bonus
        total += ob_bonus
        if ob_bonus != 0:
            breakdown["orderbook"] = {"pts": round(ob_bonus, 1), "pass": ob_bonus > 0}

        # ── Clamp ──────────────────────────────────────────────
        final = max(0, min(100, round(total)))
        passed = final >= config.MIN_SCORE

        if passed:
            log.info(f"SCORE PASS  {symbol}  {final}/100  gem={is_gem}")
        else:
            log.info(f"SKIP        {symbol}  {final}/100")

        return {
            "symbol":    symbol,
            "score":     final,
            "breakdown": breakdown,
            "pass":      passed,
            "is_gem":    is_gem,
            "reason":    "approved" if passed else f"score_{final}_below_{config.MIN_SCORE}",
        }

    def needs_pullback_entry(self, candidate: dict) -> tuple[bool, float]:
        """
        If last 5m candle pumped >= 2.5%, wait for pullback.
        Returns (True, pump_high) or (False, 0)
        """
        chg = candidate.get("candle_chg", 0)
        if chg >= 2.5:
            pump_high = candidate.get("price", 0)
            pullback_price = round(pump_high * (1 - config.PUMP_PULLBACK_PCT), 8)
            log.info(f"PULLBACK ENTRY  pump_high={pump_high}  wait for={pullback_price}")
            return True, pullback_price
        return False, 0.0

    # ── Technical helpers ─────────────────────────────────────

    def _calc_rsi(self, klines: list, period: int = 14) -> float:
        import numpy as np
        try:
            closes = np.array([float(k[4]) for k in klines])
            delta  = np.diff(closes)
            gain   = np.where(delta > 0, delta, 0)
            loss   = np.where(delta < 0, -delta, 0)
            avg_g  = np.mean(gain[-period:])
            avg_l  = np.mean(loss[-period:])
            if avg_l == 0:
                return 100.0
            rs = avg_g / avg_l
            return round(100 - (100 / (1 + rs)), 2)
        except Exception:
            return 50.0

    def _calc_macd(self, klines: list) -> dict:
        import numpy as np
        try:
            closes = np.array([float(k[4]) for k in klines])
            def ema(data, span):
                alpha = 2 / (span + 1)
                result = [data[0]]
                for v in data[1:]:
                    result.append(result[-1] * (1 - alpha) + v * alpha)
                return np.array(result)
            ema12  = ema(closes, 12)
            ema26  = ema(closes, 26)
            macd   = ema12 - ema26
            signal = ema(macd, 9)
            hist   = macd - signal
            cross_up = bool(macd[-1] > signal[-1] and macd[-2] <= signal[-2])
            return {"cross_up": cross_up, "hist": float(hist[-1]), "macd": float(macd[-1])}
        except Exception:
            return {"cross_up": False, "hist": 0, "macd": 0}

    def _simple_pattern(self, klines: list) -> dict:
        """
        Simple patterns: higher highs/lows, bullish engulfing, rising volume.
        Returns {"name": str, "strength": 0.0-1.0}
        """
        try:
            if len(klines) < 6:
                return {"name": "none", "strength": 0}

            closes  = [float(k[4]) for k in klines]
            opens   = [float(k[1]) for k in klines]
            highs   = [float(k[2]) for k in klines]
            lows    = [float(k[3]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            # Higher highs and higher lows (last 4 candles)
            hh = highs[-1] > highs[-2] > highs[-3]
            hl = lows[-1]  > lows[-2]  > lows[-3]
            higher_highs_lows = hh and hl

            # Bullish engulfing (last 2 candles)
            prev_bearish  = closes[-2] < opens[-2]
            curr_bullish  = closes[-1] > opens[-1]
            curr_engulfs  = opens[-1] <= closes[-2] and closes[-1] >= opens[-2]
            engulfing     = prev_bearish and curr_bullish and curr_engulfs

            # Rising volume on green candles
            green_vol = all(
                volumes[-i] > volumes[-i-1]
                for i in range(1, 4)
                if closes[-i] > opens[-i]
            )

            signals = sum([higher_highs_lows, engulfing, green_vol])

            if signals >= 3:
                return {"name": "strong_bullish", "strength": 1.0}
            elif signals == 2:
                return {"name": "bullish", "strength": 0.7}
            elif signals == 1:
                return {"name": "weak_bullish", "strength": 0.4}
            else:
                return {"name": "none", "strength": 0}
        except Exception:
            return {"name": "none", "strength": 0}
