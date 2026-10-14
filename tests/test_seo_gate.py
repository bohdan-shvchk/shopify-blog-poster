import unittest
from datetime import date

from modules import seo_gate


class SeoPublicationGate(unittest.TestCase):
    def setUp(self):
        self.brief = {
            "approved": True,
            "topic": "How to choose an LED device",
            "primary_keyword": "choose led device",
            "cluster_id": "led-device-choices",
            "intent": "informational",
            "target_url": "https://lunara-light.com/blogs/news/how-to-choose-an-led-device",
            "serp_checked_at": date.today().isoformat(),
            "serp_pages": [
                {"url": f"https://example{i}.com/guide", "text_characters": 1500}
                for i in range(5)
            ],
        }

    def test_valid_brief_and_article_pass(self):
        self.assertEqual(seo_gate.review_brief(self.brief, {"existing_targets": [], "approved_briefs": [self.brief]}, [], "https://lunara-light.com"), [])
        article = {"title": "How to Choose an LED Device", "html_body": "<p>" + "useful text " * 140 + "</p>"}
        self.assertEqual(seo_gate.review_article(article, self.brief, "https://lunara-light.com"), [])

    def test_existing_cluster_blocks_new_article(self):
        policy = {"existing_targets": [{"cluster_id": "led-device-choices", "target_url": "https://lunara-light.com/collections/led-therapy"}], "approved_briefs": [self.brief]}
        self.assertIn("Search-intent cluster already belongs to another page", seo_gate.review_brief(self.brief, policy, [], "https://lunara-light.com"))

    def test_excluded_serp_and_short_article_block(self):
        self.brief["serp_pages"][0]["url"] = "https://www.youtube.com/watch?v=1"
        self.assertIn("Five distinct eligible SERP pages with text lengths are required", seo_gate.review_brief(self.brief, {}, [], "https://lunara-light.com"))
        self.assertTrue(seo_gate.review_article({"title": "How to Choose an LED Device", "html_body": "<p>Short</p>"}, self.brief, "https://lunara-light.com"))

    def test_wrong_slug_blocks(self):
        article = {"title": "Different Title", "html_body": "<p>" + "useful text " * 140 + "</p>"}
        self.assertIn("Generated title does not match the approved target URL", seo_gate.review_article(article, self.brief, "https://lunara-light.com"))


if __name__ == "__main__":
    unittest.main()
