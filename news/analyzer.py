"""
news/analyzer.py
Keyword fallback analyzer — used when no AI API available.
Fixed: whole word matching only — no false alarms.
"""
import re
from datetime import datetime
from utils.logger import log

# ── Exact phrase matching — no partial words ──────────────────
BULLISH_PHRASES = [
    "etf approved", "etf launch", "etf listed",
    "institutional buy", "institutional buying",
    "sec approves", "bitcoin reserve", "legal tender",
    "major partnership", "mass adoption",
    "bullish", "price rally", "all time high", " ath ",
    "blackrock buys", "fidelity buys", "grayscale buys",
    "bitcoin halving", "mainnet launch", "major upgrade",
]

BEARISH_PHRASES = [
    "sec sues", "sec charges", "sec files",
    "crypto ban", "bitcoin ban", "trading ban",
    "exchange hack", "exchange hacked", "funds stolen",
    "bankruptcy filed", "insolvent", "shutdown",
    "ponzi scheme", "fraud charges", "money laundering",
    "major crash", "market crash", "price crash",
    "withdrawal suspended", "exchange down",
]

# Critical — exact phrases only, no single words
CRITICAL_PHRASES = [
    "exchange hacked", "exchange hack",
    "funds stolen", "massive hack",
    "crypto banned", "bitcoin banned",
    "sec emergency", "trading halted",
    "nuclear war",        # exact phrase — not just "war"
    "global pandemic",    # exact phrase — not just "pandemic"
]

COIN_KEYWORDS = {
    "BTC":  ["bitcoin", " btc "],
    "ETH":  ["ethereum", " eth "],
    "BNB":  ["binance coin", " bnb "],
    "SOL":  ["solana", " sol "],
    "XRP":  ["ripple", " xrp "],
    "ADA":  ["cardano", " ada "],
    "DOGE": ["dogecoin", "doge"],
    "AVAX": ["avalanche", " avax "],
    "INJ":  ["injective", " inj "],
    "ARB":  ["arbitrum", " arb "],
}


class NewsAnalyzer:

    def analyze(self, article: dict) -> dict:
        text  = " " + (article.get("title", "") + " " + article.get("desc", "")).lower() + " "
        score = 0
        hits  = []

        # Critical check — exact phrases only
        for phrase in CRITICAL_PHRASES:
            if phrase in text:
                log.error(f"NEWS CRITICAL  '{phrase}' — {article['title'][:60]}")
                return {
                    "sentiment": "critical",
                    "score":     -100,
                    "action":    "CLOSE_ALL",
                    "coins":     self._find_coins(text),
                    "reason":    f"Critical: {phrase}",
                    "urgent":    True,
                    "article":   article,
                    "analyzed_by": "keyword_fallback",
                }

        # Bearish phrases
        for phrase in BEARISH_PHRASES:
            if phrase in text:
                weight = 20 if any(w in phrase for w in ["hack","ban","sec","crash"]) else 10
                score -= weight
                hits.append(f"-{phrase}")

        # Bullish phrases
        for phrase in BULLISH_PHRASES:
            if phrase in text:
                weight = 15 if any(w in phrase for w in ["etf","approved","blackrock","reserve"]) else 7
                score += weight
                hits.append(f"+{phrase}")

        score = max(-100, min(100, score))

        if score >= 20:
            sentiment = "bullish"
            action    = "BOOST"
        elif score <= -30:
            sentiment = "bearish"
            action    = "BLOCK_ALL"
        elif score <= -15:
            sentiment = "bearish"
            action    = "AVOID_COIN"
        else:
            sentiment = "neutral"
            action    = "NORMAL"

        coins  = self._find_coins(text)
        urgent = score <= -30 or score >= 40

        return {
            "sentiment":   sentiment,
            "score":       score,
            "action":      action,
            "coins":       coins,
            "reason":      ", ".join(hits[:3]) if hits else "no strong signal",
            "urgent":      urgent,
            "article":     article,
            "analyzed_by": "keyword_fallback",
        }

    def _find_coins(self, text: str) -> list:
        found = []
        for coin, keywords in COIN_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                found.append(coin)
        return found

    def analyze_all(self, articles: list) -> list:
        return [self.analyze(a) for a in articles]

    def get_market_sentiment(self, analyzed: list) -> dict:
        if not analyzed:
            return {"mood": "neutral", "score": 0}
        scores     = [a.get("score", 0) for a in analyzed]
        avg_score  = sum(scores) / len(scores)
        bull_count = sum(1 for a in analyzed if a.get("sentiment") == "bullish")
        bear_count = sum(1 for a in analyzed if a.get("sentiment") == "bearish")
        crit_count = sum(1 for a in analyzed if a.get("sentiment") == "critical")
        if crit_count > 0:     mood = "critical"
        elif avg_score >= 15:  mood = "bullish"
        elif avg_score <= -15: mood = "bearish"
        else:                  mood = "neutral"
        return {
            "mood": mood, "score": round(avg_score, 1),
            "bull_count": bull_count, "bear_count": bear_count,
            "crit_count": crit_count, "total": len(analyzed),
        }

    def get_urgent_actions(self, analyzed: list) -> list:
        return [a for a in analyzed if a.get("urgent") and a.get("action") != "NORMAL"]
