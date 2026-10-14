# SEO publication gate

The scheduled run reads `stores/my-store/seo_publication_policy.json`. It publishes no new article while `approved_briefs` is empty. This is intentional: the older RSS and evergreen topic sources remain in the repository but are no longer used for publication.

Each approved brief needs `approved: true`, a unique `cluster_id`, `primary_keyword`, informational `intent`, `topic`, `target_url`, `blog_handle`, `serp_checked_at` (YYYY-MM-DD), and five distinct eligible `serp_pages`. Each SERP page has `url` and `text_characters`; Wikipedia, YouTube, Instagram, Facebook, and TikTok do not count. The review must be at most 35 days old. The planned article must be at least 1,200 characters and at least the mean character count of the eligible pages. Published or already owned keywords and clusters are rejected. The generated title must resolve to the approved article URL.

Example brief (illustrative only; do not approve without real research):

```json
{
  "approved": false,
  "cluster_id": "example-unique-intent",
  "primary_keyword": "example informational query",
  "intent": "informational",
  "topic": "Example reader question",
  "target_url": "https://lunara-light.com/blogs/news/example-reader-question",
  "blog_handle": "news",
  "serp_checked_at": "2026-10-14",
  "serp_pages": [
    {"url": "https://example.org/page-one", "text_characters": 2300}
  ]
}
```

No brief is approved in the committed policy. The gate does not itself fetch Google results or select keywords; those inputs must be prepared and reviewed separately. If the gate rejects a brief or article, it alerts through the existing Telegram channel when configured and does not publish.
