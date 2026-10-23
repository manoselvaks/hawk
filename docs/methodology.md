# Scoring methodology

How Hawk turns a Bank of England speech or set of MPC minutes into a hawkish-to-dovish
score, and how it checks whether the score means anything. The code is in
`src/hawk/scoring/`; the pilot results that chose the default model are in
[`pilot.md`](pilot.md).

## The scale

Every document gets two numbers:

| field | range | meaning |
| --- | --- | --- |
| relevance | 0 to 1 | how much of the document is about UK monetary policy |
| stance | −2 to +2 | which way the author leans on the future path of Bank Rate, relative to policy at the time |

−2 is very dovish (argues for cuts or more stimulus soon), 0 neutral or balanced, +2 very
hawkish (argues for rises soon). Stance is about the *lean*, not the level of rates: a
2023 speech defending a 5.25% Bank Rate while signalling cuts ahead is dovish. The LLM
may use half points; humans label whole points.

## Why relevance comes first

Many speeches are not about monetary policy at all: financial stability, bank
regulation, payments, banknotes, climate, data strategy, the Bank's own operations.
About half (54%) fall below the baseline's relevance threshold.
Forcing a stance onto those adds noise that looks like signal. A speech on resolution
regimes that mentions "downside risk" for bank creditors is not dovish.

So relevance is scored separately, and the LLM returns **no stance** (`null`) when
relevance is below 0.3. The analysis can then filter (for example relevance ≥ 0.5) or
weight by relevance. The baseline has its own crude relevance proxy (policy terms per
100 words), so both scorers can be checked on this too.

The other half of the same idea is the **`is_mpc_member`** flag. A speech by a sitting
MPC member carries far more policy signal than one by an Executive Director for
payments, even when both mention inflation. Membership comes from the Bank's voting
record: a speaker counts as a member from the day after the meeting before their first
vote to the day before the meeting after their last (`data/market/mpc_members.csv`, built
by `python -m hawk.scoring.mpc_members`). 1,035 of the 1,539 scorable speeches are by
sitting members.

## Text preparation (`corpus.py`, `textprep.py`, `speakers.py`)

The raw parquet files are never modified. At load time:

- **Cleaning.** Running headers ("Bank of England Page 3"), "All speeches are available
  online at …" footers, lines of chart axis numbers and the references section at the end
  are removed, and lines that a PDF wrapped mid-sentence are re-joined into paragraphs.
- **Speaker names** are normalised ("Andy Haldane" and "Andrew Haldane" are one person;
  so are "Edward George" and "Eddie George", "Minouche Shafik" and "Nemat Shafik"), with
  a fallback to the name in the page title when the parsed speaker is only a first name
  or an honorific.
- **Exclusions**, each logged with its reason: one speech with no `published_date`, and
  five texts under 1,000 characters (four video or slide pages, and the August 1997
  minutes, a scan with no text layer). That leaves 1,853 documents: 1,539 speeches and
  314 sets of minutes.
- **Policy passages.** A keyword heuristic scores each paragraph by weighted counts of
  policy terms (Bank Rate, tightening, inflation expectations, spare capacity, upside
  risks, …) and keeps the best paragraphs, in reading order, up to about 2,500
  characters. No model is involved. The labelling tool shows these passages, and they
  are the cheap input option for the LLM.

## Baseline: word lists (`lexicon.py`, `baseline.py`)

The baseline is deliberately simple and fully transparent. These are hand-written
word lists, not a trained model, and they will miss irony, hedging and context.

It follows the approach of Apel and Blix Grimaldi (2012), who measured the tone of
Riksbank minutes by counting combinations of an economic **concept** with a
**direction** word ("higher inflation", "weaker growth"). Each concept has a polarity
(+1 when more of it is hawkish, such as inflation or wage growth; −1 when more of it is
dovish, such as unemployment or spare capacity) and each direction word a sign (+1 up,
−1 down), so:

- "inflation has risen" = +1 × +1 → hawkish
- "unemployment has fallen" = −1 × −1 → hawkish (less slack)
- "demand is weak" = +1 × −1 → dovish

A short list of fixed phrases adds direct policy language ("tightening", "upside risks",
"rate cut", "quantitative easing", "spare capacity"). A match is flipped when a negator
("not", "no", "unlikely", "little", …) appears in the three tokens before it or between
the concept and its direction word, so "there is little spare capacity" and "inflation
is unlikely to rise" are read the right way round.

The document score is Apel and Blix Grimaldi's net index scaled to the project's range:

    stance = 2 × (hawkish − dovish) / (hawkish + dovish)

and 0 when there are fewer than three matches. Dictionary methods of this kind are
standard in the central-bank communication literature (see Bennani and Neuenkirch 2017,
who apply the same dictionary to speeches; and Loughran and McDonald 2011 on why
general-purpose sentiment lists fail on financial text). They are cheap, reproducible
and easy to audit, which is why the baseline exists: the LLM has to beat it to be worth
its cost.

## LLM scorer (`llm.py`, `prompts/stance_v1.md`)

The prompt is a versioned file (`stance_v1`). It defines relevance and the five stance
points with anchors, tells the model to judge the lean rather than the level of rates,
asks it to weigh the vote split for minutes, and requires a single JSON object:

```json
{"relevance": 0.95, "stance": 1.0, "confidence": 0.9,
 "reason": "Says inflation risks are 'skewed significantly to the upside' and further tightening would be required if pressures persist."}
```

The reply is validated: stance is snapped to the 0.5 grid and clipped to −2..+2,
relevance and confidence are clipped to 0..1, and a malformed reply is retried.

Engineering choices:

- **Model.** Configurable; the default is `openai/gpt-6-luna` on full text, chosen in
  the [pilot](pilot.md) over DeepSeek V4.1 Flash and Claude Haiku 5.5 (best agreement with
  the other models, concise reasons, $0.59 per full-corpus pass).
  The [evaluation against the hand labels](evaluation.md) confirmed it: tied with Haiku on
  agreement with the labels, and cheaper.
- **Input.** `full` sends the cleaned text when it is under 24,000 characters (about
  half of documents) and otherwise the policy passages at a 24,000-character budget, so
  the end of a long speech, where the policy view often is, is not cut off. `passages`
  sends the 2,500-character extract. In the pilot, full text agreed much better across
  models (ρ 0.90–0.95 against 0.75–0.81), so it is the default.
- **Temperature 0** is requested. Some models (including GPT-6 Luna) ignore the
  parameter, which is one reason self-consistency is measured, not assumed.
- **Caching.** Results are stored under `data/llm_cache/`, keyed by model, prompt
  version, a hash of the exact input and a replicate number. Re-runs cost nothing; a
  deliberate second scoring (replicate 1) measures self-consistency.
- **Spend cap.** Every call is logged with the cost OpenRouter reports
  (`usage.cost`) in `data/llm_spend.jsonl`, which is committed so the running total
  survives across machines. Before each call the tracker refuses to continue if the
  total plus a one-cent reserve would pass the cap (default $4, below the key's $5
  lifetime limit). If a response ever lacks a cost, the reserve is booked instead, so
  spend is never under-counted.

## Avoiding look-ahead

The research question is whether tone *predicted* decisions and yields, so nothing may
use information from after the date a document became public.

1. **Timing uses `published_date`**, the day the market could first read the
   document, never `speech_date` or `meeting_date`. Minutes before August 2015 were
   published about two weeks after the meeting; a document without a publication date
   is dropped.
2. **The LLM sees no date and no speaker name**, only the document type and text, and
   is told not to use anything it knows about later events. This cannot fully remove
   the risk (see limitations), but it avoids inviting the model to recall what happened
   next.
3. **The scorers are fixed before the evaluation.** The pilot that chose the model and
   input used 20 documents outside the labelling set, so the model was not tuned on
   the documents it will be judged on.
4. **The policy context** (whether the next decision was a hike, cut or hold) is used
   only to choose a balanced labelling sample. It uses the future by construction and
   must never become a feature in the prediction tests.

## Hand labels and evaluation (`make_labelling_set.py`, `evaluate.py`)

**The labelling set** is 30 speeches by sitting MPC members and 6 sets of minutes,
drawn with a fixed seed and spread across four eras (pre-2008, 2008–2015, 2016–2021,
2022+) and three policy contexts (next decision a hike, cut or hold). Drawing evenly
across cells, rather than in proportion to the corpus where holds outnumber moves seven
to one, makes sure both ends of the scale appear. There were no hikes from 2008 to 2015,
so that cell is empty. Items are shown in shuffled order.

**The labelling tool** (`labelling/label.html`) shows only the title, speaker, date and
policy passages, with the full text one click away. It never shows a model or baseline
score, so the labels are blind. A label is a whole point from −2 to +2, or "not about
monetary policy".

**The evaluation** compares both scorers with the hand labels:

- stance: Spearman rank correlation (on unrounded scores), exact and within-one accuracy
  (scorer rounded to the nearest point, halves away from zero) and a confusion matrix,
  on items the human scored;
- relevance: precision and recall of each scorer's "about monetary policy" call;
- LLM self-consistency: the same items scored a second time.

Results, with bootstrap intervals, are in [evaluation.md](evaluation.md). With about 36 labels the confidence intervals are wide: a Spearman ρ of 0.6 on 30 items
has a 95% interval of roughly 0.3 to 0.8. The evaluation can tell a useful scorer from
a useless one, not rank two good ones finely.

## Known limitations

- **One labeller.** The hand labels are one person's judgement, with no inter-rater
  agreement. A second labeller on a subset would show how hard the task is for humans.
- **Model knowledge of history.** The LLM was trained on text written after most of
  these speeches, including commentary on what the MPC did next. Hiding the date and
  speaker reduces this but does not remove it: a speech about "the mini-budget" dates
  itself. Results for older documents should be read with this in mind.
- **Word lists are crude.** They cannot tell a historical discussion ("the high inflation
  of the 1970s") from a view on the outlook, and they read hedged statements literally.
- **Passages are a heuristic.** The extractor can miss a policy view stated in
  unusual language, and it sometimes picks a boilerplate paragraph. The labelling tool's
  full-text toggle is there for this reason.
- **The relevance threshold** (0.5 for the LLM, 1.5 policy terms per 100 words for the
  baseline) was set on 20 pilot documents and is a judgement call.
- **Stance is relative to the time.** A +1 in 2008 and a +1 in 2022 are both "leans
  towards tighter policy than now", not the same absolute view.
- **Pilot prices** come from OpenRouter routing on 18 October 2026; providers and prices
  change, and the cost estimates will move with them.

## References

- Apel, M. and Blix Grimaldi, M. (2012). "The information content of central bank
  minutes". Sveriges Riksbank Working Paper 261.
- Bennani, H. and Neuenkirch, M. (2017). "The (home) bias of European central bankers:
  new evidence based on speeches". *Applied Economics* 49(11).
- Hansen, S. and McMahon, M. (2016). "Shocking language: Understanding the
  macroeconomic effects of central bank communication". *Journal of International
  Economics* 99.
- Loughran, T. and McDonald, B. (2011). "When is a liability not a liability? Textual
  analysis, dictionaries, and 10-Ks". *Journal of Finance* 66(1).
- Shapiro, A. H. and Wilson, D. J. (2022). "Taking the Fed at its word: A new approach
  to estimating central bank objectives using text analysis". *Review of Economic
  Studies* 89(5).
