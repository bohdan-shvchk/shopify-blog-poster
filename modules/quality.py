"""Post-generation validators.

Hard gates (cause regeneration):
  - hallucinated product handles
  - word count below threshold
  - title missing or too long
  - meta_description missing or too long
  - external Source URLs that 404

Soft warnings (logged + Telegram, do not fail the gate):
  - suspicious statistics ("87% of women...")
  - suspicious expert quotes ("Dr. Smith from Harvard says...")
"""
from __future__ import annotations

import re

import requests


_HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/products/([a-z0-9\-]+)", re.IGNORECASE)
_STAT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_EXPERT_PATTERN = re.compile(r"\bDr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", re.UNICODE)
_LONG_QUOTE_PATTERN = re.compile(r'"([^"]{80,})"')
_H2_PATTERN = re.compile(r"<h2\b", re.IGNORECASE)
_H3_PATTERN = re.compile(r"<h3\b", re.IGNORECASE)
_HEADING_PATTERN = re.compile(r"<(h[23])\b", re.IGNORECASE)
_QUASI_ORG_PATTERN = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(Labs|Institute|Foundation|University|Research Center|Clinic)\b"
)
_KNOWN_ORGS = {
    "Mayo Clinic",
    "Cleveland Clinic",
    "Harvard University",
    "Stanford University",
    "Yale University",
    "Oxford University",
    "Cambridge University",
    "Johns Hopkins University",
    "Columbia University",
    "Princeton University",
    "Karolinska Institute",
    "Pasteur Institute",
    "MIT",
    "Massachusetts Institute",
    "American Heart Association",
    "American Cancer Society",
    "Cancer Research Foundation",
    "World Health Organization",
    "Skin Cancer Foundation",
    "National Eczema Foundation",
    "British Skin Foundation",
    "Wellcome Foundation",
}


_STYLE_MIN_H2 = {
    "how_to": 4,
    "comparison": 4,
    "buyers_guide": 4,
    "deep_dive": 5,
    "myth_busting": 4,
    "quick_tips": 6,
}


def extract_product_handles(html: str) -> list[str]:
    handles = []
    for href in _HREF_PATTERN.findall(html):
        m = _PRODUCT_PATH.search(href)
        if m:
            handles.append(m.group(1).lower())
    return handles


def extract_external_urls(html: str) -> list[str]:
    urls = []
    for href in _HREF_PATTERN.findall(html):
        if href.startswith("http") and "/products/" not in href:
            urls.append(href)
    return urls


def validate_products_mentioned(html: str, catalog: list[dict]) -> tuple[bool, list[str]]:
    valid_handles = {p["handle"].lower() for p in catalog}
    mentioned = extract_product_handles(html)
    invalid = [h for h in mentioned if h not in valid_handles]
    return (len(invalid) == 0, invalid)


def validate_length(html: str, min_words: int = 800) -> tuple[bool, int]:
    text = re.sub(r"<[^>]+>", " ", html)
    words = len(text.split())
    return (words >= min_words, words)


def _check_external_urls(html: str) -> list[str]:
    """HEAD each external URL. Return list of URLs that returned 4xx/5xx or failed.
    A url that times out or returns connection error is treated as broken."""
    broken = []
    for url in extract_external_urls(html):
        try:
            resp = requests.head(url, timeout=5, allow_redirects=True)
            if resp.status_code >= 400:
                resp = requests.get(url, timeout=5, allow_redirects=True, stream=True)
                if resp.status_code >= 400:
                    broken.append(f"{url} ({resp.status_code})")
        except requests.RequestException as e:
            broken.append(f"{url} ({type(e).__name__})")
    return broken


def validate_structure(html: str, style_key: str | None) -> list[str]:
    """Hard structural checks. Returns list of failure reasons."""
    reasons = []
    h2_count = len(_H2_PATTERN.findall(html))
    if style_key:
        min_h2 = _STYLE_MIN_H2.get(style_key, 4)
        if h2_count < min_h2:
            reasons.append(f"too few H2 sections for style '{style_key}': {h2_count} < {min_h2}")

    # Heading hierarchy: every <h3> must be preceded by an <h2> at some point earlier.
    seen_h2 = False
    for m in _HEADING_PATTERN.finditer(html):
        tag = m.group(1).lower()
        if tag == "h2":
            seen_h2 = True
        elif tag == "h3" and not seen_h2:
            reasons.append("H3 appears before any H2 — broken heading hierarchy")
            break

    return reasons


def collect_warnings(html: str) -> list[str]:
    """Soft signals — logged but do not fail the gate."""
    warnings = []
    stats = _STAT_PATTERN.findall(html)
    if stats:
        warnings.append(f"contains {len(stats)} numeric stats — verify they are not fabricated: {stats[:5]}")
    experts = set(_EXPERT_PATTERN.findall(html))
    if experts:
        warnings.append(f"mentions {len(experts)} 'Dr. X'-style experts — verify they are real: {list(experts)[:5]}")
    long_quotes = _LONG_QUOTE_PATTERN.findall(html)
    if long_quotes:
        warnings.append(f"contains {len(long_quotes)} long direct quotes — verify they are not fabricated")
    quasi_orgs = sorted({m.group(0) for m in _QUASI_ORG_PATTERN.finditer(html)} - _KNOWN_ORGS)
    if quasi_orgs:
        warnings.append(f"mentions quasi-organizations — verify they exist: {quasi_orgs[:5]}")
    return warnings


def validate_article(
    article: dict,
    catalog: list[dict],
    check_urls: bool = True,
    style_key: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Run all gates. Returns (ok, hard_reasons, soft_warnings)."""
    reasons = []
    html = article.get("html_body", "")

    ok_products, invalid = validate_products_mentioned(html, catalog)
    if not ok_products:
        reasons.append(f"hallucinated product handles: {invalid}")

    ok_length, words = validate_length(html)
    if not ok_length:
        reasons.append(f"too short: {words} words (min 800)")

    title = article.get("title", "")
    if not title:
        reasons.append("title missing")
    elif len(title) > 60:
        reasons.append(f"title too long: {len(title)} chars (max 60)")

    meta = article.get("meta_description", "")
    if not meta:
        reasons.append("meta_description missing")
    elif len(meta) > 160:
        reasons.append(f"meta_description too long: {len(meta)} chars (max 160)")

    reasons.extend(validate_structure(html, style_key))

    if check_urls:
        broken = _check_external_urls(html)
        if broken:
            reasons.append(f"broken external URLs: {broken}")

    warnings = collect_warnings(html)

    return (len(reasons) == 0, reasons, warnings)
