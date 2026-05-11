"""Topic pool: a persistent ranked queue of candidate topics.

Each day topic_finder produces fresh candidates and adds them here. Selection
takes the top-scoring candidate that is NOT a semantic duplicate of anything in
published_slugs.json. After publishing, the chosen topic is removed from the pool.

Pool entries shape:
{
  "topic": str,
  "score": float,
  "found_date": "YYYY-MM-DD",
  "source": "rss" | "evergreen" | "ai_generated",
  "embedding": [384 floats]
}
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from modules import dedup


_POOL_FILE = "topic_pool.json"
_MAX_POOL_SIZE = 100
_MAX_AGE_DAYS = 60
_DECAY_PER_DAY = 0.05


def _days_since(iso_date: str) -> int:
    try:
        return max(0, (date.today() - date.fromisoformat(iso_date)).days)
    except (ValueError, TypeError):
        return 0


def _effective_score(item: dict) -> float:
    return float(item.get("score", 1.0)) - _DECAY_PER_DAY * _days_since(item.get("found_date", ""))


def _prune_expired(pool: list[dict]) -> list[dict]:
    return [item for item in pool if _days_since(item.get("found_date", "")) <= _MAX_AGE_DAYS]


def _path(store_path: Path) -> Path:
    return store_path / _POOL_FILE


def load(store_path: Path) -> list[dict]:
    p = _path(store_path)
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def save(store_path: Path, pool: list[dict]) -> None:
    with open(_path(store_path), "w") as f:
        json.dump(pool, f, indent=2, ensure_ascii=False)


def add_candidates(
    store_path: Path,
    candidates: list[dict],
    published_embeddings: list[list[float]],
    similarity_threshold: float = 0.75,
) -> int:
    """Append new candidates that are not semantic duplicates of pool or published.
    Each candidate dict must have keys: topic, score, source.
    Embeddings are computed here. Returns number of items added.
    Also prunes pool entries older than _MAX_AGE_DAYS."""
    pool = _prune_expired(load(store_path))
    pool_embeddings = [item["embedding"] for item in pool]
    today = date.today().isoformat()
    added = 0

    for cand in candidates:
        topic = cand["topic"].strip()
        if not topic:
            continue
        emb = dedup.embed(topic)
        if pool_embeddings and dedup.find_most_similar(emb, pool_embeddings)[1] >= similarity_threshold:
            continue
        if published_embeddings and dedup.find_most_similar(emb, published_embeddings)[1] >= similarity_threshold:
            continue
        pool.append({
            "topic": topic,
            "score": float(cand.get("score", 1.0)),
            "found_date": today,
            "source": cand.get("source", "rss"),
            "embedding": emb,
        })
        pool_embeddings.append(emb)
        added += 1

    pool.sort(key=lambda x: (_effective_score(x), x["found_date"]), reverse=True)
    if len(pool) > _MAX_POOL_SIZE:
        pool = pool[:_MAX_POOL_SIZE]

    save(store_path, pool)
    return added


def pick_best(
    store_path: Path,
    published_embeddings: list[list[float]],
    similarity_threshold: float = 0.75,
):
    """Return the highest-scoring pool item that is not a duplicate of published.
    Score is decayed by age so fresh topics float up over time.
    Returns None if pool is empty or every item is a duplicate."""
    pool = _prune_expired(load(store_path))
    pool.sort(key=_effective_score, reverse=True)
    for item in pool:
        if not published_embeddings:
            return item
        _, score = dedup.find_most_similar(item["embedding"], published_embeddings)
        if score < similarity_threshold:
            return item
    return None


def remove(store_path: Path, topic: str) -> None:
    pool = load(store_path)
    pool = [p for p in pool if p["topic"] != topic]
    save(store_path, pool)


def mark_failed(store_path: Path, topic: str, max_attempts: int = 2) -> int:
    """Increment failed_attempts counter on the matching pool entry. If the
    counter reaches max_attempts, drop the entry from the pool so we stop
    re-picking the same failing topic day after day.
    Returns the new attempts count (0 if topic was not in pool)."""
    pool = load(store_path)
    out = []
    new_count = 0
    for item in pool:
        if item["topic"] != topic:
            out.append(item)
            continue
        attempts = int(item.get("failed_attempts", 0)) + 1
        new_count = attempts
        if attempts >= max_attempts:
            continue
        item["failed_attempts"] = attempts
        out.append(item)
    save(store_path, out)
    return new_count
