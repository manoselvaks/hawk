"""LLM tone scorer through OpenRouter.

``LLMScorer.score`` sends one document to a chat model with the versioned prompt in
``prompts/`` and returns a validated ``LLMScore``: relevance (0-1), stance (-2..+2 in
0.5 steps, or ``None`` when the document is not about monetary policy), confidence
(0-1) and a one-sentence reason.

Design points:

* **Caching.** Results are stored as JSON under ``data/llm_cache/``, keyed by model,
  prompt version, a hash of the exact input text and a replicate number. Re-running
  costs nothing. Scoring the same document twice on purpose (to measure
  self-consistency) uses ``replicate=1``.
* **Spend.** Every call goes through ``SpendTracker``, which logs the cost OpenRouter
  reports and refuses to continue past the cap.
* **Determinism.** Temperature 0 is requested. Some models ignore it, which is one
  reason self-consistency is measured rather than assumed.
* **Auth.** If ``OPENROUTER_API_KEY`` is set it is sent as a bearer token; if not, no
  ``Authorization`` header is sent (in the cloud environment a proxy adds it).
* **No look-ahead through metadata.** The model sees the document type and text only,
  never the date or speaker, so it is not invited to recall what happened next.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import requests

from hawk.scoring.spend import SpendTracker
from hawk.scoring.textprep import policy_passages

log = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-6-luna"  # chosen in the pilot, see docs/pilot.md
PROMPT_VERSION = "stance_v1"
CACHE_DIR = Path("data/llm_cache")
FULL_TEXT_CHARS = 24_000
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
# OpenRouter answers 402 "in_flight_budget_exhausted" when a key with little credit left
# has too many requests open at once; it clears by itself after the Retry-After delay.
IN_FLIGHT_MARKER = "in_flight_budget"

InputMode = Literal["passages", "full"]
DEFAULT_INPUT_MODE: InputMode = "full"

RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "stance",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "relevance": {"type": "number"},
            "stance": {"type": ["number", "null"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["relevance", "stance", "confidence", "reason"],
        "additionalProperties": False,
    },
}


def load_prompt(version: str = PROMPT_VERSION) -> str:
    return (resources.files("hawk.scoring") / "prompts" / f"{version}.md").read_text()


def build_input(kind: str, text: str, mode: InputMode = "passages") -> str:
    """The user message: document type and text (passages, or full text if it fits).

    In ``full`` mode, texts longer than ``FULL_TEXT_CHARS`` are cut down with the
    policy-passage extractor at that larger budget rather than truncated, so the end
    of a long speech (where the policy view often is) is not lost.
    """
    if mode == "passages":
        body = policy_passages(text)
        note = "Extracts: the passages of the document most about monetary policy."
    elif len(text) <= FULL_TEXT_CHARS:
        body, note = text, "Full text."
    else:
        body = policy_passages(text, FULL_TEXT_CHARS)
        note = "Extracts: the document is long, so only its most policy-relevant passages."
    label = "MPC minutes" if kind == "minutes" else "Bank of England speech"
    return f"Document type: {label}\n{note}\n\n<<<\n{body}\n>>>"


@dataclass(frozen=True)
class LLMScore:
    relevance: float
    stance: float | None
    confidence: float
    reason: str


def _clip(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def parse_response(content: str) -> LLMScore:
    """Validate the model's JSON reply. Raises ``ValueError`` if it is unusable."""
    text = content.strip()
    fenced = re.search(r"\{.*\}", text, re.S)
    if fenced is None:
        raise ValueError(f"no JSON object in reply: {content[:200]!r}")
    data = json.loads(fenced.group(0))
    relevance = float(data["relevance"])
    confidence = float(data["confidence"])
    reason = str(data["reason"]).strip()
    raw_stance = data.get("stance")
    if any(math.isnan(v) for v in (relevance, confidence)) or not reason:
        raise ValueError(f"incomplete reply: {data!r}")
    stance = None
    if raw_stance is not None:
        # Snap to the 0.5 grid and the -2..+2 range the prompt asks for.
        stance = round(_clip(float(raw_stance), -2, 2) * 2) / 2
    return LLMScore(_clip(relevance, 0, 1), stance, _clip(confidence, 0, 1), reason)


def cache_key(model: str, prompt_version: str, user_message: str, replicate: int = 0) -> str:
    digest = hashlib.sha256(user_message.encode()).hexdigest()[:20]
    return f"{model}|{prompt_version}|{digest}|r{replicate}"


class LLMScorer:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        prompt_version: str = PROMPT_VERSION,
        input_mode: InputMode = DEFAULT_INPUT_MODE,
        tracker: SpendTracker | None = None,
        cache_dir: Path = CACHE_DIR,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        max_tokens: int = 2_000,
        reasoning_effort: str | None = "low",
        max_retry_after_seconds: float = 150.0,
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self.system_prompt = load_prompt(prompt_version)
        self.input_mode = input_mode
        self.tracker = tracker or SpendTracker()
        self.cache_dir = cache_dir
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.max_retry_after_seconds = max_retry_after_seconds

    # -- cache -------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        model_dir = re.sub(r"[^A-Za-z0-9._-]+", "_", self.model)
        _, version, digest, rep = key.split("|")
        return self.cache_dir / model_dir / version / f"{digest}-{rep}.json"

    def cached(self, kind: str, text: str, replicate: int = 0) -> dict[str, Any] | None:
        message = build_input(kind, text, self.input_mode)
        path = self._cache_path(cache_key(self.model, self.prompt_version, message, replicate))
        return json.loads(path.read_text()) if path.exists() else None

    # -- request -----------------------------------------------------------
    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/manoselvaks/hawk",
            "X-Title": "hawk",
        }
        key = os.environ.get("OPENROUTER_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def payload(self, user_message: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
            "usage": {"include": True},
            # Several providers serve most open models at different prices.
            "provider": {"sort": "price"},
        }
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort, "exclude": True}
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(API_URL, json=body, headers=self.headers(), timeout=180)
        if response.status_code in RETRY_STATUSES:
            raise _RetryableError(f"HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code == 402 and IN_FLIGHT_MARKER in response.text:
            headers = getattr(response, "headers", None) or {}
            try:
                wait = float(headers.get("Retry-After", 60))
            except ValueError:
                wait = 60.0
            raise _RetryableError(
                f"HTTP 402 (in-flight budget): {response.text[:200]}",
                wait=min(wait, self.max_retry_after_seconds),
            )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        if "error" in data:
            raise _RetryableError(f"OpenRouter error: {data['error']}")
        return data

    def score(self, kind: str, text: str, replicate: int = 0) -> dict[str, Any]:
        """Score one cleaned document; returns the cache record (see ``LLMScore``).

        The record holds the validated score fields plus ``model``, ``prompt_version``,
        ``input_mode``, ``cost_usd``, token counts and ``cached`` (whether this call
        was served from the cache).
        """
        message = build_input(kind, text, self.input_mode)
        key = cache_key(self.model, self.prompt_version, message, replicate)
        path = self._cache_path(key)
        if path.exists():
            record: dict[str, Any] = json.loads(path.read_text())
            return {**record, "cached": True}

        body = self.payload(message)
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self.tracker.check()
            try:
                data = self._post(body)
            except (_RetryableError, requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                log.warning("%s attempt %d failed: %s", self.model, attempt, exc)
                wait = getattr(exc, "wait", 0.0)
                time.sleep(max(wait, self.backoff_seconds * 2 ** (attempt - 1)))
                continue

            usage = data.get("usage") or {}
            if usage.get("cost") is not None:
                cost = float(usage["cost"])
            else:  # never under-count: book the per-call reserve instead
                cost = self.tracker.reserve_usd
                log.warning("no usage.cost for %s; booked the $%.2f reserve", key, cost)
            self.tracker.record(cost, model=self.model, key=key)
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            try:
                result = parse_response(content)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning("%s attempt %d: unusable reply: %s", self.model, attempt, exc)
                continue

            record = {
                **asdict(result),
                "model": self.model,
                "prompt_version": self.prompt_version,
                "input_mode": self.input_mode,
                "replicate": replicate,
                "input_chars": len(message),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "cost_usd": cost,
                "attempts": attempt,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=1))
            return {**record, "cached": False}
        raise RuntimeError(f"{self.model} failed after {self.max_retries} attempts: {last_error}")


class _RetryableError(RuntimeError):
    def __init__(self, message: str, wait: float = 0.0) -> None:
        super().__init__(message)
        self.wait = wait
