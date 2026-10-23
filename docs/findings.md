# Findings

> **Interim results, word-list scores.** Every number on this page comes from the
> transparent word-list baseline, not the AI scorer. The AI pass over the full corpus
> could not run because the OpenRouter account has no credit (see
> [evaluation.md](evaluation.md#spend)). The baseline agreed with the hand labels about
> as well as the AI did (Spearman ρ 0.42 against 0.37), so these results are a fair
> first look, not a placeholder. Once the AI scores exist, `python -m hawk.analysis.run`
> recomputes every number and chart here from them.

**Question:** did the tone of Bank of England speeches and MPC minutes shift *before* Bank
Rate decisions, and did 2-year gilt yields react to tone beyond what the decisions
themselves explain? Every test uses only documents published before the date it is
about.

## The short version

- **Tone before hikes is clearly hawkish; before cuts and holds it looks the same.** In
  the 12 weeks before the 35 hikes, average tone was +0.43 on the −2 to +2 scale, against
  −0.23 before the 35 cuts and −0.21 before the 245 holds (hike minus cut: +0.65, 95%
  interval +0.52 to +0.79). But tone did not *build up* in the final weeks: it was already
  where it ended up three months earlier.
- **Tone does not help forecast the next decision once you know the last one.** Re-fitted
  before each of 244 meetings using only earlier data, a model with tone forecast no
  better than one with just the previous decision (log-loss gain +0.004 per meeting,
  95% interval −0.030 to +0.036). The 2-year gilt yield the day before is a far better
  forecaster, and tone adds nothing reliable to it either.
- **2-year gilts did not move with speech tone.** On 648 days with an MPC-relevant speech
  (announcement and minutes days left out), a speech one point more hawkish went with a
  −0.2 bp move in the 2-year yield (95% interval −0.9 to +0.4 bp). Random non-speech days
  give slopes this large a third of the time. A typical day's move is about 3 bp.
- **Hawkish speakers dissent upwards, a little.** Members who voted for a higher rate
  than the majority had given speeches averaging +0.23, against −0.21 for members who
  voted with the majority; as a test across all votes, the slope is positive but not
  significant (p = 0.11).
- **The sample is small.** About 315 decisions, 70 of them rate changes, 36 hand labels.
  "No evidence" here means "no effect large enough to see in this sample", not "no effect".

Four tests were fixed in advance as the primary ones (one per question above). With four
tests a result needs p < 0.0125 (0.05 / 4, Bonferroni) to count. Only the event-study
difference passes; everything else on this page is either a null result or a robustness
check.

## Data and scores

- **Documents:** 1,853 (1,539 speeches, 314 sets of minutes) published from February 1997
  to October 2026. The word-list scorer counts **1,019** of them as about monetary policy
  (at least 1.5 policy terms per 100 words); only those are used.
- **Decisions:** 315 MPC Bank Rate decisions, June 1997 to September 2026: 34 hikes after
  the first meeting, 35 cuts, 245 holds (plus the first decision, which has no
  "previous decision").
- **Gilts:** 2-year nominal spot yield from the Bank's fitted curve, business-day closes.
- **Scorer:** stance = Apel and Blix Grimaldi's net index of hawkish minus dovish phrase
  matches, scaled to −2..+2 ([methodology](methodology.md#baseline-word-lists-lexiconpy-baselinepy)).
  It rarely goes beyond ±1.5, so its numbers are compressed compared with the AI's.

### The no-look-ahead rule

For the decision announced on day *D*, a document counts only if its `published_date` is
strictly before *D*, and the minutes of that same meeting never count (since August 2015
they are published at the same moment as the decision). Minutes published two weeks after
an *earlier* meeting are fine: the market had them. The rule lives in
`hawk.analysis.dataset.window_documents`, and `tests/analysis/test_dataset.py` checks it
directly, including that adding documents published on or after an announcement never
changes that decision's features.

### Meeting-level features

For each decision: mean stance of relevant documents published since the previous
decision (`tone`), its change from the previous window (`tone_change`), the same from MPC
documents only (minutes plus speeches by sitting members), and a version weighted by
relevance × confidence. With the word-list scorer the weighted version equals the plain
one (relevance is 0 or 1 and there is no confidence), and 314 of 315 windows contain at
least one relevant document (median 3).

## 1. Event study: tone before hikes, holds and cuts

![Average tone in the 12 weeks before hikes, holds and cuts](img/event_study.png)

Week 0 is the seven days before the announcement; week −12 is twelve weeks earlier. For
each decision, each week's tone is the mean stance of relevant documents published that
week; the line is the mean across decisions of that type, and the band a 95% bootstrap
interval over decisions. Windows of neighbouring meetings overlap (the MPC meets every
four to six weeks), so the weeks are not independent observations.

| next decision | events | mean tone, 12 weeks before | 95% interval | change, last 4 weeks vs first 4 | 95% interval |
| --- | ---: | ---: | --- | ---: | --- |
| Hike | 35 | +0.43 | +0.34 to +0.51 | +0.01 | −0.16 to +0.17 |
| Hold | 245 | −0.21 | −0.27 to −0.15 | +0.02 | −0.04 to +0.08 |
| Cut | 35 | −0.23 | −0.34 to −0.12 | −0.09 | −0.28 to +0.08 |

**Primary test:** pre-decision tone before hikes minus before cuts = **+0.65** (95%
interval +0.52 to +0.79). Using MPC documents only gives the same picture (+0.43, −0.21,
−0.23).

What this does and does not say. Hikes come in runs during hawkish periods (1997–98,
2004–07, 2021–23), and the tone of those periods is hawkish throughout, so the level of
tone mostly identifies the *regime*, not the timing of the next move. The flat lines are
the more telling result: there is no visible "pivot" in tone in the month before a change.
Holds look like cuts because most holds since 2009 happened at or near the zero lower
bound, when communication was dovish for years.

## 2. Prediction test: does tone add information?

Outcome: the decision (cut, hold, hike) at each **scheduled** meeting from January 2003 to
September 2026 (244 meetings; the four emergency cuts are left out because their timing
gives the answer away, but they still count as "the previous decision" for the meeting
after). Models are ordered logits, re-estimated before every meeting on the decisions
announced before it. Accuracy, log loss and Brier score are all **out of sample**;
pseudo-R² is in sample.

| model | accuracy | log loss | Brier | accuracy on rate changes (44) | log loss on changes | pseudo-R² (in sample) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Always hold (rule) | 82.0% | – | 0.361 | 0% | – | – |
| Same as last time (rule) | 78.7% | – | 0.426 | 43% | – | – |
| Previous decision | 80.7% | 0.527 | 0.286 | 0% | 1.758 | 0.147 |
| Previous decision + tone | 81.1% | 0.523 | 0.288 | 9% | 1.634 | 0.175 |
| Previous decision + market | 84.0% | 0.431 | 0.253 | 25% | 1.429 | 0.310 |
| Previous decision + market + tone | 81.1% | 0.406 | 0.251 | 36% | 1.177 | 0.393 |

"Market" is the 2-year gilt yield minus Bank Rate at the close before the announcement,
and its change since the previous meeting: what the market expected. Log loss is the
fairer score: accuracy rewards always saying "hold", which is right 82% of the time and
useless. Rules give no probabilities, so they have no log loss.

**Primary test:** mean per-meeting log-loss gain from adding tone to the previous decision
= **+0.004** (95% bootstrap interval −0.030 to +0.036; one-sided p = 0.40). No reliable
gain. Adding tone to the market model: +0.025 (−0.027 to +0.079; p = 0.17). Robustness,
same benchmark: MPC documents only −0.001 (−0.037 to +0.034); tone change only −0.004
(−0.008 to −0.001, i.e. slightly worse).

In-sample coefficients (whole period, ordered logit; positive = more likely to hike):

| term | estimate | std. error | p |
| --- | ---: | ---: | ---: |
| Previous decision: cut | −1.79 | 0.42 | <0.001 |
| Previous decision: hike | +1.92 | 0.45 | <0.001 |
| Tone since last meeting | +1.18 | 0.34 | <0.001 |
| Change in tone vs previous window | −0.60 | 0.38 | 0.12 |

Why tone is strongly "significant" in sample but useless out of sample: over the whole
period tone level and decisions share the same slow regimes, which a full-sample fit
exploits with hindsight. A forecaster standing at each meeting has to learn the
relationship from the past alone, and the regime shifts (to the zero bound in 2009, out of
it in 2021) are exactly when that fails. The out-of-sample numbers are the honest ones.
The one hint worth following up: with the market variables, tone helps on the 44 rate
changes (log loss 1.43 → 1.18; 11 → 16 called correctly), but that is a subgroup of a
non-significant overall result.

## 3. Market reaction: do 2-year gilts listen?

![Mean 2-year gilt move by speech stance](img/gilts_by_stance.png)

Unit: business days, 1997–2026, excluding the 533 days with an MPC announcement or a
minutes publication. A speech day has at least one relevant speech published that day
(weekend publications move to the next business day); its stance is the mean of those
speeches. The move is close-to-close in basis points.

| days | n | mean absolute 2y move (bp) | 95% interval |
| --- | ---: | ---: | --- |
| No relevant speech | 6,345 | 3.17 | 3.09 to 3.25 |
| Speech by an MPC member | 625 | 3.45 | 3.16 to 3.74 |
| Speech by a non-member | 23 | 2.93 | 1.79 to 4.25 |

Regressions of the move on stance (Newey-West standard errors, 5 lags):

| specification | n | bp per stance point | 95% interval | p |
| --- | ---: | ---: | --- | ---: |
| **Stance (primary)** | 648 | −0.21 | −0.86 to +0.43 | 0.52 |
| Stance surprise (vs. last 60 days) | 646 | −0.56 | −1.28 to +0.15 | 0.12 |
| Stance, two-day move (t−1 to t+1) | 606 | +0.02 | −0.81 to +0.86 | 0.95 |
| Stance, MPC members only | 625 | −0.29 | −0.95 to +0.37 | 0.39 |
| Stance, non-members only | 23 | +1.18 | +0.12 to +2.23 | 0.03 |

By era (stance): pre-2008 −0.88 (p = 0.07), 2008–15 +0.95 (p = 0.08), 2016–21 −0.68
(p = 0.05), 2022+ −2.58 (p = 0.02).

**Placebo.** Giving the real speech-day stances to randomly drawn non-speech days (1,000
times) produces slopes at least as large as the real one 32% of the time, so the primary
slope is what chance alone produces. For stance *surprise* the placebo share is 3%, but
that slope is **negative** (hawkish surprises with *falling* yields), the wrong sign for a
market reaction, and it does not survive the two-day window or the multiple-testing
threshold. The likeliest reading is reverse timing: speeches describe the data and market
moves that are already happening (a speech discussing falling inflation on a day yields
fall). The non-member and 2022+ results are small subgroups among many and should not be
read as findings.

Limits of this test: yields are end-of-day and speech times unknown, so an after-hours
speech registers a day late (hence the two-day check); data releases (CPI, labour market,
GDP) on the same day are not controlled for, because Hawk has no release calendar.

## 4. Extra: does a member's tone predict their own dissent?

For each decision and each voting member with at least one relevant speech since the
previous decision (629 member-meetings, 48 members, 75 dissents):

| vote at the next meeting | member-meetings | mean tone of their speeches |
| --- | ---: | ---: |
| For a higher rate than agreed | 43 | +0.23 |
| With the majority | 554 | −0.21 |
| For a lower rate than agreed | 32 | −0.10 |

Linear regression of the vote (+1 higher, 0 with majority, −1 lower) on tone, standard
errors clustered by member: **+0.042 per point** (95% interval −0.009 to +0.093,
p = 0.11). Upward dissenters do sound more hawkish, but downward dissenters do not sound
more dovish than the majority, so the overall slope is weak.

## Limitations

- **Interim scorer.** These results use the word-list baseline. It reads hedged and
  historical statements literally, and its scale is compressed.
- **Small samples.** 315 decisions, about 70 of them changes, 244 out-of-sample meetings
  with 44 changes. A real but modest effect of tone could easily go undetected.
- **Multiple testing.** Four primary tests at p < 0.0125. The tables also show subgroups
  and robustness checks (about 20 more p-values); some will look "significant" by chance.
- **One labeller, 36 labels.** The scorer evaluation is coarse ([evaluation.md](evaluation.md)).
- **Look-ahead through the model.** Not an issue for the word-list scorer, but for the AI
  scores: the model was trained on text written after most of these speeches.
- **Daily data.** End-of-day yields, unknown speech times, no data-release controls.
- **Correlation, not causation.** Tone and decisions both respond to the same economic
  news.

## Reproduce

```bash
python -m hawk.analysis.run                     # on data/scores.parquet (AI scores)
python -m hawk.analysis.run --scorer baseline   # word-list scores, no API needed
```

This writes `data/analysis/findings.json` (the website), `data/analysis/findings_detail.json`
(every number on this page, plus robustness checks) and the charts in `docs/img/`. Code:
`src/hawk/analysis/`; tests: `tests/analysis/`.
