# hawk

Scoring 28 years of Bank of England speeches from hawkish to dovish, and testing whether tone predicted rate moves.

Hawk collects every Bank of England speech and every set of Monetary Policy Committee (MPC)
minutes since 1997, scores each one on a scale from −2 (very dovish) to +2 (very hawkish),
and asks a simple markets question: **did the tone of BoE communication shift before rate
decisions, and did 2-year gilt yields react to tone beyond what the decision itself
explains?** See [PLAN.md](PLAN.md) for the full plan.

## Status

| Step | State |
| --- | --- |
| Speech and minutes collector | ✅ built (`src/hawk/speeches/`) |
| Market data (Bank Rate, gilt yields) | in progress (`src/hawk/market/`) |
| Tone scoring (word list + LLM) | planned |
| Analysis and website | planned |

## Install

Requires Python 3.11 or newer.

```bash
git clone https://github.com/manoselvaks/hawk.git
cd hawk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Collect the speeches and minutes

```bash
python -m hawk.speeches.collect                                  # full rebuild
python -m hawk.speeches.collect --limit-speeches 20 --limit-minutes 10   # quick smoke run
```

(or `make collect` / `make collect-sample`). This writes `data/speeches.parquet` and
`data/minutes.parquet` (1,544 speeches and 315 sets of minutes in the committed build);
see [data/README.md](data/README.md) for the fields, per-year counts and known gaps.

The collector is built to be a good citizen of the BoE website:

- it identifies itself with a `User-Agent` that links back to this repository;
- it reads `robots.txt` first, obeys it (including any `Crawl-delay`), and discovers pages
  from the sitemaps listed there;
- it waits at least one second between requests (`--min-interval` to slow it further);
- every download is cached in `data/raw/` (gitignored), so an interrupted run can simply be
  restarted and will pick up where it left off without re-downloading anything.

Older speeches and minutes are often short web pages that link to a PDF; when a page has
little text and links to a PDF, the PDF's text is used instead.

## Development

```bash
make check   # ruff (lint + format), mypy (strict) and pytest
```

Tests run fully offline against trimmed copies of real BoE pages, a sitemap excerpt and
the first pages of two real PDFs, in `tests/speeches/fixtures/`.
CI runs the same checks on every push and pull request.

## Licence

MIT, see [LICENSE](LICENSE).
