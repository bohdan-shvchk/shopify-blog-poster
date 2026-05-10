import json
import os
import re

from anthropic import Anthropic


_MODEL = "claude-haiku-4-5-20251001"


_SYSTEM_PROMPT = """You are an expert SEO content writer for an e-commerce store.
You write engaging, helpful blog posts that demonstrate first-hand experience and expertise (E-E-A-T).

Strict rules — NEVER violate:
1. NEVER invent product names, brand names, model numbers, or SKUs.
2. NEVER fabricate statistics, percentages, study results, or expert quotes.
3. NEVER reference products that are not in the provided product catalog.
   When you want to suggest a product, pick one from the catalog by its exact handle/URL.
   If no catalog product fits, write generically about the category instead — do not invent.
4. Cite 2-3 reputable external sources at the end (e.g., FDA, peer-reviewed journals,
   established publications). Only cite sources you are confident exist.
5. Return STRICT JSON only — no markdown, no commentary, no code fences."""


_USER_PROMPT = """Write a blog post for a {niche} store.

Topic: {topic}
Target audience: {audience}
Tone: {tone}
Language: {language}
Author: {author_name} — {author_bio}

PRODUCT CATALOG (the ONLY products you may mention by name or link):
{product_catalog}

Already-published topics (avoid overlap, do not rehash):
{published_topics}

Required structure:
- Engaging hook paragraph (personal, specific — frame as the author's perspective)
- "What you'll learn" / problem framing
- 3-5 H2 sections with H3 subsections where helpful
- Inside the body: 2-3 internal links using <a href="..."> tags pointing ONLY to URLs from
  the product catalog above. Use natural anchor text. If the catalog is empty or no product
  fits, OMIT product links entirely — do NOT invent any.
- An FAQ section with 3-5 questions (use <h2>FAQ</h2> + <h3>question</h3>)
- A "Sources" section at the end with 2-3 external citations as a <ul><li><a href="...">...</a></li></ul>

Length: 900-1400 words. Use semantic HTML (<h2>, <h3>, <p>, <ul>, <li>, <a>).

Return ONLY this exact JSON shape:
{{
  "title": "SEO-optimized title, max 60 chars",
  "meta_description": "Max 160 chars, includes the primary keyword",
  "tags": ["tag1", "tag2", "tag3"],
  "html_body": "<p>Hook…</p><h2>…</h2>…"
}}"""


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    return json.loads(raw.strip())


def generate_article(topic: str, config: dict, product_catalog_text: str, published_topics: list[str]) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    published_sample = "\n".join(f"- {t}" for t in published_topics[-15:]) or "- (none yet)"
    catalog = product_catalog_text.strip() or "(no products available — write educational content without product links)"

    prompt = _USER_PROMPT.format(
        niche=config["niche"],
        topic=topic,
        audience=config.get("audience", "general audience"),
        tone=config.get("tone", "friendly and informative"),
        language=config.get("language", "en"),
        author_name=config.get("author_name") or config.get("author", "Editorial Team"),
        author_bio=config.get("author_bio", "writes about consumer wellness products"),
        product_catalog=catalog,
        published_topics=published_sample,
    )

    response = client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json_response(response.content[0].text)
