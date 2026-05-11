"""Post-generation validators.

Hard gates (cause regeneration):
  - hallucinated product handles
  - word count below threshold
  - title missing or too long
  - meta_description missing or too long

External URLs are NOT a hard gate. They are sanitized in-place
(broken links stripped to plain text, fallback Sources injected
if none remain) — see sanitize_external_urls().

Soft warnings (logged + Telegram, do not fail the gate):
  - suspicious statistics ("87% of women...")
  - suspicious expert quotes ("Dr. Smith from Harvard says...")
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import requests

from . import style


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


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _probe_url(url: str) -> str | None:
    """Returns short failure reason (e.g. '404', 'ConnectionError') if the URL
    is broken, else None. Some sites reject HEAD with 403/405 but accept GET,
    so a HEAD failure falls back to a streamed GET. 403 is treated as bot-block
    (URL is live), not breakage."""
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True, headers=_BROWSER_HEADERS)
        if resp.status_code < 400 or resp.status_code == 403:
            return None
        resp = requests.get(url, timeout=5, allow_redirects=True, stream=True, headers=_BROWSER_HEADERS)
        try:
            if resp.status_code == 403:
                return None
            if resp.status_code >= 400:
                return str(resp.status_code)
        finally:
            resp.close()
        return None
    except requests.RequestException as e:
        return type(e).__name__


def _check_external_urls(html: str) -> dict[str, str]:
    """HEAD each external URL in parallel. Returns {url: reason} for broken ones."""
    urls = extract_external_urls(html)
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_probe_url, urls))
    return {url: reason for url, reason in zip(urls, results) if reason}


_FALLBACK_SOURCES = [
    ("https://www.fda.gov", "U.S. Food and Drug Administration"),
    ("https://www.cdc.gov", "Centers for Disease Control and Prevention"),
    ("https://www.nih.gov", "National Institutes of Health"),
    ("https://www.who.int", "World Health Organization"),
]

_ANCHOR_TAG_PATTERN = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def sanitize_external_urls(article: dict) -> list[str]:
    """Strip anchor tags pointing to broken external URLs (keep inner text).
    Inject a fallback Sources section with whitelist domain homepages if no
    working external URLs remain. Mutates article['html_body'].
    Returns list of human-readable notes for logging."""
    html = article.get("html_body", "")
    broken = _check_external_urls(html)
    if not broken:
        return []

    def _replace(m):
        url = m.group(1)
        return m.group(2) if url in broken else m.group(0)

    cleaned = _ANCHOR_TAG_PATTERN.sub(_replace, html)
    notes = [f"removed broken URL: {url} ({code})" for url, code in broken.items()]

    if not extract_external_urls(cleaned):
        sources_html = "\n<h2>Sources</h2>\n<ul>\n" + "\n".join(
            f'  <li><a href="{u}">{n}</a></li>' for u, n in _FALLBACK_SOURCES[:3]
        ) + "\n</ul>"
        cleaned += sources_html
        notes.append("no working external sources remained — injected fallback whitelist")

    article["html_body"] = cleaned
    return notes


def validate_structure(html: str, style_key: str | None) -> list[str]:
    """Hard structural checks. Returns list of failure reasons."""
    reasons = []
    h2_count = len(_H2_PATTERN.findall(html))
    if style_key:
        required = style.min_h2(style_key)
        if h2_count < required:
            reasons.append(f"too few H2 sections for style '{style_key}': {h2_count} < {required}")

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
    style_key: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Run all gates. Returns (ok, hard_reasons, soft_warnings).
    Assumes external URLs were already sanitized by sanitize_external_urls()."""
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

    warnings = collect_warnings(html)

    return (len(reasons) == 0, reasons, warnings)
