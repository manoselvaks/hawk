from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from hawk.scoring.score_all import SCORES_COLUMNS
from hawk.site.build import build, main, render_markdown
from hawk.site.data import Inputs, parse_dissenters, trailing_mean

from .conftest import FIXTURES

PAGES = [
    "index.html",
    "speeches/index.html",
    "members/index.html",
    "members/huw-pill/index.html",
    "members/swati-dhingra/index.html",
    "findings/index.html",
    "methodology/index.html",
    "about/index.html",
    "404.html",
]


def _docs(out: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / "data" / "docs.json").read_text())
    return data


def test_preview_build_without_scores_or_findings(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    manifest = build(Inputs(repo), out, images=False)

    assert manifest["preview"] is True
    assert manifest["has_findings"] is False and manifest["has_evaluation"] is False
    for page in PAGES:
        html = (out / page).read_text()
        assert "<title>" in html and 'name="description"' in html and "og:image" in html
        assert "Preview: scores are not final" in html, page
    assert "Coming soon" in (out / "findings" / "index.html").read_text()
    assert "Coming soon" in (out / "index.html").read_text()
    assert "Scored against 36 hand labels" in (out / "methodology" / "index.html").read_text()

    docs = _docs(out)
    assert len(docs["rows"]) == 6  # 4 speeches + 2 minutes
    assert docs["columns"][:3] == ["id", "kind", "date"]
    assert not any("bankofengland" in str(r[5]) for r in docs["rows"])  # prefix stripped
    assert (out / "data" / "site.json").exists() and (out / ".nojekyll").exists()
    assert (out / "static" / "vendor" / "uPlot.iife.min.js").exists()
    assert (out / "favicon.svg").exists()
    # The preview scores are cached, so a second build reuses them.
    assert list((repo / "site" / ".cache").glob("preview_scores-*.parquet"))


def test_build_with_scores_findings_and_evaluation(repo: Path, tmp_path: Path) -> None:
    preview_out = tmp_path / "preview"
    build(Inputs(repo), preview_out, images=False)
    cached = next((repo / "site" / ".cache").glob("preview_scores-*.parquet"))
    scores = pd.read_parquet(cached)
    scores["model"], scores["input_mode"], scores["prompt_version"] = "m/x", "full", "stance_v1"
    assert list(scores.columns) == SCORES_COLUMNS
    scores.to_parquet(repo / "data" / "scores.parquet", index=False)
    (repo / "data" / "analysis").mkdir()
    shutil.copy(FIXTURES / "findings.json", repo / "data" / "analysis" / "findings.json")
    shutil.copy(FIXTURES / "evaluation.json", repo / "data" / "analysis" / "evaluation.json")

    out = tmp_path / "out"
    manifest = build(Inputs(repo), out)

    assert manifest["preview"] is False and manifest["has_findings"] is True
    assert manifest["stats"]["model"] == "m/x"
    for page in PAGES:
        assert "Preview: scores are not final" not in (out / page).read_text(), page
    home = (out / "index.html").read_text()
    assert "\u03c1 = 0.71" in home and "Coming soon" not in home
    findings = (out / "findings" / "index.html").read_text()
    assert 'id="es-chart"' in findings and "Previous decision + tone change" in findings
    assert "Change in tone (4 weeks)" in findings and "MPC speech day" in findings
    methodology = (out / "methodology" / "index.html").read_text()
    assert "Spearman" in methodology and "0.78" in methodology
    assert (out / "og.png").stat().st_size > 1000
    assert (out / "apple-touch-icon.png").exists()


def test_member_pages_show_dissents(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    build(Inputs(repo), out, images=False)
    pill = (out / "members" / "huw-pill" / "index.html").read_text()
    assert "Dissent history" in pill and "1.50%" in pill  # wanted +75bp from 0.75%
    dhingra = (out / "members" / "swati-dhingra" / "index.html").read_text()
    assert "3.50%" in dhingra  # voted to hold at 3.5% when the MPC hiked to 4%


def test_cli(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "cli"
    assert main(["--root", str(repo), "--out", str(out)]) == 0
    assert (out / "index.html").exists()


def test_parse_dissenters() -> None:
    assert parse_dissenters("Huw Pill (hike 25bp); Swati Dhingra (hold)") == [
        {"name": "Huw Pill", "move": "hike", "bp": 25},
        {"name": "Swati Dhingra", "move": "hold", "bp": 0},
    ]
    assert parse_dissenters(None) == []


def test_trailing_mean_never_looks_ahead() -> None:
    dates = pd.Series(pd.to_datetime(["2020-01-10", "2020-01-20", "2020-03-01"]))
    values = pd.Series([1.0, -1.0, 2.0])
    at = pd.DatetimeIndex(pd.to_datetime(["2020-01-15", "2020-01-31", "2020-02-29"]))
    means, counts = trailing_mean(dates, values, at, window_days=30, min_docs=1)
    assert counts == [1, 2, 0]  # the March document never counts
    assert means == [1.0, 0.0, None]


def test_render_markdown_links_and_anchors() -> None:
    html = str(render_markdown("# Title\n\n## The scale\n\nSee [pilot](pilot.md).\n"))
    assert "<h1>" not in html and 'id="the-scale"' in html
    assert 'href="https://github.com/manoselvaks/hawk/blob/main/docs/pilot.md"' in html
