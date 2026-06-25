"""
intelligence/whale_tracker.py
SHAHKAR Layer 13 — Real Whale Wallet Tracking
Binance large order detection + on-chain whale alerts
"""
import requests
import json
import os
import time
import threading
from datetime import datetime
from utils.logger import log

WHALE_FILE = "logs/whale_data.json"

# Known whale alert RSS/API sources (free)
WHALE_SOURCES = [
    "https://cryptopanic.com/api/v1/posts/?auth_token=public&kind=news&filter=important",
]


class WhaleTracker:
    def __init__(self, exchange=None):
        self.exchange      = exchange
        self.whale_signals = {}   # symbol → signal
        self.large_orders  = []   # recent large orders
        self._lock         = threading.Lock()
        self._load()

    def _load(self):
        try:
            if os.path.exists(WHALE_FILE):
                with open(WHALE_FILE) as f:
                    data = json.load(f)
                    self.whale_signals = data.get("signals", {})
        except Exception:
            pass

    def _save(self):
        os.makedirs("logs", exist_ok=True)
        try:
            with open(WHALE_FILE, "w") as f:
                json.dump({
                    "signals": self.whale_signals,
                    "updated": datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception:
            pass

    def analyze_order_book(self, symbol: str) -> dict:
        """
        Analyze order book for whale presence.
        Large buy walls = accumulation
        Large sell walls = distribution
        """
        try:
            book = self.exchange.get_orderbook(symbol, limit=20)
            bids = book.get("bids", [])  # Buy orders
            asks = book.get("asks", [])  # Sell orders

            if not bids or not asks:
                return {"signal": "neutral", "buy_pressure": 0.5}

            # Total bid/ask volume
            bid_vol = sum(float(b[0]) * float(b[1]) for b in bids[:10])
            ask_vol = sum(float(a[0]) * float(a[1]) for a in asks[:10])

            total = bid_vol + ask_vol
            if total == 0:
                return {"signal": "neutral", "buy_pressure": 0.5}

            buy_pressure = bid_vol / total

            # Check for large individual orders (whales)
            max_bid = max(float(b[0]) * float(b[1]) for b in bids[:5])
            max_ask = max(float(a[0]) * float(a[1]) for a in asks[:5])

            # Large buy wall = whale accumulating
            if buy_pressure > 0.65 and max_bid > max_ask * 1.5:
                signal = "accumulation"
            elif buy_pressure < 0.35 and max_ask > max_bid * 1.5:
                signal = "distribution"
            else:
                signal = "neutral"

            return {
                "signal":       signal,
                "buy_pressure": round(buy_pressure, 3),
                "bid_vol":      round(bid_vol, 2),
                "ask_vol":      round(ask_vol, 2),
                "max_bid_wall": round(max_bid, 2),
                "max_ask_wall": round(max_ask, 2),
            }

        except Exception as e:
            log.debug(f"Order book analysis failed {symbol}: {e}")
            return {"signal": "neutral", "buy_pressure": 0.5}

    def get_large_trade_signal(self, symbol: str) -> dict:
        """
        Check recent trades for unusually large transactions.
        Large buy = whale accumulating.
        """
        try:
            # Get recent trades
            trades = self.exchange.client.get_recent_trades(symbol=symbol, limit=50)
            if not trades:
                return {"signal": "neutral"}

            prices  = [float(t["price"]) for t in trades]
            qtys    = [float(t["qty"]) for t in trades]
            avg_qty = sum(qtys) / len(qtys) if qtys else 1

            # Find whale trades (10x average size)
            whale_buys  = 0
            whale_sells = 0

            for t in trades[-20:]:   # Last 20 trades
                qty = float(t["qty"])
                if qty > avg_qty * 8:
                    if t.get("isBuyerMaker") == False:
                        whale_buys += 1
                    else:
                        whale_sells += 1

            if whale_buys >= 2:
                signal = "accumulation"
                log.info(f"WHALE BUY  {symbol}  {whale_buys} large buys detected")
            elif whale_sells >= 2:
                signal = "distribution"
                log.info(f"WHALE SELL  {symbol}  {whale_sells} large sells detected")
            else:
                signal = "neutral"

            return {
                "signal":      signal,
                "whale_buys":  whale_buys,
                "whale_sells": whale_sells,
                "avg_qty":     round(avg_qty, 4),
            }

        except Exception as e:
            log.debug(f"Large trade check failed {symbol}: {e}")
            return {"signal": "neutral"}

    def get_whale_signal(self, symbol: str) -> str:
        """
        Combined whale signal for a symbol.
        Returns: 'accumulation', 'distribution', 'neutral'
        """
        try:
            # Order book analysis
            ob  = self.analyze_order_book(symbol)
            lt  = self.get_large_trade_signal(symbol)

            ob_signal = ob.get("signal", "neutral")
            lt_signal = lt.get("signal", "neutral")

            # Both agree = strong signal
            if ob_signal == "accumulation" and lt_signal == "accumulation":
                return "accumulation"
            elif ob_signal == "distribution" and lt_signal == "distribution":
                return "distribution"
            elif ob_signal == "accumulation" or lt_signal == "accumulation":
                return "accumulation"
            elif ob_signal == "distribution" or lt_signal == "distribution":
                return "distribution"
            else:
                return "neutral"

        except Exception:
            return "neutral"

    def get_all_signals(self) -> dict:
        return self.whale_signals
