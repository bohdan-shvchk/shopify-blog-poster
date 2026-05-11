"""Style templates for article generation.

Six distinct article formats. Each has a name (for logging), a structure
fragment that overrides the default section list in the generator prompt,
and a tone/intent fragment.

Picker is rule-based on topic keywords; falls back to deep_dive.
The full ranked list is exposed so the generator can rotate through styles
on retry instead of regenerating the same shape.
"""
from __future__ import annotations

import re


STYLES = {
    "how_to": {
        "name": "How-To Tutorial",
        "min_h2": 4,
        "structure": (
            "- Hook: a concrete moment when the reader needs this skill — author's own first try.\n"
            "- 'What you'll need' — short list of tools / products / prerequisites.\n"
            "- 3-6 H2 sections, each one a numbered step (e.g., 'Step 1: ...'). "
            "Inside each step use H3 for sub-actions or warnings.\n"
            "- 'Common mistakes' H2 with 3-4 pitfalls and how to avoid them.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources."
        ),
        "intent": (
            "Write as a walkthrough: imperative verbs, second-person ('you'), "
            "explicit ordering. The reader should be able to follow along step by step."
        ),
    },
    "comparison": {
        "name": "Comparison / Versus",
        "min_h2": 4,
        "structure": (
            "- Hook: why the choice matters — set up the dilemma.\n"
            "- 'At a glance' H2 with a brief side-by-side summary.\n"
            "- One H2 per option being compared. Each option H2 covers: "
            "what it is, who it suits, pros, cons.\n"
            "- 'Which one should you pick?' H2 with 2-3 use-case recommendations.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources."
        ),
        "intent": (
            "Be even-handed: each option gets equal depth. Use concrete criteria "
            "(price tier, skill level, time, durability), not vague adjectives."
        ),
    },
    "buyers_guide": {
        "name": "Buyer's Guide",
        "min_h2": 4,
        "structure": (
            "- Hook: the buying frustration the reader is in right now.\n"
            "- 'What to look for' H2 with 4-6 H3 criteria (e.g., material, certifications, size).\n"
            "- 'Our picks' H2 with 3-5 H3 sub-sections, each one a category "
            "(e.g., 'Best for beginners', 'Best on a budget'). Recommend ONLY catalog products; "
            "if no catalog product fits a category, OMIT that category.\n"
            "- 'Red flags' H2 — 3-4 things that signal a bad purchase.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources."
        ),
        "intent": (
            "Be a knowledgeable friend, not a salesperson. Acknowledge tradeoffs. "
            "Tie every recommendation to the criteria established earlier."
        ),
    },
    "deep_dive": {
        "name": "Deep-Dive Explainer",
        "min_h2": 5,
        "structure": (
            "- Hook: a counterintuitive or surprising opening fact about the topic.\n"
            "- 'The basics' H2 — definition and why it matters.\n"
            "- 3-5 H2 sections that progressively go deeper "
            "(history → mechanism → current best practice → edge cases).\n"
            "- 'What this means for you' H2 — practical takeaways.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources."
        ),
        "intent": (
            "Be the most thorough explainer the reader will find. Layer the explanation: "
            "each H2 assumes the previous one. Avoid bullet-point thinking — use full paragraphs."
        ),
    },
    "myth_busting": {
        "name": "Myth-Busting",
        "min_h2": 4,
        "structure": (
            "- Hook: how widespread the misconceptions are — author's own past mistake.\n"
            "- 'How these myths spread' short H2 (1-2 paragraphs).\n"
            "- 4-6 H2 sections, each one a single myth. Inside each: "
            "'The claim' (H3, what people believe), 'The reality' (H3, evidence-based correction).\n"
            "- 'What actually works' H2 — short list of evidence-backed practices.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources (cite peer-reviewed or institutional sources where possible)."
        ),
        "intent": (
            "Be assertive but kind. Don't mock people who believed the myth — explain why "
            "it sounds plausible, then dismantle it. Always cite evidence for the correction."
        ),
    },
    "quick_tips": {
        "name": "Quick Tips List",
        "min_h2": 6,
        "structure": (
            "- Hook: the audience-specific pain these tips address.\n"
            "- 8-12 H2 sections, each one a single tip. Each H2 is the tip stated as a directive "
            "('Tip 1: ...'). Inside each: 1-2 paragraphs explaining the why and how.\n"
            "- 'Putting it together' H2 — a short paragraph on combining the tips.\n"
            "- FAQ (3-5 Q&A).\n"
            "- Sources."
        ),
        "intent": (
            "Be scannable. Each tip should stand alone and be useful even if read in isolation. "
            "Lead each tip with the action, not with backstory."
        ),
    },
}


_RULES = [
    # Myth-busting first because "the truth about X" / "X debunked" can also match other patterns.
    (re.compile(r"\b(myth|myths|debunk|debunked|truth about|facts vs|misconception|misconceptions|busted|wrong about)\b", re.I), "myth_busting"),
    (re.compile(r"\b(how to|how do|step[- ]by[- ]step|tutorial|diy|guide to (?:applying|using|making|building|setting))\b", re.I), "how_to"),
    (re.compile(r"\b(vs\.?|versus|compared to|comparison|which is better|or which|head[- ]to[- ]head)\b", re.I), "comparison"),
    (re.compile(r"\b(best|top \d+|ultimate guide|buyer'?s? guide|buying guide|what to look for|shopping for)\b", re.I), "buyers_guide"),
    (re.compile(r"\b(tips|hacks|tricks|ways to|things you|secrets|secret of|reasons (?:why|to)|quick wins)\b", re.I), "quick_tips"),
]


def pick_style(topic: str) -> str:
    """Returns style key. Deterministic, rule-based on topic keywords."""
    for pattern, key in _RULES:
        if pattern.search(topic):
            return key
    return "deep_dive"


def ranked_styles(topic: str) -> list[str]:
    """Primary style first, then the rest in stable order. Used for retry diversification."""
    primary = pick_style(topic)
    rest = [k for k in STYLES if k != primary]
    return [primary, *rest]


def render(style_key: str) -> str:
    """Returns the prompt fragment for the given style. Falls back to deep_dive."""
    style = STYLES.get(style_key) or STYLES["deep_dive"]
    return (
        f"\nARTICLE FORMAT: {style['name']}\n"
        f"Required structure (overrides the default section list):\n"
        f"{style['structure']}\n"
        f"Voice and intent: {style['intent']}\n"
    )


def min_h2(style_key: str) -> int:
    """Minimum H2 count required for the style. Falls back to 4 if style is unknown."""
    return (STYLES.get(style_key) or {}).get("min_h2", 4)
