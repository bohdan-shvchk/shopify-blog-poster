"""Fail-closed publication rules for approved SEO article briefs."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

from .slug import slugify

EXCLUDED_HOSTS = ("wikipedia.org", "youtube.com", "instagram.com", "facebook.com", "tiktok.com")


def load_policy(store_path: Path) -> dict:
    path = store_path / "seo_publication_policy.json"
    if not path.exists():
        raise ValueError("SEO publication policy is missing")
    return json.loads(path.read_text())


def review_brief(brief: dict, policy: dict, records: list[dict], public_domain: str) -> list[str]:
    errors = []
    if brief.get("approved") is not True:
        errors.append("SEO brief is not approved")
    keyword = str(brief.get("primary_keyword", "")).strip().lower()
    topic = str(brief.get("topic", "")).strip()
    target = str(brief.get("target_url", "")).strip().rstrip("/")
    if not keyword or not topic:
        errors.append("Primary keyword and topic are required")
    if brief.get("intent") != "informational":
        errors.append("New blog articles require informational search intent")
    if not target.startswith(public_domain.rstrip("/") + "/blogs/"):
        errors.append("Target URL must be an article URL on this store")
    cluster = str(brief.get("cluster_id", "")).strip().lower()
    if not cluster:
        errors.append("An approved search-intent cluster is required")
    if keyword and any(str(r.get("primary_keyword", "")).lower() == keyword for r in records):
        errors.append("This keyword has already been published")
    if target and any(str(r.get("target_url", "")).rstrip("/") == target for r in records):
        errors.append("This target URL has already been published")
    for owner in policy.get("existing_targets", []):
        if str(owner.get("primary_keyword", "")).strip().lower() == keyword and owner.get("target_url", "").rstrip("/") != target:
            errors.append("Keyword already belongs to another page")
        if cluster and str(owner.get("cluster_id", "")).strip().lower() == cluster and owner.get("target_url", "").rstrip("/") != target:
            errors.append("Search-intent cluster already belongs to another page")
    try:
        checked = date.fromisoformat(str(brief.get("serp_checked_at", "")))
        if checked < date.today() - timedelta(days=35) or checked > date.today():
            errors.append("SERP review is stale or in the future")
    except ValueError:
        errors.append("SERP review date is missing or invalid")
    pages = brief.get("serp_pages") or []
    eligible = []
    for page in pages:
        url = str(page.get("url", ""))
        host = (urlparse(url).hostname or "").lower()
        if not host or any(host == bad or host.endswith("." + bad) for bad in EXCLUDED_HOSTS):
            continue
        try:
            length = int(page.get("text_characters", 0))
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            eligible.append((url, length))
    if len({url for url, _ in eligible}) < 5:
        errors.append("Five distinct eligible SERP pages with text lengths are required")
    if keyword and any(str(b.get("primary_keyword", "")).strip().lower() == keyword and b is not brief for b in policy.get("approved_briefs", [])):
        errors.append("Primary keyword is duplicated across approved briefs")
    if cluster and any(str(b.get("cluster_id", "")).strip().lower() == cluster and b is not brief for b in policy.get("approved_briefs", [])):
        errors.append("Search-intent cluster is duplicated across approved briefs")
    if target and any(str(b.get("target_url", "")).rstrip("/") == target and b is not brief for b in policy.get("approved_briefs", [])):
        errors.append("Target URL is duplicated across approved briefs")
    return errors


def target_length(brief: dict) -> int:
    lengths = []
    for page in brief.get("serp_pages", []):
        host = (urlparse(str(page.get("url", ""))).hostname or "").lower()
        if any(host == bad or host.endswith("." + bad) for bad in EXCLUDED_HOSTS):
            continue
        try:
            length = int(page.get("text_characters", 0))
        except (TypeError, ValueError):
            continue
        if length > 0:
            lengths.append(length)
    return max(1200, round(sum(lengths) / len(lengths))) if lengths else 1200


def review_article(article: dict, brief: dict, public_domain: str) -> list[str]:
    errors = []
    text = unescape(re.sub(r"<[^>]+>", " ", article.get("html_body", "")))
    text = " ".join(text.split())
    if len(text) < target_length(brief):
        errors.append(f"Article has {len(text)} characters; target is {target_length(brief)}")
    expected = public_domain.rstrip("/") + "/blogs/" + str(brief.get("blog_handle", "news")) + "/" + slugify(article.get("title", ""))
    if expected != str(brief.get("target_url", "")).rstrip("/"):
        errors.append("Generated title does not match the approved target URL")
    return errors
