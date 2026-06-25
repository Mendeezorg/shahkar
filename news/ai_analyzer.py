"""
news/ai_analyzer.py
SHAHKAR AI News Analyzer
Groq free tier: batch of 3, then sleep 15s.
Strict ASCII cleaning to prevent 400 errors.
Conservative CLOSE_ALL — only real emergencies.
"""
import requests, json, os, time, re
from datetime import datetime
from utils.logger import log

AI_CACHE_FILE = "logs/ai_analysis_cache.json"

SYSTEM_PROMPT = """You are a crypto trading news analyzer. Respond with ONLY a JSON object, nothing else.

Format:
{"sentiment":"bullish|bearish|neutral","score":<-100 to 100>,"action":"CLOSE_ALL|BLOCK_ALL|AVOID_COIN|REDUCE_SIZE|BOOST|NORMAL","affected_coins":[],"urgency":"critical|high|medium|low","reason":"one sentence max"}

STRICT action rules:
- CLOSE_ALL: ONLY for "exchange hack", "exchange bankrupt", "market crash -20%". NOT for regulatory news.
- BLOCK_ALL: SEC confirmed action, government ban confirmed (not rumor)
- AVOID_COIN: bad news for one specific coin only
- REDUCE_SIZE: general uncertainty, bearish macro, minor regulatory concern
- BOOST: ETF approved, major institutional buy confirmed, positive regulation
- NORMAL: everything else — analysis, price discussion, minor news"""


def _clean_text(text: str) -> str:
    """Strictly remove ALL non-ASCII to prevent Groq 400 errors."""
    if not text:
        return ""
    # Remove non-ASCII
    text = text.encode("ascii", "ignore").decode("ascii")
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text[:250]


class AINewsAnalyzer:
    def __init__(self):
        self.cache    = self._load_cache()
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.provider = "groq" if self.groq_key else "keyword"
        log.info(f"NEWS AI  provider={self.provider}")

    def _load_cache(self) -> dict:
        try:
            if os.path.exists(AI_CACHE_FILE):
                with open(AI_CACHE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self):
        os.makedirs("logs", exist_ok=True)
        try:
            # Keep only last 200
            if len(self.cache) > 200:
                keys = list(self.cache.keys())
                for k in keys[:50]:
                    del self.cache[k]
            with open(AI_CACHE_FILE, "w") as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass

    def _call_groq(self, title: str, desc: str, source: str) -> dict | None:
        try:
            t = _clean_text(title)
            d = _clean_text(desc)
            s = _clean_text(source)

            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"},
                json={
                    "model":       "llama-3.1-8b-instant",
                    "max_tokens":  150,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": f"Source:{s}\nTitle:{t}\nDesc:{d}\nJSON only."}
                    ]
                },
                timeout=10
            )
            if r.status_code == 200:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                if "{" in raw and "}" in raw:
                    raw = raw[raw.index("{"):raw.rindex("}")+1]
                return json.loads(raw)
            elif r.status_code == 429:
                log.warning("Groq rate limit — sleeping 20s")
                time.sleep(20)
            else:
                log.error(f"Groq error {r.status_code}")
        except Exception as e:
            log.error(f"Groq call failed: {e}")
        return None

    def _keyword_fallback(self, article: dict) -> dict:
        from news.analyzer import NewsAnalyzer
        r = NewsAnalyzer().analyze(article)
        r["analyzed_by"] = "keyword_fallback"
        return r

    def analyze(self, article: dict) -> dict:
        title = article.get("title", "")
        cache_key = _clean_text(title)[:60]

        if cache_key in self.cache:
            return self.cache[cache_key]

        ai_result = self._call_groq(title, article.get("desc",""), article.get("source","")) \
                    if self.provider == "groq" else None

        if ai_result:
            result = {
                "sentiment":   ai_result.get("sentiment", "neutral"),
                "score":       int(ai_result.get("score", 0)),
                "action":      ai_result.get("action", "NORMAL"),
                "coins":       ai_result.get("affected_coins", []),
                "urgency":     ai_result.get("urgency", "low"),
                "reason":      ai_result.get("reason", ""),
                "urgent":      ai_result.get("urgency") in ["critical", "high"],
                "analyzed_by": "groq",
                "article":     article,
                "analyzed_at": datetime.utcnow().isoformat(),
            }
            log.info(f"AI [{result['sentiment'].upper()}] score={result['score']:+d} action={result['action']} '{_clean_text(title)[:40]}'")
        else:
            result = self._keyword_fallback(article)

        self.cache[cache_key] = result
        self._save_cache()
        return result

    def analyze_batch(self, articles: list, delay: float = 2.0) -> list:
        """Process max 3 articles, then sleep 15s (Groq free tier)."""
        results = []
        for i, article in enumerate(articles):
            results.append(self.analyze(article))
            if (i + 1) % 3 == 0:
                time.sleep(15)
            else:
                time.sleep(delay)
        return results

    def get_market_sentiment(self, analyzed: list) -> dict:
        if not analyzed:
            return {"mood": "neutral", "score": 0}
        scores     = [a.get("score", 0) for a in analyzed]
        avg        = sum(scores) / len(scores)
        bull       = sum(1 for a in analyzed if a.get("sentiment") == "bullish")
        bear       = sum(1 for a in analyzed if a.get("sentiment") == "bearish")
        if avg >= 15:   mood = "bullish"
        elif avg <= -15: mood = "bearish"
        else:            mood = "neutral"
        return {"mood": mood, "score": round(avg, 1), "bull_count": bull, "bear_count": bear, "total": len(analyzed)}

    def get_urgent_actions(self, analyzed: list) -> list:
        return [a for a in analyzed if a.get("urgent") and a.get("action") != "NORMAL"]
