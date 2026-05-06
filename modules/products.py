"""Fetch the active product catalog from Shopify Admin GraphQL API.

Results are cached per-store in products_cache.json with a 24h TTL so we don't
hit Shopify on every run. Returned shape is a list of dicts with keys:
title, handle, url, description, product_type, tags.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests


_CACHE_TTL_SECONDS = 24 * 60 * 60
_PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after, query: "status:active") {
    edges {
      cursor
      node {
        title
        handle
        description
        productType
        tags
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _fetch_all(domain: str, token: str) -> list[dict]:
    url = f"https://{domain}/admin/api/2024-10/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    products = []
    cursor = None
    for _ in range(20):  # hard cap: 20 pages × 50 = 1000 products
        resp = requests.post(
            url,
            json={"query": _PRODUCTS_QUERY, "variables": {"first": 50, "after": cursor}},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]["products"]
        for edge in data["edges"]:
            n = edge["node"]
            products.append({
                "title": n["title"],
                "handle": n["handle"],
                "description": (n.get("description") or "")[:300],
                "product_type": n.get("productType") or "",
                "tags": n.get("tags") or [],
            })
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]
    return products


def get_products(store_path: Path, config: dict, force_refresh: bool = False) -> list[dict]:
    cache_file = store_path / "products_cache.json"
    if not force_refresh and cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if time.time() - cached.get("fetched_at", 0) < _CACHE_TTL_SECONDS:
            return cached.get("products", [])

    domain = config["shopify_domain"]
    token = os.environ["SHOPIFY_TOKEN"]
    products = _fetch_all(domain, token)

    with open(cache_file, "w") as f:
        json.dump({"fetched_at": time.time(), "products": products}, f, indent=2, ensure_ascii=False)
    return products


def product_url(handle: str, config: dict) -> str:
    base = config.get("public_domain") or f"https://{config['shopify_domain']}"
    return f"{base.rstrip('/')}/products/{handle}"


def format_for_prompt(products: list[dict], config: dict, limit: int = 30) -> str:
    """Compact, cheap-to-tokenize listing for the LLM prompt."""
    lines = []
    for p in products[:limit]:
        url = product_url(p["handle"], config)
        desc = p["description"].replace("\n", " ").strip()
        if desc:
            lines.append(f"- {p['title']} | {url} | {desc[:120]}")
        else:
            lines.append(f"- {p['title']} | {url}")
    return "\n".join(lines)
