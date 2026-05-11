"""Single source of truth for slug generation.

Used by poster.py (history records) and publisher.py (canonical URL prediction).
The two used to maintain duplicate inline implementations; any drift between
them caused the schema URL to diverge from the actual Shopify handle.
"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)
