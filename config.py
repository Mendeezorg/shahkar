import os
from dotenv import load_dotenv
load_dotenv()

# ── Binance API ──────────────────────────────────────────────
API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── Mode ─────────────────────────────────────────────────────
MODE = os.getenv("MODE", "paper")

# ── Capital ──────────────────────────────────────────────────
CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", 5.0))
MAX_OPEN_TRADES   = int(os.getenv("MAX_OPEN_TRADES", 3))
AUTO_COMPOUND     = True

# ── Score & Risk ─────────────────────────────────────────────
MIN_SCORE         = int(os.getenv("MIN_SCORE", 63))
MIN_RR            = 2.8
STOP_LOSS_PCT     = 0.02
PARTIAL_EXIT_PCT  = 0.03
PARTIAL_EXIT_SIZE = 0.30
TRAILING_STOP_PCT = 0.02
DAILY_LOSS_LIMIT  = float(os.getenv("DAILY_LOSS_LIMIT", 30.0))

# ── Pump / Gem settings ───────────────────────────────────────
PUMP_PULLBACK_PCT     = 0.015   # Wait for 1.5% dip before buying pump
GEM_EXEMPT_FROM_CRASH = True    # Gems survive BTC crash
ML_PATTERN_ENABLED    = False   # Use simple pattern instead

# ── Volume ───────────────────────────────────────────────────
MIN_VOLUME_USDT   = 50_000    # Very low — catch rank #222 gems
MIN_VOLUME_SPIKE  = 2.0       # 2x average volume

# ── Scanning ─────────────────────────────────────────────────
SCAN_INTERVAL_SEC      = 90   # 90 seconds
MAX_PAIRS_TO_SCAN      = 400  # Scan all — async is fast enough
ASYNC_SEMAPHORE_LIMIT  = 15   # Concurrent connections

# ── Timing — HARD BLOCK outside these hours ──────────────────
HOT_HOURS = list(range(6, 23))   # 6-22 UTC inclusive

# ── News ─────────────────────────────────────────────────────
NEWS_FETCH_INTERVAL        = 180   # 3 minutes
GROQ_MAX_ARTICLES_PER_BATCH = 3   # Groq free tier limit

# ── External APIs ─────────────────────────────────────────────
GLASSNODE_ENABLED = False
COINGLASS_ENABLED = False
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY   = os.getenv("BSCSCAN_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")

# ── State storage ─────────────────────────────────────────────
USE_FILE_STATE  = True
STATE_FILE_PATH = "shahkar_state.json"
REDIS_URL       = os.getenv("REDIS_URL", "")

# ── Blacklist ─────────────────────────────────────────────────
BLACKLIST_KEYWORDS = [
    "UP","DOWN","BULL","BEAR","LONG","SHORT",
    "BUSD","USDC","TUSD","DAI","FDUSD","UST","USDT"
]

# ── Indicator Weights (new — max base 92) ─────────────────────
INDICATOR_WEIGHTS = {
    "whale_dark_pool":  22,
    "volume_spike":     20,
    "macd":             15,
    "rsi":              12,
    "btc_trend":        13,
    "momentum":         10,
    "simple_pattern":   10,
}
