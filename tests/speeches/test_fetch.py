from pathlib import Path

import pytest

from hawk.speeches.fetch import USER_AGENT, DisallowedByRobots, FetchError, PoliteFetcher
from tests.speeches.conftest import FakeSession

PAGE = "https://www.bankofengland.co.uk/speech/2023/march/x"


def test_get_caches_and_resumes(tmp_path: Path, session: FakeSession) -> None:
    session.pages[PAGE] = b"<html>hello</html>"
    first = PoliteFetcher(tmp_path, session=session, sleep=lambda _: None)
    assert first.get(PAGE) == b"<html>hello</html>"
    assert session.headers["User-Agent"] == USER_AGENT

    # A fresh fetcher (as after a restart) serves the page from disk without any request.
    session.calls.clear()
    second = PoliteFetcher(tmp_path, session=session, sleep=lambda _: None)
    assert second.get(PAGE) == b"<html>hello</html>"
    assert session.calls == []


def test_robots_disallow(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages["https://www.bankofengland.co.uk/robots.txt"] = (
        b"User-agent: *\nDisallow: /speech/\n"
    )
    with pytest.raises(DisallowedByRobots):
        fetcher.get(PAGE)
    assert PAGE not in session.calls


def test_rate_limit_and_crawl_delay(tmp_path: Path, session: FakeSession) -> None:
    session.pages["https://www.bankofengland.co.uk/robots.txt"] = b"User-agent: *\nCrawl-delay: 2\n"
    session.pages[PAGE] = b"a"
    session.pages[PAGE + "2"] = b"b"
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    fetcher = PoliteFetcher(tmp_path, session=session, clock=lambda: now[0], sleep=sleep)

    fetcher.get(PAGE)
    fetcher.get(PAGE + "2")

    # robots.txt, then two pages: each later request waits for the 2s crawl delay.
    assert sleeps == [2.0, 2.0]


def test_retries_then_raises(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[PAGE] = 503
    with pytest.raises(FetchError, match="HTTP 503"):
        fetcher.get(PAGE)
    assert session.calls.count(PAGE) == 3


def test_not_found_is_not_retried(fetcher: PoliteFetcher, session: FakeSession) -> None:
    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get(PAGE)
    assert session.calls.count(PAGE) == 1


def test_missing_robots_allows_but_unreachable_robots_blocks(
    tmp_path: Path, session: FakeSession
) -> None:
    session.pages[PAGE] = b"ok"
    session.pages["https://www.bankofengland.co.uk/robots.txt"] = 404
    assert PoliteFetcher(tmp_path / "a", session=session, sleep=lambda _: None).get(PAGE) == b"ok"

    session.pages["https://www.bankofengland.co.uk/robots.txt"] = 503
    with pytest.raises(DisallowedByRobots):
        PoliteFetcher(tmp_path / "b", session=session, sleep=lambda _: None).get(PAGE)
