"""Discover candidate topics from Google News RSS and score them.

Scoring is purely heuristic — pytrends was archived in April 2025 and using it
produces stale or rate-limited data. We rely on:
  - title quality prefixes (how to / best / top / vs / why)
  - long-tail bonus (5-9 words)
  - source diversity (number of RSS hits for the same headline stem)
  - recency (RSS feeds are already chronologically ordered)
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import feedparser


_PRIORITY_PREFIXES = ("how to", "what is", "best", "top ", "why ", "vs ", "is ", "are ")


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def _score(title: str, source_count: int) -> float:
    score = 1.0 + min(source_count, 5) * 0.5
    lower = title.lower()
    if any(lower.startswith(p) for p in _PRIORITY_PREFIXES):
        score += 2.0
    word_count = len(title.split())
    if 5 <= word_count <= 9:
        score += 1.0
    if "?" in title:
        score += 0.5
    if any(year in title for year in ("2026", "2027")):
        score += 0.5
    return score


def _fetch_rss(query: str, limit: int = 8) -> list[str]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return []
    titles = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "").split(" - ")[0].strip()
        if title and len(title) > 12:
            titles.append(title)
    return titles


def discover_candidates(config: dict) -> list[dict]:
    """Returns list of {topic, score, source} for new candidates from RSS."""
    niche = config["niche"]
    keywords = config.get("keywords", [])

    queries = list(dict.fromkeys(
        keywords[:5]
        + [f"best {niche}", f"how to {niche}", f"{niche} 2026", f"{niche} guide"]
    ))

    titles_per_query = [(_fetch_rss(q)) for q in queries]

    raw_counts: dict[str, int] = {}
    for titles in titles_per_query:
        for title in titles:
            stem = _slugify(title)[:60]
            raw_counts[stem] = raw_counts.get(stem, 0) + 1

    candidates = []
    seen_stems = set()
    for titles in titles_per_query:
        for title in titles:
            stem = _slugify(title)[:60]
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            candidates.append({
                "topic": title,
                "score": _score(title, raw_counts.get(stem, 1)),
                "source": "rss",
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:25]
