"""Turn downloaded Bank of England pages and PDFs into structured fields.

The parsers are deliberately tolerant: the site's markup has changed over the
years, so each field is tried against several selectors and text patterns, and
anything that cannot be found is returned as ``None`` rather than guessed.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from pypdf import PdfReader

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_ABBR = "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec"
DATE_PATTERN = rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS}|{MONTH_ABBR})\.?,?\s+\d{{4}}"

_PUBLISHED = re.compile(rf"Published\s+on\s+(?P<date>{DATE_PATTERN})", re.IGNORECASE)
_DELIVERED = re.compile(
    rf"\b(?:given|delivered|speaking)\b[^.]{{0,200}}?\bon\s+(?:\w+day,?\s+)?(?P<date>{DATE_PATTERN})",
    re.IGNORECASE,
)
_MEETING = re.compile(
    rf"meeting\s+(?:ending\s+on|held\s+on|on|of)\s+(?:\w+day,?\s+)?"
    rf"(?P<span>[\d\s\w,\-\u2013]{{0,30}}?{DATE_PATTERN})",
    re.IGNORECASE,
)
_SPEECH_BY = re.compile(
    r"\b(?i:speech|remarks|lecture|address|comments)\s+(?:given\s+)?by\s+"
    r"(?P<name>(?:Sir\s+|Dame\s+|Dr\.?\s+|Professor\s+)?[A-Z][\w.'\-]+(?:\s+[A-Z][\w.'\-]+){0,3})"
)
_ROLE = re.compile(
    r"(?P<role>(?:Deputy\s+)?Governor(?:\s+for\s+[A-Z][\w\s,]+?)?"
    r"|Chief\s+Economist(?:\s+and\s+Executive\s+Director[\w\s,]*?)?"
    r"|External\s+(?:MPC\s+)?[Mm]ember(?:\s+of\s+the\s+Monetary\s+Policy\s+Committee)?"
    r"|Member,?\s+(?:of\s+the\s+)?Monetary\s+Policy\s+Committee"
    r"|Executive\s+Director(?:\s+(?:for|of)\s+[A-Z][\w\s,]+?)?)"
    r"(?=[,.;\n]|\s+(?:at|to|of\s+the\s+Bank|on)\b|$)"
)
_SITE_SUFFIX = re.compile(r"\s*[|\-\u2013]\s*Bank of England\s*$", re.IGNORECASE)

# A page's own PDF is its download button ("btn-pubs" on older pages, "button-download"
# on newer ones). Links in the body are citations of other publications (including other
# speeches), which must not be mistaken for it.
OWN_PDF_BUTTON = "a.btn-pubs[href], a.button-download[href]"
_PDF_HREF = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)

# Old speech PDFs repeat a banner and a page number on every page.
_PDF_FURNITURE = re.compile(
    r"^(?:All speeches are available online at \S+|\d{1,3}|Page \d+ of \d+)$", re.IGNORECASE
)
_DATE_LINE = re.compile(rf"^(?:\w+day,?\s+)?(?P<date>{DATE_PATTERN})$", re.IGNORECASE)

CONTENT_SELECTORS = (
    "div.page-content",
    "section.page-section",
    "div.content-block",
    "article",
    "main",
)
BLOCK_TAGS = ("p", "div", "section", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote")
NOISE_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe")


@dataclass(frozen=True)
class SpeechPage:
    title: str | None
    speaker: str | None
    role: str | None
    speech_date: date | None
    published_date: date | None
    text: str
    pdf_url: str | None


@dataclass(frozen=True)
class MinutesPage:
    title: str | None
    meeting_date: date | None
    published_date: date | None
    text: str
    pdf_url: str | None


def parse_date(value: str) -> date | None:
    """Parse dates such as ``14 March 2023``, ``1st Sept. 1998`` or ``2023-03-14``."""
    value = value.strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if iso:
        return date(int(iso[1]), int(iso[2]), int(iso[3]))
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value)
    cleaned = re.sub(r"[.,]", " ", cleaned)
    cleaned = re.sub(r"\bSept\b", "Sep", cleaned)
    cleaned = " ".join(cleaned.split())
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_meeting_date(text: str) -> date | None:
    """Find the (final day of the) MPC meeting a set of minutes refers to.

    Handles phrasings such as "meeting ending on 8 May 2024", "meeting held on
    4-5 June 1997" and "meeting on 30 June-1 July 1998"; for a multi-day meeting
    the last day is returned, because that is when the decision was taken.
    """
    match = _MEETING.search(text)
    if not match:
        return None
    span = match["span"]
    year = re.findall(r"\d{4}", span)[-1]
    month = re.findall(rf"(?:{MONTHS}|{MONTH_ABBR})", span)[-1]
    day = re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", span.split(month)[-2])[-1]
    return parse_date(f"{day} {month} {year}")


def parse_speech_html(html: str | bytes, url: str) -> SpeechPage:
    soup = BeautifulSoup(html, "lxml")
    title = _title(soup)
    # The banner under the title says e.g. "Speech by Spencer Dale" or "Given at the LSE".
    description = _description(soup)
    text = _body_text(soup)
    header = f"{description or ''}\n{text[:1500]}"
    speaker = _speaker_from(title) or _speaker_from(header)
    return SpeechPage(
        title=title,
        speaker=speaker,
        role=_first_role(header),
        speech_date=_first_date(_DELIVERED, header),
        published_date=_published_date(soup, text),
        text=text,
        pdf_url=_pdf_link(soup, url),
    )


def parse_minutes_html(html: str | bytes, url: str) -> MinutesPage:
    soup = BeautifulSoup(html, "lxml")
    title = _title(soup)
    text = _body_text(soup)
    return MinutesPage(
        title=title,
        # Older titles name the meeting ("Minutes of the MPC Meeting held on 5 and 6 June 1997");
        # newer ones only the month, but the summary says "At its meeting ending on ...".
        meeting_date=parse_meeting_date(title or "") or parse_meeting_date(text),
        published_date=_published_date(soup, text),
        text=text,
        pdf_url=_pdf_link(soup, url),
    )


def pdf_text(body: bytes) -> str:
    """Extract plain text from a PDF, page by page."""
    reader = PdfReader(io.BytesIO(body))
    pages = [page.extract_text() or "" for page in reader.pages]
    lines = _tidy("\n".join(pages)).splitlines()
    return "\n".join(line for line in lines if not _PDF_FURNITURE.match(line))


def speaker_and_role_from_text(text: str) -> tuple[str | None, str | None]:
    """Best-effort speaker and role from the opening of a speech (used for PDFs)."""
    header = text[:1500]
    return _speaker_from(header), _first_role(header)


def _title(soup: BeautifulSoup) -> str | None:
    candidates = [_meta(soup, "og:title")]
    h1 = soup.find("h1")
    candidates.append(h1.get_text(" ", strip=True) if h1 else None)
    candidates.append(soup.title.get_text(" ", strip=True) if soup.title else None)
    for candidate in candidates:
        if candidate:
            return _SITE_SUFFIX.sub("", " ".join(candidate.split())) or None
    return None


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    if isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _description(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one(".page-description")
    return tag.get_text(" ", strip=True) if tag else None


def _speaker_from(text: str | None) -> str | None:
    if not text:
        return None
    match = _SPEECH_BY.search(text)
    return match["name"].strip() if match else None


def _first_role(text: str) -> str | None:
    match = _ROLE.search(text)
    return " ".join(match["role"].split()).rstrip(" ,") if match else None


def _published_date(soup: BeautifulSoup, text: str) -> date | None:
    # Every page has a "Published on 15 December 1998" line under the banner. (The <time>
    # tags on the page belong to the "Other speeches" panel, so they are not used.)
    tag = soup.select_one(".published-date")
    if tag and (parsed := _first_date(_PUBLISHED, tag.get_text(" ", strip=True))):
        return parsed
    return _first_date(_PUBLISHED, text)


def _first_date(pattern: re.Pattern[str], text: str) -> date | None:
    match = pattern.search(text)
    return parse_date(match["date"]) if match else None


def _body_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()
    container: Tag | None = None
    for selector in CONTENT_SELECTORS:
        container = soup.select_one(selector)
        if container is not None:
            break
    root = container or soup.body or soup
    # Source line-wraps are not paragraph breaks: flatten whitespace inside text nodes,
    # then mark the edges of block elements so paragraphs survive as lines.
    for string in root.find_all(string=True):
        if type(string) is NavigableString:
            string.replace_with(re.sub(r"\s+", " ", string))
    for br in root.find_all("br"):
        br.replace_with("\n")
    for block in root.find_all(BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    return _tidy(root.get_text())


def _pdf_link(soup: BeautifulSoup, base_url: str) -> str | None:
    for anchor in soup.select(OWN_PDF_BUTTON):
        href = anchor["href"]
        if isinstance(href, str) and _PDF_HREF.search(href):
            return urljoin(base_url, href)
    return None


def _tidy(text: str) -> str:
    """Collapse runs of whitespace while keeping paragraph breaks."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def speech_date_from_pdf(text: str) -> date | None:
    """The date on a speech PDF's cover ("Speech given by / Name, Role / 21 October 1998").

    Only a line that is nothing but a date, near the top, is trusted; dates inside
    sentences are as likely to be about something else.
    """
    for line in text.splitlines()[:25]:
        match = _DATE_LINE.match(line.strip())
        if match:
            return parse_date(match["date"])
    return None
