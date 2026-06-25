"""
core/trade_manager.py
Trade manager with Redis persistence.
Trades survive Railway restarts/redeploys.
"""
import json, os, time
from datetime import datetime
import config
from utils.logger import log

HISTORY_FILE = "logs/trade_history.json"


class TradeManager:
    def __init__(self, exchange, guard):
        self.ex      = exchange
        self.guard   = guard
        # Load from Redis — survive restarts
        from utils.state import state
        self.state   = state
        self.trades  = self.state.get("open_trades") or {}
        self.pending = self.state.get("pending_entries") or {}
        log.info(f"TRADE MANAGER  loaded {len(self.trades)} open trades from Redis")

    def _save_trades(self):
        self.state.set("open_trades", self.trades, expiry=86400)

    def _save_pending(self):
        self.state.set("pending_entries", self.pending, expiry=3600)

    def _save_history(self, trade: dict):
        history = self.state.get("trade_history") or []
        history.append(trade)
        history = history[-200:]  # Keep last 200
        self.state.set("trade_history", history, expiry=2592000)  # 30 days
        # Also save to file as backup
        try:
            os.makedirs("logs", exist_ok=True)
            with open(HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2, default=str)
        except Exception:
            pass

    # ── Pullback pending entries ──────────────────────────────

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
        log.info(f"PENDING ENTRY  {symbol}  wait_price={pullback_price}  expires=5min")

    async def check_pending_entries(self, current_prices: dict):
        now     = time.time()
        expired = []
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

    # ── Open trade ────────────────────────────────────────────

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
        if price == 0:
            return False

        self.trades[symbol] = {
            "symbol":         symbol,
            "entry_price":    price,
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
        }
        self._save_trades()
        log.info(f"ENTRY  {symbol}  price={price}  qty={qty:.6f}  score={score}  gem={is_gem}")
        return True

    # ── Monitor trades ────────────────────────────────────────

    async def monitor_trades(self):
        for symbol in list(self.trades.keys()):
            try:
                t = self.trades[symbol]
                ticker = await self.ex.client.get_symbol_ticker(symbol=symbol)
                current_price = float(ticker["price"])

                if current_price > t["highest_price"]:
                    t["highest_price"] = current_price
                    self._save_trades()

                pnl_pct = (current_price - t["entry_price"]) / t["entry_price"] * 100

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

                log.info(f"MONITOR  {symbol}  {pnl_pct:+.2f}%  price={current_price}")

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
        await self.ex.sell_market(symbol, qty)
        pnl     = (price - t["entry_price"]) * qty
        pnl_pct = (price - t["entry_price"]) / t["entry_price"] * 100
        closed  = {**t, "exit_price": price, "exit_time": datetime.utcnow().isoformat(),
                   "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 2),
                   "reason": reason, "win": pnl > 0}
        self._save_history(closed)
        del self.trades[symbol]
        self._save_trades()
        if pnl < 0:
            self.guard.record_loss(abs(pnl))
            log.warning(f"EXIT LOSS   {symbol}  ${pnl:.3f} ({pnl_pct:.2f}%)  {reason}")
        else:
            log.info(f"EXIT PROFIT {symbol}  +${pnl:.3f} (+{pnl_pct:.2f}%)  {reason}")

    def open_count(self) -> int:
        return len(self.trades)

    def is_open(self, symbol: str) -> bool:
        return symbol in self.trades

    def is_pending(self, symbol: str) -> bool:
        return symbol in self.pending
