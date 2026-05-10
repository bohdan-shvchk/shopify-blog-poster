"""Evergreen topic bank.

Two responsibilities:
  1. expose unused evergreen topics from store_config (skipping any that are
     semantic duplicates of published topics);
  2. when the bank runs low, ask the LLM to generate fresh evergreen ideas
     across diverse template categories (how-to, comparison, science, history,
     myth-busting, buyer guide, ingredient deep-dive, seasonal).
"""
from __future__ import annotations

import json
import os
import re

from anthropic import Anthropic

from modules import dedup


_MODEL = "claude-haiku-4-5-20251001"


_CATEGORIES = [
    "how-to / tutorial",
    "comparison (X vs Y)",
    "science / how it works",
    "history / evolution of the category",
    "common myths debunked",
    "buyer's guide",
    "ingredient or technology deep-dive",
    "seasonal advice",
    "FAQ-style explainer",
    "checklist or routine",
]


def get_unused(config: dict, published_embeddings: list[list[float]], threshold: float = 0.75) -> list[str]:
    bank = config.get("evergreen_topics", []) or []
    if not bank:
        return []
    if not published_embeddings:
        return list(bank)
    unused = []
    for topic in bank:
        emb = dedup.embed(topic)
        _, score = dedup.find_most_similar(emb, published_embeddings)
        if score < threshold:
            unused.append(topic)
    return unused


_GEN_PROMPT = """Generate {n} fresh blog post topic ideas for a {niche} store.
Audience: {audience}.

Already-covered topics (avoid overlap):
{published}

Spread the ideas across these template categories:
{categories}

Rules:
- Each topic must be a full headline (60-80 chars), not a fragment.
- No clickbait, no fake claims, no "shocking" hyperbole.
- Mix evergreen themes that won't go stale in 6 months.
- Do NOT invent product names or brands.

Return STRICT JSON: {{"topics": ["...", "...", ...]}}."""


def replenish(config: dict, published_topics: list[str], n: int = 20) -> list[str]:
    """Ask the LLM for n new evergreen ideas. Returns the topic strings."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = _GEN_PROMPT.format(
        n=n,
        niche=config["niche"],
        audience=config.get("audience", "general audience"),
        published="\n".join(f"- {t}" for t in published_topics[-30:]) or "- (none)",
        categories="\n".join(f"- {c}" for c in _CATEGORIES),
    )
    response = client.messages.create(
        model=_MODEL,
        max_tokens=1500,
        system="You generate diverse, evergreen blog topic ideas. Return strict JSON only.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    data = json.loads(raw)
    topics = [t.strip() for t in data.get("topics", []) if isinstance(t, str) and t.strip()]
    return topics[:n]
