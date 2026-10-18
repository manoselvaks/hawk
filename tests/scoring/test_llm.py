from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from hawk.scoring.llm import LLMScorer, build_input, load_prompt, parse_response
from hawk.scoring.spend import BudgetExceededError, SpendTracker

TEXT = "Inflation is well above target and the MPC raised Bank Rate. " * 10


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def reply(content: str, cost: float | None = 0.001) -> FakeResponse:
    usage: dict[str, Any] = {"prompt_tokens": 100, "completion_tokens": 20}
    if cost is not None:
        usage["cost"] = cost
    return FakeResponse(200, {"choices": [{"message": {"content": content}}], "usage": usage})


GOOD = '{"relevance": 0.9, "stance": 1.2, "confidence": 0.8, "reason": "Says rates must rise."}'


def make(tmp_path: Path, session: FakeSession, cap: float = 1.0) -> LLMScorer:
    tracker = SpendTracker(tmp_path / "spend.jsonl", cap_usd=cap)
    return LLMScorer(
        "test/model",
        tracker=tracker,
        cache_dir=tmp_path / "cache",
        session=session,  # type: ignore[arg-type]
        backoff_seconds=0,
    )


def test_parse_response_snaps_and_clips() -> None:
    score = parse_response("```json\n" + GOOD + "\n```")
    assert score.stance == 1.0  # 1.2 snaps to the 0.5 grid
    assert parse_response(GOOD.replace("1.2", "3.7")).stance == 2.0
    assert parse_response(GOOD.replace("1.2", "null")).stance is None
    with pytest.raises(ValueError):
        parse_response("no json here")


def test_prompt_is_versioned_file() -> None:
    assert "RELEVANCE" in load_prompt("stance_v1")


def test_input_hides_date_and_speaker() -> None:
    message = build_input("speech", TEXT, "full")
    assert message.startswith("Document type: Bank of England speech")
    assert TEXT.strip() in message


def test_score_caches_and_tracks_spend(tmp_path: Path) -> None:
    session = FakeSession([reply(GOOD, cost=0.002)])
    scorer = make(tmp_path, session)
    first = scorer.score("speech", TEXT)
    second = scorer.score("speech", TEXT)
    assert first["stance"] == 1.0 and not first["cached"]
    assert second["cached"] and len(session.calls) == 1
    assert scorer.tracker.spent_usd == pytest.approx(0.002)
    body = session.calls[0]["json"]
    assert body["temperature"] == 0 and body["model"] == "test/model"


def test_replicate_is_a_separate_cache_entry(tmp_path: Path) -> None:
    session = FakeSession([reply(GOOD), reply(GOOD)])
    scorer = make(tmp_path, session)
    scorer.score("speech", TEXT, replicate=0)
    scorer.score("speech", TEXT, replicate=1)
    assert len(session.calls) == 2


def test_no_auth_header_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert "Authorization" not in make(tmp_path, FakeSession([])).headers()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    assert make(tmp_path, FakeSession([])).headers()["Authorization"] == "Bearer sk-test"


def test_retries_http_errors_and_bad_json(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(429), reply("not json"), reply(GOOD)])
    result = make(tmp_path, session).score("speech", TEXT)
    assert result["attempts"] == 3 and len(session.calls) == 3


def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        make(tmp_path, session).score("speech", TEXT)


def test_missing_cost_books_reserve(tmp_path: Path) -> None:
    scorer = make(tmp_path, FakeSession([reply(GOOD, cost=None)]))
    scorer.score("speech", TEXT)
    assert scorer.tracker.spent_usd == pytest.approx(scorer.tracker.reserve_usd)


def test_refuses_when_over_cap(tmp_path: Path) -> None:
    session = FakeSession([reply(GOOD)])
    with pytest.raises(BudgetExceededError):
        make(tmp_path, session, cap=0.005).score("speech", TEXT)
    assert session.calls == []
