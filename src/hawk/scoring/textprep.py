"""Text preparation: clean PDF debris and pull out the passages about monetary policy.

Nothing here touches the raw parquet files; every function takes a string and
returns a new one.

``clean_text``
    Drops running headers and footers ("Bank of England Page 3", "All speeches are
    available online at ..."), lines of chart axis numbers, and the references and
    footnotes at the end; then re-joins lines that a PDF wrapped mid-sentence, so
    each line of the result is one paragraph.

``policy_passages``
    Scores each paragraph by how many monetary-policy terms it contains and keeps
    the best ones, in their original order, up to about 2,500 characters. This is a
    keyword heuristic, not a model: it is cheap, deterministic and easy to inspect.
    The labelling tool shows these passages, and the LLM scorer can use them as a
    short input.
"""

from __future__ import annotations

import re

PASSAGE_CHAR_LIMIT = 2_500

# Whole lines that are page furniture rather than text.
_BOILERPLATE = [
    r"bank of england\s+page\s+\d+",
    r"page\s+\d+(\s+of\s+\d+)?",
    r"all speeches are available online at.*",
    r"www\.bankofengland\.co\.uk.*",
    r"they are also available on the internet.*",
    r"speech given by",
    r"speech",
    r"slides",
    r"insert document classification.*",
]
_BOILERPLATE_RE = re.compile(rf"^\s*(?:{'|'.join(_BOILERPLATE)})\s*$", re.I)
# Inline variant: PDF extraction sometimes glues the page header onto a sentence.
_INLINE_PAGE_RE = re.compile(r"[ \t]*\bBank of England[ \t]+Page[ \t]+\d+\b[ \t]*")
_LETTER_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"\d")
# Headings that start the back matter. Only cut there if it is in the last part
# of the text, so a "References" heading early on cannot delete the speech.
_BACK_MATTER_RE = re.compile(r"^\s*(references|bibliography|footnotes|endnotes)\s*:?\s*$", re.I)
_BACK_MATTER_MIN_POSITION = 0.6
_SENTENCE_END = tuple('.!?:;"\u201d\u2019)')
_HEADING_MAX_CHARS = 60


def _is_debris(line: str) -> bool:
    """Page furniture, or a line of numbers such as chart axis labels."""
    if _BOILERPLATE_RE.match(line):
        return True
    letters = len(_LETTER_RE.findall(line))
    return letters == 0 or len(_DIGIT_RE.findall(line)) > letters


def _strip_back_matter(lines: list[str]) -> list[str]:
    total = sum(len(line) for line in lines) or 1
    seen = 0
    for idx, line in enumerate(lines):
        if seen / total >= _BACK_MATTER_MIN_POSITION and _BACK_MATTER_RE.match(line):
            return lines[:idx]
        seen += len(line)
    return lines


def _join_wrapped(lines: list[str]) -> list[str]:
    """Re-join lines a PDF wrapped mid-sentence into paragraphs.

    A line is glued to the previous one when the previous line does not end a
    sentence and either is long (a wrapped line, not a heading) or the new line
    starts in lower case (a sentence carrying on).
    """
    paragraphs: list[str] = []
    for line in lines:
        if paragraphs:
            prev = paragraphs[-1]
            carries_on = not prev.endswith(_SENTENCE_END) and (
                len(prev) > _HEADING_MAX_CHARS or line[:1].islower()
            )
            if carries_on:
                joiner = "" if prev.endswith("-") and line[:1].islower() else " "
                paragraphs[-1] = (prev[:-1] if joiner == "" else prev) + joiner + line
                continue
        paragraphs.append(line)
    return paragraphs


def clean_text(text: str) -> str:
    """Text with PDF headers, numeric debris and back matter removed, one paragraph per line."""
    text = _INLINE_PAGE_RE.sub(" ", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line and not _is_debris(line)]
    lines = _strip_back_matter(lines)
    return "\n".join(_join_wrapped(lines))


# Terms that mark a paragraph as being about the monetary-policy outlook. Weights
# favour the policy decision itself over the general macro backdrop.
POLICY_TERMS: dict[str, float] = {
    r"bank rate": 3,
    r"interest rates?": 2,
    r"policy rate": 3,
    r"monetary policy": 2,
    r"(?:the )?(?:mpc|monetary policy committee)": 2,
    r"tighten\w*": 2,
    r"loosen\w*": 2,
    r"(?:rate|policy) (?:rise|rises|increase|increases|cut|cuts|reduction)s?": 3,
    r"asset purchases|quantitative easing|\bqe\b|gilt purchases": 2,
    r"forward guidance": 2,
    r"inflation": 1,
    r"cpi|rpix": 1,
    r"(?:2|two) per ?cent target|inflation target": 2,
    r"second[- ]round effects?": 2,
    r"inflation expectations": 2,
    r"wage (?:growth|settlements|pressures?)|pay growth|unit labour costs": 1,
    r"spare capacity|slack|output gap|excess demand|margin of spare capacity": 2,
    r"upside risks?|downside risks?|balance of risks": 2,
    r"demand|growth|unemployment|labour market": 0.5,
}
_POLICY_RES = [(re.compile(rf"\b(?:{pat})\b", re.I), w) for pat, w in POLICY_TERMS.items()]
_MIN_PARAGRAPH_CHARS = 120


def policy_term_score(paragraph: str) -> float:
    """Weighted count of monetary-policy terms in ``paragraph``."""
    return sum(weight * len(rx.findall(paragraph)) for rx, weight in _POLICY_RES)


def policy_density(text: str) -> float:
    """Policy-term score per 100 words of ``text``: a crude relevance signal."""
    words = len(text.split())
    return 100 * policy_term_score(text) / words if words else 0.0


def _truncate(paragraph: str, limit: int) -> str:
    """Cut at the last sentence end before ``limit``, or at a word boundary."""
    if len(paragraph) <= limit:
        return paragraph
    cut = paragraph[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end > limit // 2:
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0] + " …"


def policy_passages(text: str, limit: int = PASSAGE_CHAR_LIMIT) -> str:
    """The paragraphs of ``text`` most about monetary policy, in reading order, within ``limit``.

    ``text`` should already be cleaned. Paragraphs are ranked by policy-term score
    per character (with a floor on length so one-line fragments do not win), the
    best are taken until the budget is spent, and they are returned in their
    original order separated by blank lines. If no paragraph mentions policy at all
    the opening of the text is returned instead, so a reader still sees something.
    """
    paragraphs = [p for p in text.split("\n") if p.strip()]
    scored = []
    for idx, para in enumerate(paragraphs):
        score = policy_term_score(para)
        if score > 0 and len(para) >= _MIN_PARAGRAPH_CHARS:
            scored.append((score / max(len(para), 300), score, idx))
    if not scored:
        return _truncate(" ".join(paragraphs), limit)

    chosen: list[int] = []
    used = 0
    for _, _, idx in sorted(scored, key=lambda s: (-s[0], -s[1], s[2])):
        para = paragraphs[idx]
        if used + len(para) <= limit:
            chosen.append(idx)
            used += len(para) + 2
        elif not chosen:  # the single best paragraph is longer than the budget
            return _truncate(para, limit)
    return "\n\n".join(paragraphs[i] for i in sorted(chosen))
