"""
core/scanner.py
SHAHKAR Full-Board Async Scanner
Scans ALL 300-400 pairs in 3-5 seconds using AsyncClient + asyncio.
Catches rank #222 gems that 24h filters miss.
"""
import asyncio
import time
import numpy as np
from binance import AsyncClient
import config
from utils.logger import log


class Scanner:
    def __init__(self, async_client: AsyncClient):
        self.client = async_client
        self.pairs  = []

    # ── Step 1: Get all tradeable pairs ──────────────────────

    async def get_tradeable_pairs(self) -> list[str]:
        """
        One API call to get all USDT pairs.
        Filter: active, no leverage tokens, min volume, min recent trade activity.
        """
        try:
            tickers = await self.client.get_ticker()
            pairs   = []
            for t in tickers:
                sym = t.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                base = sym.replace("USDT", "")
                if any(kw in base for kw in config.BLACKLIST_KEYWORDS):
                    continue
                try:
                    vol = float(t.get("quoteVolume", 0))
                    trade_count = int(t.get("count", 0))
                except (ValueError, TypeError):
                    continue
                if vol < config.MIN_VOLUME_USDT:
                    continue
                # Recent-activity check: high 24h volume but very few trades
                # usually means a handful of large orders, not genuine ongoing
                # trading — the coin can sit flat for long stretches.
                if trade_count < config.MIN_TRADE_COUNT_24H:
                    continue
                pairs.append(sym)
            self.pairs = pairs
            log.info(f"SCANNER  {len(pairs)} tradeable pairs found")
            return pairs
        except Exception as e:
            log.error(f"get_tradeable_pairs failed: {e}")
            return []

    # ── Step 2: Async full-board scan ────────────────────────

    async def scan_full_board_async(self) -> list[dict]:
        """
        Fetch 5m klines for ALL pairs simultaneously.
        Uses Semaphore(15) to avoid Binance rate limits.
        400 pairs in ~3-5 seconds.
        """
        if not self.pairs:
            await self.get_tradeable_pairs()

        semaphore = asyncio.Semaphore(config.ASYNC_SEMAPHORE_LIMIT)

        async def fetch_one(symbol: str):
            async with semaphore:
                try:
                    klines = await self.client.get_klines(
                        symbol=symbol, interval="5m", limit=100
                    )
                    return symbol, klines
                except Exception:
                    return symbol, None

        log.info(f"SCANNER  Async scanning {len(self.pairs)} pairs...")
        t0      = time.time()
        tasks   = [fetch_one(s) for s in self.pairs]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - t0
        log.info(f"SCANNER  Fetched {len(self.pairs)} pairs in {elapsed:.1f}s")

        # Step 3: Immediate spike filter
        candidates = []
        for symbol, klines in results:
            if klines is None or len(klines) < 25:
                continue
            spike = self._calculate_initial_5m_spike(symbol, klines)
            if spike:
                candidates.append(spike)

        log.info(f"SCANNER  {len(candidates)} candidates passed spike filter")
        return candidates

    # ── Step 3: Quick spike check ─────────────────────────────

    def _calculate_initial_5m_spike(self, symbol: str, klines: list) -> dict | None:
        """
        Fast check — discard 90% of pairs immediately.
        Only pass coins showing real 5m movement.
        """
        try:
            closes  = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            opens   = [float(k[1]) for k in klines]

            # Last candle
            last_close  = closes[-1]
            last_open   = opens[-1]
            last_vol    = volumes[-1]

            # Average volume of last 20 candles (excluding last)
            avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else float(np.mean(volumes[:-1]))
            if avg_vol == 0:
                return None

            vol_ratio    = last_vol / avg_vol
            candle_chg   = (last_close - last_open) / last_open * 100 if last_open > 0 else 0

            # 3-candle momentum
            price_3ago   = closes[-4] if len(closes) >= 4 else closes[0]
            momentum_3   = (last_close - price_3ago) / price_3ago * 100 if price_3ago > 0 else 0

            # 24h change from first candle
            price_start  = closes[0]
            change_24h   = (last_close - price_start) / price_start * 100 if price_start > 0 else 0

            # Filter: must show some activity
            if vol_ratio < 1.5 and abs(candle_chg) < 1.0:
                return None

            return {
                "symbol":      symbol,
                "price":       last_close,
                "candle_chg":  round(candle_chg, 3),
                "vol_ratio":   round(vol_ratio, 2),
                "momentum_3":  round(momentum_3, 3),
                "change":      round(change_24h, 2),
                "volume":      round(last_vol * last_close, 0),
                "avg_vol":     avg_vol,
                "klines":      klines,   # Pass for full scoring
            }
        except Exception:
            return None

    # ── Step 4: Enrich with order book (only top scorers) ────

    async def enrich_candidate(self, symbol: str) -> dict:
        """
        Fetch order book ONLY for pairs that passed 63+ score.
        Saves ~380 unnecessary API calls per cycle.
        """
        try:
            book = await self.client.get_order_book(symbol=symbol, limit=20)
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if not bids or not asks:
                return {"signal": "neutral", "buy_pressure": 50.0, "score_bonus": 0}

            bid_vol = sum(float(b[0]) * float(b[1]) for b in bids[:10])
            ask_vol = sum(float(a[0]) * float(a[1]) for a in asks[:10])
            total   = bid_vol + ask_vol
            if total == 0:
                return {"signal": "neutral", "buy_pressure": 50.0, "score_bonus": 0}

            buy_pct  = bid_vol / total * 100
            imbalance = (buy_pct - 50) / 50   # -1 to +1

            # Spread check
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread   = (best_ask - best_bid) / best_bid * 100
            if spread > 2.5:
                return {"signal": "skip", "reason": f"spread {spread:.2f}%", "score_bonus": 0}
            signal = "bullish" if buy_pct >= 60 else "bearish" if buy_pct <= 40 else "neutral"
            bonus  = round(imbalance * 10, 1)   # Max ±10

            return {
                "signal":       signal,
                "buy_pressure": round(buy_pct, 1),
                "spread":       round(spread, 3),
                "score_bonus":  bonus,
            }
        except Exception:
            return {"signal": "neutral", "buy_pressure": 50.0, "score_bonus": 0}

    # ── Gem detector ──────────────────────────────────────────

    def find_decoupled_gems(self, candidates: list[dict], btc_change: float) -> set[str]:
        """
        Coins going UP while BTC is flat/down.
        These are the real 20-40% pumpers.
        """
        gems = set()
        for c in candidates:
            coin_chg = c.get("change", 0)
            edge     = coin_chg - btc_change
            # BTC flat/down + coin significantly up
            # Must have ACTUAL upward movement — flat coins (dead) excluded
            if btc_change <= 1.0 and coin_chg >= 3.0 and edge >= 2.0:
                gems.add(c["symbol"])
            elif btc_change < -1.0 and coin_chg >= 1.5:
                gems.add(c["symbol"])
        if gems:
            log.info(f"GEMS  {len(gems)} decoupled: {list(gems)[:8]}")
        return gems
