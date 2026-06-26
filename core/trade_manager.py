"""
core/trade_manager.py
Trade manager — fixed:
1. Live PnL calculated on every monitor cycle
2. Saves to both Redis (open_trades + trades keys) and file
3. trade_history saved on every close
"""
import json, os, time
from datetime import datetime
import config
from utils.logger import log

HISTORY_FILE     = "logs/trade_history.json"
OPEN_TRADES_FILE = "logs/open_trades.json"


def _save_json(path: str, data):
    try:
        os.makedirs("logs", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        log.error(f"File save failed {path}: {e}")


def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


class TradeManager:
    def __init__(self, exchange, guard):
        self.ex      = exchange
        self.guard   = guard
        from utils.state import state
        self.state   = state
        self.trades  = self.state.get("open_trades") or _load_json(OPEN_TRADES_FILE, {})
        self.pending = self.state.get("pending_entries") or {}
        log.info(f"TRADE MANAGER  loaded {len(self.trades)} open trades")

    def _save_trades(self):
        """Save to Redis (both keys) AND file."""
        self.state.set("open_trades", self.trades, expiry=86400)
        self.state.set("trades", self.trades, expiry=86400)
        _save_json(OPEN_TRADES_FILE, self.trades)

    def _save_pending(self):
        self.state.set("pending_entries", self.pending, expiry=3600)

    def _save_history(self, trade: dict):
        history = _load_json(HISTORY_FILE, [])
        if not isinstance(history, list):
            history = []
        history.append(trade)
        history = history[-200:]
        _save_json(HISTORY_FILE, history)
        self.state.set("trade_history", history, expiry=2592000)

    def add_pending_entry(self, symbol: str, pullback_price: float,
                           score: int, capital: float, is_gem: bool):
        expires = time.time() + 300
        self.pending[symbol] = {
            "symbol":         symbol,
            "pullback_price": pullback_price,
            "score":          score,
            "capital":        capital,
            "is_gem":         is_gem,
            "expires":        expires,
            "created":        datetime.utcnow().isoformat(),
        }
        self._save_pending()
        log.info(f"PENDING ENTRY  {symbol}  wait_price={pullback_price:.6f}  expires=5min")

    async def check_pending_entries(self, current_prices: dict):
        now      = time.time()
        expired  = []
        executed = []

        for sym, entry in list(self.pending.items()):
            if now > entry["expires"]:
                expired.append(sym)
                log.info(f"PENDING EXPIRED  {sym}")
                continue

            current = current_prices.get(sym, 0)
            if current <= 0:
                continue

            if current <= entry["pullback_price"]:
                log.info(f"PULLBACK HIT  {sym}  price={current}")
                success = await self.open_trade(
                    sym, entry["score"], entry["capital"], entry["is_gem"]
                )
                if success:
                    executed.append(sym)

        for sym in expired + executed:
            self.pending.pop(sym, None)
        if expired or executed:
            self._save_pending()

    async def open_trade(self, symbol: str, score: int,
                          capital: float, is_gem: bool = False) -> bool:
        if symbol in self.trades:
            return False
        if len(self.trades) >= config.MAX_OPEN_TRADES:
            log.warning(f"Max trades reached — SKIP {symbol}")
            return False

        if self.guard.should_reduce_size():
            capital *= 0.5
            log.warning(f"Reduced size to ${capital:.2f}")

        order = await self.ex.buy_market(symbol, capital)
        if not order:
            return False

        price = order.get("price", 0)
        qty   = order.get("qty", 0)
        if price == 0 or qty == 0:
            log.error(f"Bad order data for {symbol}: price={price} qty={qty}")
            return False

        self.trades[symbol] = {
            "symbol":         symbol,
            "entry_price":    price,
            "current_price":  price,
            "qty":            qty,
            "capital":        capital,
            "score":          score,
            "is_gem":         is_gem,
            "open_time":      datetime.utcnow().isoformat(),
            "highest_price":  price,
            "partial_done":   False,
            "remaining_qty":  qty,
            "stop_loss":      round(price * (1 - config.STOP_LOSS_PCT), 8),
            "target":         round(price * 1.10, 8),
            "partial_target": round(price * (1 + config.PARTIAL_EXIT_PCT), 8),
            "mode":           config.MODE,
            "pnl":            0.0,
            "pnl_pct":        0.0,
        }
        self._save_trades()
        log.info(f"ENTRY  {symbol}  price={price}  qty={qty:.6f}  score={score}  gem={is_gem}  capital=${capital:.2f}")
        return True

    async def monitor_trades(self):
        if not self.trades:
            return

        for symbol in list(self.trades.keys()):
            try:
                t = self.trades[symbol]
                ticker = await self.ex.client.get_symbol_ticker(symbol=symbol)
                current_price = float(ticker["price"])

                # Update live price AND pnl every cycle
                t["current_price"] = current_price
                pnl_pct = (current_price - t["entry_price"]) / t["entry_price"] * 100
                pnl     = (current_price - t["entry_price"]) * t["remaining_qty"]
                t["pnl"]     = round(pnl, 4)
                t["pnl_pct"] = round(pnl_pct, 2)

                if current_price > t["highest_price"]:
                    t["highest_price"] = current_price

                self._save_trades()

                if self.guard.check_stop_loss(t["entry_price"], current_price):
                    await self._close_trade(symbol, current_price, "stop_loss")
                    continue

                if t["partial_done"]:
                    if self.guard.check_trailing_stop(t["highest_price"], current_price):
                        await self._close_trade(symbol, current_price, "trailing_stop")
                        continue

                if not t["partial_done"] and current_price >= t["partial_target"]:
                    await self._partial_exit(symbol, current_price)
                    continue

                if current_price >= t["target"]:
                    await self._close_trade(symbol, current_price, "target_hit")
                    continue

                log.info(f"MONITOR  {symbol}  {pnl_pct:+.2f}%  ${pnl:+.3f}  price={current_price}")

            except Exception as e:
                log.error(f"Monitor error {symbol}: {e}")

    async def _partial_exit(self, symbol: str, price: float):
        t        = self.trades[symbol]
        sell_qty = round(t["qty"] * config.PARTIAL_EXIT_SIZE, 6)
        await self.ex.sell_market(symbol, sell_qty)
        pnl = (price - t["entry_price"]) * sell_qty
        t["partial_done"]  = True
        t["remaining_qty"] = round(t["qty"] - sell_qty, 6)
        t["stop_loss"]     = t["entry_price"]
        self._save_trades()
        log.info(f"PARTIAL EXIT  {symbol}  30% at {price}  pnl=+${pnl:.3f}")

    async def _close_trade(self, symbol: str, price: float, reason: str):
        t   = self.trades[symbol]
        qty = t["remaining_qty"]

        if price == 0:
            try:
                ticker = await self.ex.client.get_symbol_ticker(symbol=symbol)
                price  = float(ticker["price"])
            except Exception:
                price = t["entry_price"]

        await self.ex.sell_market(symbol, qty)

        pnl      = (price - t["entry_price"]) * qty
        pnl_pct  = (price - t["entry_price"]) / t["entry_price"] * 100
        duration_min = 0
        try:
            open_dt = datetime.fromisoformat(t["open_time"])
            duration_min = int((datetime.utcnow() - open_dt).total_seconds() / 60)
        except Exception:
            pass

        closed = {
            **t,
            "exit_price":   price,
            "exit_time":    datetime.utcnow().isoformat(),
            "pnl":          round(pnl, 4),
            "pnl_pct":      round(pnl_pct, 2),
            "reason":       reason,
            "win":          pnl > 0,
            "duration_min": duration_min,
        }
        self._save_history(closed)
        del self.trades[symbol]
        self._save_trades()

        if pnl < 0:
            self.guard.record_loss(abs(pnl))
            log.warning(f"EXIT LOSS   {symbol}  ${pnl:.3f} ({pnl_pct:.2f}%)  {reason}  ({duration_min}min)")
        else:
            log.info(f"EXIT PROFIT {symbol}  +${pnl:.3f} (+{pnl_pct:.2f}%)  {reason}  ({duration_min}min)")

    def open_count(self) -> int:
        return len(self.trades)

    def is_open(self, symbol: str) -> bool:
        return symbol in self.trades

    def is_pending(self, symbol: str) -> bool:
        return symbol in self.pending
