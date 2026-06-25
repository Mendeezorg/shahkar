"""
dashboard/server.py
SHAHKAR Web Dashboard — Live BTC price + all data
"""
import json, os, sys, time, threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template
from flask_socketio import SocketIO

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "shahkar_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

OPEN_TRADES_FILE = "logs/open_trades.json"
HISTORY_FILE     = "logs/trade_history.json"
LOG_FILE         = "logs/shahkar.log"
PROTECTION_FILE  = "logs/protection_state.json"
WEIGHTS_FILE     = "logs/learned_weights.json"
NEWS_STATE_FILE  = "logs/news_state.json"
NEWS_CACHE_FILE  = "logs/news_cache.json"
AI_CACHE_FILE    = "logs/ai_analysis_cache.json"
BTC_FILE         = "logs/btc_data.json"

def read_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, encoding='utf-8', errors='replace') as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}

def read_log_tail(n=40):
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            return [l.strip() for l in lines[-n:]]
    except Exception:
        pass
    return []

def get_btc_live():
    """Try to get BTC price from Binance public API directly."""
    try:
        import requests
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",
            timeout=5
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "price":      float(d["lastPrice"]),
                "change_24h": float(d["priceChangePercent"]),
                "high":       float(d["highPrice"]),
                "low":        float(d["lowPrice"]),
                "volume":     float(d["quoteVolume"]),
                "ok":         True
            }
    except Exception:
        pass
    # Fallback to log file
    return read_json(BTC_FILE, {"price": 0, "change_24h": 0, "ok": False})

def get_dashboard_data():
    open_trades = read_json(OPEN_TRADES_FILE, {})
    history     = read_json(HISTORY_FILE, [])
    protection  = read_json(PROTECTION_FILE, {})
    weights     = read_json(WEIGHTS_FILE, {})
    news_state  = read_json(NEWS_STATE_FILE, {})
    news_cache  = read_json(NEWS_CACHE_FILE, [])
    ai_cache    = read_json(AI_CACHE_FILE, {})
    logs        = read_log_tail(40)
    btc         = get_btc_live()

    if not isinstance(history, list):     history = []
    if not isinstance(open_trades, dict): open_trades = {}
    if not isinstance(news_cache, list):  news_cache = []
    if not isinstance(ai_cache, dict):    ai_cache = {}

    # Build analyzed news from AI cache
    analyzed = []
    state_analyzed = news_state.get("analyzed", [])
    if isinstance(state_analyzed, list) and state_analyzed:
        analyzed = state_analyzed[:20]
    else:
        for title_key, result in list(ai_cache.items())[-20:]:
            if isinstance(result, dict) and result.get("article"):
                analyzed.append(result)

    market_mood = news_state.get("market_mood", {"mood": "neutral", "score": 0})
    urgent      = [a for a in analyzed if a.get("urgent") and a.get("action") not in ["NORMAL", None]]

    wins      = [t for t in history if t.get("win")]
    losses    = [t for t in history if not t.get("win")]
    total_pnl = sum(t.get("pnl", 0) for t in history)
    win_rate  = round(len(wins) / len(history) * 100, 1) if history else 0

    return {
        "open_trades": list(open_trades.values()),
        "history":     history[-20:][::-1],
        "protection":  protection,
        "weights":     weights,
        "logs":        logs,
        "btc":         btc,
        "news": {
            "articles":      news_cache[:15],
            "analyzed":      analyzed[:15],
            "market_mood":   market_mood,
            "urgent":        urgent[:5],
            "score_boost":   news_state.get("score_boost", 0),
            "total_sources": 25,
        },
        "stats": {
            "total_trades": len(history),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     win_rate,
            "total_pnl":    round(total_pnl, 2),
            "open_count":   len(open_trades),
            "daily_loss":   protection.get("daily_loss", 0),
            "halted":       protection.get("halted", False),
            "news_mood":    market_mood.get("mood", "neutral"),
            "news_count":   len(analyzed),
        },
        "timestamp": datetime.utcnow().strftime("%H:%M:%S UTC"),
    }

def background_push():
    while True:
        try:
            socketio.emit("update", get_dashboard_data())
        except Exception:
            pass
        time.sleep(3)

@app.route("/")
def index():
    return render_template("dashboard.html")

@socketio.on("connect")
def on_connect():
    socketio.emit("update", get_dashboard_data())

if __name__ == "__main__":
    threading.Thread(target=background_push, daemon=True).start()
    print("\n" + "="*50)
    print("  SHAHKAR Dashboard → http://localhost:5000")
    print("="*50 + "\n")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
