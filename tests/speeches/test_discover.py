import gzip

from hawk.speeches.discover import classify, discover, parse_sitemap
from hawk.speeches.fetch import PoliteFetcher
from tests.speeches.conftest import FakeSession, fixture

BOE = "https://www.bankofengland.co.uk"
SITEMAP = f"{BOE}/_api/sitemap/getsitemap"


def test_parse_sitemap_index_and_urlset() -> None:
    # The Bank serves one flat urlset, but the sitemap protocol also allows an index.
    index = parse_sitemap(
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + f"<sitemap><loc>{SITEMAP}</loc></sitemap></sitemapindex>".encode()
    )
    assert (index.sitemaps, index.pages) == ([SITEMAP], [])

    pages = parse_sitemap(gzip.compress(fixture("sitemap_pages.xml")))
    assert len(pages.pages) == 12


def test_classify() -> None:
    assert classify(f"{BOE}/speech/2025/april/david-bailey-speech") == "speech"
    assert classify(f"{BOE}/speech/1998/alice-in-euroland/") == "speech"
    assert classify(f"{BOE}/speech/1996/may/too-early") is None
    assert classify(f"{BOE}/speech/speaker-request-form") is None
    assert classify(f"{BOE}/monetary-policy-summary-and-minutes/2025/may-2025") == "minutes"
    # Before August 2015 the MPC minutes live under /minutes/ with three slug styles.
    assert classify(f"{BOE}/minutes/1997/monetary-policy-committee-june-1997") == "minutes"
    assert classify(f"{BOE}/minutes/2003/minutes-april-2003") == "minutes"
    assert classify(f"{BOE}/minutes/2001/monetary-policy-committee-18-september-2001") == "minutes"
    # ... next to the minutes of other committees, which are not MPC minutes.
    assert classify(f"{BOE}/minutes/2013/court-redactions-from-2013") is None
    assert classify(f"{BOE}/minutes/2014/fxjsc-chief-dealers-subgroup-minutes-may-2014") is None
    assert classify(f"{BOE}/news/2023/march/press-release") is None


def test_discover_reads_sitemap_from_robots(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[f"{BOE}/robots.txt"] = f"User-agent: *\nSitemap: {SITEMAP}\n".encode()
    session.pages[SITEMAP] = fixture("sitemap_pages.xml")

    found = discover(fetcher)

    assert found.speeches == [
        f"{BOE}/speech/1998/alice-in-euroland",
        f"{BOE}/speech/2025/april/david-bailey-speech-at-a-climate-financial-risk-forum",
    ]
    assert found.minutes == [
        f"{BOE}/minutes/1997/monetary-policy-committee-june-1997",
        f"{BOE}/minutes/2001/monetary-policy-committee-18-september-2001",
        f"{BOE}/minutes/2003/minutes-april-2003",
        f"{BOE}/monetary-policy-summary-and-minutes/2025/may-2025",
        f"{BOE}/monetary-policy-summary-and-minutes/2027/february-2027",
    ]


def test_discover_skips_missing_sitemaps(fetcher: PoliteFetcher, session: FakeSession) -> None:
    found = discover(fetcher, [f"{BOE}/missing.xml"])  # 404: logged, not fatal
    assert (found.speeches, found.minutes) == ([], [])
