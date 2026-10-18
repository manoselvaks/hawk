from __future__ import annotations

from pathlib import Path

import pytest

from hawk.market.http import USER_AGENT, PoliteDownloader


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = responses
        self.calls = 0

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls += 1
        return self.responses.pop(0)


def make(tmp_path: Path, session: FakeSession, **kwargs: object) -> PoliteDownloader:
    return PoliteDownloader(tmp_path, min_interval=0, session=session, **kwargs)  # type: ignore[arg-type]


def test_sets_user_agent_and_caches(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200, b"body")])
    downloader = make(tmp_path, session)
    assert downloader.get("https://example.org/a") == b"body"
    assert downloader.get("https://example.org/a") == b"body"
    assert session.calls == 1
    assert session.headers["User-Agent"] == USER_AGENT


def test_refresh_bypasses_cache(tmp_path: Path) -> None:
    make(tmp_path, FakeSession([FakeResponse(200, b"old")])).get("https://example.org/a")
    session = FakeSession([FakeResponse(200, b"new")])
    assert make(tmp_path, session, refresh=True).get("https://example.org/a") == b"new"


def test_retries_transient_errors_then_gives_up(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(503), FakeResponse(200, b"ok")])
    assert make(tmp_path, session).get("https://example.org/a") == b"ok"

    failing = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(RuntimeError, match="503"):
        make(tmp_path, failing).get("https://example.org/b")
    assert failing.calls == 3
