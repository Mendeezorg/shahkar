"""
core/order_flow.py
SHAHKAR Layer 14 — Order Book Pressure Analysis
Real buy/sell pressure detection
"""
from utils.logger import log


class OrderFlowAnalyzer:
    def __init__(self, exchange):
        self.exchange = exchange

    def analyze(self, symbol: str) -> dict:
        """
        Full order flow analysis.
        Returns buy pressure, sell walls, support/resistance.
        """
        try:
            book = self.exchange.get_orderbook(symbol, limit=20)
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            if not bids or not asks:
                return self._empty()

            # Current price
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread   = (best_ask - best_bid) / best_bid * 100

            # Too wide spread = risky
            if spread > 0.5:
                return {"signal": "skip", "reason": f"spread too wide {spread:.2f}%"}

            # Calculate pressure
            bid_levels = [(float(b[0]), float(b[1])) for b in bids[:10]]
            ask_levels = [(float(a[0]), float(a[1])) for a in asks[:10]]

            bid_vol = sum(p * q for p, q in bid_levels)
            ask_vol = sum(p * q for p, q in ask_levels)
            total   = bid_vol + ask_vol

            buy_pressure = bid_vol / total if total > 0 else 0.5

            # Find support/resistance walls
            max_bid_wall = max(bid_levels, key=lambda x: x[1])
            max_ask_wall = max(ask_levels, key=lambda x: x[1])

            # Imbalance score
            imbalance = buy_pressure - 0.5  # Positive = more buys

            # Signal
            if buy_pressure >= 0.60:
                signal = "bullish"
            elif buy_pressure <= 0.40:
                signal = "bearish"
            else:
                signal = "neutral"

            result = {
                "signal":        signal,
                "buy_pressure":  round(buy_pressure * 100, 1),
                "bid_vol_usdt":  round(bid_vol, 0),
                "ask_vol_usdt":  round(ask_vol, 0),
                "spread_pct":    round(spread, 3),
                "imbalance":     round(imbalance, 3),
                "support":       round(max_bid_wall[0], 8),
                "resistance":    round(max_ask_wall[0], 8),
                "score_bonus":   round(imbalance * 20, 1),  # Max +10 / -10
                "ok":            True,
            }

            return result

        except Exception as e:
            log.debug(f"Order flow analysis failed {symbol}: {e}")
            return self._empty()

    def _empty(self) -> dict:
        return {
            "signal":       "neutral",
            "buy_pressure": 50.0,
            "score_bonus":  0,
            "ok":           False,
        }

    def get_score_adjustment(self, symbol: str) -> float:
        """Quick score adjustment based on order book."""
        result = self.analyze(symbol)
        return result.get("score_bonus", 0)
