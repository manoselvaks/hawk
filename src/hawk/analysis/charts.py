"""Static PNG charts for docs/findings.md and the README (matplotlib, site colours)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hawk.site.config import ERAS
from hawk.site.data import mpc_signal, trailing_mean

HAWK, DOVE, NEUTRAL = "#d9480f", "#2a78d6", "#8e8e93"
INK, MUTED, GRID = "#1d1d1f", "#6e6e73", "#e6e6ea"
COLOURS = {"hike": HAWK, "cut": DOVE, "hold": NEUTRAL}


def _style(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def event_study_chart(es: dict[str, Any], path: Path) -> None:
    x = np.array(es["offsets_weeks"], dtype=float)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    _style(ax)
    ax.axhline(0, color="#c7c7cc", linewidth=1)
    for s in es["series"]:
        c = COLOURS[s["decision"]]
        mean = np.array([np.nan if v is None else v for v in s["mean"]], dtype=float)
        lo = np.array([np.nan if v is None else v for v in s["ci_low"]], dtype=float)
        hi = np.array([np.nan if v is None else v for v in s["ci_high"]], dtype=float)
        ax.fill_between(x, lo, hi, color=c, alpha=0.12, linewidth=0)
        ax.plot(x, mean, color=c, linewidth=2)
        ax.annotate(
            f"{s['decision'].capitalize()} ({s['n_events']})",
            (x[-1], mean[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            color=INK,
            fontsize=9,
            va="center",
        )
    ax.set_xticks(x[::2])
    ax.set_xticklabels([("0" if v == 0 else f"{int(v)}w") for v in x[::2]])
    ax.set_xlim(x[0], x[-1] + 2.2)
    ax.set_xlabel(
        "Weeks before the decision (0 = the 7 days before the announcement)",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylabel("Mean stance (\u22122 dovish \u2026 +2 hawkish)", color=MUTED, fontsize=9)
    ax.set_title(
        "Tone of Bank of England communication before hikes, holds and cuts",
        loc="left",
        color=INK,
        fontsize=11,
    )
    fig.text(
        0.01,
        0.01,
        "Shaded: 95% bootstrap interval over decisions. MPC-relevant speeches "
        "and minutes, published before the announcement.",
        color=MUTED,
        fontsize=7.5,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def tone_rate_chart(scores: pd.DataFrame, decisions: pd.DataFrame, path: Path) -> None:
    """Two panels sharing the time axis: trailing six-month MPC tone, and Bank Rate."""
    sig = mpc_signal(scores)
    months = pd.date_range(sig["published_date"].min(), sig["published_date"].max(), freq="ME")
    tone, _ = trailing_mean(sig["published_date"], sig["llm_stance"], months)
    t = np.array([np.nan if v is None else v for v in tone], dtype=float)
    dec = decisions.sort_values("date")
    fig, (a1, a2) = plt.subplots(
        2, 1, figsize=(9, 5), dpi=150, sharex=True, gridspec_kw={"height_ratios": [3, 2]}
    )
    for ax in (a1, a2):
        _style(ax)
        for e in ERAS:
            ax.axvspan(
                pd.Timestamp(e.start),
                pd.Timestamp(e.end),
                color="#000000",
                alpha=0.045,
                linewidth=0,
            )
    a1.axhline(0, color="#c7c7cc", linewidth=1)
    a1.fill_between(months, 0, t, where=t >= 0, color=HAWK, alpha=0.15, linewidth=0)
    a1.fill_between(months, 0, t, where=t < 0, color=DOVE, alpha=0.15, linewidth=0)
    a1.plot(months, t, color=INK, linewidth=1.2)
    a1.set_ylabel("Tone (6-month avg)", color=MUTED, fontsize=9)
    a1.set_title("MPC tone and Bank Rate, 1997\u20132026", loc="left", color=INK, fontsize=11)
    a2.step(dec["date"], dec["rate_pct"], where="post", color=INK, linewidth=1.4)
    for kind, c in (("hike", HAWK), ("cut", DOVE)):
        d = dec[dec["decision"] == kind]
        a2.scatter(
            d["date"],
            d["rate_pct"],
            s=12,
            color=c,
            zorder=3,
            label=kind.capitalize(),
            edgecolor="white",
            linewidth=0.5,
        )
    a2.set_ylabel("Bank Rate (%)", color=MUTED, fontsize=9)
    a2.legend(frameon=False, fontsize=8, loc="upper right")
    fig.text(
        0.01,
        0.01,
        "Tone: trailing six-month mean stance of MPC minutes and speeches by "
        "sitting members about monetary policy. Shaded: financial crisis, Brexit vote, "
        "COVID, inflation surge.",
        color=MUTED,
        fontsize=7,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def market_chart(mr: dict[str, Any], path: Path) -> None:
    rows = mr["by_stance"]
    fig, ax = plt.subplots(figsize=(7, 3), dpi=150)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    y = np.arange(len(rows))[::-1]
    colours = [DOVE, NEUTRAL, HAWK]
    for yi, r, c in zip(y, rows, colours, strict=True):
        ax.barh(yi, r["value"], color=c, height=0.5)
        if r.get("ci_low") is not None:
            ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=INK, linewidth=1)
    ax.axvline(0, color="#c7c7cc", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r['label']}  n={r['n']}" for r in rows], color=INK, fontsize=9)
    ax.set_xlabel(
        "Mean change in 2-year gilt yield on the day (bp), with 95% interval",
        color=MUTED,
        fontsize=9,
    )
    ax.set_title(
        "2-year gilt moves on days with an MPC-relevant speech", loc="left", color=INK, fontsize=11
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
