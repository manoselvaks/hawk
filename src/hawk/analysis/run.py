"""Run every analysis and write the results.

Usage::

    python -m hawk.analysis.run          # needs data/scores.parquet

Writes:

* ``data/analysis/findings.json``: the website's file (schema in
  ``docs/data-contract.md``);
* ``data/analysis/findings_detail.json``: every number behind it, including the
  robustness checks, for ``docs/findings.md``;
* ``docs/img/*.png``: the charts used in ``docs/findings.md`` and the README.

Four tests are primary, fixed before looking at the results: the hike-minus-cut
difference in pre-decision tone (event study), the out-of-sample log-loss gain from
adding tone to the previous decision (prediction), the slope of the 2-year gilt move
on speech stance (market), and the slope of a member's dissent on their own tone.
With four tests, a Bonferroni threshold of 0.05 / 4 = 0.0125 keeps the chance of
any false positive near 5%. Everything else is a robustness check or description.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hawk.analysis import charts, dataset, dissent, event_study, market, prediction

log = logging.getLogger("hawk.analysis.run")

OUT_DIR = Path("data/analysis")
IMG_DIR = Path("docs/img")
MEMBERS_PATH = Path("data/market/mpc_members.csv")
EVALUATION_PATH = OUT_DIR / "evaluation.json"
N_PRIMARY = 4
ALPHA = 0.05 / N_PRIMARY


def clean(x: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python, floats rounded."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [clean(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float):
        return None if not math.isfinite(x) else round(x, 4)
    if isinstance(x, pd.Timestamp):
        return x.date().isoformat()
    return x


def _p_text(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def _sig(p: float | None) -> bool:
    return p is not None and p < ALPHA


def prediction_section(meetings: pd.DataFrame) -> dict[str, Any]:
    data = prediction.design(meetings)
    oos = prediction.expanding_window(data)
    rows = prediction.evaluate(oos)
    pr2 = prediction.in_sample_pseudo_r2(data)
    for r in rows:
        r["pseudo_r2"] = pr2.get(r["name"])
    gain = prediction.compare_log_loss(oos, "Previous decision", "Previous decision + tone")
    gain_mkt = prediction.compare_log_loss(
        oos, "Previous decision + market", "Previous decision + market + tone"
    )
    coefs, _ = prediction.full_sample(data, prediction.PREV + prediction.TONE)
    coefs_mkt, _ = prediction.full_sample(
        data, prediction.PREV + prediction.MARKET + prediction.TONE
    )

    # Robustness: other tone measures, same benchmark, out of sample.
    variants = [
        prediction.Spec("Previous decision", prediction.PREV, False),
        prediction.Spec(
            "+ tone, MPC documents only", [*prediction.PREV, "tone_mpc", "tone_mpc_change"], True
        ),
        prediction.Spec("+ tone, weighted", [*prediction.PREV, "tone_w", "tone_w_change"], True),
        prediction.Spec("+ tone change only", [*prediction.PREV, "tone_change"], True),
    ]
    oos_v = prediction.expanding_window(data, variants)
    robustness = {
        v.name: prediction.compare_log_loss(oos_v, "Previous decision", v.name)
        for v in variants[1:]
    }
    return {
        "n_meetings": len(data),
        "oos_start": prediction.OOS_START.date().isoformat(),
        "models": rows,
        "log_loss_gain_tone": gain,
        "log_loss_gain_tone_over_market": gain_mkt,
        "coefficients": coefs,
        "coefficients_with_market": coefs_mkt,
        "robustness": robustness,
        "class_counts": data["decision"].value_counts().to_dict(),
    }


def robustness_thresholds(
    scores: pd.DataFrame, decisions: pd.DataFrame, yields: pd.DataFrame
) -> dict[str, Any]:
    """Primary market slope and in-sample tone coefficient at other relevance cut-offs."""
    out: dict[str, Any] = {}
    for thr in (0.3, 0.8):
        m = dataset.add_market_features(
            dataset.meeting_features(scores, decisions, threshold=thr), yields
        )
        coefs, _ = prediction.full_sample(prediction.design(m), prediction.PREV + prediction.TONE)
        days = market.daily_changes(yields)
        sd = market.speech_days(scores, days, threshold=thr)
        ev = market.event_days(scores, decisions, days)
        p = days.merge(sd, on="date", how="inner")
        p = p[~p["date"].isin(ev)]
        out[str(thr)] = {
            "prediction_coefficients": coefs,
            "market_slope": market.slope(p, "stance"),
        }
    return out


# Rank agreement between the two AI models (GPT-6 Luna and Claude Haiku 5.5) on the same
# 33 labelled items, from the scorer comparison in docs/evaluation.md.
MODEL_AGREEMENT_RHO = 0.96


def _fmt(x: float, d: int = 2) -> str:
    """Signed number with a real minus sign, for text shown on the site."""
    return f"{x:+.{d}f}".replace("-", "\u2212")


def headline(es: dict[str, Any], pred: dict[str, Any], dis: dict[str, Any]) -> list[dict[str, Any]]:
    """The three home-page tiles: one per primary result, in plain English."""
    diff = es["hike_minus_cut"]
    tab = {r["decision"]: r for r in es["table"]}
    tiles = [
        {
            "id": "event_study",
            "label": (
                "Tone was clearly more hawkish before hikes than before cuts"
                if diff["ci_low"] > 0
                else "Tone before hikes and cuts was not clearly different"
            ),
            "value": diff["difference"],
            "display": _fmt(diff["difference"]),
            "detail": (
                f"Average tone in the 12 weeks before {tab['hike']['n_events']} hikes minus "
                f"before {tab['cut']['n_events']} cuts, on a \u22122 to +2 scale (95% CI "
                f"{_fmt(diff['ci_low'])} to {_fmt(diff['ci_high'])})."
            ),
        }
    ]
    gain = pred["log_loss_gain_tone"]
    tiles.append(
        {
            "id": "prediction",
            "label": (
                "But it didn't beat the market at predicting decisions"
                if gain["ci_low"] <= 0
                else "Tone helped predict decisions out of sample"
            ),
            "value": gain["mean_gain"],
            "display": _fmt(gain["mean_gain"], 3),
            "detail": (
                "Out-of-sample log-loss gain per meeting from adding tone to the previous "
                f"decision (95% CI {_fmt(gain['ci_low'], 3)} to {_fmt(gain['ci_high'], 3)}, "
                f"p = {gain['p_one_sided']:.2f}): not a reliable gain. The 2-year gilt yield, "
                "the market's own forecast, does far better."
            ),
        }
    )
    ds, dc = dis.get("slope"), dis.get("slope_controlling_prev_vote")
    if ds:
        tiles.append(
            {
                "id": "dissent",
                "label": (
                    "MPC members' speeches predicted their own dissenting votes"
                    if _sig(ds["p_value"])
                    else "Members' speeches did not clearly predict their dissents"
                ),
                "value": ds["estimate"],
                "display": _fmt(ds["estimate"], 2),
                "detail": (
                    "Change in a member's vote (+1 higher than the majority, \u22121 lower) per "
                    f"point of their own speech tone (p {_p_text(ds['p_value'])})"
                    + (
                        f"; {_fmt(dc['estimate'], 2)} after allowing for their previous vote."
                        if dc
                        else "."
                    )
                ),
            }
        )
    return tiles


def accuracy_line(evaluation: dict[str, Any] | None) -> dict[str, Any] | None:
    """How well the AI scorer agrees with the hand labels: shown under the home tiles."""
    if not evaluation:
        return None
    llm = next(x for x in evaluation["scorers"] if x["kind"] == "llm" and x.get("chosen", True))
    rho = llm["stance"]["spearman"]
    ci = llm["stance"].get("spearman_ci") or [None, None]
    ci_txt = f" (95% CI {ci[0]:.2f} to {ci[1]:.2f})" if ci[0] is not None else ""
    return {
        "label": "How good is the AI?",
        "value": rho,
        "display": f"\u03c1 = {rho:.2f}",
        "detail": (
            f"Only modestly in line with one student's {evaluation['n_relevant']} hand labels: "
            f"Spearman \u03c1 = {rho:.2f}{ci_txt}. Two different AI models agree with each "
            f"other at {MODEL_AGREEMENT_RHO:.2f}, so the labels and the models read some "
            "speeches differently."
        ),
    }


def dissent_section(dis: dict[str, Any]) -> dict[str, Any] | None:
    """Findings-page section for the dissent test (schema in docs/data-contract.md)."""
    ds, dc = dis.get("slope"), dis.get("slope_controlling_prev_vote")
    if not ds:
        return None
    dv = {v["label"]: v["mean_tone"] for v in dis["by_vote"]}
    takeaway = (
        "Members who went on to vote for a higher rate than the majority had given speeches "
        f"averaging {dv['Voted for a higher rate']:+.2f}; those who voted with the majority "
        f"{dv['Voted with the majority']:+.2f}; those who voted for a lower rate "
        f"{dv['Voted for a lower rate']:+.2f}. Each point of hawkishness in a member's own "
        f"speeches moved their vote by {ds['estimate']:+.3f} (95% CI {ds['ci_low']:+.3f} to "
        f"{ds['ci_high']:+.3f}, p {_p_text(ds['p_value'])})"
        + (
            ", a primary result that passes the multiple-testing threshold."
            if _sig(ds["p_value"])
            else ", not significant at the multiple-testing threshold."
        )
    )
    cautions = [
        {
            "title": "Partly persistence",
            "text": "The same members tend to dissent again and again, and their speeches may "
            "simply restate a position the market already knew from their last vote. "
            + (
                f"Allowing for each member's previous vote halves the slope, to "
                f"{dc['estimate']:+.3f} (95% CI {dc['ci_low']:+.3f} to {dc['ci_high']:+.3f}, "
                f"p {_p_text(dc['p_value'])}), but it stays positive."
                if dc
                else ""
            ),
        },
        {
            "title": "The model may recognise famous speeches",
            "text": "Speeches were scored without the speaker's name or date, but the model may "
            "still recognise a well-known speech and know how its author voted.",
        },
    ]
    return {
        "takeaway": takeaway,
        "method": (
            "Each voting member with at least one relevant speech since the previous decision "
            f"({dis['n']} member-meetings, {dis['n_members']} members, {dis['n_dissents']} "
            "dissents). Vote coded +1 higher than the majority, 0 with it, \u22121 lower; "
            "linear regression on the member's mean speech tone, standard errors clustered by "
            "member."
        ),
        "by_vote": [
            {"label": v["label"], "n": v["n"], "value": v["mean_tone"]} for v in dis["by_vote"]
        ],
        "regression": [
            {"term": "tone", "label": "Own speech tone (vote per point)", **_coef(ds)},
            *(
                [
                    {
                        "term": "tone_prev_vote",
                        "label": "Own speech tone, controlling for previous vote",
                        **_coef(dc),
                    }
                ]
                if dc
                else []
            ),
        ],
        "cautions": cautions,
    }


def takeaways(detail: dict[str, Any]) -> dict[str, str]:
    es = detail["event_study"]
    diff = es["hike_minus_cut"]
    tab = {r["decision"]: r for r in es["table"]}
    es_txt = (
        f"Tone in the 12 weeks before hikes averaged {tab['hike']['mean_tone_before']:+.2f}, "
        f"against {tab['cut']['mean_tone_before']:+.2f} before cuts and "
        f"{tab['hold']['mean_tone_before']:+.2f} before holds (hike minus cut "
        f"{diff['difference']:+.2f}, 95% CI {diff['ci_low']:+.2f} to {diff['ci_high']:+.2f}). "
    )
    holds_like_cuts = (
        abs((tab["hold"]["mean_tone_before"] or 0) - (tab["cut"]["mean_tone_before"] or 0)) < 0.1
    )
    moved = [k for k in ("hike", "cut") if abs(tab[k]["tone_change"] or 0) >= 0.15]
    es_txt += (
        "Tone before hikes stood out"
        + (", while holds and cuts looked alike" if holds_like_cuts else "")
        + (
            "; tone did not visibly build up in the final weeks before a move."
            if not moved
            else "; "
            + " and ".join(
                f"tone {'rose' if tab[k]['tone_change'] > 0 else 'fell'} a further "
                f"{abs(tab[k]['tone_change']):.2f} in the last four weeks before {k}s "
                f"(95% CI {tab[k]['tone_change_ci_low']:+.2f} to "
                f"{tab[k]['tone_change_ci_high']:+.2f})"
                for k in moved
            )
            + "".join(
                f", with no such build-up before {k}s ({tab[k]['tone_change']:+.2f})"
                for k in ("hike", "cut")
                if k not in moved
            )
            + "."
        )
    )
    pred = detail["prediction_test"]
    g = pred["log_loss_gain_tone"]
    gm = pred["log_loss_gain_tone_over_market"]
    pt_txt = (
        "Adding tone to the previous decision "
        + ("improved" if g["ci_low"] > 0 else "did not reliably improve")
        + f" out-of-sample forecasts (log-loss gain {g['mean_gain']:+.3f}, 95% CI "
        f"{g['ci_low']:+.3f} to {g['ci_high']:+.3f}). Once the 2-year gilt yield is in the "
        "model, which on its own forecasts far better, tone "
        + ("still adds" if gm["ci_low"] > 0 else "adds nothing reliable")
        + f" (gain {gm['mean_gain']:+.3f}, CI {gm['ci_low']:+.3f} to {gm['ci_high']:+.3f})."
    )
    s = detail["market_reaction"]["regressions"]["stance"]
    pl = detail["market_reaction"]["placebo_stance"]
    mr_txt = (
        f"On {s['n']} speech days, a one-point more hawkish speech went with a "
        f"{s['estimate']:+.2f} bp move in the 2-year gilt (95% CI {s['ci_low']:+.2f} to "
        f"{s['ci_high']:+.2f}, p = {s['p_value']:.2f}); "
        + (
            "that is larger than chance, but small next to a typical 3-4 bp daily move."
            if _sig(s["p_value"])
            else f"random non-speech days produce slopes this large {100 * pl['p_value']:.0f}% "
            "of the time, so this is a null result."
        )
    )
    return {"event_study": es_txt, "prediction_test": pt_txt, "market_reaction": mr_txt}


WORDLIST_CAVEAT = {
    "title": "Word-list scores",
    "text": "These results use the word-list baseline, not the AI scorer: a robustness run. "
    "The baseline agreed with the hand labels about as well as the AI did, but it is a "
    "cruder reading of tone, and its scale is compressed.",
}


def findings_json(detail: dict[str, Any], evaluation: dict[str, Any] | None) -> dict[str, Any]:
    tk = takeaways(detail)
    wordlist = detail["model"] == dataset.BASELINE_MODEL
    if wordlist:
        tk = {k: "Word-list scores. " + v for k, v in tk.items()}
    es = detail["event_study"]
    pred = detail["prediction_test"]
    mkt = detail["market_reaction"]
    keep = {
        "Same as last time",
        "Always hold",
        "Previous decision",
        "Previous decision + tone",
        "Previous decision + market",
        "Previous decision + market + tone",
    }
    return {
        "schema_version": 1,
        "generated_at": detail["generated_at"],
        "model": detail["model"],
        "prompt_version": detail["prompt_version"],
        "sample": detail["sample"],
        "headline": [
            {**h, "detail": "Word-list scores: " + h["detail"]} if wordlist else h
            for h in headline(es, pred, detail["dissent"])
        ],
        "accuracy": accuracy_line(evaluation),
        "event_study": {
            "takeaway": tk["event_study"],
            "method": (
                "Mean stance of MPC-relevant speeches and minutes published in each week "
                "before the announcement (week 0 = the 7 days before it; the decision's own "
                "minutes never count); 95% bands by bootstrap over decisions."
            ),
            "offsets_weeks": es["offsets_weeks"],
            "series": es["series"],
            "table": [
                {
                    k: r[k]
                    for k in (
                        "decision",
                        "n_events",
                        "mean_tone_before",
                        "ci_low",
                        "ci_high",
                        "tone_change",
                    )
                }
                for r in es["table"]
            ],
        },
        "prediction_test": {
            "takeaway": tk["prediction_test"],
            "method": (
                f"Ordered logit, expanding window: before each scheduled decision from "
                f"{pred['oos_start'][:4]} the model is re-fitted on earlier decisions only, "
                "with tone from documents published before each announcement. Accuracy is "
                "out of sample; pseudo R² is in sample."
            ),
            "outcome": "cut / hold / hike",
            "models": [
                {
                    k: m[k]
                    for k in (
                        "name",
                        "features",
                        "uses_tone",
                        "n",
                        "accuracy",
                        "log_loss",
                        "pseudo_r2",
                    )
                }
                for m in pred["models"]
                if m["name"] in keep
            ],
            "coefficients": pred["coefficients"],
        },
        "market_reaction": {
            "takeaway": tk["market_reaction"],
            "measure": "Average absolute daily change in the 2-year gilt yield",
            "method": (
                "Close-to-close change on the business day a speech was published; MPC "
                "announcement and minutes days excluded. Newey-West standard errors."
            ),
            "groups": [
                {k: g[k] for k in ("label", "n", "value", "ci_low", "ci_high")}
                for g in mkt["groups"]
            ],
            "by_stance": [{k: g[k] for k in ("label", "n", "value")} for g in mkt["by_stance"]],
            "regression": [
                {
                    "term": "stance",
                    "label": "Speech stance (bp per point)",
                    **_coef(mkt["regressions"]["stance"]),
                },
                {
                    "term": "surprise",
                    "label": "Stance surprise vs last 60 days (bp per point)",
                    **_coef(mkt["regressions"]["surprise"]),
                },
                {
                    "term": "stance_2day",
                    "label": "Speech stance, two-day change",
                    **_coef(mkt["regressions"]["stance_2day"]),
                },
            ],
        },
        "dissent": (
            {**dis_sec, "takeaway": "Word-list scores. " + dis_sec["takeaway"]}
            if wordlist and (dis_sec := dissent_section(detail["dissent"]))
            else dissent_section(detail["dissent"])
        ),
        "caveats": ([WORDLIST_CAVEAT] if wordlist else []) + CAVEATS,
    }


def _coef(r: dict[str, Any]) -> dict[str, Any]:
    return {k: r.get(k) for k in ("estimate", "std_error", "p_value", "ci_low", "ci_high")}


CAVEATS = [
    {
        "title": "A small sample",
        "text": "About 315 decisions, only about 70 of them rate changes, and 36 hand labels. "
        "Effects of a plausible size are hard to detect, so 'no evidence' is not 'no effect'.",
    },
    {
        "title": "One labeller",
        "text": "The AI was checked against one student's labels. The two AI models agree with "
        "each other far more than either agrees with the labels, so the labels are a noisy "
        "yardstick.",
    },
    {
        "title": "The model knows history",
        "text": "The language model was trained on text written after most of these speeches. "
        "Hiding the date and speaker reduces, but cannot remove, the risk that it recalls "
        "what happened next.",
    },
    {
        "title": "End-of-day yields",
        "text": "Gilt yields are daily closes and speech times are unknown, so a speech after the "
        "close shows up a day late, and other news on the same day (data releases) is not "
        "controlled for.",
    },
    {
        "title": "Correlation, not causation",
        "text": "Tone and decisions are both driven by the economic data. A link between them "
        "does not mean speeches caused the moves.",
    },
]


def write_findings(
    detail: dict[str, Any], evaluation: dict[str, Any] | None, out_dir: Path
) -> None:
    findings = clean(findings_json(detail, evaluation))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "findings.json").write_text(
        json.dumps(findings, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scores", type=Path, default=dataset.SCORES_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--img-dir", type=Path, default=IMG_DIR)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument(
        "--rebuild-json",
        action="store_true",
        help="only rewrite findings.json (and the dissent chart) from the existing "
        "findings_detail.json and evaluation.json; re-runs no analysis",
    )
    parser.add_argument(
        "--scorer",
        choices=["llm", "baseline"],
        default="llm",
        help="baseline: run on the word-list scores (built from the corpus if "
        "data/scores.parquet does not exist)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    evaluation = json.loads(args.evaluation.read_text()) if args.evaluation.exists() else None

    if args.rebuild_json:
        saved: dict[str, Any] = json.loads((args.out_dir / "findings_detail.json").read_text())
        write_findings(saved, evaluation, args.out_dir)
        args.img_dir.mkdir(parents=True, exist_ok=True)
        charts.dissent_chart(saved["dissent"], args.img_dir / "dissent_tone.png")
        log.info("rewrote %s from findings_detail.json", args.out_dir / "findings.json")
        return 0

    if args.scorer == "llm":
        inp = dataset.load(args.scores)
    elif args.scores.exists():
        inp = dataset.load(scores=dataset.baseline_as_scores(pd.read_parquet(args.scores)))
    else:
        log.info("no %s: scoring the corpus with the word-list baseline", args.scores)
        inp = dataset.load(scores=dataset.baseline_scores())
    scores, decisions, yields = inp.scores, inp.decisions, inp.yields
    members = pd.read_csv(MEMBERS_PATH)

    log.info("meeting features")
    meetings = dataset.add_market_features(dataset.meeting_features(scores, decisions), yields)
    log.info("event study")
    es = event_study.event_study(scores, decisions)
    es["hike_minus_cut"] = event_study.difference_test(scores, decisions)
    es["mpc_only"] = event_study.event_study(scores, decisions, mpc_only=True)["table"]
    log.info("prediction test (expanding window; takes a minute or two)")
    pred = prediction_section(meetings)
    log.info("market reaction")
    mkt = market.market_reaction(scores, decisions, yields)
    log.info("dissent")
    dis = dissent.dissent_test(scores, decisions, members)
    log.info("robustness")
    rob = robustness_thresholds(scores, decisions, yields)

    rel = dataset.relevant(scores)
    detail: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": str(scores["model"].iloc[0]),
        "prompt_version": str(scores["prompt_version"].iloc[0]),
        "sample": {
            "start": decisions["date"].min().date().isoformat(),
            "end": decisions["date"].max().date().isoformat(),
            "n_documents": len(scores),
            "n_relevant": len(rel),
            "n_decisions": len(decisions),
        },
        "alpha_bonferroni": ALPHA,
        "meetings": {
            "n": len(meetings),
            "empty_windows": int(meetings["tone_empty"].sum()),
            "empty_windows_mpc": int(meetings["tone_mpc_empty"].sum()),
            "median_docs": float(meetings["n_docs"].median()),
        },
        "event_study": es,
        "prediction_test": pred,
        "market_reaction": mkt,
        "dissent": dis,
        "robustness_thresholds": rob,
    }
    detail = clean(detail)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "findings_detail.json").write_text(
        json.dumps(detail, indent=1, allow_nan=False) + "\n"
    )
    write_findings(detail, evaluation, args.out_dir)
    args.img_dir.mkdir(parents=True, exist_ok=True)
    charts.event_study_chart(detail["event_study"], args.img_dir / "event_study.png")
    charts.tone_rate_chart(scores, decisions, args.img_dir / "tone_and_bank_rate.png")
    charts.market_chart(detail["market_reaction"], args.img_dir / "gilts_by_stance.png")
    charts.dissent_chart(detail["dissent"], args.img_dir / "dissent_tone.png")
    log.info("wrote %s and charts in %s", args.out_dir / "findings.json", args.img_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
