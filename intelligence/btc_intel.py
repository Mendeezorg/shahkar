"""
intelligence/btc_intel.py — Async BTC Intelligence
"""
from core.scorer import ScoreEngine
from utils.logger import log


class BTCIntelligence:
    def __init__(self, exchange):
        self.exchange = exchange

    async def get_btc_data(self) -> dict:
        try:
            ticker   = await self.exchange.client.get_ticker(symbol="BTCUSDT")
            klines1h = await self.exchange.client.get_klines(symbol="BTCUSDT", interval="1h", limit=50)
            klines5m = await self.exchange.client.get_klines(symbol="BTCUSDT", interval="5m", limit=10)

            change_24h = float(ticker["priceChangePercent"])
            price      = float(ticker["lastPrice"])

            closes_5m  = [float(k[4]) for k in klines5m]
            change_5m  = (closes_5m[-1] - closes_5m[0]) / closes_5m[0] * 100 if closes_5m else 0

            scorer = ScoreEngine()
            rsi    = scorer._calc_rsi(klines1h)
            macd   = scorer._calc_macd(klines1h)

            if change_24h > 1.5:
                trend, mode = "up",       "trend_following"
            elif change_24h < -1.5:
                trend, mode = "down",     "decouple_hunt"
            else:
                trend, mode = "sideways", "volume_spike_hunt"

            result = {
                "price":      price,
                "change_24h": round(change_24h, 2),
                "change_5m":  round(change_5m, 2),
                "rsi":        rsi,
                "macd":       macd,
                "trend":      trend,
                "mode":       mode,
                "ok":         True,
            }
            log.info(f"BTC ${price:,.0f} ({change_24h:+.2f}%) trend={trend}")
            return result

        except Exception as e:
            log.error(f"BTC intel error: {e}")
            return {"ok": False, "trend": "sideways", "mode": "unknown",
                    "change_24h": 0, "change_5m": 0, "price": 0}
