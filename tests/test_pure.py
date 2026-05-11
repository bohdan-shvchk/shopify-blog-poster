"""Tests for pure functions — no network, no model loading.

Modules with side effects (dedup loads sentence-transformers; topic_pool, products,
publisher hit disk/network) are exercised only at the helper-function layer.
"""
from __future__ import annotations

import unittest

from modules import quality, style, topic_finder
from modules.image_fetcher import count_h2, topic_to_keywords
from modules.publisher import (
    _extract_faq_pairs,
    _extract_product_handles,
    _product_schemas,
    _word_count,
)
from modules.slug import slugify
from modules.topic_pool import _days_since, _effective_score


class StylePicker(unittest.TestCase):
    def test_myth_busting_wins_over_other_keywords(self):
        self.assertEqual(style.pick_style("The truth about retinol myths debunked"), "myth_busting")
        self.assertEqual(style.pick_style("5 misconceptions about SPF"), "myth_busting")

    def test_how_to(self):
        self.assertEqual(style.pick_style("How to apply mineral sunscreen"), "how_to")
        self.assertEqual(style.pick_style("Step-by-step guide to applying foundation"), "how_to")

    def test_comparison(self):
        self.assertEqual(style.pick_style("LED mask vs microcurrent: which is better"), "comparison")

    def test_buyers_guide(self):
        self.assertEqual(style.pick_style("Best vitamin C serum for sensitive skin"), "buyers_guide")
        self.assertEqual(style.pick_style("Top 5 retinol creams under $50"), "buyers_guide")

    def test_quick_tips(self):
        self.assertEqual(style.pick_style("7 tips for clearer skin"), "quick_tips")

    def test_default_deep_dive(self):
        self.assertEqual(style.pick_style("Niacinamide and the skin barrier"), "deep_dive")

    def test_ranked_starts_with_primary(self):
        ranked = style.ranked_styles("How to apply sunscreen")
        self.assertEqual(ranked[0], "how_to")
        self.assertEqual(set(ranked), set(style.STYLES.keys()))


class QualityValidators(unittest.TestCase):
    def test_extract_product_handles(self):
        html = '<a href="/products/foo-bar">x</a><a href="https://shop.com/products/baz">y</a>'
        self.assertEqual(quality.extract_product_handles(html), ["foo-bar", "baz"])

    def test_extract_external_urls_excludes_products(self):
        html = '<a href="https://example.com/x">e</a><a href="https://shop.com/products/baz">p</a>'
        self.assertEqual(quality.extract_external_urls(html), ["https://example.com/x"])

    def test_validate_products_mentioned(self):
        catalog = [{"handle": "real-one"}]
        ok, invalid = quality.validate_products_mentioned(
            '<a href="/products/real-one">a</a><a href="/products/fake">b</a>', catalog
        )
        self.assertFalse(ok)
        self.assertEqual(invalid, ["fake"])

    def test_validate_length(self):
        ok, words = quality.validate_length("<p>" + ("word " * 900) + "</p>")
        self.assertTrue(ok)
        self.assertEqual(words, 900)
        ok2, _ = quality.validate_length("<p>too short</p>")
        self.assertFalse(ok2)

    def test_validate_structure_h2_count(self):
        html = "<h2>a</h2><h2>b</h2>"
        reasons = quality.validate_structure(html, style_key="how_to")
        self.assertTrue(any("too few H2" in r for r in reasons))

    def test_validate_structure_hierarchy(self):
        html = "<h3>orphan</h3><h2>finally</h2>"
        reasons = quality.validate_structure(html, style_key=None)
        self.assertTrue(any("H3 appears before any H2" in r for r in reasons))

    def test_validate_structure_ok(self):
        html = "<h2>a</h2><h3>sub</h3><h2>b</h2><h2>c</h2><h2>d</h2>"
        self.assertEqual(quality.validate_structure(html, style_key="how_to"), [])

    def test_collect_warnings_known_org_whitelisted(self):
        html = "<p>Mayo Clinic and Harvard University researchers found...</p>"
        warnings = quality.collect_warnings(html)
        self.assertFalse(any("quasi-organizations" in w for w in warnings))

    def test_collect_warnings_flags_unknown_quasi_org(self):
        html = "<p>Acme Labs published a paper.</p>"
        warnings = quality.collect_warnings(html)
        self.assertTrue(any("quasi-organizations" in w for w in warnings))

    def test_collect_warnings_stats_and_experts(self):
        html = '<p>Dr. Jane Smith says 87% of people benefit.</p>'
        warnings = quality.collect_warnings(html)
        self.assertTrue(any("numeric stats" in w for w in warnings))
        self.assertTrue(any("'Dr. X'-style experts" in w for w in warnings))

    def test_filter_fixable_strips_url_reasons(self):
        reasons = [
            "too short: 100 words (min 800)",
            "broken external URLs: ['https://x.com (404)']",
            "title too long: 70 chars (max 60)",
        ]
        self.assertEqual(
            quality.filter_fixable(reasons),
            ["too short: 100 words (min 800)", "title too long: 70 chars (max 60)"],
        )


class ImageHelpers(unittest.TestCase):
    def test_topic_to_keywords_drops_stopwords_and_year(self):
        self.assertEqual(topic_to_keywords("The best retinol serum 2026 guide"), "retinol serum")

    def test_topic_to_keywords_handles_punctuation(self):
        self.assertEqual(topic_to_keywords("LED Mask vs Microcurrent: Which Wins?"), "led mask microcurrent")

    def test_topic_to_keywords_fallback_when_all_stopwords(self):
        self.assertEqual(topic_to_keywords("the best of you"), "the best of you")

    def test_count_h2(self):
        self.assertEqual(count_h2("<h2>a</h2><H2 class='x'>b</H2><h3>c</h3>"), 2)


class TopicFinderHelpers(unittest.TestCase):
    def test_split_title_and_source(self):
        self.assertEqual(
            topic_finder._split_title_and_source("Best foo - Reuters"),
            ("Best foo", "Reuters"),
        )
        self.assertEqual(
            topic_finder._split_title_and_source("How to do X - in 5 minutes - The Verge"),
            ("How to do X - in 5 minutes", "The Verge"),
        )
        self.assertEqual(topic_finder._split_title_and_source("No source here"), ("No source here", ""))

    def test_source_to_domain_known(self):
        self.assertEqual(topic_finder._source_to_domain("Reuters"), "reuters.com")
        self.assertEqual(topic_finder._source_to_domain("Mayo Clinic"), "mayoclinic.org")

    def test_source_to_domain_unknown_falls_back(self):
        self.assertEqual(topic_finder._source_to_domain("Unknown Site"), "unknownsite")

    def test_domain_weight_known(self):
        self.assertEqual(topic_finder._domain_weight("reuters.com"), 1.5)
        self.assertEqual(topic_finder._domain_weight("www.reuters.com"), 1.5)
        self.assertEqual(topic_finder._domain_weight("news.reuters.com"), 1.5)

    def test_domain_weight_unknown(self):
        self.assertEqual(topic_finder._domain_weight("randomblog.example"), 1.0)
        self.assertEqual(topic_finder._domain_weight(""), 1.0)

    def test_domain_from_link_strips_www(self):
        self.assertEqual(topic_finder._domain_from_link("https://www.example.com/path"), "example.com")
        self.assertEqual(topic_finder._domain_from_link("https://wwwgreat.example/x"), "wwwgreat.example")
        self.assertEqual(topic_finder._domain_from_link("not-a-url"), "")

    def test_score_priority_prefix(self):
        with_prefix = topic_finder._score("How to apply sunscreen properly", source_count=1, domain_weight=1.0)
        without_prefix = topic_finder._score("Sunscreen application notes", source_count=1, domain_weight=1.0)
        self.assertGreater(with_prefix, without_prefix)

    def test_score_domain_multiplier(self):
        weighted = topic_finder._score("How to apply sunscreen properly", 1, 1.5)
        plain = topic_finder._score("How to apply sunscreen properly", 1, 1.0)
        self.assertAlmostEqual(weighted / plain, 1.5)


class TopicPoolDecay(unittest.TestCase):
    def test_days_since_invalid(self):
        self.assertEqual(_days_since(""), 0)
        self.assertEqual(_days_since("not-a-date"), 0)

    def test_effective_score_decays(self):
        from datetime import date, timedelta
        ten_days_ago = (date.today() - timedelta(days=10)).isoformat()
        fresh = {"score": 5.0, "found_date": date.today().isoformat()}
        old = {"score": 5.0, "found_date": ten_days_ago}
        self.assertGreater(_effective_score(fresh), _effective_score(old))
        self.assertAlmostEqual(_effective_score(old), 5.0 - 10 * 0.05)


class PublisherHelpers(unittest.TestCase):
    def test_word_count_strips_tags(self):
        self.assertEqual(_word_count("<p>one two three</p><h2>four</h2>"), 4)

    def test_extract_faq_pairs(self):
        html = (
            "<h2>FAQ</h2>"
            "<h3>What is X?</h3><p>X is a thing.</p>"
            "<h3>Why Y?</h3><p>Because Y.</p>"
            "<h2>Sources</h2><p>...</p>"
        )
        pairs = _extract_faq_pairs(html)
        self.assertEqual(pairs, [("What is X?", "X is a thing."), ("Why Y?", "Because Y.")])

    def test_extract_faq_pairs_no_section(self):
        self.assertEqual(_extract_faq_pairs("<h2>Intro</h2><p>no faq here</p>"), [])

    def test_extract_faq_pairs_full_phrase(self):
        html = (
            "<h2>Frequently Asked Questions</h2>"
            "<h3>Q1?</h3><p>A1.</p>"
            "<h2>Sources</h2>"
        )
        self.assertEqual(_extract_faq_pairs(html), [("Q1?", "A1.")])

    def test_extract_faq_pairs_questions_and_answers(self):
        html = "<h2>Questions &amp; Answers</h2><h3>Q?</h3><p>A.</p><h2>End</h2>"
        self.assertEqual(_extract_faq_pairs(html), [("Q?", "A.")])

    def test_extract_product_handles_dedupes_and_preserves_order(self):
        html = (
            '<a href="/products/foo">a</a>'
            '<a href="https://shop.com/products/bar">b</a>'
            '<a href="/products/foo?ref=2">c</a>'
        )
        self.assertEqual(_extract_product_handles(html), ["foo", "bar"])

    def test_product_schemas_use_catalog_names(self):
        html = '<a href="/products/foo">link text</a><a href="/products/missing">x</a>'
        catalog = [{"handle": "foo", "title": "Real Foo Product"}]
        schemas = _product_schemas(html, catalog, "https://shop.example")
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["name"], "Real Foo Product")
        self.assertEqual(schemas[0]["url"], "https://shop.example/products/foo")
        self.assertEqual(schemas[0]["@type"], "Product")

    def test_product_schemas_empty_when_no_catalog(self):
        html = '<a href="/products/foo">x</a>'
        self.assertEqual(_product_schemas(html, None, "https://shop.example"), [])
        self.assertEqual(_product_schemas(html, [], "https://shop.example"), [])


class StyleStructureSourceOfTruth(unittest.TestCase):
    def test_min_h2_for_each_style(self):
        for key in style.STYLES:
            self.assertIsInstance(style.min_h2(key), int)
            self.assertGreaterEqual(style.min_h2(key), 1)

    def test_min_h2_unknown_falls_back(self):
        self.assertEqual(style.min_h2("nonexistent"), 4)

    def test_quality_uses_style_min_h2(self):
        # quick_tips requires 6 H2; 4 should fail.
        html = "<h2>1</h2><h2>2</h2><h2>3</h2><h2>4</h2>"
        reasons = quality.validate_structure(html, style_key="quick_tips")
        self.assertTrue(any("4 < 6" in r for r in reasons))


class SlugifyShared(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")
        self.assertEqual(slugify("  Foo Bar Baz  "), "foo-bar-baz")
        self.assertEqual(slugify("LED Mask vs. Microcurrent: Which Wins?"), "led-mask-vs-microcurrent-which-wins")
        self.assertEqual(slugify("under_score and-hyphens"), "under-score-and-hyphens")


if __name__ == "__main__":
    unittest.main()
