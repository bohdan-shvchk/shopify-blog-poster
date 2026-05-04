import feedparser
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def _load_published_slugs(store_path: Path) -> set:
    slugs_file = store_path / "published_slugs.json"
    if not slugs_file.exists():
        return set()
    with open(slugs_file) as f:
        data = json.load(f)
    result = set()
    for item in data:
        result.add(item["slug"])
        if item.get("topic"):
            result.add(_slugify(item["topic"]))
    return result


def _fetch_rss_topics(keywords: list[str], niche: str) -> list[str]:
    topics = []
    queries = keywords[:3] + [f"{niche} 2026", f"best {niche}"]
    for query in queries:
        url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "").split(" - ")[0].strip()
                if title and len(title) > 10:
                    topics.append(title)
        except Exception:
            continue
    return topics


def _check_trends(topics: list[str]) -> list[tuple[str, float]]:
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        scored = []
        for topic in topics[:5]:
            try:
                pytrends.build_payload([topic], timeframe="now 7-d")
                interest = pytrends.interest_over_time()
                if not interest.empty:
                    score = float(interest[topic].mean())
                else:
                    score = 0.0
                scored.append((topic, score))
            except Exception:
                scored.append((topic, 50.0))
        return sorted(scored, key=lambda x: x[1], reverse=True)
    except Exception:
        return [(t, 50.0) for t in topics]


def _filter_topics(topics: list[str], published_slugs: set) -> list[str]:
    priority_prefixes = ("how to", "what is", "best", "why", "top ")
    seen_slugs = set()
    filtered = []
    for topic in topics:
        slug = _slugify(topic)
        if slug in published_slugs or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        score = 1
        if any(topic.lower().startswith(p) for p in priority_prefixes):
            score += 1
        filtered.append((topic, score))
    filtered.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in filtered]


def find_topic(config: dict, store_path: Path) -> str:
    published_slugs = _load_published_slugs(store_path)
    niche = config["niche"]
    keywords = config.get("keywords", [])
    evergreen = config.get("evergreen_topics", [])

    raw_topics = _fetch_rss_topics(keywords, niche)

    if not raw_topics:
        return evergreen[0] if evergreen else f"guide to {niche}"

    filtered = _filter_topics(raw_topics, published_slugs)

    if not filtered:
        unused_evergreen = [t for t in evergreen if _slugify(t) not in published_slugs]
        return unused_evergreen[0] if unused_evergreen else f"ultimate guide to {niche}"

    top5 = filtered[:5]
    scored = _check_trends(top5)
    best = scored[0][0] if scored else top5[0]

    return best
