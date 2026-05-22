from __future__ import annotations

import os
import re

import requests


_STOP_WORDS = {
    "the", "a", "an", "your", "my", "our", "this", "that", "these", "those",
    "and", "or", "but", "with", "for", "in", "of", "on", "at", "to", "from",
    "is", "are", "was", "were", "be", "best", "top", "ultimate", "complete",
    "how", "why", "what", "when", "where", "which", "who", "whose",
    "vs", "versus", "guide", "tips", "tricks", "hacks", "ways", "things",
    "you", "yours", "we", "us", "i", "me",
}
_YEAR_PATTERN = re.compile(r"\b(19|20|21)\d{2}\b")
_NON_WORD = re.compile(r"[^\w\s-]")


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def topic_to_keywords(topic: str, max_words: int = 3) -> str:
    """Reduce a long article title to 2-3 stock-photo-friendly keywords.
    Drops stop words, years, and boilerplate. Word order is preserved so the
    earliest meaningful nouns win."""
    text = _YEAR_PATTERN.sub(" ", topic)
    text = _NON_WORD.sub(" ", text).lower()
    words = [w for w in text.split() if w and w not in _STOP_WORDS and len(w) > 2]
    return " ".join(words[:max_words]) or topic


def _fetch_pexels(query: str, count: int = 15, page: int = 1) -> list[tuple[str, str]]:
    """Returns [(url, alt), ...]. We fetch a larger pool than we need so the
    LLM judge has enough candidates to pick contextually appropriate ones."""
    key = os.environ.get("PEXELS_KEY")
    if not key or count < 1:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": count, "page": page, "orientation": "landscape"},
            headers={"Authorization": key},
            timeout=10,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        return [(p["src"]["large"], (p.get("alt") or "").strip()) for p in photos]
    except Exception:
        return []


def _fetch_pexels_pages(query: str, per_page: int = 15, pages: int = 3) -> list[tuple[str, str]]:
    """Fetch multiple pages so the candidate pool is wide enough for cross-article
    deduplication to still leave the judge real options. Stops early on empty page."""
    out: list[tuple[str, str]] = []
    for page in range(1, pages + 1):
        batch = _fetch_pexels(query, per_page, page)
        if not batch:
            break
        out.extend(batch)
    return out


def _normalize_url(url: str) -> str:
    """Pexels CDN appends transform params (?auto=compress&w=...) that vary across
    fetches of the same photo. Dedup on the path so the same photo isn't reused
    just because its query string changed."""
    return url.split("?", 1)[0]


_GENERIC_ANCHOR_WORDS = {
    "woman", "women", "man", "men", "person", "people", "home", "use", "using",
    "the", "a", "an", "for", "with", "and", "or",
}


def _niche_anchor(fallback_query: str, max_words: int = 2) -> str:
    """Pick 1-2 distinctive niche words from the store's image_query to anchor
    stock-photo searches. 'woman skincare beauty' → 'skincare beauty'. Without
    an anchor, a topic like 'Red Light Therapy' matches traffic lights on Pexels."""
    words = [w for w in fallback_query.lower().split() if w and w not in _GENERIC_ANCHOR_WORDS]
    return " ".join(words[:max_words])


_JUDGE_MODEL = "claude-haiku-4-5-20251001"

_JUDGE_TOOL = {
    "name": "select_relevant_images",
    "description": (
        "Return the indices of images whose descriptions are contextually appropriate "
        "as illustrations for the given article topic. Reject anything off-topic even "
        "if a keyword overlaps (e.g. 'traffic light' for an article about 'red light therapy', "
        "or 'car headlights' for 'LED skincare'). Empty descriptions are uncertain — "
        "include them only if you cannot find enough clearly relevant candidates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "0-based indices of relevant images, ordered by relevance (most relevant first).",
            }
        },
        "required": ["relevant_indices"],
    },
}


def _judge_images(candidates: list[tuple[str, str]], topic: str, niche: str, min_keep: int) -> list[tuple[str, str]]:
    """Ask Haiku which Pexels candidates are contextually appropriate.
    Returns the filtered list in the order Haiku ranked them.
    On API failure or no API key, returns originals (best-effort fallback)."""
    if not candidates or not os.environ.get("ANTHROPIC_API_KEY"):
        return candidates
    listing = "\n".join(f"{i}: {alt or '(no description)'}" for i, (_, alt) in enumerate(candidates))
    prompt = (
        f"Article topic: \"{topic}\"\n"
        f"Store niche: \"{niche}\"\n\n"
        f"Candidate stock photos (description from photographer):\n{listing}\n\n"
        f"Pick at least {min_keep} indices that would work as illustrations for this article. "
        "Prefer photos that clearly show the article's subject. Reject any photo whose "
        "description is off-topic even if it shares a keyword (e.g. traffic lights for an "
        "article about red light therapy). Order results by relevance, most relevant first."
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=_JUDGE_MODEL,
            max_tokens=512,
            tools=[_JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "select_relevant_images"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "select_relevant_images":
                indices = block.input.get("relevant_indices") or []
                kept = [candidates[i] for i in indices if 0 <= i < len(candidates)]
                return kept or candidates
    except Exception:
        pass
    return candidates


def fetch_images(
    primary_query: str,
    fallback_query: str,
    count: int = 3,
    used_urls: set[str] | None = None,
) -> list:
    """Fetch a pool from Pexels (niche-anchored query first, then fallbacks),
    drop anything already used in prior posts, then let Haiku judge which are
    contextually appropriate. Returns top N URLs.

    `used_urls` is the set of every URL ever published by this store. Excluding
    them at the pool stage is the only structural guard against cross-article
    duplicates — without it the judge keeps re-ranking the same elite photos."""
    keyword_query = topic_to_keywords(primary_query)
    anchor = _niche_anchor(fallback_query)
    anchored = f"{keyword_query} {anchor}".strip() if anchor else keyword_query

    used_norm = {_normalize_url(u) for u in (used_urls or [])}

    pool = (
        _fetch_pexels_pages(anchored, 15, 3)
        or _fetch_pexels_pages(keyword_query, 15, 3)
        or _fetch_pexels_pages(fallback_query, 15, 3)
    )
    if not pool:
        return []

    if used_norm:
        pool = [(u, alt) for u, alt in pool if _normalize_url(u) not in used_norm]
        if not pool:
            return []

    judged = _judge_images(pool, topic=primary_query, niche=fallback_query, min_keep=count)

    seen: set[str] = set()
    out: list[str] = []
    for url, _ in judged:
        n = _normalize_url(url)
        if n in seen:
            continue
        seen.add(n)
        out.append(url)
        if len(out) >= count:
            break
    return out


_BOILERPLATE_H2 = re.compile(
    r"^\s*(faq|frequently\s+asked|sources?|references?|further\s+reading|"
    r"questions?\s*(?:&|and)\s*answers?)\b",
    re.IGNORECASE,
)


def inject_images_into_html(html: str, image_urls: list, topic: str = "") -> str:
    """Distribute images evenly across H2 sections (skipping the first H2,
    which is usually the intro/hook, and skipping FAQ/Sources/etc. boilerplate
    sections at the end). Alt text is derived from each section's H2 so it
    stays contextual."""
    if not image_urls:
        return html

    h2_pattern = re.compile(r"(<h2[^>]*>(.*?)</h2>)", re.IGNORECASE | re.DOTALL)
    matches = list(h2_pattern.finditer(html))
    candidates = [
        m for m in matches[1:]
        if not _BOILERPLATE_H2.match(_strip_tags(m.group(2)))
    ]
    if not candidates:
        return html

    n = min(len(image_urls), len(candidates))
    if n == 1:
        target_indices = [0]
    else:
        step = (len(candidates) - 1) / (n - 1) if n > 1 else 1
        target_indices = [round(i * step) for i in range(n)]

    insertions = []
    for slot, idx in enumerate(target_indices):
        match = candidates[idx]
        url = image_urls[slot]
        section_title = _strip_tags(match.group(2))[:120]
        alt = (section_title or topic or "illustration").replace('"', "'")
        insertions.append((match.end(), url, alt))

    for pos, url, alt in reversed(insertions):
        tag = (
            f'\n<img src="{url}" alt="{alt}" '
            f'style="width:100%;border-radius:8px;margin:16px 0;" loading="lazy">\n'
        )
        html = html[:pos] + tag + html[pos:]

    return html


def count_h2(html: str) -> int:
    return len(re.findall(r"<h2\b", html, re.IGNORECASE))
