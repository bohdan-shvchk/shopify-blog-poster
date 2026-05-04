#!/usr/bin/env python3
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from modules.generator import generate_article
from modules.image_fetcher import fetch_images, inject_images_into_html
from modules.publisher import publish_article
from modules.topic_finder import find_topic


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def load_config(store_path: Path) -> dict:
    with open(store_path / "store_config.json") as f:
        return json.load(f)


def load_published_slugs(store_path: Path) -> list[dict]:
    slugs_file = store_path / "published_slugs.json"
    if not slugs_file.exists():
        return []
    with open(slugs_file) as f:
        return json.load(f)


def save_published_slug(store_path: Path, slug: str):
    slugs = load_published_slugs(store_path)
    slugs.append({"slug": slug, "date": date.today().isoformat()})
    with open(store_path / "published_slugs.json", "w") as f:
        json.dump(slugs, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True, help="Store folder name under stores/")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't publish")
    args = parser.parse_args()

    store_path = Path("stores") / args.store
    if not store_path.exists():
        print(f"Store folder not found: {store_path}")
        sys.exit(1)

    config = load_config(store_path)
    published = load_published_slugs(store_path)
    published_slug_list = [item["slug"] for item in published]

    print(f"[1/4] Finding topic for '{config['niche']}'...")
    topic = find_topic(config, store_path)
    print(f"      Topic: {topic}")

    print("[2/4] Generating article with Groq...")
    article = generate_article(topic, config, published_slug_list)
    print(f"      Title: {article['title']}")

    print("[3/4] Fetching images...")
    image_query = config.get("unsplash_query", config["niche"])
    images = fetch_images(image_query, count=3)
    cover_image = images[0] if images else None
    print(f"      Cover: {cover_image or 'none'}")
    print(f"      Inline images: {len(images[1:])}")

    if images[1:]:
        article["html_body"] = inject_images_into_html(article["html_body"], images[1:])

    if args.dry_run:
        print("\n--- DRY RUN: not publishing ---")
        print(json.dumps(article, indent=2, ensure_ascii=False))
        return

    print("[4/4] Publishing to Shopify...")
    result = publish_article(article, config, cover_image)
    print(f"      Published: {result['handle']} (id: {result['id']})")

    slug = slugify(article["title"])
    save_published_slug(store_path, slug)
    print(f"      Slug saved: {slug}")
    print("\nDone.")


if __name__ == "__main__":
    main()
