# ⚡ SHAHKAR — World-Class Crypto Trading Bot

> **Sirf Jeetna Hai — Only Winning**

SHAHKAR is a fully automated, self-learning crypto trading bot for Binance.  
Score-based entry system. Hard 2% stop loss. No emotions. No bad trades.

---

## 🏗️ Architecture — 8 Layers

| Layer | System | What it does |
|-------|--------|--------------|
| L1 | Core Engine | BTC Intelligence, 400+ pair scanner, whale tracker |
| L2 | Entry System | 6-indicator scorer, time filter, volume spike, RR calculator |
| L3 | Protection | Hard SL, daily loss limit, crash detector, whipsaw shield, news blocker |
| L4 | Exit System | Partial exit at +3%, trailing stop on 70%, whale dump exit |
| L5 | Market Intelligence | Alt season, cross-exchange arb, order flow, correlation matrix |
| L6 | Advanced AI | Sentiment analysis, on-chain data, ML pattern matching, time patterns |
| L7 | Self Learning | Trade memory, win pattern recognition, weight auto-adjustment |
| L8 | Dashboard | Unified visual command center |

---

## ⚙️ Core Rules (never broken)

- ✅ Score **85+** required to enter — no exceptions
- ✅ Stop loss **−2% hard** — never moved down
- ✅ Risk/Reward minimum **5:1**
- ✅ Volume spike **3x+** required
- ✅ Max **3 trades** simultaneously
- ✅ Daily loss limit **$30** — auto halt if hit
- ✅ All 6 indicators must confirm
- ✅ News time blocked (±30 min around major events)
- ✅ Low probability hours blocked

---

## 🚀 Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/shahkar.git
cd shahkar
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up your API keys
```bash
cp .env.example .env
# Now edit .env and add your Binance API key and secret
```

### 4. Run in Paper Mode first (fake money — safe to test)
```bash
python shahkar.py
```

### 5. Switch to Live when ready
Edit `.env`:
```
MODE=live
```

---

## 🔑 Binance API Setup

1. Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Create a new API key
3. Enable: **Read Info** + **Spot Trading**
4. Disable: Withdrawals (never needed)
5. Whitelist your IP for safety
6. Copy key + secret into `.env`

---

## 📁 Project Structure

```
shahkar/
├── shahkar.py              ← Main bot — run this
├── config.py               ← All settings (loaded from .env)
├── requirements.txt
├── .env.example            ← Copy to .env and fill in keys
├── .gitignore
│
├── core/
│   ├── exchange.py         ← Binance connection + order execution
│   ├── scanner.py          ← 400+ pair scanner + decoupled coin detector
│   ├── indicators.py       ← RSI, MACD, volume spike, momentum
│   ├── scorer.py           ← Score engine (0-100)
│   └── trade_manager.py    ← Open/monitor/close trades
│
├── protection/
│   └── guard.py            ← SL engine, daily limit, crash detector, whipsaw
│
├── intelligence/
│   ├── btc_intel.py        ← BTC trend + mode detection
│   └── memory.py           ← Self-learning, weight adjustment
│
├── utils/
│   └── logger.py           ← Color-coded terminal + file logging
│
└── logs/                   ← Auto-created (gitignored)
    ├── shahkar.log
    ├── open_trades.json
    ├── trade_history.json
    └── learned_weights.json
```

---

## ⚙️ Configuration

All settings in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | — | Your Binance API key |
| `BINANCE_API_SECRET` | — | Your Binance secret |
| `MODE` | `paper` | `paper` or `live` |
| `CAPITAL_PER_TRADE` | `5.0` | $ per trade |
| `MAX_OPEN_TRADES` | `3` | Max simultaneous trades |
| `MIN_SCORE` | `85` | Entry score threshold |
| `DAILY_LOSS_LIMIT` | `30.0` | $ daily halt limit |

---

## 📊 Scoring System

Each of 6 indicators contributes points. Max = 100. Need 85+ to trade.

| Indicator | Max Points | Pass Condition |
|-----------|-----------|----------------|
| Whale Accumulation | 18.8 | Large wallet buying |
| Volume Spike | 17.2 | 3x+ average volume |
| ML Pattern Match | 14.0 | Known winning setup |
| MACD Cross | 12.4 | Bullish crossover |
| BTC Trend Align | 11.1 | BTC up or decoupled |
| RSI Zone | 9.8 | RSI between 40–60 |
| Momentum | 8.0 | Price rising |

---

## 🛡️ Protection System

- **Hard SL −2%** — triggers automatically, no override possible
- **Daily loss limit** — at 50% → reduce size; at 100% → full halt
- **Crash detector** — monitors BTC 5m and 1h drops, closes all on crash
- **Whipsaw shield** — detects fake breakouts, blocks entry
- **News blocker** — blocks ±30min around Fed, CPI, SEC events
- **Time filter** — only trades during high-probability UTC hours

---

## 📈 Exit System

1. **Partial exit**: sell 30% at +3% profit
2. **Move SL to breakeven** after partial exit
3. **Trailing stop** on remaining 70% (follows price up)
4. **Full exit** at target +10%
5. **Emergency exit** on whale dump or sentiment reversal

---

## 🧬 Self-Learning

After every 10 cycles, SHAHKAR:
- Reads all past trades
- Boosts weights of indicators that appeared in winning trades
- Reduces weights of indicators that appeared in losing trades
- Saves updated weights to `logs/learned_weights.json`
- Applies new weights immediately to next cycle

---

## ⚠️ Disclaimer

This bot trades real money when `MODE=live`.  
Always start with `MODE=paper` and test for at least 1–2 weeks.  
Past performance does not guarantee future results.  
You are responsible for your own funds. Trade safely.

---

## 📝 License

MIT License — free to use, modify, and distribute.

---

**SHAHKAR — Sirf Jeetna Hai** ⚡
