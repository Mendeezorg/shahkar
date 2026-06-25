"""
news/fetcher.py — Accepts custom source list from engine.
"""
import requests, json, os, re, time
import xml.etree.ElementTree as ET
from datetime import datetime
from utils.logger import log

CACHE_FILE = "logs/news_cache.json"


class NewsFetcher:
    def __init__(self, sources: list = None):
        self.sources  = sources or []
        self.articles = self._load_cache()

    def _load_cache(self) -> list:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_cache(self):
        os.makedirs("logs", exist_ok=True)
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self.articles[-200:], f, indent=2)
        except Exception:
            pass

    def _fetch_rss(self, source: dict) -> list:
        articles = []
        try:
            headers = {"User-Agent": "Mozilla/5.0 SHAHKAR-Bot/1.0"}
            r = requests.get(source["url"], headers=headers, timeout=8)
            if r.status_code != 200:
                return []
            root = ET.fromstring(r.content)
            for item in list(root.iter("item"))[:10]:
                title = item.findtext("title", "")
                desc  = re.sub(r"<[^>]+>", "", item.findtext("description", "") or "")
                if title:
                    articles.append({
                        "title":   title.strip()[:200],
                        "desc":    desc.strip()[:300],
                        "link":    item.findtext("link", ""),
                        "source":  source["name"],
                        "time":    item.findtext("pubDate", datetime.utcnow().isoformat())[:25],
                        "fetched": datetime.utcnow().isoformat(),
                    })
        except Exception as e:
            log.debug(f"RSS fetch failed {source['name']}: {e}")
        return articles

    def _fetch_api(self, source: dict) -> list:
        articles = []
        try:
            headers = {"User-Agent": "SHAHKAR-Bot/1.0"}
            r = requests.get(source["url"], headers=headers, timeout=8)
            if r.status_code != 200:
                return []
            for p in r.json().get("results", [])[:10]:
                if p.get("title"):
                    articles.append({
                        "title":   p.get("title", "")[:200],
                        "desc":    "",
                        "link":    p.get("url", ""),
                        "source":  source["name"],
                        "time":    p.get("published_at", datetime.utcnow().isoformat())[:25],
                        "fetched": datetime.utcnow().isoformat(),
                    })
        except Exception as e:
            log.debug(f"API fetch failed {source['name']}: {e}")
        return articles

    def fetch_all(self) -> list:
        new_articles   = []
        existing       = {a["title"] for a in self.articles}
        for src in self.sources:
            try:
                items = self._fetch_rss(src) if src["type"] == "rss" else self._fetch_api(src)
                for item in items:
                    if item["title"] and item["title"] not in existing:
                        new_articles.append(item)
                        existing.add(item["title"])
            except Exception:
                continue
            time.sleep(0.3)
        if new_articles:
            log.info(f"NEWS fetched {len(new_articles)} new articles")
            self.articles = new_articles + self.articles
            self.articles = self.articles[:200]
            self._save_cache()
        return new_articles

    def get_latest(self, n: int = 20) -> list:
        return self.articles[:n]
