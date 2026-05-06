"""Post-generation validators.

The most important check: every internal product link the LLM produced must
point to a real product handle from the Shopify catalog. This is the last line
of defense against hallucinated products.
"""
from __future__ import annotations

import re


_HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/products/([a-z0-9\-]+)", re.IGNORECASE)


def extract_product_handles(html: str) -> list[str]:
    handles = []
    for href in _HREF_PATTERN.findall(html):
        m = _PRODUCT_PATH.search(href)
        if m:
            handles.append(m.group(1).lower())
    return handles


def validate_products_mentioned(html: str, catalog: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, invalid_handles). ok=True iff every /products/<handle> link
    in the html resolves to a handle present in the catalog."""
    valid_handles = {p["handle"].lower() for p in catalog}
    mentioned = extract_product_handles(html)
    invalid = [h for h in mentioned if h not in valid_handles]
    return (len(invalid) == 0, invalid)


def validate_length(html: str, min_words: int = 600) -> tuple[bool, int]:
    text = re.sub(r"<[^>]+>", " ", html)
    words = len(text.split())
    return (words >= min_words, words)


def validate_article(article: dict, catalog: list[dict]) -> tuple[bool, list[str]]:
    """Run all gates. Returns (ok, list of failure reasons)."""
    reasons = []
    html = article.get("html_body", "")

    ok_products, invalid = validate_products_mentioned(html, catalog)
    if not ok_products:
        reasons.append(f"hallucinated product handles: {invalid}")

    ok_length, words = validate_length(html)
    if not ok_length:
        reasons.append(f"too short: {words} words")

    if not article.get("title") or len(article["title"]) > 80:
        reasons.append("title missing or too long")

    if not article.get("meta_description"):
        reasons.append("meta_description missing")

    return (len(reasons) == 0, reasons)
