"""
news/engine.py
7 reliable free news sources only.
No Nitter (unstable). No paid sources.
"""
import threading, time, json, os
from datetime import datetime
from news.fetcher     import NewsFetcher
from news.ai_analyzer import AINewsAnalyzer
from utils.logger     import log
import config

NEWS_STATE_FILE = "logs/news_state.json"

# 7 reliable free sources only
RELIABLE_SOURCES = [
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",                  "type": "rss"},
    {"name": "Decrypt",       "url": "https://decrypt.co/feed",                                          "type": "rss"},
    {"name": "CryptoSlate",   "url": "https://cryptoslate.com/feed/",                                    "type": "rss"},
    {"name": "Bitcoin Mag",   "url": "https://bitcoinmagazine.com/feed",                                 "type": "rss"},
    {"name": "CryptoPanic",   "url": "https://cryptopanic.com/api/v1/posts/?auth_token=public&kind=news","type": "api"},
    {"name": "Reddit Crypto", "url": "https://www.reddit.com/r/CryptoCurrency/hot.rss?limit=10",         "type": "rss"},
    {"name": "Reddit Bitcoin","url": "https://www.reddit.com/r/Bitcoin/hot.rss?limit=10",                "type": "rss"},
]


class NewsEngine:
    def __init__(self):
        self.fetcher        = NewsFetcher(sources=RELIABLE_SOURCES)
        self.analyzer       = AINewsAnalyzer()
        self.analyzed       = []
        self.market_mood    = {"mood": "neutral", "score": 0}
        self.urgent_actions = []
        self._lock          = threading.Lock()
        self._running       = False
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(NEWS_STATE_FILE):
                with open(NEWS_STATE_FILE) as f:
                    s = json.load(f)
                    self.analyzed    = s.get("analyzed", [])[-50:]
                    self.market_mood = s.get("market_mood", {"mood":"neutral","score":0})
        except Exception:
            pass

    def _save_state(self):
        os.makedirs("logs", exist_ok=True)
        try:
            with open(NEWS_STATE_FILE, "w") as f:
                json.dump({"analyzed": self.analyzed[-50:], "market_mood": self.market_mood,
                           "updated": datetime.utcnow().isoformat()}, f, indent=2)
        except Exception:
            pass

    def _fetch_and_analyze(self):
        new_articles = self.fetcher.fetch_all()
        if not new_articles:
            return
        log.info(f"NEWS  analyzing {len(new_articles)} articles...")
        new_analyzed = self.analyzer.analyze_batch(new_articles, delay=2.0)
        with self._lock:
            self.analyzed       = new_analyzed + self.analyzed
            self.analyzed       = self.analyzed[:50]
            self.market_mood    = self.analyzer.get_market_sentiment(self.analyzed[:20])
            # Only block on severe score
            self.urgent_actions = [
                a for a in self.analyzer.get_urgent_actions(new_analyzed)
                if a.get("action") in ["CLOSE_ALL", "BLOCK_ALL"] and a.get("score", 0) <= -70
            ]
        self._save_state()

    def _run_loop(self):
        log.info("NEWS ENGINE started")
        while self._running:
            try:
                self._fetch_and_analyze()
            except Exception as e:
                log.error(f"News loop error: {e}")
            time.sleep(config.NEWS_FETCH_INTERVAL)

    def start(self):
        self._running = True
        threading.Thread(target=self._run_loop, daemon=True).start()
        threading.Thread(target=self._fetch_and_analyze, daemon=True).start()

    def stop(self):
        self._running = False

    def should_block_entry(self, symbol: str = None) -> tuple[bool, str]:
        with self._lock:
            for a in self.urgent_actions:
                if a["action"] == "CLOSE_ALL":
                    return True, f"CRITICAL: {a.get('reason','')}"
                if a["action"] == "BLOCK_ALL":
                    return True, f"BLOCK: {a.get('reason','')}"
                if a["action"] == "AVOID_COIN" and symbol:
                    base = symbol.replace("USDT", "")
                    if base in a.get("coins", []):
                        return True, f"COIN NEWS: {a.get('reason','')}"
        return False, "ok"

    def should_close_all(self) -> tuple[bool, str]:
        with self._lock:
            for a in self.urgent_actions:
                if a["action"] == "CLOSE_ALL" and a.get("score", 0) <= -85:
                    return True, a.get("reason", "critical")
        return False, "ok"

    def get_score_boost(self) -> float:
        mood  = self.market_mood.get("mood", "neutral")
        score = self.market_mood.get("score", 0)
        if mood == "bullish":  return min(8.0, score * 0.08)
        if mood == "bearish":  return max(-8.0, score * 0.08)
        return 0.0

    def get_dashboard_data(self) -> dict:
        with self._lock:
            return {
                "analyzed":       self.analyzed[:15],
                "market_mood":    self.market_mood,
                "urgent_actions": self.urgent_actions,
                "score_boost":    self.get_score_boost(),
            }
