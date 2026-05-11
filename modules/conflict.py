"""Topic-relationship classifier.

Before generating, ask the LLM how the new topic relates to the most recent
published articles. The result feeds the generator prompt so the new post can:

  - NEW          → stand alone (no extra instructions).
  - CONTINUATION → naturally reference the prior post and build on it.
  - FORCED       → acknowledge the overlap and clearly differentiate angle.

This is the agency-website pattern adapted to the Shopify pipeline.
"""
from __future__ import annotations

import json
import os
import re

from anthropic import Anthropic

from .generator import _create_with_backoff


_MODEL = "claude-haiku-4-5-20251001"


_PROMPT = """You classify how a new blog post topic relates to recent posts.

NEW topic:
{topic}

Recently published (index. topic, most recent first):
{recent}

Pick exactly one relationship:
- NEW: unrelated to any listed topic. Standalone post.
- CONTINUATION: directly extends one of the listed topics. The new post should reference the prior one and build deeper.
- FORCED: overlaps a listed topic but takes a clearly different angle. The new post must acknowledge the overlap and differentiate.

Return STRICT JSON, no markdown, no commentary:
{{
  "relationship": "NEW" | "CONTINUATION" | "FORCED",
  "related_index": null | integer,
  "rationale": "one short sentence"
}}"""


def classify(topic: str, recent_topics: list[str], n: int = 5) -> dict:
    """recent_topics: list of recent article topic strings, newest first.
    Returns dict with keys: relationship, related_topic (str|None), rationale."""
    if not recent_topics:
        return {"relationship": "NEW", "related_topic": None, "rationale": "no prior articles"}

    sample = recent_topics[:n]
    recent_lines = "\n".join(f"{i}. {t}" for i, t in enumerate(sample))

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = _create_with_backoff(
        client,
        model=_MODEL,
        max_tokens=300,
        system="You classify topic relationships precisely. Return strict JSON only.",
        messages=[{"role": "user", "content": _PROMPT.format(topic=topic, recent=recent_lines)}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"relationship": "NEW", "related_topic": None, "rationale": "classifier parse failed"}

    rel = data.get("relationship", "NEW")
    if rel not in ("NEW", "CONTINUATION", "FORCED"):
        rel = "NEW"

    idx = data.get("related_index")
    related = sample[idx] if (isinstance(idx, int) and 0 <= idx < len(sample)) else None

    if rel != "NEW" and related is None:
        rel = "NEW"

    return {
        "relationship": rel,
        "related_topic": related,
        "rationale": (data.get("rationale") or "").strip(),
    }
