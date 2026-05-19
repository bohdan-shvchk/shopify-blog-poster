from __future__ import annotations

import json
import os
import re
from datetime import date

import requests

from .slug import slugify


_FAQ_SECTION_PATTERN = re.compile(
    r"<h2[^>]*>\s*(?:FAQ[s]?|Frequently\s+Asked\s+Questions|Questions\s*(?:&|&amp;|and)\s*Answers|Common\s+Questions)\b.*?</h2>(.*?)(?=<h2|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_FAQ_QA_PATTERN = re.compile(
    r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TAG_STRIP = re.compile(r"<[^>]+>")
_PRODUCT_LINK_PATTERN = re.compile(
    r'<a\s[^>]*href=["\'][^"\']*?/products/([a-z0-9\-]+)[^"\']*["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


_ARTICLE_CREATE = """
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article {
      id
      title
      handle
      publishedAt
      blog { handle }
    }
    userErrors {
      field
      message
    }
  }
}
"""

_BLOG_HANDLE_QUERY = """
query BlogHandle($id: ID!) {
  blog(id: $id) { handle }
}
"""

_blog_handle_cache: dict[str, str] = {}


def _fetch_blog_handle(domain: str, blog_id: str, token: str) -> str | None:
    if blog_id in _blog_handle_cache:
        return _blog_handle_cache[blog_id]
    try:
        resp = requests.post(
            f"https://{domain}/admin/api/2024-10/graphql.json",
            json={"query": _BLOG_HANDLE_QUERY, "variables": {"id": blog_id}},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        handle = (resp.json().get("data") or {}).get("blog", {}).get("handle")
    except requests.RequestException:
        handle = None
    if handle:
        _blog_handle_cache[blog_id] = handle
    return handle


def _author_bio_html(config: dict) -> str:
    name = config.get("author_name") or config.get("author")
    bio = config.get("author_bio")
    url = config.get("author_url")
    if not name or not bio:
        return ""
    name_html = f'<a href="{url}">{name}</a>' if url else name
    return (
        '<div class="author-bio" style="margin-top:32px;padding:16px;'
        'border-top:1px solid #eee;font-size:0.95em;color:#555;">'
        f'<strong>About the author:</strong> {name_html} — {bio}'
        "</div>"
    )


def _word_count(html: str) -> int:
    return len(_TAG_STRIP.sub(" ", html).split())


def _extract_faq_pairs(html: str) -> list[tuple[str, str]]:
    """Find <h2>FAQ</h2> ... <h3>Q</h3>A<h3>Q</h3>A ... and return (question, answer) pairs."""
    section_match = _FAQ_SECTION_PATTERN.search(html)
    if not section_match:
        return []
    section_html = section_match.group(1)
    pairs = []
    for q_match in _FAQ_QA_PATTERN.finditer(section_html):
        question = _TAG_STRIP.sub("", q_match.group(1)).strip()
        answer = _TAG_STRIP.sub(" ", q_match.group(2)).strip()
        answer = re.sub(r"\s+", " ", answer)
        if question and answer:
            pairs.append((question, answer))
    return pairs


def _article_schema(article: dict, config: dict, image_url, article_url) -> dict:
    today = date.today().isoformat()
    publisher_name = config.get("name") or config.get("author") or ""
    author_name = config.get("author_name") or config.get("author") or "Editorial Team"
    payload = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "description": article.get("meta_description", ""),
        "datePublished": today,
        "dateModified": today,
        "author": {"@type": "Person", "name": author_name},
        "publisher": {"@type": "Organization", "name": publisher_name},
        "wordCount": _word_count(article["html_body"]),
        "keywords": ", ".join(article.get("tags") or []),
    }
    if article_url:
        payload["mainEntityOfPage"] = {"@type": "WebPage", "@id": article_url}
    if image_url:
        payload["image"] = image_url
    return payload


def _extract_product_handles(html: str) -> list[str]:
    """Return product handles in order of first appearance, deduplicated."""
    seen: dict[str, None] = {}
    for m in _PRODUCT_LINK_PATTERN.finditer(html):
        seen.setdefault(m.group(1).lower(), None)
    return list(seen.keys())


def _product_schemas(html: str, catalog: list[dict] | None, base: str, currency: str = "USD") -> list[dict]:
    """Build a Product schema per catalog product mentioned in the article body."""
    if not catalog:
        return []
    by_handle = {p["handle"].lower(): p for p in catalog}
    schemas = []
    for handle in _extract_product_handles(html):
        product = by_handle.get(handle)
        if not product:
            continue
        url = f"{base}/products/{handle}"
        schema: dict = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": product["title"],
            "url": url,
        }
        price = product.get("price")
        if price:
            schema["offers"] = {
                "@type": "Offer",
                "url": url,
                "priceCurrency": currency,
                "price": str(price),
                "availability": "https://schema.org/InStock",
                "itemCondition": "https://schema.org/NewCondition",
            }
        schemas.append(schema)
    return schemas


def _faq_schema(html: str) -> dict | None:
    pairs = _extract_faq_pairs(html)
    if not pairs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }


def _schema_jsonld(article: dict, config: dict, image_url=None, article_url=None, catalog=None, base=None) -> str:
    blocks = [_article_schema(article, config, image_url, article_url)]
    faq = _faq_schema(article["html_body"])
    if faq:
        blocks.append(faq)
    if catalog and base:
        currency = config.get("currency", "USD")
        blocks.extend(_product_schemas(article["html_body"], catalog, base, currency))
    return "".join(
        f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>'
        for b in blocks
    )


def _decorate_html(article: dict, config: dict, image_url=None, article_url=None, catalog=None, base=None) -> str:
    return (
        _schema_jsonld(article, config, image_url, article_url, catalog, base)
        + article["html_body"]
        + _author_bio_html(config)
    )


def publish_article(article: dict, config: dict, image_url=None, catalog: list[dict] | None = None) -> dict:
    domain = config["shopify_domain"]
    blog_id = config["blog_id"]
    token = os.environ["SHOPIFY_TOKEN"]

    blog_handle = config.get("blog_handle") or _fetch_blog_handle(domain, blog_id, token)
    if blog_handle and not config.get("blog_handle"):
        config["blog_handle"] = blog_handle  # caller saves config back to disk
    expected_slug = slugify(article["title"])
    base = (config.get("public_domain") or f"https://{domain}").rstrip("/")
    expected_url = f"{base}/blogs/{blog_handle}/{expected_slug}" if blog_handle else None

    body_html = _decorate_html(article, config, image_url, expected_url, catalog, base)

    variables = {
        "article": {
            "blogId": blog_id,
            "title": article["title"],
            "body": body_html,
            "tags": article.get("tags", []),
            "author": {"name": config.get("author_name") or config.get("author", "Editorial Team")},
        }
    }

    if image_url:
        variables["article"]["image"] = {"url": image_url}

    if article.get("meta_description"):
        # Shopify's native SEO description lives in the global.description_tag
        # metafield. Themes read it via {{ article.metafields.global.description_tag }}
        # and Dawn/most themes fall back to it for <meta name="description">.
        variables["article"]["metafields"] = [
            {
                "namespace": "global",
                "key": "description_tag",
                "value": article["meta_description"],
                "type": "single_line_text_field",
            }
        ]

    resp = requests.post(
        f"https://{domain}/admin/api/2024-10/graphql.json",
        json={"query": _ARTICLE_CREATE, "variables": variables},
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    errors = data.get("data", {}).get("articleCreate", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"Shopify errors: {errors}")

    created = data["data"]["articleCreate"]["article"]
    actual_handle = (created.get("blog") or {}).get("handle") or blog_handle
    if actual_handle:
        created["url"] = f"{base}/blogs/{actual_handle}/{created['handle']}"
    return created
