# Scorer evaluation against hand labels

How well do the scorers agree with a human reading of the same documents, and which
model should score the full corpus? Built by `python -m hawk.scoring.compare` from the
cached LLM scores (no API calls); the numbers the website shows are in
[`data/analysis/evaluation.json`](../data/analysis/evaluation.json).

## In short

- **Agreement with the hand labels is modest for every scorer.** Spearman ρ is 0.37 for
  GPT-6 Luna, 0.41 for Claude Haiku 5.5 and 0.42 for the word-list baseline, each with a
  95% interval running from about 0.05 to 0.7. With 33 scored items these three cannot be
  told apart.
- **The two AI models agree with each other far more than with the labels** (ρ = 0.96
  between Luna and Haiku on the same 33 items). Whatever separates the models from the
  labels is not random model noise; it is a systematic difference in how the documents
  were read (see [Where the labels and the models disagree](#where-the-labels-and-the-models-disagree)).
- **The AI is much better at the "is this about monetary policy?" call**: Luna has 97%
  precision and 94% recall against the labels, the baseline 96% and 76%.
- **Production model: `openai/gpt-6-luna` (full text).** By the rule fixed before the
  comparison (below), Luna and Haiku are tied on agreement, and Luna is the cheaper of the
  two ($0.59 against $1.31 for the corpus). It also had the best relevance recall.
- **The labels come from one person**, an 18-year-old student, labelling blind. Read
  every accuracy number here as "agreement with one careful non-expert reader", not as
  accuracy against a ground truth.

## The labels

36 documents (30 speeches by sitting MPC members and 6 sets of minutes), drawn across
four eras and three policy contexts, labelled blind by Manoj with
[`labelling/label.html`](../labelling/label.html) on 22 October 2026. The tool never showed
a model or baseline score. 33 were scored from −2 to +2; 3 were marked "not about monetary
policy" (two speeches on payments and fintech, and one Eddie George speech from 2001).

| label | −2 | −1 | 0 | +1 | +2 | not monetary policy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| items | 2 | 4 | 11 | 9 | 7 | 3 |

What one labeller implies:

- **No inter-rater check.** We cannot say how much two careful humans would agree on this
  task. Published studies of central-bank tone usually find human–human agreement well
  short of perfect, so a ρ of 0.4 between a model and one human is not by itself
  evidence that the model is poor.
- **Personal calibration.** The labels lean hawkish: their mean is +0.45, against −0.09
  for Luna and −0.13 for Haiku on the same items. A labeller who reads "inflation is
  above target" as hawkish whatever the speaker concludes will disagree with a model told
  to judge the *lean on the future path of rates*.
- **What the labeller read.** The tool shows about 2,500 characters of keyword-selected
  "policy passages" first, with the full text one click away; the models read the full
  text (or 24,000 characters of passages for very long documents). Several of the largest
  disagreements are documents whose passages miss the conclusion (examples below).

## Results

Stance is compared on the 33 items the labeller scored. Exact and within-one accuracy
round the scorer's stance to the nearest whole point (halves away from zero); Spearman
uses the unrounded value. Intervals are 95% percentile bootstraps over items (4,000
resamples, the same resamples for every scorer so comparisons are paired).

| scorer | compared | Spearman ρ (95% CI) | exact (95% CI) | within 1 (95% CI) |
| --- | ---: | ---: | ---: | ---: |
| Baseline (word lists) | 33 of 33 | 0.42 (0.09 to 0.68) | 33% (18% to 48%) | 55% (36% to 73%) |
| LLM (openai/gpt-6-luna, full) | 31 of 33 | 0.37 (0.01 to 0.68) | 35% (19% to 53%) | 81% (67% to 94%) |
| LLM (anthropic/claude-haiku-5.5, full) | 30 of 33 | 0.41 (0.05 to 0.73) | 37% (20% to 55%) | 80% (66% to 93%) |

"Compared" counts items where the scorer gave a stance at all: the LLMs give none when
they judge relevance below 0.3. The baseline's low within-one score comes from its
compressed scale: it rarely goes beyond ±1, so a human +2 is often two points away.

### Relevance ("about monetary policy")

Positive class: the labeller scored the item rather than marking it "not about monetary
policy". LLM: relevance ≥ 0.5. Baseline: at least 1.5 policy terms per 100 words.

| scorer | items | precision | recall | accuracy |
| --- | ---: | ---: | ---: | ---: |
| Baseline (word lists) | 36 | 96% | 76% | 75% |
| LLM (openai/gpt-6-luna, full) | 36 | 97% | 94% | 92% |
| LLM (anthropic/claude-haiku-5.5, full) | 36 | 96% | 82% | 81% |

### Confusion matrices

Rows: the hand label. Columns: the scorer, rounded. The diagonal is exact agreement.

**GPT-6 Luna (chosen)**

| human \ model | −2 | −1 | 0 | +1 | +2 | no stance |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| −2 | 1 | 0 | 0 | 0 | 0 | 1 |
| −1 | 0 | 2 | 2 | 0 | 0 | 0 |
| 0 | 1 | 3 | 4 | 3 | 0 | 0 |
| +1 | 0 | 1 | 3 | 3 | 1 | 1 |
| +2 | 0 | 3 | 0 | 3 | 1 | 0 |

**Claude Haiku 5.5**

| human \ model | −2 | −1 | 0 | +1 | +2 | no stance |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| −2 | 1 | 0 | 0 | 0 | 0 | 1 |
| −1 | 0 | 3 | 1 | 0 | 0 | 0 |
| 0 | 1 | 4 | 3 | 3 | 0 | 0 |
| +1 | 1 | 0 | 2 | 3 | 1 | 2 |
| +2 | 1 | 1 | 1 | 3 | 1 | 0 |

**Baseline (word lists)**

| human \ model | −2 | −1 | 0 | +1 | +2 | no stance |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| −2 | 0 | 1 | 1 | 0 | 0 | 0 |
| −1 | 0 | 3 | 1 | 0 | 0 | 0 |
| 0 | 0 | 4 | 5 | 2 | 0 | 0 |
| +1 | 0 | 3 | 4 | 2 | 0 | 0 |
| +2 | 0 | 1 | 4 | 1 | 1 | 0 |

### Self-consistency and cost

Each labelled item scored a second time with the same model, prompt and input.

| model | items run twice | identical stance | within 0.5 | mean abs. difference | same relevance call | cost per doc | full corpus |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| openai/gpt-6-luna | 36 | 78% | 100% | 0.12 | 100% | $0.00032 | $0.59 |
| anthropic/claude-haiku-5.5 | 24 | 100% | 100% | 0.00 | 96% | $0.00071 | $1.31 |

Luna ignores the temperature setting, so a re-run moves about one score in five by half a
point, never more. Haiku's second run stopped at 24 items when the OpenRouter account ran
out of credit (see [Spend](#spend)). Cost per document is the pilot's average.

## Choosing the model

The rule was written into `hawk/scoring/compare.py` before the comparison was run:
take the model with the highest Spearman ρ against the labels; treat any model whose
paired-bootstrap ρ difference from it has a 95% interval including zero as tied; choose
the cheapest of the tied models.

- Haiku had the highest ρ (0.41). Luna's ρ is 0.04 lower, with a 95% interval for the
  difference of −0.09 to +0.19, so the two are tied, and Luna is cheaper.
- **DeepSeek V4.1 Flash could not be fully compared**: the account ran out of credit
  after it had scored 28 of the 36 items. On the 24 items where DeepSeek, Luna and the
  labeller all gave a stance, DeepSeek's ρ was 0.31 against Luna's 0.41, and its
  agreement with Luna (0.88) was the lowest of the three models. Its reasoning output
  also made it use 5–10 times as many completion tokens as Luna. Nothing suggests it
  would have won; with the full set it would only have been chosen if tied with Haiku and
  cheaper, which the partial data make unlikely.

Choosing on the same 36 labels that measure accuracy makes the chosen model's numbers
slightly optimistic (a winner's curse), but with the models this close the effect is
small, and the choice did not change the prompt or settings.

**The prompt was not changed.** All scores use `stance_v1`, fixed in the pilot on 20
documents outside the labelling set. Nothing was tuned on these labels, so the numbers
above are out of sample for the prompt.

## Where the labels and the models disagree

The biggest gaps between the labeller and both AI models:

| item | document | label | Luna | Haiku | Luna's reason (shortened) |
| ---: | --- | ---: | ---: | ---: | --- |
| 11 | David Miles, March 2012 | +2 | −1 | −1 | "spare capacity and muted domestically generated inflation justify very expansionary policy and QE" |
| 12 | Silvana Tenreyro, February 2023 (slides) | +2 | −1 | −1.5 | "the energy shock's inflationary effects will fade while monetary policy works with a lag, so further tightening risks overtightening" |
| 25 | MPC minutes, February 2009 | 0 | −2 | −2 | "inflation would fall well below target … further monetary easing was likely to be required" |
| 19 | MPC minutes, April 2001 | +1 | −1 | −1.5 | "the Committee agreed a rate reduction was needed … citing increased downside risks" |
| 32 | Paul Tucker, September 2008 | +2 | −0.5 | 0 | "recent developments are mostly downside news" despite inflation at 4.4% |

On these five the documents' own conclusions support the models: Miles and Tenreyro
were the MPC's best-known doves of their time, and both sets of minutes record a
committee cutting or about to ease. A plausible reason for the gap is what was on
screen: the Tenreyro passages are mostly chart notes about a counterfactual "extra policy
tightening", the February 2009 passages discuss asset purchases without the decision, and
the April 2001 passages are the minutes' boilerplate preamble. The labeller's reading of
the passages was reasonable; the passages were not a good summary.

This is not independent evidence (the author of this note also read the models'
reasons), and it does not make the labels "wrong". It does suggest two things for a
next round: show the full text by default, and have a second person label a subset so the
human ceiling is known.

## Full-corpus run

The production pass (`python -m hawk.scoring.score_all --confirm --max-retries 12
--max-tokens 800`) scored all 1,853 documents with `openai/gpt-6-luna`, full text,
`stance_v1`, on 23–24 October 2026. One document (`speech-d0cbbe0793`) failed once on a
dropped connection and was filled in by a re-run from the cache; **none were skipped**.

What came back: 1,086 documents with relevance ≥ 0.5 (773 speeches, all 314 minutes);
1,135 with a stance (the model gives none below relevance 0.3, and occasionally none
above it). Stances use the whole scale
(42 at −2, 18 at +2; 385 at 0), mean confidence on relevant documents is 0.88. Era means
move the expected way: −0.02 before 2008, −0.32 in 2008–15, −0.15 in 2016–21, +0.30 from
2022. On the 1,001 documents both scorers call relevant, AI and word-list stances
correlate at Spearman 0.41: they agree on direction often, but far from always.

### Spot check: 10 random scores

Ten documents drawn at random (`scores.sample(10, random_state=6)`), with the model's
reason read against the document title and the word-list score:

| document | relevance | stance | judgement |
| --- | ---: | ---: | --- |
| Hauser 2015, Fair and Effective Markets Review | 0.05 | – | Right: market conduct, not monetary policy |
| Tucker 2009, Turner Review conference | 0.2 | – | Right: financial regulation (word lists said +0.67) |
| MPC minutes, November 2015 | 1.0 | −0.5 | Right: hold, downside inflation risks, one member for a hike |
| Plenderleith 2001, "Addressing the uncertainties" | 1.0 | −1.0 | Right: describes five cuts and readiness to ease (word lists 0) |
| Clark 2011, macroprudential policy | 0.35 | 0 | Reasonable: mentions rates, no lean; below the 0.5 cut-off, so unused |
| MPC minutes, December 2012 | 1.0 | −0.5 | Right: QE held, one member for more |
| Miles 2013, asset purchases | 1.0 | −1.0 | Right: "next move might be more support" |
| Jenkins 2011, lobbying | 0.05 | – | Right |
| Posen 2011, "soft tyranny of inflation expectations" | 1.0 | −1.5 | Right: argues against tightening (word lists +0.27) |
| Stimson 2023, climate transition plan | 0.05 | – | Right |

All ten are defensible; none looks wrong. Where the word lists differ (Posen,
Plenderleith, Tucker), the AI's reading matches the document's argument and the word
lists are counting vocabulary.

### Systematic issues noticed

None that change the analysis, but four things worth knowing:

- **"The extract".** 127 reasons call the input "the extract". These are the 955
  documents longer than 24,000 characters, for which the model sees keyword-selected
  passages rather than the whole text. A long speech whose conclusion falls outside the
  passages can be misread, the same failure seen with the labelling tool
  ([above](#where-the-labels-and-the-models-disagree)), though the model's 24,000
  characters are ten times what the labeller saw first.
- **Relevance between 0.3 and 0.5.** 65 documents get a stance but fall below the
  analysis cut-off; most are financial-stability speeches that mention rates in passing
  (Clark 2011 above). The robustness runs at cut-offs 0.3 and 0.8 give the same
  conclusions ([findings](findings.md#3-market-reaction-do-2-year-gilts-listen)).
- **Relevant but no stance.** One document (Haldane 2018, "How monetary policy affects
  your GDP", relevance 0.85) has no stance: the model judged it about past policy with
  no lean on the future path, which is what the prompt asks for.
- **Non-determinism.** Luna ignores the temperature setting (see self-consistency
  above), so a re-run would move about one score in five by half a point. The cache
  pins the scores used here.

## Spend

| run | calls | cost |
| --- | ---: | ---: |
| Pilot and earlier sessions | 244 | $0.075 |
| Evaluation (72 Luna, 60 Haiku, 28 DeepSeek) | 160 | $0.094 |
| **Full corpus, Luna (this run)** | **1,797** | **$0.992** |
| Project total, logged | 2,201 | $1.161 |

Every call is logged with OpenRouter's reported cost in
[`data/llm_spend.jsonl`](../data/llm_spend.jsonl). The full pass averaged $0.00055 per
document, against $0.00032 in the pilot, so it cost $0.99 rather than the estimated $0.59
(the pilot's documents were about as long, so length is not the reason; the cause is not
established). It stayed well inside the $2 stop set for this run. OpenRouter reports
$1.162 used on the project's key, matching the log; the account total ($1.19) is $0.03
higher because it also counts usage outside this key. The evaluation round had earlier stopped on "Insufficient credits";
credit was added before this run.

## Reproduce

```bash
python -m hawk.scoring.evaluate --labels labelling/labels.csv --model openai/gpt-6-luna
python -m hawk.scoring.evaluate --labels labelling/labels.csv --model anthropic/claude-haiku-5.5
python -m hawk.scoring.evaluate --labels labelling/labels.csv --model deepseek/deepseek-v4.1-flash
python -m hawk.scoring.compare --labels labelling/labels.csv \
    --models openai/gpt-6-luna anthropic/claude-haiku-5.5 deepseek/deepseek-v4.1-flash
```

The first three call the API only for items not yet in `data/llm_cache/`; the last one
never does.
