"""Build the static website into ``site/_build/``.

Usage::

    python -m hawk.site.build                  # from the repository root
    python -m hawk.site.build --out /tmp/site --scores path/to/scores.parquet

Reads the files described in ``docs/data-contract.md``. Without ``data/scores.parquet``
the site is built in preview mode (demo scores, a banner on every page); without
``data/analysis/findings.json`` the findings show "coming soon" placeholders.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup

from hawk.site import config
from hawk.site.data import (
    Inputs,
    SiteData,
    committee_line,
    corpus_stats,
    docs_json,
    eras,
    load,
    member_profiles,
    rate_path,
    tone_index,
)

log = logging.getLogger("hawk.site.build")

OUT_DIR = Path("site/_build")
DASH, MINUS = "\u2013", "\u2212"
NAV = [
    ("home", "Home", ""),
    ("speeches", "Speeches", "speeches/"),
    ("members", "MPC members", "members/"),
    ("findings", "Findings", "findings/"),
    ("methodology", "Methodology", "methodology/"),
    ("about", "About", "about/"),
]


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("hawk.site", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["stance"] = fmt_stance
    env.filters["pct"] = lambda x: DASH if x is None else f"{100 * x:.0f}%"
    env.filters["num"] = lambda x, d=2: DASH if x is None else f"{x:.{d}f}"
    env.filters["thousands"] = lambda x: f"{x:,}"
    env.filters["stance_class"] = stance_class
    return env


def fmt_stance(x: float | None) -> str:
    if x is None or pd.isna(x):
        return DASH
    return f"{x:+.2f}".replace("-", MINUS) if x else "0.00"


def stance_class(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "none"
    return "hawk" if x > 0.05 else "dove" if x < -0.05 else "neutral"


def render_markdown(text: str) -> Markup:
    """Methodology markdown to HTML: drop the H1, anchor the H2s, point repo links at GitHub."""
    text = re.sub(r"\A# .*\n", "", text)
    html = MarkdownIt("commonmark").enable("table").render(text)

    def anchor(m: re.Match[str]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", m[2]).lower()).strip("-")
        return f'<h{m[1]} id="{slug}">{m[2]}</h{m[1]}>'

    html = re.sub(r"<h([23])>(.*?)</h\1>", anchor, html)

    def link(m: re.Match[str]) -> str:
        href = m[1]
        if re.match(r"^(https?:|#|mailto:)", href):
            return f'href="{href}"'
        return f'href="{config.REPO_URL}/blob/main/docs/{href}"'

    html = re.sub(r'href="([^"]+)"', link, html)
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )
    return Markup(html)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def render_images(out: Path, tone: dict[str, Any]) -> None:
    """Open Graph card (1200x630) and the Apple touch icon, drawn with matplotlib."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hawk, dove, ink, muted = "#d9480f", "#2a78d6", "#1d1d1f", "#6e6e73"
    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor="#fbfbfd")
    fig.text(0.06, 0.82, "Hawk", fontsize=60, fontweight="bold", color=ink)
    fig.text(0.06, 0.72, config.TAGLINE, fontsize=22, color=muted)
    ax = fig.add_axes((0.06, 0.12, 0.88, 0.5))
    pts = [(x, y) for x, y in zip(tone["x"], tone["tone"], strict=True) if y is not None]
    if pts:
        xs = [pd.Timestamp(x, unit="s") for x, _ in pts]
        ys = [y for _, y in pts]
        ax.fill_between(xs, ys, 0, where=[y >= 0 for y in ys], color=hawk, alpha=0.18, lw=0)
        ax.fill_between(xs, ys, 0, where=[y < 0 for y in ys], color=dove, alpha=0.18, lw=0)
        ax.plot(xs, ys, color=ink, lw=2.2)
        ax.axhline(0, color=muted, lw=0.8, alpha=0.5)
    ax.set_axis_off()
    fig.text(
        0.06,
        0.05,
        "Dovish  ←  tone of Bank of England communication  →  Hawkish",
        fontsize=15,
        color=muted,
    )
    fig.savefig(out / "og.png", facecolor=fig.get_facecolor())
    plt.close(fig)

    fig = plt.figure(figsize=(1.8, 1.8), dpi=100, facecolor=ink)
    ax = fig.add_axes((0.2, 0.2, 0.6, 0.6))
    ax.plot([0, 0.5], [0.15, 0.85], color=hawk, lw=9, solid_capstyle="round")
    ax.plot([0.5, 1], [0.85, 0.15], color=dove, lw=9, solid_capstyle="round")
    ax.set_xlim(-0.1, 1.1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    fig.savefig(out / "apple-touch-icon.png", facecolor=ink)
    plt.close(fig)


def build(inputs: Inputs, out: Path = OUT_DIR, *, images: bool = True) -> dict[str, Any]:
    """Build the whole site into ``out`` (wiped first). Returns the site manifest."""
    data: SiteData = load(inputs)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    end = max(data.scores["published_date"].max(), data.decisions["date"].max())
    tone = tone_index(data.scores, end)
    rates = rate_path(data.bank_rate, data.decisions, end)
    stats = corpus_stats(data)
    profiles = member_profiles(data)
    built_at = datetime.now(UTC)
    pages: list[str] = []
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "built_at": built_at.isoformat(timespec="seconds"),
        "preview": data.preview,
        "has_findings": data.findings is not None,
        "has_evaluation": data.evaluation is not None,
        "stats": stats,
        "pages": pages,
    }

    env = _env()
    methodology_md = inputs.path("docs/methodology.md")
    common: dict[str, Any] = {
        "config": config,
        "nav": NAV,
        "preview": data.preview,
        "stats": stats,
        "findings": data.findings,
        "evaluation": data.evaluation,
        "built": f"{built_at.day} {built_at:%B %Y}",
        "json": _json,
    }

    def page(rel: str, template: str, active: str, title: str, desc: str, **ctx: Any) -> None:
        # Relative links everywhere, so the site works under any base path. The 404 page
        # is served at whatever URL was missing, so it uses absolute ones instead.
        root = "../" * rel.count("/") if rel != "404.html" else urlparse(config.SITE_URL).path
        path = rel.removesuffix("index.html")
        html = env.get_template(template).render(
            **common,
            **ctx,
            root=root,
            active=active,
            title=title,
            description=desc,
            canonical=config.SITE_URL + path,
        )
        _write(out / rel, html)
        pages.append(rel)

    hero = {"tone": tone, "rate": rates, "eras": eras()}
    page(
        "index.html",
        "home.html",
        "home",
        f"{config.SITE_NAME}: Bank of England tone, 1997 to today",
        config.DESCRIPTION,
        hero=hero,
    )
    page(
        "speeches/index.html",
        "speeches.html",
        "speeches",
        f"Speech explorer · {config.SITE_NAME}",
        "Search and filter every Bank of England speech and set of MPC minutes since 1997 "
        "by speaker, year and hawkish-to-dovish tone.",
    )
    page(
        "members/index.html",
        "members.html",
        "members",
        f"MPC members · {config.SITE_NAME}",
        "The tone and voting record of every member of the Bank of England's Monetary "
        "Policy Committee since 1997.",
        members=profiles,
    )
    for p in profiles:
        p["committee"] = committee_line(data.scores, p["chart"]["first"], p["chart"]["last"])
        page(
            f"members/{p['slug']}/index.html",
            "member.html",
            "members",
            f"{p['name']} · MPC members · {config.SITE_NAME}",
            f"{p['name']} on the Bank of England's Monetary Policy Committee "
            f"({p['first_vote']} to {'today' if p['serving'] else p['last_vote']}): speech "
            "tone compared with the committee, and dissent history.",
            m=p,
        )
    page(
        "findings/index.html",
        "findings.html",
        "findings",
        f"Findings · {config.SITE_NAME}",
        "Did Bank of England tone shift before rate decisions, and did 2-year gilt yields "
        "react? The event study, prediction test and market reaction.",
    )
    page(
        "methodology/index.html",
        "methodology.html",
        "methodology",
        f"Methodology · {config.SITE_NAME}",
        "How Hawk scores Bank of England communication from dovish to hawkish, how it avoids "
        "look-ahead, and how accurate the AI scorer is against hand labels.",
        body=render_markdown(methodology_md.read_text()) if methodology_md.exists() else "",
    )
    page(
        "about/index.html",
        "about.html",
        "about",
        f"About · {config.SITE_NAME}",
        f"About {config.SITE_NAME}, an open-source project by {config.AUTHOR}.",
    )
    page("404.html", "404.html", "", f"Not found · {config.SITE_NAME}", config.DESCRIPTION)

    static = resources.files("hawk.site") / "static"
    for item in static.iterdir():
        dest = out / "static" / item.name
        if item.is_dir():
            for sub in item.iterdir():
                (dest).mkdir(parents=True, exist_ok=True)
                (dest / sub.name).write_bytes(sub.read_bytes())
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item.read_bytes())
    (out / "favicon.svg").write_bytes((static / "favicon.svg").read_bytes())

    _write(out / "data" / "docs.json", _json(docs_json(data.scores, data.member_slugs)))
    _write(out / "data" / "tone_index.json", _json(hero))
    _write(out / ".nojekyll", "")
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}sitemap.xml\n")
    urls = "".join(
        f"<url><loc>{config.SITE_URL}{p.removesuffix('index.html')}</loc></url>"
        for p in pages
        if p != "404.html"
    )
    _write(
        out / "sitemap.xml",
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
    )
    if images:
        render_images(out, tone)
    _write(out / "data" / "site.json", json.dumps(manifest, indent=2) + "\n")
    log.info(
        "built %d pages into %s (%s)",
        len(pages),
        out,
        "PREVIEW scores" if data.preview else "final scores",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--findings", type=Path, default=None)
    parser.add_argument("--evaluation", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("hawk.scoring.corpus").setLevel(logging.ERROR)
    inputs = Inputs(args.root, args.scores, args.findings, args.evaluation)
    build(inputs, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
