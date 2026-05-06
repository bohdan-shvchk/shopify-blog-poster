import json
import os
from datetime import date

import requests


_ARTICLE_CREATE = """
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article {
      id
      title
      handle
      publishedAt
    }
    userErrors {
      field
      message
    }
  }
}
"""


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


def _schema_jsonld(article: dict, config: dict, image_url=None) -> str:
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
    }
    if image_url:
        payload["image"] = image_url
    return f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'


def _decorate_html(article: dict, config: dict, image_url=None) -> str:
    return (
        _schema_jsonld(article, config, image_url)
        + article["html_body"]
        + _author_bio_html(config)
    )


def publish_article(article: dict, config: dict, image_url=None) -> dict:
    domain = config["shopify_domain"]
    blog_id = config["blog_id"]
    token = os.environ["SHOPIFY_TOKEN"]

    body_html = _decorate_html(article, config, image_url)

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
        variables["article"]["metafields"] = [
            {
                "namespace": "seo",
                "key": "description",
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

    return data["data"]["articleCreate"]["article"]
