import json
import os
import re
from groq import Groq


_SYSTEM_PROMPT = """You are an expert SEO content writer for e-commerce stores.
You write engaging, helpful blog posts that rank well on Google.
Never invent statistics or fake quotes. Always return valid JSON only."""

_USER_PROMPT = """Write a blog post for a {niche} store.

Topic: {topic}
Target audience: {audience}
Tone: {tone}
Language: {language}

Structure required:
- Hook (engaging opening paragraph)
- Problem section
- Solution / main content with H2 and H3 headings
- 2-3 internal product links from the list below (use naturally, as anchor text)
- Call to action (CTA)
- FAQ section (3-5 questions)

Length: 1000-1500 words.

Internal links to include (pick 1-2 most relevant):
{internal_links}

Do NOT repeat these already published topics:
{published_topics}

Return ONLY valid JSON in this exact format:
{{
  "title": "SEO-optimized title (max 60 chars)",
  "meta_description": "Meta description (max 160 chars)",
  "tags": ["tag1", "tag2", "tag3"],
  "html_body": "<h2>...</h2><p>...</p>..."
}}"""


def generate_article(topic: str, config: dict, published_slugs: list[str]) -> dict:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    internal_links_text = "\n".join(
        f"- [{link['anchor']}]({link['url']})"
        for link in config.get("internal_links", [])
    )

    published_sample = ", ".join(published_slugs[-10:]) if published_slugs else "none"

    prompt = _USER_PROMPT.format(
        niche=config["niche"],
        topic=topic,
        audience=config.get("audience", "general audience"),
        tone=config.get("tone", "friendly and informative"),
        language=config.get("language", "en"),
        internal_links=internal_links_text or "none",
        published_topics=published_sample,
    )

    models = ["meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.3-70b-versatile"]

    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            # strip markdown code fences if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            # extract JSON object if there's extra text around it
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]
            # remove control characters that break JSON parsing
            raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
            return json.loads(raw.strip())
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"All models failed. Last error: {last_error}")
