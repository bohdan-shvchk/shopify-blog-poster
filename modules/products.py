"""Fetch the active product catalog from Shopify Admin GraphQL API.

Results are cached per-store in products_cache.json with a 24h TTL so we don't
hit Shopify on every run. Embeddings live in a separate products_embeddings.json
keyed by handle — this keeps the human-readable cache file small and lets us
recompute embeddings without re-fetching the catalog.

The embedding is built from title + description + tags + product_type so we can
rank products by relevance to the article topic before sending to the LLM.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from modules import dedup


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
        variants(first: 1) {
          nodes { price }
        }
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
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Shopify GraphQL errors: {body['errors']}")
        if not body.get("data") or not body["data"].get("products"):
            raise RuntimeError(f"Unexpected Shopify response: {body}")
        data = body["data"]["products"]
        for edge in data["edges"]:
            n = edge["node"]
            variants = (n.get("variants") or {}).get("nodes") or []
            price = variants[0].get("price") if variants else None
            products.append({
                "title": n["title"],
                "handle": n["handle"],
                "description": (n.get("description") or "")[:300],
                "product_type": n.get("productType") or "",
                "tags": n.get("tags") or [],
                "price": price,
            })
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]
    return products


def _product_text(p: dict) -> str:
    parts = [p.get("title", ""), p.get("product_type", ""), " ".join(p.get("tags") or []), p.get("description", "")]
    return " ".join(filter(None, parts))


def _embeddings_file(store_path: Path) -> Path:
    return store_path / "products_embeddings.json"


def _load_embeddings(store_path: Path) -> dict[str, list[float]]:
    f = _embeddings_file(store_path)
    if not f.exists():
        return {}
    with open(f) as fp:
        return json.load(fp)


def _save_embeddings(store_path: Path, mapping: dict[str, list[float]]) -> None:
    with open(_embeddings_file(store_path), "w") as fp:
        json.dump(mapping, fp, indent=2)


def _migrate_inline_embeddings(products: list[dict], mapping: dict[str, list[float]]) -> bool:
    """Pull embeddings out of legacy cache entries into the mapping. Returns True if migration happened."""
    migrated = False
    for p in products:
        emb = p.pop("embedding", None)
        if emb and p["handle"] not in mapping:
            mapping[p["handle"]] = emb
            migrated = True
    return migrated


def _attach_embeddings(products: list[dict], mapping: dict[str, list[float]]) -> bool:
    """Attach embeddings from mapping to products in-memory; compute and add missing ones to mapping.
    Returns True if mapping changed (caller should persist)."""
    changed = False
    for p in products:
        handle = p["handle"]
        emb = mapping.get(handle)
        if emb is None:
            emb = dedup.embed(_product_text(p))
            mapping[handle] = emb
            changed = True
        p["embedding"] = emb
    return changed


def get_products(store_path: Path, config: dict, force_refresh: bool = False) -> list[dict]:
    cache_file = store_path / "products_cache.json"
    embeddings_map = _load_embeddings(store_path)

    cache_hit = False
    products: list[dict] = []
    fetched_at = time.time()

    if not force_refresh and cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if time.time() - cached.get("fetched_at", 0) < _CACHE_TTL_SECONDS:
            products = cached.get("products", [])
            fetched_at = cached.get("fetched_at", fetched_at)
            cache_hit = True

    if not cache_hit:
        domain = config["shopify_domain"]
        token = os.environ["SHOPIFY_TOKEN"]
        products = _fetch_all(domain, token)
        fetched_at = time.time()

    migrated = _migrate_inline_embeddings(products, embeddings_map)
    embeddings_changed = _attach_embeddings(products, embeddings_map)

    if not cache_hit or migrated:
        # rewrite cache without inline embeddings
        with open(cache_file, "w") as f:
            json.dump(
                {"fetched_at": fetched_at, "products": [{k: v for k, v in p.items() if k != "embedding"} for p in products]},
                f, indent=2, ensure_ascii=False,
            )
    if embeddings_changed or migrated:
        _save_embeddings(store_path, embeddings_map)

    return products


def rank_by_relevance(products: list[dict], topic: str, top_n: int = 15) -> list[dict]:
    """Sort products by cosine similarity of their embedding to the topic embedding.
    Products without embeddings sink to the bottom. Returns a new list, top_n items."""
    if not products:
        return []
    topic_emb = dedup.embed(topic)
    scored = []
    for p in products:
        emb = p.get("embedding")
        score = dedup.cosine(topic_emb, emb) if emb else -1.0
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:top_n]]


def product_url(handle: str, config: dict) -> str:
    base = config.get("public_domain") or f"https://{config['shopify_domain']}"
    return f"{base.rstrip('/')}/products/{handle}"


def format_for_prompt(products: list[dict], config: dict, limit: int = 30) -> str:
    """Compact, cheap-to-tokenize listing for the LLM prompt."""
    lines = []
    for p in products[:limit]:
        url = product_url(p["handle"], config)
        desc = p["description"].replace("\n", " ").strip()
        ptype = p.get("product_type", "")
        meta = f" [{ptype}]" if ptype else ""
        if desc:
            lines.append(f"- {p['title']}{meta} | {url} | {desc[:120]}")
        else:
            lines.append(f"- {p['title']}{meta} | {url}")
    return "\n".join(lines)
