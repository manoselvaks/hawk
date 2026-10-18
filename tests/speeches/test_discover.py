import gzip

from hawk.speeches.discover import classify, discover, parse_sitemap
from hawk.speeches.fetch import PoliteFetcher
from tests.speeches.conftest import FakeSession, fixture

BOE = "https://www.bankofengland.co.uk"


def test_parse_sitemap_index_and_urlset() -> None:
    index = parse_sitemap(fixture("sitemap_index.xml"))
    assert index.sitemaps == [f"{BOE}/sitemap/speeches.xml", f"{BOE}/sitemap/other.xml"]
    assert index.pages == []

    pages = parse_sitemap(gzip.compress(fixture("sitemap_pages.xml")))
    assert len(pages.pages) == 5


def test_classify() -> None:
    assert classify(f"{BOE}/speech/2023/march/andrew-bailey-lse") == "speech"
    assert classify(f"{BOE}/speech/1999/february/x/") == "speech"
    assert classify(f"{BOE}/speech/1996/may/too-early") is None
    assert classify(f"{BOE}/monetary-policy-summary-and-minutes/2023/march-2023") == "minutes"
    assert classify(f"{BOE}/news/2023/march/press-release") is None


def test_discover_walks_sitemaps_from_robots(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[f"{BOE}/robots.txt"] = f"User-agent: *\nSitemap: {BOE}/sitemap.xml\n".encode()
    session.pages[f"{BOE}/sitemap.xml"] = fixture("sitemap_index.xml")
    session.pages[f"{BOE}/sitemap/speeches.xml"] = fixture("sitemap_pages.xml")
    # sitemap/other.xml is missing (404) and should be skipped, not fatal.

    found = discover(fetcher)

    assert found.speeches == [
        f"{BOE}/speech/1999/february/monetary-policy-in-an-uncertain-world",
        f"{BOE}/speech/2023/march/andrew-bailey-lse",
    ]
    assert found.minutes == [f"{BOE}/monetary-policy-summary-and-minutes/2023/march-2023"]
