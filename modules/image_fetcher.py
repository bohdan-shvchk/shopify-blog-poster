import os
import re

import requests


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


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


def _fetch_unsplash(query: str, count: int = 1, page: int = 1) -> list:
    key = os.environ.get("UNSPLASH_KEY")
    if not key or count < 1:
        return []
    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": count, "page": page, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [r["urls"]["regular"] for r in results]
    except Exception:
        return []


def fetch_images(primary_query: str, fallback_query: str, count: int = 3) -> list:
    """Try the topic-specific query first; fall back to the broader niche query
    if the topic query yields nothing. Cover and inline use different pages so
    we never serve the same image twice."""
    def grab(query, page, n):
        return _fetch_pexels(query, n, page) or _fetch_unsplash(query, n, page)

    cover = grab(primary_query, 1, 1) or grab(fallback_query, 1, 1)
    inline_n = max(0, count - 1)
    inline = grab(primary_query, 2, inline_n) or grab(fallback_query, 2, inline_n)
    return cover + inline


def inject_images_into_html(html: str, image_urls: list, topic: str = "") -> str:
    """Insert images after the 1st and 2nd <h2>. Alt text is derived from the
    h2 text so each image has a unique, contextual description."""
    if not image_urls:
        return html

    h2_pattern = re.compile(r"(<h2[^>]*>(.*?)</h2>)", re.IGNORECASE | re.DOTALL)
    matches = list(h2_pattern.finditer(html))

    insertions = []
    for i, match in enumerate(matches[1:3]):
        if i >= len(image_urls):
            break
        url = image_urls[i]
        section_title = _strip_tags(match.group(2))[:120]
        alt = section_title or topic or "illustration"
        alt = alt.replace('"', "'")
        insertions.append((match.end(), url, alt))

    for pos, url, alt in reversed(insertions):
        tag = (
            f'\n<img src="{url}" alt="{alt}" '
            f'style="width:100%;border-radius:8px;margin:16px 0;" loading="lazy">\n'
        )
        html = html[:pos] + tag + html[pos:]

    return html
