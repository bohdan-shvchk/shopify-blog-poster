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


def _fetch_pexels(query: str, count: int = 1, page: int = 1) -> list:
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
        return [p["src"]["large"] for p in photos]
    except Exception:
        return []


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


def fetch_images(primary_query: str, fallback_query: str, count: int = 3) -> list:
    """Try the niche-anchored topic query first, then unanchored topic keywords,
    then the broader niche query. Anchoring forces Pexels to weigh both the topic
    and the niche context — without it 'red light therapy' returns traffic lights.
    Cover and inline use different pages so we never serve the same image twice."""
    keyword_query = topic_to_keywords(primary_query)
    anchor = _niche_anchor(fallback_query)
    anchored = f"{keyword_query} {anchor}".strip() if anchor else keyword_query

    cover = (
        _fetch_pexels(anchored, 1, 1)
        or _fetch_pexels(keyword_query, 1, 1)
        or _fetch_pexels(fallback_query, 1, 1)
    )
    inline_n = max(0, count - 1)
    inline = (
        _fetch_pexels(anchored, inline_n, 2)
        or _fetch_pexels(keyword_query, inline_n, 2)
        or _fetch_pexels(fallback_query, inline_n, 2)
    )
    return cover + inline


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
