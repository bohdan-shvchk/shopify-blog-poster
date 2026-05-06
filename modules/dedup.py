"""Semantic duplicate detection via sentence-transformers embeddings.

The model is loaded lazily and cached at module level. Embeddings are 384-dim
float lists (JSON-serializable) so they can be stored in published_slugs.json.
"""
from __future__ import annotations

from functools import lru_cache


_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_THRESHOLD = 0.75


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(_MODEL_NAME)


def embed(text: str) -> list[float]:
    vec = _model().encode(text, normalize_embeddings=True, convert_to_numpy=True)
    return vec.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    # both vectors are already normalized → dot product == cosine similarity
    return sum(x * y for x, y in zip(a, b))


def find_most_similar(query_emb: list[float], candidates: list[list[float]]) -> tuple[int, float]:
    """Returns (index, score) of the most similar candidate, or (-1, 0.0) if empty."""
    if not candidates:
        return -1, 0.0
    best_idx, best_score = -1, -1.0
    for i, c in enumerate(candidates):
        s = cosine(query_emb, c)
        if s > best_score:
            best_score = s
            best_idx = i
    return best_idx, best_score


def is_duplicate(text: str, past_embeddings: list[list[float]], threshold: float = _DEFAULT_THRESHOLD) -> bool:
    if not past_embeddings:
        return False
    q = embed(text)
    _, score = find_most_similar(q, past_embeddings)
    return score >= threshold
