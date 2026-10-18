"""Shared test helpers: fixture loading, a fake HTTP session and a tiny PDF builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

from hawk.speeches.fetch import PoliteFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF containing ``text`` (one line per ``\\n``)."""
    lines = " ".join(f"({line}) Tj T*" for line in text.splitlines())
    stream = f"BT /F1 11 Tf 14 TL 72 720 Td {lines} ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


@dataclass
class FakeSession(requests.Session):
    """A stand-in for ``requests.Session`` that serves canned responses by URL."""

    pages: dict[str, bytes | int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    def get(self, url: str | bytes, **kwargs: object) -> requests.Response:
        url = str(url)
        self.calls.append(url)
        response = requests.Response()
        page = self.pages.get(url, 404)
        if isinstance(page, int):
            response.status_code = page
        else:
            response.status_code = 200
            response._content = page
        response.url = url
        return response


@pytest.fixture
def session() -> FakeSession:
    return FakeSession(pages={"https://www.bankofengland.co.uk/robots.txt": b"User-agent: *\n"})


@pytest.fixture
def fetcher(tmp_path: Path, session: FakeSession) -> PoliteFetcher:
    return PoliteFetcher(tmp_path / "cache", session=session, sleep=lambda _: None)
