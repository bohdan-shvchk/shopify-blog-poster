import os
import re
import requests


def _fetch_pexels(query: str, count: int = 1, page: int = 1) -> list:
    key = os.environ.get("PEXELS_KEY")
    if not key:
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
    if not key:
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


def fetch_images(query: str, count: int = 3) -> list:
    cover = _fetch_pexels(query, count=1, page=1) or _fetch_unsplash(query, count=1, page=1)
    inline = _fetch_pexels(query, count=count - 1, page=2) or _fetch_unsplash(query, count=count - 1, page=2)
    return cover + inline


def inject_images_into_html(html: str, image_urls: list) -> str:
    if not image_urls:
        return html

    h2_pattern = re.compile(r'(<h2[^>]*>.*?</h2>)', re.IGNORECASE)
    matches = list(h2_pattern.finditer(html))

    # insert images after 1st and 2nd h2 tags
    offsets = []
    for i, match in enumerate(matches[1:3]):
        img_url = image_urls[i] if i < len(image_urls) else None
        if img_url:
            offsets.append((match.end(), img_url))

    for pos, url in reversed(offsets):
        img_tag = f'\n<img src="{url}" alt="" style="width:100%;border-radius:8px;margin:16px 0;" loading="lazy">\n'
        html = html[:pos] + img_tag + html[pos:]

    return html
