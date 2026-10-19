"""Load the data the site is built from, and derive the series its charts show.

The site reads the files described in ``docs/data-contract.md``:

* ``data/scores.parquet`` (written by ``hawk.scoring.score_all``). When it does not
  exist yet, ``preview_scores`` builds a stand-in with the same columns: the real
  pilot LLM scores for the documents the pilot covered, and the word-list baseline
  for everything else. The site then says "Preview" on every page.
* ``data/analysis/findings.json`` and ``data/analysis/evaluation.json``, both optional.
* the market files in ``data/market/``.

Everything here is a pure function of those files, so the build is reproducible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hawk.scoring import baseline, lexicon, speakers
from hawk.scoring.corpus import build_documents
from hawk.scoring.llm import DEFAULT_INPUT_MODE, DEFAULT_MODEL, PROMPT_VERSION
from hawk.scoring.score_all import scores_table
from hawk.site import config

log = logging.getLogger(__name__)

PREVIEW_MODEL = "preview"


@dataclass
class Inputs:
    """Paths of every input file, relative to ``root`` unless given explicitly."""

    root: Path = Path(".")
    scores: Path | None = None
    findings: Path | None = None
    evaluation: Path | None = None
    cache_dir: Path | None = None

    def path(self, rel: str) -> Path:
        return self.root / rel

    @property
    def scores_path(self) -> Path:
        return self.scores or self.path("data/scores.parquet")

    @property
    def findings_path(self) -> Path:
        return self.findings or self.path("data/analysis/findings.json")

    @property
    def evaluation_path(self) -> Path:
        return self.evaluation or self.path("data/analysis/evaluation.json")

    @property
    def cache_path(self) -> Path:
        return self.cache_dir or self.path("site/.cache")


@dataclass
class SiteData:
    scores: pd.DataFrame
    preview: bool
    decisions: pd.DataFrame
    bank_rate: pd.DataFrame
    members: pd.DataFrame
    findings: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    member_slugs: dict[str, str] = field(default_factory=dict)


# -- scores -------------------------------------------------------------------


def _fingerprint(paths: list[Path]) -> str:
    """Cache key for the preview scores: input files plus the baseline's own code."""
    h = hashlib.sha256()
    for p in [*paths, Path(str(baseline.__file__)), Path(str(lexicon.__file__))]:
        h.update(p.read_bytes() if p.suffix in {".py", ".csv"} else str(p.stat()).encode())
    return h.hexdigest()[:16]


def preview_scores(inputs: Inputs, decisions: pd.DataFrame) -> pd.DataFrame:
    """A stand-in for ``data/scores.parquet`` built without calling any API.

    Pilot LLM scores (default model and input mode, first replicate) are used where
    the pilot scored the document. Elsewhere the ``llm_*`` columns are filled from the
    word-list baseline: stance = baseline stance (``None`` when the baseline thinks
    the document is not about policy), relevance = policy density / 3, capped at 1.
    The ``model`` column says ``preview`` and ``input_mode`` says where each score
    came from (``pilot`` or ``baseline``).
    """
    sources = [
        inputs.path("data/speeches.parquet"),
        inputs.path("data/minutes.parquet"),
        inputs.path("data/market/mpc_members.csv"),
        inputs.path("data/pilot/pilot_scores.csv"),
    ]
    cache = inputs.cache_path / f"preview_scores-{_fingerprint([s for s in sources if s.exists()])}"
    cache = cache.with_suffix(".parquet")
    if cache.exists():
        return pd.read_parquet(cache)

    tenures = speakers.load_tenures(sources[2], decisions=decisions)
    docs = build_documents(pd.read_parquet(sources[0]), pd.read_parquet(sources[1]), tenures)

    pilot: dict[str, dict[str, Any]] = {}
    if sources[3].exists():
        p = pd.read_csv(sources[3])
        p = p[
            (p["model"] == DEFAULT_MODEL)
            & (p["input_mode"] == DEFAULT_INPUT_MODE)
            & (p["replicate"] == 0)
        ]
        pilot = {str(r["doc_id"]): {str(k): v for k, v in r.items()} for r in p.to_dict("records")}

    rows = []
    for doc_id, text in zip(docs["doc_id"], docs["text"], strict=True):
        b = baseline.score_text(text)
        row: dict[str, Any] = {
            "doc_id": doc_id,
            "baseline_stance": round(b.stance, 3),
            "baseline_hawkish": b.hawkish,
            "baseline_dovish": b.dovish,
            "baseline_relevance": round(b.relevance, 3),
        }
        if doc_id in pilot:
            rec = pilot[doc_id]
            stance = None if pd.isna(rec["stance"]) else float(rec["stance"])
            row |= {
                "llm_relevance": float(rec["relevance"]),
                "llm_stance": stance,
                "llm_confidence": float(rec["confidence"]),
                "llm_reason": str(rec["reason"]),
                "source": "pilot",
            }
        else:
            row |= {
                "llm_relevance": round(min(1.0, b.relevance / 3), 2),
                "llm_stance": round(b.stance, 2) if b.is_relevant else None,
                "llm_confidence": None,
                "llm_reason": (
                    f"Preview: word-list baseline ({b.hawkish} hawkish and {b.dovish} dovish "
                    "phrases). The AI score will replace this."
                ),
                "source": "baseline",
            }
        rows.append(row)

    out = scores_table(docs, rows, model=PREVIEW_MODEL, input_mode="", prompt_version="")
    out["input_mode"] = [r["source"] for r in rows]
    out["llm_confidence"] = pd.to_numeric(out["llm_confidence"]).astype("float64")
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def load_scores(inputs: Inputs, decisions: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """``(scores, preview)``; preview scores when ``data/scores.parquet`` is missing."""
    if inputs.scores_path.exists():
        df = pd.read_parquet(inputs.scores_path)
        missing = {"doc_id", "kind", "published_date", "llm_stance"} - set(df.columns)
        if missing:
            raise ValueError(f"{inputs.scores_path} is missing columns {sorted(missing)}")
        return df, False
    log.warning("%s not found: building with PREVIEW scores", inputs.scores_path)
    return preview_scores(inputs, decisions), True


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load(inputs: Inputs) -> SiteData:
    market = inputs.path("data/market")
    decisions = pd.read_parquet(market / "mpc_decisions.parquet")
    scores, preview = load_scores(inputs, decisions)
    scores = scores.copy()
    scores["published_date"] = pd.to_datetime(scores["published_date"])
    scores = scores.sort_values(["published_date", "doc_id"]).reset_index(drop=True)
    members = pd.read_csv(market / "mpc_members.csv", parse_dates=["first_vote", "last_vote"])
    return SiteData(
        scores=scores,
        preview=preview,
        decisions=decisions,
        bank_rate=pd.read_parquet(market / "bank_rate.parquet"),
        members=members,
        findings=_read_json(inputs.findings_path),
        evaluation=_read_json(inputs.evaluation_path),
        member_slugs={str(m): slugify(str(m)) for m in members["member"]},
    )


# -- derived series -------------------------------------------------------------


def _num(x: Any, digits: int = 2) -> float | None:
    if x is None or pd.isna(x):
        return None
    return round(float(x), digits)


def day_month_year(d: pd.Timestamp) -> str:
    """``3 Aug 2023`` (no ``%-d``, which Windows lacks)."""
    return f"{d.day} {d:%b %Y}"


def _ts(d: pd.Timestamp) -> int:
    """Unix seconds, which is what uPlot's time axis expects."""
    return int(pd.Timestamp(d).timestamp())


def mpc_signal(scores: pd.DataFrame) -> pd.DataFrame:
    """Documents that carry MPC policy signal: minutes, and speeches by sitting members,
    that are about monetary policy and have a stance."""
    is_mpc = (scores["kind"] == "minutes") | scores["is_mpc_member"].fillna(False).astype(bool)
    keep = (
        is_mpc
        & (scores["llm_relevance"] >= config.RELEVANCE_THRESHOLD)
        & scores["llm_stance"].notna()
    )
    return scores.loc[keep, ["published_date", "llm_stance", "speaker", "kind"]]


def trailing_mean(
    dates: pd.Series,
    values: pd.Series,
    at: pd.DatetimeIndex,
    window_days: int = config.TONE_WINDOW_DAYS,
    min_docs: int = config.TONE_MIN_DOCS,
) -> tuple[list[float | None], list[int]]:
    """Mean of ``values`` published in the ``window_days`` up to and including each
    date in ``at`` (never after it), or ``None`` with fewer than ``min_docs``."""
    d = pd.to_datetime(dates).to_numpy()
    v = values.to_numpy(dtype=float)
    order = np.argsort(d)
    d, v = d[order], v[order]
    csum = np.concatenate([[0.0], np.cumsum(v)])
    window = np.timedelta64(window_days, "D")
    means: list[float | None] = []
    counts: list[int] = []
    for t in at.to_numpy():
        hi = np.searchsorted(d, t, side="right")
        lo = np.searchsorted(d, t - window, side="right")
        n = int(hi - lo)
        counts.append(n)
        means.append(round(float((csum[hi] - csum[lo]) / n), 3) if n >= min_docs else None)
    return means, counts


def tone_index(scores: pd.DataFrame, end: pd.Timestamp | None = None) -> dict[str, Any]:
    """Monthly trailing tone of MPC-relevant documents (see ``mpc_signal``)."""
    sig = mpc_signal(scores)
    if sig.empty:
        return {"x": [], "tone": [], "n": []}
    start = sig["published_date"].min()
    end = end or sig["published_date"].max()
    months = pd.date_range(start, end + pd.offsets.MonthEnd(0), freq="ME")
    tone, n = trailing_mean(sig["published_date"], sig["llm_stance"], months)
    return {"x": [_ts(m) for m in months], "tone": tone, "n": n}


def rate_path(
    bank_rate: pd.DataFrame, decisions: pd.DataFrame, end: pd.Timestamp
) -> dict[str, Any]:
    """Bank Rate as a step series, and the hike and cut decision dates."""
    br = bank_rate.sort_values("date")
    x = [_ts(d) for d in br["date"]] + [_ts(end)]
    y = [round(float(r), 3) for r in br["rate_pct"]] + [round(float(br["rate_pct"].iloc[-1]), 3)]
    moves = decisions[decisions["decision"].isin(["hike", "cut"])].sort_values("date")
    return {
        "x": x,
        "rate": y,
        "moves": [
            {
                "x": _ts(r["date"]),
                "date": day_month_year(r["date"]),
                "decision": r["decision"],
                "bp": int(r["change_bp"]),
                "rate": float(r["rate_pct"]),
            }
            for r in moves.to_dict("records")
        ],
    }


def eras() -> list[dict[str, Any]]:
    return [
        {"label": e.label, "from": _ts(pd.Timestamp(e.start)), "to": _ts(pd.Timestamp(e.end))}
        for e in config.ERAS
    ]


# -- explorer -------------------------------------------------------------------

DOC_COLUMNS = [
    "id",
    "kind",
    "date",
    "speaker",
    "title",
    "url",
    "mpc",
    "relevance",
    "stance",
    "confidence",
    "reason",
    "baseline",
]


def docs_json(scores: pd.DataFrame, member_slugs: dict[str, str]) -> dict[str, Any]:
    """Compact table for the speech explorer: no texts, speaker names interned, and the
    BoE URL prefix stripped (the page adds it back)."""
    names = sorted({str(s) for s in scores["speaker"].dropna()})
    index = {n: i for i, n in enumerate(names)}
    prefix = config.BOE_URL_PREFIX
    rows = []
    for r in scores.to_dict("records"):
        url = str(r["url"])
        mpc = r["is_mpc_member"]
        rows.append(
            [
                r["doc_id"],
                "m" if r["kind"] == "minutes" else "s",
                r["published_date"].strftime("%Y-%m-%d"),
                index[str(r["speaker"])] if isinstance(r["speaker"], str) else -1,
                r["title"],
                url.removeprefix(prefix),
                None if mpc is None or pd.isna(mpc) else int(bool(mpc)),
                _num(r["llm_relevance"]),
                _num(r["llm_stance"]),
                _num(r["llm_confidence"]),
                r["llm_reason"] if isinstance(r["llm_reason"], str) else "",
                _num(r["baseline_stance"]),
            ]
        )
    return {
        "columns": DOC_COLUMNS,
        "url_prefix": prefix,
        "speakers": names,
        "members": {n: member_slugs[n] for n in names if n in member_slugs},
        "rows": rows,
    }


# -- members --------------------------------------------------------------------

_DISSENT = re.compile(r"\s*(?P<name>[^;(]+?)\s*\((?P<move>hike|cut|hold)(?:\s+(?P<bp>\d+)bp)?\)")


def parse_dissenters(text: str | None) -> list[dict[str, Any]]:
    """``"Huw Pill (hike 25bp); Swati Dhingra (hold)"`` -> one dict per dissenter;
    ``bp`` is the move each wanted from the previous Bank Rate."""
    if not text or pd.isna(text):
        return []
    out = []
    for m in _DISSENT.finditer(str(text)):
        move, bp = m["move"], int(m["bp"] or 0)
        out.append({"name": m["name"].strip(), "move": move, "bp": 0 if move == "hold" else bp})
    return out


def member_profiles(data: SiteData) -> list[dict[str, Any]]:
    """One record per MPC member: tenure, speech tone and dissent history."""
    scores, decisions = data.scores, data.decisions.sort_values("date")
    latest = decisions["date"].max()
    sig = mpc_signal(scores)
    speeches = sig[sig["kind"] == "speech"]
    profiles = []
    for row in data.members.to_dict("records"):
        name = str(row["member"])
        first, last = pd.Timestamp(row["first_vote"]), pd.Timestamp(row["last_vote"])
        window_end = latest if last >= latest else last
        own_all = scores[(scores["speaker"] == name) & (scores["kind"] == "speech")]
        own = speeches[speeches["speaker"] == name]
        in_tenure = speeches[
            (speeches["published_date"] >= first - pd.Timedelta(days=90))
            & (speeches["published_date"] <= window_end + pd.Timedelta(days=45))
        ]
        dissents = []
        for d in decisions[(decisions["date"] >= first) & (decisions["date"] <= last)].to_dict(
            "records"
        ):
            for p in parse_dissenters(d["dissenters"]):
                if p["name"] != name:
                    continue
                sign = {"hike": 1, "cut": -1, "hold": 0}[p["move"]]
                wanted = float(d["prev_rate_pct"]) + sign * p["bp"] / 100
                agreed = float(d["rate_pct"])
                dissents.append(
                    {
                        "date": day_month_year(d["date"]),
                        "x": _ts(d["date"]),
                        "decision": d["decision"],
                        "agreed": agreed,
                        "wanted": round(wanted, 3),
                        "direction": "higher" if wanted > agreed else "lower",
                        "vote_split": d["vote_split"],
                    }
                )
        own_mean = _num(own["llm_stance"].mean()) if len(own) else None
        committee_mean = _num(in_tenure["llm_stance"].mean()) if len(in_tenure) else None
        speeches_list = [
            {
                "id": r["doc_id"],
                "date": r["published_date"].strftime("%Y-%m-%d"),
                "title": r["title"],
                "url": r["url"],
                "stance": _num(r["llm_stance"]),
                "relevance": _num(r["llm_relevance"]),
                "mpc": bool(r["is_mpc_member"]) if not pd.isna(r["is_mpc_member"]) else False,
            }
            for r in own_all.sort_values("published_date", ascending=False).to_dict("records")
        ]
        profiles.append(
            {
                "name": name,
                "slug": data.member_slugs[name],
                "first_vote": first.strftime("%b %Y"),
                "last_vote": last.strftime("%b %Y"),
                "first_year": first.year,
                "serving": bool(last >= latest),
                "n_votes": int(row["n_votes"]),
                "n_speeches": len(own_all),
                "n_scored": len(own),
                "mean_stance": own_mean,
                "committee_mean": committee_mean,
                "dissents": dissents,
                "n_higher": sum(d["direction"] == "higher" for d in dissents),
                "n_lower": sum(d["direction"] == "lower" for d in dissents),
                "chart": {
                    "x": [_ts(d) for d in own["published_date"]],
                    "stance": [float(s) for s in own["llm_stance"]],
                    "first": _ts(first),
                    "last": _ts(window_end),
                },
                "speeches": speeches_list,
            }
        )
    return profiles


def committee_line(scores: pd.DataFrame, start: int, end: int) -> dict[str, Any]:
    """Trailing committee tone (all MPC documents) at month ends between two times."""
    sig = mpc_signal(scores)
    lo = pd.Timestamp(start, unit="s") - pd.Timedelta(days=60)
    hi = pd.Timestamp(end, unit="s") + pd.Timedelta(days=31)
    months = pd.date_range(lo, hi, freq="ME")
    tone, _ = trailing_mean(sig["published_date"], sig["llm_stance"], months)
    return {"x": [_ts(m) for m in months], "tone": tone}


def corpus_stats(data: SiteData) -> dict[str, Any]:
    s = data.scores
    return {
        "n_docs": len(s),
        "n_speeches": int((s["kind"] == "speech").sum()),
        "n_minutes": int((s["kind"] == "minutes").sum()),
        "n_mpc_speeches": int(s["is_mpc_member"].fillna(False).astype(bool).sum()),
        "n_members": len(data.members),
        "n_decisions": len(data.decisions),
        "first_year": int(s["published_date"].min().year) if len(s) else None,
        "last_year": int(s["published_date"].max().year) if len(s) else None,
        "n_pilot": int((s["input_mode"] == "pilot").sum()) if data.preview else 0,
        "model": None if data.preview else str(s["model"].iloc[0]) if len(s) else None,
        "prompt_version": PROMPT_VERSION,
    }
