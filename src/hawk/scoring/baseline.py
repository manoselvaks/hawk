"""Baseline tone scorer: count hawkish and dovish matches from the word lists.

For each sentence the scorer finds

1. fixed phrases from ``lexicon.HAWKISH_PHRASES`` / ``DOVISH_PHRASES``;
2. concept-direction pairs ("higher inflation", "unemployment has fallen"),
   signed by ``concept polarity x direction sign``;

and flips a match when a negator ("not", "no", "unlikely", ...) appears in the few
tokens before it. The document score is the net index of Apel and Blix Grimaldi
(2012), ``(hawkish - dovish) / (hawkish + dovish)``, scaled from [-1, 1] to [-2, 2].
Documents with fewer than ``MIN_MATCHES`` matches score 0: there is not enough
evidence either way.

The baseline also returns a relevance proxy (policy terms per 100 words) so it can
be compared with the LLM's relevance judgement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hawk.scoring import lexicon
from hawk.scoring.textprep import policy_density

MIN_MATCHES = 3
# Policy terms per 100 words above which the baseline calls a document "about
# monetary policy". Chosen on the 20 pilot documents, where it splits those the three
# LLMs rate relevant (mean relevance >= 0.5) from the rest with one miss.
RELEVANCE_DENSITY_THRESHOLD = 1.5

_TOKEN_RE = re.compile(r"[a-z]+(?:[-'][a-z]+)*|n't")
_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower().replace("\u2019", "'"))


def _by_first_token(entries: list[tuple[str, int]]) -> dict[str, list[tuple[tuple[str, ...], int]]]:
    """Index phrases by their first token, longest first ("quantitative easing" before
    "easing"), so matching only looks at phrases that can start at a given token."""
    index: dict[str, list[tuple[tuple[str, ...], int]]] = {}
    for text, sign in entries:
        tokens = tuple(tokenize(text))
        index.setdefault(tokens[0], []).append((tokens, sign))
    for options in index.values():
        options.sort(key=lambda o: -len(o[0]))
    return index


_PHRASES = _by_first_token(
    [(p, +1) for p in lexicon.HAWKISH_PHRASES] + [(p, -1) for p in lexicon.DOVISH_PHRASES]
)
_CONCEPTS = _by_first_token(list(lexicon.CONCEPTS.items()))


@dataclass
class Match:
    text: str
    sign: int  # +1 hawkish, -1 dovish, after negation
    negated: bool


@dataclass
class BaselineScore:
    stance: float  # -2 .. +2
    hawkish: int
    dovish: int
    relevance: float  # policy terms per 100 words
    is_relevant: bool
    matches: list[Match] = field(default_factory=list)


def _at(
    tokens: list[str], idx: int, index: dict[str, list[tuple[tuple[str, ...], int]]]
) -> tuple[int, int] | None:
    """(end, sign) of the longest indexed phrase starting at ``idx``, if any."""
    for phrase, sign in index.get(tokens[idx], []):
        if tuple(tokens[idx : idx + len(phrase)]) == phrase:
            return idx + len(phrase), sign
    return None


def sentence_matches(sentence: str) -> list[Match]:
    """Every hawkish or dovish match in one sentence.

    Concept-direction pairs are found first, then fixed phrases on the tokens no
    pair used. A match is negated when a negator sits in the few tokens before it
    or inside it ("inflation is unlikely to rise").
    """
    tokens = tokenize(sentence)
    used = [False] * len(tokens)
    found: list[Match] = []

    def add(start: int, end: int, sign: int) -> None:
        window = tokens[max(0, start - lexicon.NEGATION_WINDOW) : end]
        neg = any(tok in lexicon.NEGATORS for tok in window)
        found.append(Match(" ".join(tokens[start:end]), -sign if neg else sign, neg))
        for k in range(start, end):
            used[k] = True

    for idx in range(len(tokens)):
        hit = None if used[idx] else _at(tokens, idx, _CONCEPTS)
        if hit is None:
            continue
        end, polarity = hit
        before = range(idx - 1, max(-1, idx - 1 - lexicon.DIRECTION_BEFORE), -1)
        after = range(end, min(len(tokens), end + lexicon.DIRECTION_AFTER))
        for k in [*before, *after]:
            direction = lexicon.DIRECTIONS.get(tokens[k])
            if direction is not None and not used[k]:
                add(min(k, idx), max(k + 1, end), polarity * direction)
                break

    idx = 0
    while idx < len(tokens):
        hit = _at(tokens, idx, _PHRASES)
        if hit is not None and not any(used[idx : hit[0]]):
            add(idx, hit[0], hit[1])
            idx = hit[0]
        else:
            idx += 1
    return found


def score_text(text: str) -> BaselineScore:
    """Score a cleaned document."""
    matches = [m for sentence in _SENTENCE_RE.split(text) for m in sentence_matches(sentence)]
    hawk = sum(1 for m in matches if m.sign > 0)
    dove = sum(1 for m in matches if m.sign < 0)
    total = hawk + dove
    stance = 0.0 if total < MIN_MATCHES else round(2 * (hawk - dove) / total, 3)
    density = policy_density(text)
    return BaselineScore(
        stance=stance,
        hawkish=hawk,
        dovish=dove,
        relevance=round(density, 3),
        is_relevant=density >= RELEVANCE_DENSITY_THRESHOLD,
        matches=matches,
    )
