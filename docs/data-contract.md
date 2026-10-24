# Data contract: scores, findings and evaluation

The website (`python -m hawk.site.build`) is built from three files that later steps of
the pipeline write. This page fixes their schema so the scorer, the analysis and the
site can be built separately. The site works before any of them exist (see
[Preview mode](#preview-mode)).

| file | written by | required by the site |
| --- | --- | --- |
| `data/scores.parquet` | `python -m hawk.scoring.score_all --confirm` | no (preview mode without it) |
| `data/analysis/evaluation.json` | `python -m hawk.scoring.compare --labels … --models …` | no ("coming soon" without it) |
| `data/analysis/findings.json` | `python -m hawk.analysis.run` | no ("coming soon" without it) |

It also reads `data/speeches.parquet`, `data/minutes.parquet` (preview mode only),
`data/market/` (Bank Rate, decisions and votes, MPC members) and `docs/methodology.md`.

## `data/scores.parquet`

One row per scored document, in the column order of `SCORES_COLUMNS` in
`src/hawk/scoring/score_all.py`, built by `score_all.scores_table` (the site's preview
uses the same function, so both always match). Documents excluded by
`load_documents` (no publication date, under 1,000 characters) have no row.

| column | type | meaning |
| --- | --- | --- |
| `doc_id` | string | stable id, `speech-<10 hex>` or `minutes-<10 hex>` (hash of the URL) |
| `kind` | string | `speech` or `minutes` (the document type) |
| `url` | string | the original on bankofengland.co.uk |
| `title` | string | page title |
| `speaker` | string, null for minutes | canonical name (`speakers.normalise_speaker`); MPC members match `mpc_members.csv` |
| `role` | string, nullable | role as the page gives it |
| `is_mpc_member` | boolean, null for minutes | speaker sat on the MPC on `published_date` |
| `published_date` | datetime64 | day the market could first read it; the only date used for timing |
| `speech_date` | datetime64, nullable | day the speech was given (speeches only) |
| `meeting_date` | datetime64, nullable | MPC meeting date (minutes only) |
| `n_chars` | int | length of the cleaned text |
| `policy_density` | float | policy terms per 100 words (`textprep.policy_density`) |
| `llm_relevance` | float, 0 to 1 | how much of the document is about UK monetary policy |
| `llm_stance` | float, −2 to +2 in 0.5 steps, nullable | −2 very dovish … +2 very hawkish; null when relevance < 0.3 |
| `llm_confidence` | float, 0 to 1 | the model's own confidence |
| `llm_reason` | string | one-sentence justification, quoting the text |
| `baseline_stance` | float, −2 to +2 | word-list net index (`baseline.score_text`) |
| `baseline_hawkish`, `baseline_dovish` | int | hawkish / dovish matches |
| `baseline_relevance` | float | policy terms per 100 words; ≥ 1.5 counts as relevant |
| `model` | string | OpenRouter model id, e.g. `openai/gpt-6-luna` (`preview` in preview mode) |
| `input_mode` | string | `full` or `passages` (`pilot` / `baseline` per row in preview mode) |
| `prompt_version` | string | e.g. `stance_v1` |

The site counts a document as "about monetary policy" when `llm_relevance >= 0.5` and
treats minutes plus speeches with `is_mpc_member` as MPC communication.

## `data/analysis/evaluation.json`

Written by `compare.py` (which reuses `evaluate.build_json` for the chosen model and
appends the other scorers). `NaN` is written as `null`. Beyond the fields below it adds
`*_ci` 95% intervals to each `stance`, per-model `consistency`, `cost_per_doc_usd`,
`corpus_cost_usd` and `chosen`, and a top-level `selection` record of how the model was
chosen; the site ignores what it does not use.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-25T12:00:00+00:00",
  "model": "openai/gpt-6-luna",
  "input_mode": "full",
  "n_labelled": 36,
  "n_relevant": 31,
  "scorers": [
    {
      "name": "LLM (openai/gpt-6-luna, full)",
      "kind": "llm",
      "stance": {
        "n_scored": 31, "n_compared": 30,
        "spearman": 0.78, "exact": 0.6, "within_one": 0.97,
        "confusion": {"labels": [-2, -1, 0, 1, 2], "rows": [[3, 1, 0, 0, 0], "…5 rows"], "no_stance": [0, 0, 1, 0, 0]}
      },
      "relevance": {"n": 36, "precision": 0.94, "recall": 0.97, "accuracy": 0.92}
    }
  ],
  "consistency": {"n": 36, "exact": 0.86, "within_half": 0.97, "mean_abs_diff": 0.21, "relevance_agree": 0.97}
}
```

`scorers` has one entry per scorer (`kind` `baseline` or `llm`); `confusion.rows[i][j]`
counts items the human labelled `labels[i]` and the scorer (rounded) gave `labels[j]`.
`consistency` is `null` when the second run was skipped. A full example is
[`tests/site/fixtures/evaluation.json`](../tests/site/fixtures/evaluation.json).

## `data/analysis/findings.json`

Written by `python -m hawk.analysis.run` (every number behind it, including robustness
checks, is in `findings_detail.json` next to it). Every top-level section is optional: the site shows a
"coming soon" card for any that is missing, so the analysis can land one test at a time.
Numbers are plain floats (`null` when undefined); `display` strings are shown as given.
A full example, with every field, is
[`tests/site/fixtures/findings.json`](../tests/site/fixtures/findings.json).

```text
schema_version   1
generated_at     ISO 8601 timestamp
model, prompt_version   strings, as in scores.parquet
sample           {start, end (ISO dates), n_documents, n_decisions}

headline[]       up to 3 tiles on the home page, in order
  id, label, value (float), display (string, e.g. "+7 pts"), detail (one sentence)

event_study      tone before hikes, cuts and holds
  takeaway       one plain-English sentence
  method         one sentence (shown under the chart title)
  offsets_weeks  [-12, …, 0]   x axis; 0 = week of the decision
  series[]       {decision: hike|cut|hold, n_events, mean[], ci_low[], ci_high[]}
                 arrays aligned with offsets_weeks; null for empty weeks
  table[]        {decision, n_events, mean_tone_before, ci_low, ci_high, tone_change}

prediction_test  does tone add to the previous decision?
  takeaway, method, outcome (e.g. "cut / hold / hike")
  models[]       {name, features[], uses_tone (bool), n, accuracy (0-1), log_loss, pseudo_r2}
  coefficients[] {term, label, estimate, std_error, p_value, ci_low, ci_high}

market_reaction  2-year gilt moves on speech days
  takeaway, method, measure (chart title)
  groups[]       {label, n, value (bp), ci_low, ci_high}     magnitude bars
  by_stance[]    {label, n, value (signed bp)}               diverging bars
  regression[]   {term, label, estimate, std_error, p_value, ci_low, ci_high}

caveats[]        {title, text}   replaces the default caveats when present
```

Rules the analysis must keep, so the site's claims stay true:

- Every number uses only documents with `published_date` on or before the date it is
  attached to (no look-ahead); say how in `method`.
- `takeaway` sentences state the result, including when it is a null result.
- Intervals are 95%.

## Preview mode

Without `data/scores.parquet` the build makes a stand-in with the same columns
(`hawk.site.data.preview_scores`): the real pilot LLM scores (default model, full text,
first run, from `data/pilot/pilot_scores.csv`) for the 20 pilot documents, and the
word-list baseline for every other document (stance from the baseline, relevance =
policy density / 3). No API is called. Every page then carries a "Preview: scores are
not final" banner and a `noindex` tag, and `data/site.json` has `"preview": true`. The
stand-in is cached in `site/.cache/` (gitignored), keyed on the input files.

## Site outputs

`site/_build/` (gitignored) is the deployable site. Besides the pages it holds:

- `data/docs.json`: the explorer table, `{columns, url_prefix, speakers, members, rows}`,
  one row per document with no text (speaker as an index into `speakers`, URL without
  `url_prefix`);
- `data/tone_index.json`: the home chart series (monthly trailing six-month mean stance
  of MPC documents, Bank Rate steps, hikes and cuts, eras);
- `data/site.json`: build manifest (preview flag, counts, pages).
