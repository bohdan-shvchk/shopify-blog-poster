import json
import os
import re

from groq import Groq


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
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

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

    models = ["meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile"]
    last_error = None

    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            return _parse_json_response(response.choices[0].message.content)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"All models failed. Last error: {last_error}")
