#!/usr/bin/env python3
"""One-time backfill: pull every article currently in the Shopify blog and
record its cover + inline image URLs into stores/*/published_slugs.json so the
new cross-article image dedup has a complete history to exclude.

Articles already in published_slugs.json get an `image_urls` field added.
Articles in Shopify that we never logged locally get appended as bare history
records (slug, title, date, image_urls) so dedup sees them too — they have no
embedding so they don't influence topic dedup."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_IMG_PATTERN = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
_ARTICLES_QUERY = """
query Articles($cursor: String) {
  articles(first: 50, after: $cursor, sortKey: PUBLISHED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        publishedAt
        image { url }
        body
      }
    }
  }
}
"""


def fetch_all_articles(domain: str, token: str) -> list[dict]:
    out: list[dict] = []
    cursor = None
    while True:
        resp = requests.post(
            f"https://{domain}/admin/api/2024-10/graphql.json",
            json={"query": _ARTICLES_QUERY, "variables": {"cursor": cursor}},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]["articles"]
        for e in data["edges"]:
            out.append(e["node"])
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]
    return out


def article_image_urls(article: dict) -> list[str]:
    urls: list[str] = []
    cover = (article.get("image") or {}).get("url")
    if cover:
        urls.append(cover)
    urls.extend(_IMG_PATTERN.findall(article.get("body") or ""))
    seen = set()
    deduped: list[str] = []
    for u in urls:
        key = u.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(u)
    return deduped


def backfill_store(store_path: Path, domain: str, token: str) -> None:
    slugs_file = store_path / "published_slugs.json"
    records = json.loads(slugs_file.read_text()) if slugs_file.exists() else []

    articles = fetch_all_articles(domain, token)
    print(f"  fetched {len(articles)} articles from Shopify")

    by_handle = {a["handle"]: a for a in articles}
    by_id = {a["id"]: a for a in articles}

    matched = 0
    for rec in records:
        article = None
        if rec.get("article_id") and rec["article_id"] in by_id:
            article = by_id[rec["article_id"]]
        elif rec.get("handle") and rec["handle"] in by_handle:
            article = by_handle[rec["handle"]]
        elif rec.get("slug") and rec["slug"] in by_handle:
            article = by_handle[rec["slug"]]
        if not article:
            continue
        rec["image_urls"] = article_image_urls(article)
        matched += 1

    known_handles = {r.get("handle") or r.get("slug") for r in records}
    appended = 0
    for a in articles:
        if a["handle"] in known_handles:
            continue
        records.append({
            "slug": a["handle"],
            "title": a["title"],
            "handle": a["handle"],
            "article_id": a["id"],
            "date": (a.get("publishedAt") or "")[:10],
            "url": None,
            "source": "shopify_backfill",
            "image_urls": article_image_urls(a),
        })
        appended += 1

    slugs_file.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"  backfilled {matched} existing records, appended {appended} from Shopify")


def main() -> None:
    token = os.environ.get("SHOPIFY_TOKEN")
    if not token:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("SHOPIFY_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        print("SHOPIFY_TOKEN not set")
        sys.exit(1)

    for store_dir in (ROOT / "stores").iterdir():
        if not store_dir.is_dir():
            continue
        config_file = store_dir / "store_config.json"
        if not config_file.exists():
            continue
        config = json.loads(config_file.read_text())
        print(f"\n[{store_dir.name}] domain={config['shopify_domain']}")
        backfill_store(store_dir, config["shopify_domain"], token)


if __name__ == "__main__":
    main()
