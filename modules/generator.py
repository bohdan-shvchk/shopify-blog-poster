import os
import time

import anthropic
from anthropic import Anthropic

from . import style as style_module


_RETRYABLE = (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError)


def _create_with_backoff(client, **kwargs):
    """Retry on 429 / 5xx / connection errors with exponential backoff.
    Total wait across 4 attempts: 0 + 2 + 4 + 8 = 14s (last attempt re-raises)."""
    for attempt in range(4):
        try:
            return client.messages.create(**kwargs)
        except _RETRYABLE:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


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

Return the article by calling the `submit_article` tool with the required fields."""


_ARTICLE_TOOL = {
    "name": "submit_article",
    "description": "Submit the finished blog post. All fields are required.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "SEO-optimized title, max 60 characters.",
            },
            "meta_description": {
                "type": "string",
                "description": "Meta description, max 160 characters, includes the primary keyword.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-6 short topical tags.",
            },
            "html_body": {
                "type": "string",
                "description": "Article body as semantic HTML (h2/h3/p/ul/li/a). No h1. 900-1400 words.",
            },
        },
        "required": ["title", "meta_description", "tags", "html_body"],
    },
}


_USER_PROMPT = """Write a blog post for a {niche} store.

Topic: {topic}
Target audience: {audience}
Tone: {tone}
Language: {language}
Author: {author_name} — {author_bio}

PRODUCT CATALOG (the ONLY products you may mention by name or link):
{product_catalog}
{category_links_block}
Already-published topics (avoid overlap, do not rehash):
{published_topics}
{style_block}{previous_failure_block}
Universal rules (apply on top of the format above):
- Use semantic HTML only: <h2>, <h3>, <p>, <ul>, <li>, <a>. Never use <h1>.
- Inside the body: EXACTLY 2-3 internal links total — never more than 3.
  Prefer a mix: 1-2 product links from the catalog above + 1 link to a category page
  from the "Category links" list (if provided). Use natural anchor text.
  Do NOT invent URLs. If the catalog is empty AND no category fits, omit links entirely.
- The FAQ section uses <h2>FAQ</h2> with <h3> for each question.
- The Sources section is a <ul><li><a href="...">...</a></li></ul> with 2-3 external citations.

Length: strictly 900-1400 words.
{relationship_block}
Call the `submit_article` tool with: title, meta_description, tags, html_body."""


def _extract_tool_input(response, tool_name: str) -> dict:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(
        f"Model did not call tool '{tool_name}'. Stop reason: {response.stop_reason}"
    )


def _category_links_block(config: dict) -> str:
    """Render the category/collection links from config.internal_links so the
    model can include one in the article body for topical clustering."""
    links = config.get("internal_links") or []
    categories = [
        l for l in links
        if "/collections/" in (l.get("url") or "") and l.get("anchor") and l.get("url")
    ]
    if not categories:
        return ""
    bullets = "\n".join(f'- "{l["anchor"]}" → {l["url"]}' for l in categories)
    return f"\nCategory links you may use (in addition to the product catalog):\n{bullets}\n"


def _previous_failure_block(reasons: list[str] | None) -> str:
    if not reasons:
        return ""
    bullets = "\n".join(f"- {r}" for r in reasons)
    return (
        "\nPREVIOUS ATTEMPT FAILED quality validation. Fix specifically these issues this time:\n"
        f"{bullets}\n"
    )


def _relationship_block(relationship: dict | None) -> str:
    if not relationship:
        return ""
    rel = relationship.get("relationship")
    related = relationship.get("related_topic")
    if rel == "CONTINUATION" and related:
        return (
            "\nRELATIONSHIP TO PRIOR CONTENT — CONTINUATION:\n"
            f"This post is a follow-up to a recent article titled: \"{related}\".\n"
            "In the hook paragraph, naturally reference that prior post (e.g., \"In our recent article on …\")"
            " and frame this one as the next logical step. Build deeper, do NOT rehash.\n"
        )
    if rel == "FORCED" and related:
        return (
            "\nRELATIONSHIP TO PRIOR CONTENT — DIFFERENTIATE:\n"
            f"We have already published an article titled: \"{related}\".\n"
            "Acknowledge the overlap briefly in the hook (e.g., \"While we've previously covered …\")"
            " and then take a clearly different angle — do NOT repeat the same advice.\n"
        )
    return ""


def generate_article(
    topic: str,
    config: dict,
    product_catalog_text: str,
    published_topics: list[str],
    relationship: dict | None = None,
    style_key: str | None = None,
    previous_failure_reasons: list[str] | None = None,
) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    published_sample = "\n".join(f"- {t}" for t in published_topics) or "- (none yet)"
    catalog = product_catalog_text.strip() or "(no products available — write educational content without product links)"
    style_block = style_module.render(style_key or style_module.pick_style(topic))

    prompt = _USER_PROMPT.format(
        niche=config["niche"],
        topic=topic,
        audience=config.get("audience", "general audience"),
        tone=config.get("tone", "friendly and informative"),
        language=config.get("language", "en"),
        author_name=config.get("author_name") or config.get("author", "Editorial Team"),
        author_bio=config.get("author_bio", "writes about consumer wellness products"),
        product_catalog=catalog,
        category_links_block=_category_links_block(config),
        published_topics=published_sample,
        relationship_block=_relationship_block(relationship),
        style_block=style_block,
        previous_failure_block=_previous_failure_block(previous_failure_reasons),
    )

    response = _create_with_backoff(
        client,
        model=_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        tools=[_ARTICLE_TOOL],
        tool_choice={"type": "tool", "name": "submit_article"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_tool_input(response, "submit_article")
