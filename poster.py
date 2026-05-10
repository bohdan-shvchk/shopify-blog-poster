#!/usr/bin/env python3
import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

from modules import conflict, dedup, evergreen, products, quality, style, topic_finder, topic_pool
from modules.generator import generate_article
from modules.image_fetcher import fetch_images, inject_images_into_html
from modules.publisher import publish_article


_MAX_GENERATION_RETRIES = 2
_MAX_TOPIC_FALLBACKS = 3


def send_telegram(message: str) -> None:
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(f"[Telegram skipped] {message}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": f"[Shopify] {message}"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram failed: {e}")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def load_config(store_path: Path) -> dict:
    with open(store_path / "store_config.json") as f:
        return json.load(f)


def load_published(store_path: Path) -> list:
    f = store_path / "published_slugs.json"
    if not f.exists():
        return []
    with open(f) as fp:
        return json.load(fp)


def save_published(store_path: Path, records: list) -> None:
    with open(store_path / "published_slugs.json", "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def backfill_embeddings(records: list) -> list:
    """Compute and store embeddings for legacy records that have a topic but no embedding."""
    changed = False
    for rec in records:
        topic = rec.get("topic")
        if topic and not rec.get("embedding"):
            rec["embedding"] = dedup.embed(topic)
            changed = True
    return records if changed else records


def published_embeddings(records: list) -> list:
    return [r["embedding"] for r in records if r.get("embedding")]


def published_topics(records: list) -> list:
    return [r["topic"] for r in records if r.get("topic")]


def select_topic(store_path: Path, config: dict, pub_embeddings: list, pub_topics: list):
    """Returns dict with keys topic, source, embedding. None if nothing safe."""
    # 1. fresh RSS candidates → pool
    print("       discovering candidates from RSS...")
    candidates = topic_finder.discover_candidates(config)
    added = topic_pool.add_candidates(store_path, candidates, pub_embeddings)
    print(f"       added {added} new candidates to pool")

    # 2. best from pool
    pick = topic_pool.pick_best(store_path, pub_embeddings)
    if pick:
        return pick

    # 3. fallback to evergreen bank
    print("       pool exhausted, trying evergreen bank...")
    unused = evergreen.get_unused(config, pub_embeddings)
    if unused:
        topic = unused[0]
        return {"topic": topic, "source": "evergreen", "embedding": dedup.embed(topic)}

    # 4. last resort: ask LLM for fresh evergreen
    print("       evergreen bank exhausted, asking LLM for new ideas...")
    new_topics = evergreen.replenish(config, pub_topics, n=20)
    for t in new_topics:
        emb = dedup.embed(t)
        if not pub_embeddings or dedup.find_most_similar(emb, pub_embeddings)[1] < 0.75:
            return {"topic": t, "source": "ai_generated", "embedding": emb}
    return None


def generate_with_quality_gate(
    topic: str,
    config: dict,
    catalog: list,
    pub_topics: list,
    relationship: dict | None = None,
) -> dict:
    catalog_text = products.format_for_prompt(catalog, config) if catalog else ""
    style_order = style.ranked_styles(topic)
    last_reasons = []
    for attempt in range(_MAX_GENERATION_RETRIES + 1):
        style_key = style_order[attempt % len(style_order)]
        print(f"       attempt {attempt + 1}/{_MAX_GENERATION_RETRIES + 1} — style: {style.STYLES[style_key]['name']}")
        article = generate_article(
            topic, config, catalog_text, pub_topics,
            relationship=relationship, style_key=style_key,
        )
        ok, reasons, warnings = quality.validate_article(article, catalog)
        if warnings:
            for w in warnings:
                print(f"       WARN: {w}")
            send_telegram(f"Quality warnings for '{topic}':\n" + "\n".join(f"- {w}" for w in warnings))
        if ok:
            return article
        last_reasons = reasons
        print(f"       quality check failed: {reasons}")
    raise RuntimeError(f"Could not produce a valid article: {last_reasons}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    store_path = Path("stores") / args.store
    if not store_path.exists():
        print(f"Store folder not found: {store_path}")
        sys.exit(1)

    config = load_config(store_path)

    print(f"[1/6] Loading history for '{config['niche']}'...")
    pub_records = backfill_embeddings(load_published(store_path))
    save_published(store_path, pub_records)
    pub_embeddings = published_embeddings(pub_records)
    pub_topics = published_topics(pub_records)
    print(f"      {len(pub_records)} previously published, {len(pub_embeddings)} with embeddings")

    print("[2/6] Selecting topic...")
    pick = None
    for _ in range(_MAX_TOPIC_FALLBACKS):
        pick = select_topic(store_path, config, pub_embeddings, pub_topics)
        if pick:
            break
    if not pick:
        print("ERROR: no safe topic could be found. Skipping today.")
        send_telegram("No safe topic found. Skipping today.")
        sys.exit(0)
    topic = pick["topic"]
    print(f"      Topic: {topic}  (source: {pick['source']})")

    print("[3/6] Fetching product catalog...")
    try:
        catalog = products.get_products(store_path, config)
    except Exception as e:
        print(f"      WARN: could not fetch products: {e}")
        send_telegram(f"WARN: product fetch failed: {e}")
        catalog = []
    print(f"      {len(catalog)} active products available for grounding")

    print("[3.5/6] Classifying topic relationship to recent posts...")
    recent_topics_newest_first = list(reversed(pub_topics))
    try:
        relationship = conflict.classify(topic, recent_topics_newest_first, n=5)
    except Exception as e:
        print(f"      WARN: classifier failed: {e} (treating as NEW)")
        relationship = {"relationship": "NEW", "related_topic": None, "rationale": str(e)}
    print(f"      Relationship: {relationship['relationship']} — {relationship['rationale']}")

    print("[4/6] Generating article (with quality gate)...")
    try:
        article = generate_with_quality_gate(topic, config, catalog, pub_topics, relationship=relationship)
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        send_telegram(f"Generation failed for topic: {topic}\n{type(e).__name__}: {e}")
        sys.exit(0)
    print(f"      Title: {article['title']}")

    print("[5/6] Fetching images...")
    fallback_query = config.get("image_query") or config["niche"]
    images = fetch_images(primary_query=topic, fallback_query=fallback_query, count=3)
    cover_image = images[0] if images else None
    print(f"      Cover: {cover_image or 'none'}")
    print(f"      Inline images: {len(images[1:])}")
    if images[1:]:
        article["html_body"] = inject_images_into_html(article["html_body"], images[1:], topic=topic)

    if args.dry_run:
        print("\n--- DRY RUN: not publishing ---")
        print(json.dumps(article, indent=2, ensure_ascii=False))
        return

    print("[6/6] Publishing to Shopify...")
    result = publish_article(article, config, cover_image)
    print(f"      Published: {result['handle']} (id: {result['id']})")

    slug = slugify(article["title"])
    pub_records.append({
        "slug": slug,
        "topic": topic,
        "date": date.today().isoformat(),
        "source": pick["source"],
        "embedding": pick["embedding"],
    })
    save_published(store_path, pub_records)
    topic_pool.remove(store_path, topic)
    send_telegram(f"Published: {article['title']}")
    print(f"      Slug saved: {slug}")
    print("\nDone.")


if __name__ == "__main__":
    main()
