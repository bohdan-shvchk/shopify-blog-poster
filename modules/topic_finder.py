"""Discover candidate topics from Google News RSS and score them.

Scoring is heuristic — pytrends was archived in April 2025 and using it
produces stale or rate-limited data. We rely on:
  - title quality prefixes (how to / best / top / vs / why / myths / science / review)
  - long-tail bonus (5-9 words)
  - source diversity (number of RSS hits for the same headline stem)
  - source quality (whitelisted domains get a multiplier)

Query diversity matters: different query templates feed different style
buckets in the picker (best/top → buyers_guide, myth → myth_busting, etc.).
Without varied queries the pool would be dominated by listicles.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import feedparser


_PRIORITY_PREFIXES = (
    "how to", "what is", "best", "top ", "why ", "vs ", "is ", "are ",
    "the science", "myths", "myth", "review", "comparing",
)

_DOMAIN_WEIGHTS = {
    "reuters.com": 1.5,
    "bbc.com": 1.5,
    "bbc.co.uk": 1.5,
    "nytimes.com": 1.4,
    "theguardian.com": 1.4,
    "washingtonpost.com": 1.4,
    "healthline.com": 1.4,
    "medicalnewstoday.com": 1.4,
    "webmd.com": 1.3,
    "mayoclinic.org": 1.5,
    "harvard.edu": 1.5,
    "nih.gov": 1.5,
    "fda.gov": 1.5,
    "wired.com": 1.3,
    "theverge.com": 1.3,
    "techcrunch.com": 1.2,
    "vogue.com": 1.3,
    "elle.com": 1.2,
    "allure.com": 1.3,
    "byrdie.com": 1.2,
    "self.com": 1.2,
}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def _domain_weight(source_domain: str) -> float:
    if not source_domain:
        return 1.0
    domain = source_domain.lower().lstrip("www.")
    for d, w in _DOMAIN_WEIGHTS.items():
        if domain == d or domain.endswith("." + d):
            return w
    return 1.0


def _score(title: str, source_count: int, domain_weight: float) -> float:
    score = 1.0 + min(source_count, 5) * 0.5
    lower = title.lower()
    if any(lower.startswith(p) for p in _PRIORITY_PREFIXES):
        score += 2.0
    word_count = len(title.split())
    if 5 <= word_count <= 9:
        score += 1.0
    if any(year in title for year in ("2026", "2027")):
        score += 0.5
    return score * domain_weight


def _split_title_and_source(raw: str) -> tuple[str, str]:
    """Google News titles end with ' - <source>'. Split at the LAST ' - '."""
    if " - " not in raw:
        return raw.strip(), ""
    title, source = raw.rsplit(" - ", 1)
    return title.strip(), source.strip()


def _source_to_domain(source: str) -> str:
    s = source.lower()
    return {
        "reuters": "reuters.com",
        "the new york times": "nytimes.com",
        "the guardian": "theguardian.com",
        "the washington post": "washingtonpost.com",
        "bbc": "bbc.com",
        "healthline": "healthline.com",
        "medical news today": "medicalnewstoday.com",
        "webmd": "webmd.com",
        "mayo clinic": "mayoclinic.org",
        "harvard health": "harvard.edu",
        "wired": "wired.com",
        "the verge": "theverge.com",
        "techcrunch": "techcrunch.com",
        "vogue": "vogue.com",
        "elle": "elle.com",
        "allure": "allure.com",
        "byrdie": "byrdie.com",
        "self": "self.com",
    }.get(s, s.replace(" ", ""))


def _fetch_google_news(query: str, limit: int = 8) -> list[tuple[str, str]]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return []
    items = []
    for entry in feed.entries[:limit]:
        raw = entry.get("title", "")
        title, source = _split_title_and_source(raw)
        if title and len(title) > 12:
            items.append((title, _source_to_domain(source) if source else ""))
    return items


def _fetch_bing_news(query: str, limit: int = 8) -> list[tuple[str, str]]:
    """Bing News RSS. Source is in entry.source.title or the link domain."""
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=RSS"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return []
    items = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        if not title or len(title) <= 12:
            continue
        source_obj = entry.get("source") or {}
        source_name = source_obj.get("title") if isinstance(source_obj, dict) else ""
        domain = _source_to_domain(source_name) if source_name else _domain_from_link(entry.get("link", ""))
        items.append((title, domain))
    return items


def _domain_from_link(link: str) -> str:
    m = re.match(r"https?://([^/]+)/", link)
    if not m:
        return ""
    domain = m.group(1).lower()
    return domain[4:] if domain.startswith("www.") else domain


def _fetch_rss(query: str, limit: int = 8) -> list[tuple[str, str]]:
    """Merge Google News + Bing News for redundancy and source diversity."""
    return _fetch_google_news(query, limit) + _fetch_bing_news(query, limit)


def _build_queries(config: dict) -> list[str]:
    niche = config["niche"]
    keywords = config.get("keywords", [])
    templates = [
        f"best {niche}",
        f"how to {niche}",
        f"{niche} 2026",
        f"{niche} guide",
        f"{niche} myth",
        f"{niche} science",
        f"{niche} review",
        f"{niche} comparison",
        f"{niche} tutorial",
    ]
    return list(dict.fromkeys(keywords[:5] + templates))


def discover_candidates(config: dict) -> list[dict]:
    """Returns list of {topic, score, source} for new candidates from RSS."""
    queries = _build_queries(config)
    items_per_query = [_fetch_rss(q) for q in queries]

    raw_counts: dict[str, int] = {}
    best_domain: dict[str, str] = {}
    for items in items_per_query:
        for title, domain in items:
            stem = _slugify(title)[:60]
            raw_counts[stem] = raw_counts.get(stem, 0) + 1
            if domain and (stem not in best_domain or _domain_weight(domain) > _domain_weight(best_domain[stem])):
                best_domain[stem] = domain

    candidates = []
    seen_stems = set()
    for items in items_per_query:
        for title, _ in items:
            stem = _slugify(title)[:60]
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            domain = best_domain.get(stem, "")
            candidates.append({
                "topic": title,
                "score": _score(title, raw_counts.get(stem, 1), _domain_weight(domain)),
                "source": "rss",
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:25]
