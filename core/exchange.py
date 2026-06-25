"""
core/exchange.py
Async Binance client wrapper.
Uses AsyncClient for the async scanner.
"""
import config
from binance import AsyncClient
from binance.exceptions import BinanceAPIException
from utils.logger import log


async def get_async_client() -> AsyncClient:
    if not config.API_KEY or config.API_KEY == "your_api_key_here":
        log.warning("No API keys — public data mode")
        return await AsyncClient.create("", "")
    client = await AsyncClient.create(config.API_KEY, config.API_SECRET)
    log.info(f"Binance AsyncClient connected — MODE: {config.MODE.upper()}")
    return client


class Exchange:
    def __init__(self, async_client: AsyncClient):
        self.client = async_client
        self.mode   = config.MODE

    async def buy_market(self, symbol: str, usdt_amount: float) -> dict | None:
        if self.mode == "paper":
            try:
                ticker = await self.client.get_symbol_ticker(symbol=symbol)
                price  = float(ticker["price"])
                qty    = round(usdt_amount / price, 6)
                log.info(f"[PAPER] BUY  {symbol}  qty={qty}  price={price}")
                return {"symbol": symbol, "qty": qty, "price": price, "mode": "paper"}
            except Exception as e:
                log.error(f"Paper buy failed {symbol}: {e}")
                return None
        try:
            order = await self.client.order_market_buy(
                symbol=symbol, quoteOrderQty=usdt_amount
            )
            price = float(order["fills"][0]["price"]) if order.get("fills") else 0
            qty   = float(order.get("executedQty", 0))
            log.info(f"[LIVE] BUY  {symbol}  ${usdt_amount:.2f}  id={order['orderId']}")
            return {"symbol": symbol, "qty": qty, "price": price, "mode": "live", "order": order}
        except BinanceAPIException as e:
            log.error(f"Buy failed {symbol}: {e}")
            return None

    async def sell_market(self, symbol: str, qty: float) -> dict | None:
        if self.mode == "paper":
            try:
                ticker = await self.client.get_symbol_ticker(symbol=symbol)
                price  = float(ticker["price"])
                log.info(f"[PAPER] SELL {symbol}  qty={qty}  price={price}")
                return {"symbol": symbol, "qty": qty, "price": price, "mode": "paper"}
            except Exception as e:
                log.error(f"Paper sell failed {symbol}: {e}")
                return None
        try:
            order = await self.client.order_market_sell(symbol=symbol, quantity=qty)
            log.info(f"[LIVE] SELL {symbol}  qty={qty}  id={order['orderId']}")
            return order
        except BinanceAPIException as e:
            log.error(f"Sell failed {symbol}: {e}")
            return None

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100):
        return await self.client.get_klines(symbol=symbol, interval=interval, limit=limit)

    async def get_orderbook(self, symbol: str, limit: int = 20):
        return await self.client.get_order_book(symbol=symbol, limit=limit)

    async def get_balance(self, asset: str = "USDT") -> float:
        try:
            account = await self.client.get_account()
            for b in account["balances"]:
                if b["asset"] == asset:
                    return float(b["free"])
        except Exception as e:
            log.error(f"Balance fetch failed: {e}")
        return 0.0
