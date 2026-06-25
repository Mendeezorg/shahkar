"""
shahkar.py — SHAHKAR v22 — Full Async Main Loop
Async scanner scans 400 pairs in 3-5 seconds.
Pullback entry, gem crash exemption, hard time block.
"""
import asyncio, sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from binance import AsyncClient
from core.exchange           import Exchange, get_async_client
from core.scanner            import Scanner
from core.scorer             import ScoreEngine
from core.trade_manager      import TradeManager
from protection.guard        import ProtectionGuard
from protection.risk_manager import RiskManager
from intelligence.btc_intel  import BTCIntelligence
from intelligence.memory     import MemoryEngine
from intelligence.whale_onchain   import UltimateWhaleTracker
from intelligence.institutional   import InstitutionalIntelligence
from news.engine             import NewsEngine
from utils.logger            import log
from utils.state             import state

BANNER = """
╔══════════════════════════════════════════════╗
║   SHAHKAR v22  —  Sirf Jeetna Hai           ║
║   Async Full-Board Scanner (400 pairs/5s)   ║
║   Pullback Entry | Gem Crash Exempt         ║
╚══════════════════════════════════════════════╝
"""


async def push_state(btc, guard, tm, memory, news_engine, risk, inst):
    try:
        state.update_btc(btc)
        state.update_stats({
            "total_trades":  memory.total_trades(),
            "win_rate":      memory.win_rate(),
            "total_pnl":     round(sum(t.get("pnl", 0) for t in memory.history), 2),
            "open_count":    tm.open_count(),
            "daily_loss":    guard.daily_loss_used(),
            "halted":        guard.is_halted(),
            "news_mood":     news_engine.market_mood.get("mood", "neutral"),
            "mode":          config.MODE.upper(),
            "drawdown":      risk.get_drawdown(),
            "inst_signal":   inst.data.get("signal", "neutral"),
            "fear_greed":    inst.data.get("fear_greed", {}).get("value", 50),
        })
        state.update_trades(tm.trades)
        nd = news_engine.get_dashboard_data()
        state.update_news({
            "analyzed":    nd.get("analyzed", [])[:15],
            "market_mood": nd.get("market_mood", {}),
            "urgent":      nd.get("urgent_actions", [])[:5],
            "score_boost": nd.get("score_boost", 0),
        })
        state.update_weights(config.INDICATOR_WEIGHTS)
        state.set("shahkar_protection", {
            "daily_loss": guard.daily_loss_used(),
            "halted":     guard.is_halted(),
        })
        state.set("shahkar_history", {"trades": memory.history[-20:][::-1]})
        try:
            if os.path.exists("logs/shahkar.log"):
                with open("logs/shahkar.log", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                state.update_logs([l.strip() for l in lines[-40:]])
        except Exception:
            pass
    except Exception as e:
        log.error(f"State push error: {e}")


async def main():
    print(BANNER)
    log.info(f"SHAHKAR v22 starting — MODE={config.MODE.upper()}")

    # ── Init async client ─────────────────────────────────────
    async_client = await get_async_client()
    exchange     = Exchange(async_client)
    scanner      = Scanner(async_client)
    scorer       = ScoreEngine()
    guard        = ProtectionGuard()
    risk         = RiskManager()
    tm           = TradeManager(exchange, guard)
    btc_ai       = BTCIntelligence(exchange)
    memory       = MemoryEngine()
    whale_chain  = UltimateWhaleTracker()
    inst         = InstitutionalIntelligence()
    news_engine  = NewsEngine()

    news_engine.start()
    inst.start_background()
    log.info("All systems operational — entering async main loop")
    log.info("-" * 55)

    cycle = 0

    try:
        while True:
            cycle += 1
            now    = datetime.utcnow()
            hour   = now.hour
            minute = now.minute

            # ── HARD time block ───────────────────────────────
            if not guard.is_trading_allowed():
                log.info(f"HARD BLOCK  {hour} UTC — sleeping 5 min")
                await asyncio.sleep(300)
                continue

            log.info(f"CYCLE {cycle} START")

            # ── Halt check ────────────────────────────────────
            if guard.is_halted():
                log.error("DAILY LIMIT HIT — sleeping 1hr")
                await asyncio.sleep(3600)
                continue

            # ── Risk check ────────────────────────────────────
            should_stop, stop_reason = risk.should_stop_trading()
            if should_stop:
                log.error(f"RISK STOP — {stop_reason}")
                await tm.monitor_trades()
                await asyncio.sleep(300)
                continue

            # ── News emergency ────────────────────────────────
            close_all, close_reason = news_engine.should_close_all()
            if close_all:
                log.error(f"NEWS EMERGENCY — {close_reason}")
                for sym in list(tm.trades.keys()):
                    await tm._close_trade(sym, 0, f"news_emergency: {close_reason}")
                await asyncio.sleep(60)
                continue

            # ── BTC Intelligence ──────────────────────────────
            btc = await btc_ai.get_btc_data()
            if not btc.get("ok"):
                await asyncio.sleep(30)
                continue

            log.info(
                f"BTC ${btc['price']:,.0f} ({btc['change_24h']:+.1f}%)  "
                f"trend={btc['trend']}  "
                f"Trades:{tm.open_count()}/3  "
                f"Loss:${guard.daily_loss_used():.2f}  "
                f"DD:{risk.get_drawdown():.1f}%"
            )

            await push_state(btc, guard, tm, memory, news_engine, risk, inst)

            # ── Monitor existing trades ───────────────────────
            await tm.monitor_trades()

            # ── Check pending pullback entries ────────────────
            try:
                tickers = await async_client.get_all_tickers()
                prices  = {t["symbol"]: float(t["price"]) for t in tickers}
                await tm.check_pending_entries(prices)
            except Exception as e:
                log.error(f"Pending entries check failed: {e}")

            # ── Entry check ───────────────────────────────────
            can_enter, reason = guard.can_enter_trade(
                hour, minute,
                btc_change_5m=btc.get("change_5m", 0),
                btc_change_1h=btc.get("change_24h", 0) / 4
            )
            if not can_enter:
                log.warning(f"ENTRY BLOCKED — {reason}")
                await asyncio.sleep(config.SCAN_INTERVAL_SEC)
                continue

            if tm.open_count() >= config.MAX_OPEN_TRADES:
                log.info("Max trades — monitoring only")
                await asyncio.sleep(config.SCAN_INTERVAL_SEC)
                continue

            # ── ASYNC FULL BOARD SCAN ─────────────────────────
            candidates   = await scanner.scan_full_board_async()
            gem_set      = scanner.find_decoupled_gems(candidates, btc["change_24h"])
            news_boost   = news_engine.get_score_boost()
            inst_bonus   = inst.get_score_bonus()
            chain_bonus  = whale_chain.get_score_bonus("BTCUSDT")

            # Priority: gems first
            priority = [c for c in candidates if c["symbol"] in gem_set]
            rest     = [c for c in candidates if c["symbol"] not in gem_set]
            sorted_candidates = priority + rest

            approved = []

            for coin in sorted_candidates:
                sym = coin["symbol"]
                if tm.is_open(sym) or tm.is_pending(sym):
                    continue

                # News block
                blocked, block_reason = news_engine.should_block_entry(sym)
                if blocked:
                    log.warning(f"NEWS BLOCK {sym} — {block_reason}")
                    continue

                is_gem = sym in gem_set

                # Quick score without order book
                result = scorer.score(
                    symbol     = sym,
                    candidate  = coin,
                    btc_trend  = btc["trend"],
                    whale_signal = "neutral",
                    is_gem     = is_gem,
                    hour_utc   = hour,
                    ob_bonus   = 0.0,
                )

                # Apply bonuses
                adjusted = result["score"] + news_boost + inst_bonus + chain_bonus
                result["score"] = max(0, min(100, int(adjusted)))

                if result["score"] < config.MIN_SCORE:
                    continue

                # ── Enrich with order book (only top scorers) ─
                ob_data = await scanner.enrich_candidate(sym)
                if ob_data.get("signal") == "skip":
                    log.info(f"SKIP {sym} — {ob_data.get('reason','spread too wide')}")
                    continue

                # Final score with order book
                final = result["score"] + ob_data.get("score_bonus", 0)
                result["score"] = max(0, min(100, int(final)))

                if result["score"] < config.MIN_SCORE:
                    continue

                # RR check
                price = coin.get("price", 0)
                if price <= 0:
                    continue
                sl  = price * (1 - config.STOP_LOSS_PCT)
                tp  = price * 1.10
                rr  = (tp - price) / (price - sl) if (price - sl) > 0 else 0
                if rr < config.MIN_RR:
                    log.info(f"SKIP {sym} — RR={rr:.1f} < {config.MIN_RR}")
                    continue

                approved.append({**result, "rr": round(rr, 1), "coin": coin})

            # Sort by score
            approved.sort(key=lambda x: x["score"], reverse=True)

            for r in approved:
                if tm.open_count() >= config.MAX_OPEN_TRADES:
                    break

                sym    = r["symbol"]
                is_gem = r["is_gem"]
                coin   = r["coin"]

                # Check if needs pullback entry
                needs_pullback, pullback_price = scorer.needs_pullback_entry(coin)

                capital = risk.calculate_position_size(
                    base_capital     = config.CAPITAL_PER_TRADE,
                    win_rate         = memory.win_rate(),
                    score            = r["score"],
                    daily_loss_used  = guard.daily_loss_used(),
                    daily_loss_limit = config.DAILY_LOSS_LIMIT,
                )

                if needs_pullback:
                    tm.add_pending_entry(sym, pullback_price, r["score"], capital, is_gem)
                else:
                    log.info(f"APPROVED {sym} score={r['score']} RR={r['rr']}:1 gem={is_gem} capital=${capital}")
                    await tm.open_trade(sym, r["score"], capital, is_gem)

            # Self-learn every 10 cycles
            if cycle % 10 == 0:
                memory.learn()

            log.info(f"Cycle {cycle} done — sleeping {config.SCAN_INTERVAL_SEC}s")
            await asyncio.sleep(config.SCAN_INTERVAL_SEC)

    except KeyboardInterrupt:
        log.info("SHAHKAR stopped")
        news_engine.stop()
        inst.stop()
        log.info(f"Final: {memory.summary()}")
    finally:
        await async_client.close_connection()


if __name__ == "__main__":
    asyncio.run(main())
