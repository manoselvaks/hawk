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

## Spend

OpenRouter spend in this session: **$0.094** (72 Luna calls, 60 Haiku, 28 DeepSeek),
logged call by call in [`data/llm_spend.jsonl`](../data/llm_spend.jsonl); $0.169 over the
project's life. The run then stopped: OpenRouter answered "Insufficient credits. This
account never purchased credits." The key's $5 limit is a cap, not a balance, and the
calls so far ran on a small grace allowance. Scoring the full corpus (about $0.59 with
Luna) needs credit added to the account.

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
