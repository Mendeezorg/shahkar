"""
core/pump_scanner.py
SHAHKAR Layer 12 — 5 Minute Early Pump Detector
Har 60 second pe 5 min candles scan karta hai
Jab coin suddenly 3-5% pump kare volume ke saath — turant signal
"""
import time
from core.exchange import Exchange
from utils.logger import log


# Minimum conditions for early pump signal
MIN_PUMP_PCT     = 2.5   # 2.5% move in 5 minutes
MIN_VOLUME_RATIO = 3.0   # 3x average volume
MAX_COINS_CHECK  = 80    # Top 80 coins by volume


class PumpScanner:
    def __init__(self, exchange: Exchange):
        self.ex            = exchange
        self.prev_prices   = {}   # symbol → last price
        self.pump_history  = {}   # symbol → pump count

    def scan(self, candidates: list[dict]) -> list[dict]:
        """
        Scan top coins for early pump signals.
        Returns list of coins showing early pump pattern.
        """
        pumps = []
        checked = 0

        for coin in candidates[:MAX_COINS_CHECK]:
            sym = coin["symbol"]
            checked += 1

            try:
                # Get 5 minute candles — last 20
                klines_5m = self.ex.get_klines(sym, "5m", 20)
                if len(klines_5m) < 10:
                    continue

                # Latest candle
                latest   = klines_5m[-1]
                prev     = klines_5m[-2]
                open_5m  = float(latest[1])
                close_5m = float(latest[4])
                high_5m  = float(latest[2])
                vol_5m   = float(latest[5])

                # Average volume of last 10 candles
                avg_vol = sum(float(k[5]) for k in klines_5m[-11:-1]) / 10
                if avg_vol == 0:
                    continue

                vol_ratio = vol_5m / avg_vol

                # Price change in last candle
                if open_5m == 0:
                    continue
                candle_change = (close_5m - open_5m) / open_5m * 100

                # 3 candle momentum
                price_3_ago = float(klines_5m[-4][4])
                momentum_3  = (close_5m - price_3_ago) / price_3_ago * 100 if price_3_ago > 0 else 0

                # ── Pump signal conditions ────────────────────
                is_pump = (
                    candle_change >= MIN_PUMP_PCT and
                    vol_ratio >= MIN_VOLUME_RATIO and
                    momentum_3 >= 1.5   # Rising for last 3 candles
                )

                # ── Strong pump — very aggressive ─────────────
                is_strong_pump = (
                    candle_change >= 4.0 and
                    vol_ratio >= 5.0
                )

                if is_pump or is_strong_pump:
                    strength = "STRONG" if is_strong_pump else "NORMAL"
                    score_bonus = 35 if is_strong_pump else 20

                    pumps.append({
                        "symbol":       sym,
                        "candle_change": round(candle_change, 2),
                        "vol_ratio":    round(vol_ratio, 2),
                        "momentum_3":   round(momentum_3, 2),
                        "current_price": close_5m,
                        "strength":     strength,
                        "score_bonus":  score_bonus,
                        "coin_data":    coin,
                    })

                    log.info(
                        f"PUMP DETECTED  {sym}  "
                        f"change={candle_change:+.2f}%  "
                        f"vol={vol_ratio:.1f}x  "
                        f"strength={strength}"
                    )

            except Exception as e:
                log.debug(f"Pump scan error {sym}: {e}")
                continue

        if pumps:
            pumps.sort(key=lambda x: (x["vol_ratio"] * x["candle_change"]), reverse=True)
            log.info(f"PUMP SCANNER  {len(pumps)} pumps found out of {checked} checked")

        return pumps

    def is_still_pumping(self, symbol: str) -> bool:
        """Check if coin is still in pump phase — not exhausted."""
        try:
            klines = self.ex.get_klines(symbol, "5m", 5)
            if len(klines) < 3:
                return True

            closes = [float(k[4]) for k in klines[-3:]]
            # Still pumping if last candle not red
            return closes[-1] >= closes[-2] * 0.995
        except Exception:
            return True
