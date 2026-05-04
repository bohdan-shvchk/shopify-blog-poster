import os
import requests


_ARTICLE_CREATE = """
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article {
      id
      title
      handle
      publishedAt
    }
    userErrors {
      field
      message
    }
  }
}
"""


def publish_article(
    article: dict,
    config: dict,
    image_url=None,
) -> dict:
    domain = config["shopify_domain"]
    blog_id = config["blog_id"]
    token = os.environ["SHOPIFY_TOKEN"]

    variables = {
        "article": {
            "blogId": blog_id,
            "title": article["title"],
            "body": article["html_body"],
            "tags": article.get("tags", []),
            "author": {"name": config.get("author", "Editorial Team")},
        }
    }

    if image_url:
        variables["article"]["image"] = {"url": image_url}

    if article.get("meta_description"):
        variables["article"]["metafields"] = [
            {
                "namespace": "seo",
                "key": "description",
                "value": article["meta_description"],
                "type": "single_line_text_field",
            }
        ]

    resp = requests.post(
        f"https://{domain}/admin/api/2024-10/graphql.json",
        json={"query": _ARTICLE_CREATE, "variables": variables},
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    errors = data.get("data", {}).get("articleCreate", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"Shopify errors: {errors}")

    return data["data"]["articleCreate"]["article"]
