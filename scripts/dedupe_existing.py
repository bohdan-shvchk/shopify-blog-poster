#!/usr/bin/env python3
"""One-time cleanup of stores/*/published_slugs.json: remove duplicate slugs and topics,
keeping the earliest record. Run from project root."""
import json
import sys
from pathlib import Path


def dedupe_store(store_path: Path) -> None:
    slugs_file = store_path / "published_slugs.json"
    if not slugs_file.exists():
        return

    with open(slugs_file) as f:
        records = json.load(f)

    seen_slugs = set()
    seen_topics = set()
    cleaned = []
    for rec in records:
        slug = rec.get("slug", "").strip()
        topic = (rec.get("topic") or "").strip().lower()
        if slug and slug in seen_slugs:
            continue
        if topic and topic in seen_topics:
            continue
        if slug:
            seen_slugs.add(slug)
        if topic:
            seen_topics.add(topic)
        cleaned.append(rec)

    if len(cleaned) == len(records):
        print(f"{store_path.name}: no duplicates")
        return

    with open(slugs_file, "w") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
    print(f"{store_path.name}: {len(records)} → {len(cleaned)} records")


def main() -> None:
    stores_dir = Path("stores")
    if not stores_dir.exists():
        print("stores/ not found — run from project root")
        sys.exit(1)
    for store in sorted(stores_dir.iterdir()):
        if store.is_dir():
            dedupe_store(store)


if __name__ == "__main__":
    main()
