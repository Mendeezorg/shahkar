"""
dashboard_app.py — SHAHKAR Dashboard
News seedha fetch karta hai — Redis ki zaroorat nahi!
"""
import os, sys, time, threading, json, requests
import xml.etree.ElementTree as ET
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template
from flask_socketio import SocketIO
from utils.state import state

app = Flask(__name__,
    template_folder="dashboard/templates",
    static_folder="dashboard/static"
)
app.config["SECRET_KEY"] = "shahkar_dashboard"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Live news cache ───────────────────────────────────────────
_news_cache = []
_news_lock  = threading.Lock()

NEWS_SOURCES = [
    {"name": "CryptoPanic",   "url": "https://cryptopanic.com/api/v1/posts/?auth_token=public&kind=news", "type": "api"},
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",                  "type": "rss"},
    {"name": "Bitcoin Mag",   "url": "https://bitcoinmagazine.com/feed",                                 "type": "rss"},
    {"name": "Decrypt",       "url": "https://decrypt.co/feed",                                         "type": "rss"},
    {"name": "Google BTC",    "url": "https://news.google.com/rss/search?q=bitcoin+crypto&hl=en-US&gl=US&ceid=US:en", "type": "rss"},
    {"name": "Google ETF",    "url": "https://news.google.com/rss/search?q=bitcoin+ETF+approved&hl=en-US&gl=US&ceid=US:en", "type": "rss"},
    {"name": "Reddit Crypto", "url": "https://www.reddit.com/r/CryptoCurrency/hot.rss?limit=10",        "type": "rss"},
]

def fetch_news():
    global _news_cache
    articles = []
    headers  = {"User-Agent": "Mozilla/5.0 SHAHKAR-Bot/1.0"}

    for src in NEWS_SOURCES:
        try:
            r = requests.get(src["url"], headers=headers, timeout=8)
            if r.status_code != 200:
                continue

            if src["type"] == "api":
                data = r.json()
                for p in data.get("results", [])[:8]:
                    articles.append({
                        "title":   p.get("title", ""),
                        "source":  src["name"],
                        "time":    p.get("published_at", datetime.utcnow().isoformat()),
                        "link":    p.get("url", ""),
                        "sentiment": "neutral",
                        "action":    "NORMAL",
                        "score":     0,
                    })
            else:
                import re
                root = ET.fromstring(r.content)
                for item in list(root.iter("item"))[:8]:
                    title = item.findtext("title", "")
                    pub   = item.findtext("pubDate", "")
                    link  = item.findtext("link", "")
                    if title:
                        articles.append({
                            "title":     title.strip()[:150],
                            "source":    src["name"],
                            "time":      pub[:25] if pub else datetime.utcnow().isoformat(),
                            "link":      link,
                            "sentiment": "neutral",
                            "action":    "NORMAL",
                            "score":     0,
                        })
        except Exception:
            continue

    with _news_lock:
        _news_cache = articles[:30]

def get_btc():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=5)
        if r.status_code == 200:
            d = r.json()
            return {
                "price":      float(d["lastPrice"]),
                "change_24h": float(d["priceChangePercent"]),
                "ok": True
            }
    except Exception:
        pass
    return {"price": 0, "change_24h": 0, "ok": False}

def get_dashboard_data():
    # Try Redis first
    redis_data = state.get_all_dashboard_data()

    # BTC always live
    btc = get_btc()

    # News from cache
    with _news_lock:
        news_list = list(_news_cache)

    analyzed = []
    for a in news_list[:15]:
        analyzed.append({
            "sentiment": a.get("sentiment", "neutral"),
            "score":     a.get("score", 0),
            "action":    a.get("action", "NORMAL"),
            "urgent":    False,
            "reason":    "",
            "article":   a,
        })

    return {
        "btc":         btc,
        "open_trades": redis_data.get("trades", {}).values() if isinstance(redis_data.get("trades"), dict) else [],
        "history":     redis_data.get("history", []),
        "protection":  redis_data.get("protection", {}),
        "weights":     redis_data.get("weights", {}),
        "logs":        redis_data.get("logs", []),
        "news": {
            "articles":    news_list[:15],
            "analyzed":    analyzed,
            "market_mood": redis_data.get("news", {}).get("market_mood", {"mood": "neutral", "score": 0}),
            "urgent":      [],
            "score_boost": 0,
        },
        "stats": redis_data.get("stats", {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "total_pnl": 0, "open_count": 0,
            "daily_loss": 0, "halted": False, "news_mood": "neutral",
        }),
        "timestamp": datetime.utcnow().strftime("%H:%M:%S UTC"),
    }

def news_refresh_loop():
    while True:
        try:
            fetch_news()
        except Exception:
            pass
        time.sleep(120)

def push_loop():
    while True:
        try:
            socketio.emit("update", get_dashboard_data())
        except Exception:
            pass
        time.sleep(5)

@app.route("/")
def index():
    return render_template("dashboard.html")

@socketio.on("connect")
def on_connect():
    socketio.emit("update", get_dashboard_data())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Fetch news immediately
    threading.Thread(target=fetch_news, daemon=True).start()
    # Start loops
    threading.Thread(target=news_refresh_loop, daemon=True).start()
    threading.Thread(target=push_loop, daemon=True).start()
    print(f"\nSHAHKAR Dashboard → http://0.0.0.0:{port}\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
