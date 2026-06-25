"""
dashboard_app.py — SHAHKAR Dashboard for Railway
Reads PORT from environment variable (Railway sets this automatically)
"""
import os, sys, time, threading, json, requests
import xml.etree.ElementTree as ET
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template
from flask_socketio import SocketIO
from utils.state import state
from utils.logger import log

app = Flask(__name__,
    template_folder="dashboard/templates",
    static_folder="dashboard/static"
)
app.config["SECRET_KEY"] = "shahkar_dashboard"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

NEWS_SOURCES = [
    {"name": "CryptoPanic", "url": "https://cryptopanic.com/api/v1/posts/?auth_token=public&kind=news", "type": "api"},
    {"name": "CoinDesk",    "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "type": "rss"},
    {"name": "Decrypt",     "url": "https://decrypt.co/feed", "type": "rss"},
    {"name": "Reddit",      "url": "https://www.reddit.com/r/CryptoCurrency/hot.rss?limit=10", "type": "rss"},
]

_news_cache = []
_news_lock  = threading.Lock()


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
                for p in r.json().get("results", [])[:8]:
                    if p.get("title"):
                        articles.append({
                            "title":     p.get("title", "")[:150],
                            "source":    src["name"],
                            "time":      p.get("published_at", "")[:19],
                            "sentiment": "neutral",
                            "action":    "NORMAL",
                        })
            else:
                import re
                root = ET.fromstring(r.content)
                for item in list(root.iter("item"))[:8]:
                    title = item.findtext("title", "")
                    if title:
                        articles.append({
                            "title":     title.strip()[:150],
                            "source":    src["name"],
                            "time":      item.findtext("pubDate", "")[:19],
                            "sentiment": "neutral",
                            "action":    "NORMAL",
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
    redis_data = state.get_all_dashboard_data()
    btc        = get_btc()

    with _news_lock:
        news_list = list(_news_cache)

    news_state = redis_data.get("news", {})
    analyzed   = news_state.get("analyzed", []) if isinstance(news_state, dict) else []

    if not analyzed:
        analyzed = [{"sentiment": "neutral", "score": 0, "action": "NORMAL",
                     "urgent": False, "reason": "", "article": a} for a in news_list[:15]]

    stats = redis_data.get("stats", {})
    if not stats:
        stats = {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "total_pnl": 0, "open_count": 0,
            "daily_loss": 0, "halted": False, "news_mood": "neutral",
            "mode": "PAPER", "drawdown": 0,
        }

    trades = redis_data.get("trades", {})
    open_trades = list(trades.values()) if isinstance(trades, dict) else []

    return {
        "btc":         btc,
        "open_trades": open_trades,
        "history":     redis_data.get("history", []),
        "protection":  redis_data.get("protection", {}),
        "weights":     redis_data.get("weights", {}),
        "logs":        redis_data.get("logs", []),
        "news": {
            "articles":    news_list[:15],
            "analyzed":    analyzed,
            "market_mood": news_state.get("market_mood", {"mood": "neutral", "score": 0}) if isinstance(news_state, dict) else {"mood": "neutral", "score": 0},
            "urgent":      [],
            "score_boost": 0,
        },
        "stats":       stats,
        "timestamp":   datetime.utcnow().strftime("%H:%M:%S UTC"),
    }


def news_loop():
    while True:
        try:
            fetch_news()
        except Exception:
            pass
        time.sleep(180)


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


@app.route("/health")
def health():
    return {"status": "ok", "service": "SHAHKAR Dashboard"}


@socketio.on("connect")
def on_connect():
    socketio.emit("update", get_dashboard_data())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    threading.Thread(target=fetch_news, daemon=True).start()
    threading.Thread(target=news_loop,  daemon=True).start()
    threading.Thread(target=push_loop,  daemon=True).start()

    log.info(f"SHAHKAR Dashboard starting on port {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False,
                 allow_unsafe_werkzeug=True)
