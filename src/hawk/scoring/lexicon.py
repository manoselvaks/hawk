"""Hawkish and dovish word lists for the baseline scorer.

These are simple, hand-written lists. They follow the general approach of
Apel and Blix Grimaldi (2012), who count combinations of an economic *concept*
with a *direction* word ("higher inflation", "weaker growth"), and add a short list
of fixed policy phrases ("tightening", "downside risks"). Nothing here is learnt
from data, so every match can be traced to a line in this file.

How a concept-direction match is signed: each concept has a polarity (+1 when more
of it is hawkish, like inflation or wage growth; -1 when more of it is dovish, like
unemployment or spare capacity) and each direction word has a sign (+1 up, -1 down).
The match is hawkish when the product is positive. So "rising inflation" (+1 x +1)
and "falling unemployment" (-1 x -1) are hawkish; "weak demand" (+1 x -1) is dovish.
"""

from __future__ import annotations

# Concept -> polarity. Keys are single tokens or two-token phrases (lower case).
CONCEPTS: dict[str, int] = {
    "inflation": +1,
    "inflationary": +1,
    "prices": +1,
    "price pressures": +1,
    "cost pressures": +1,
    "wages": +1,
    "wage growth": +1,
    "pay growth": +1,
    "earnings": +1,
    "unit labour costs": +1,
    "inflation expectations": +1,
    "demand": +1,
    "growth": +1,
    "activity": +1,
    "output": +1,
    "spending": +1,
    "consumption": +1,
    "employment": +1,
    "house prices": +1,
    "credit growth": +1,
    "unemployment": -1,
    "slack": -1,
    "spare capacity": -1,
    "output gap": -1,  # a (negative) output gap is spare capacity
    "margin of spare capacity": -1,
}

# Direction words: +1 means "up / strong", -1 means "down / weak".
DIRECTIONS: dict[str, int] = {
    # up
    "higher": +1,
    "high": +1,
    "rising": +1,
    "rise": +1,
    "rises": +1,
    "rose": +1,
    "risen": +1,
    "increase": +1,
    "increased": +1,
    "increasing": +1,
    "increases": +1,
    "strong": +1,
    "stronger": +1,
    "strengthening": +1,
    "robust": +1,
    "elevated": +1,
    "accelerating": +1,
    "accelerated": +1,
    "faster": +1,
    "firm": +1,
    "firmer": +1,
    "persistent": +1,
    "buoyant": +1,
    "picked": +1,  # "picked up"
    "picking": +1,
    "above": +1,
    "tight": +1,
    "tighter": +1,
    # down
    "lower": -1,
    "low": -1,
    "falling": -1,
    "fall": -1,
    "falls": -1,
    "fell": -1,
    "fallen": -1,
    "decrease": -1,
    "decreased": -1,
    "declining": -1,
    "decline": -1,
    "declined": -1,
    "weak": -1,
    "weaker": -1,
    "weakening": -1,
    "weakness": -1,
    "subdued": -1,
    "slowing": -1,
    "slowed": -1,
    "slower": -1,
    "softer": -1,
    "soft": -1,
    "moderating": -1,
    "moderated": -1,
    "below": -1,
    "muted": -1,
    "easing": -1,  # "inflation easing" (the policy sense is a fixed phrase below)
    "eased": -1,
    "loose": -1,
    "looser": -1,
    "narrowed": -1,  # "spare capacity has narrowed": slack (-1) x down (-1) = hawkish
    "narrowing": -1,
    "widened": +1,
    "widening": +1,
}

# Fixed phrases with their own sign. Matched after concept-direction pairs, on the
# tokens no pair used, so "spare capacity has narrowed" is one hawkish pair rather
# than the dovish phrase "spare capacity".
HAWKISH_PHRASES: list[str] = [
    "upside risk",
    "upside risks",
    "to the upside",
    "inflationary pressure",
    "inflationary pressures",
    "second round effects",
    "second-round effects",
    "overheating",
    "tightening",
    "tighten policy",
    "tighter policy",
    "tighter monetary policy",
    "raise bank rate",
    "raise interest rates",
    "increase bank rate",
    "increase in bank rate",
    "rise in bank rate",
    "higher bank rate",
    "rate rise",
    "rate rises",
    "rate increase",
    "rate increases",
    "hike",
    "hikes",
    "excess demand",
    "capacity constraints",
    "labour shortages",
    "recruitment difficulties",
    "de-anchoring",
    "unanchored",
    "price stability is at risk",
]
DOVISH_PHRASES: list[str] = [
    "downside risk",
    "downside risks",
    "to the downside",
    "spare capacity",
    "slack",
    "disinflation",
    "disinflationary",
    "deflation",
    "deflationary",
    "recession",
    "stimulus",
    "monetary stimulus",
    "easing",
    "loosening",
    "looser policy",
    "loosen policy",
    "accommodative",
    "cut bank rate",
    "reduce bank rate",
    "reduction in bank rate",
    "cut in bank rate",
    "lower bank rate",
    "rate cut",
    "rate cuts",
    "cut interest rates",
    "reduce interest rates",
    "quantitative easing",
    "asset purchases",
    "headwinds",
    "deficient demand",
]

# Words that flip the sign of a match: within ``NEGATION_WINDOW`` tokens before it,
# or between a concept and its direction word ("inflation is unlikely to rise").
NEGATORS: frozenset[str] = frozenset(
    {
        "not",
        "no",
        "nor",
        "never",
        "neither",
        "without",
        "unlikely",
        "little",
        "less",
        "limited",
        "hardly",
        "n't",
        "cannot",
    }
)
NEGATION_WINDOW = 3

# How far a direction word may sit from its concept: "higher inflation" (before)
# or "inflation has risen" (after).
DIRECTION_BEFORE = 2
DIRECTION_AFTER = 4
