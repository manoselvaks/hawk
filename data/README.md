# Data

| File | What it is |
| --- | --- |
| `speeches.parquet` | One row per Bank of England speech since 1997 |
| `minutes.parquet` | One row per set of MPC minutes / Monetary Policy Summary since 1997 |
| `raw/` | Download cache used by the collector (gitignored, rebuildable) |
| `collect_failures.csv` | URLs that could not be collected on the last run, with the error (only written if any failed) |

Rebuild everything with `python -m hawk.speeches.collect` (see the main README).

## Status: not yet built

The parquet files have not been generated yet. The session that wrote the collector ran in
a sandbox whose network policy blocked `www.bankofengland.co.uk`, so the collector has only
been tested offline against fixtures. Run the collector from a machine with normal internet
access and replace this section with the counts it prints (records per year).

**Expected rebuild time:** roughly 1–1.5 hours at one request per second (an estimate:
on the order of 2,000–2,500 speech pages, a PDF for many older speeches, and about 300 sets
of minutes). Re-runs reuse the cache in `data/raw/` and take a few seconds plus the time to
re-read the sitemaps.

## Fields

### `speeches.parquet`

| Column | Type | Notes |
| --- | --- | --- |
| `url` | str | Canonical page URL (unique key) |
| `title` | str, nullable | Page title, without the " \| Bank of England" suffix |
| `speaker` | str, nullable | From "speech by …"/"speech given by …"; `None` if not stated |
| `role` | str, nullable | e.g. "Governor", "Deputy Governor for Monetary Policy", "Chief Economist", "External MPC member" |
| `speech_date` | datetime, nullable | Date the speech was *given*, when the page says so |
| `published_date` | datetime, nullable | Date the Bank *published* it ("Published on …") |
| `source` | str | `html` or `pdf`: where `text` came from |
| `pdf_url` | str, nullable | Linked PDF, if any |
| `text` | str | Full text, one paragraph per line |

### `minutes.parquet`

| Column | Type | Notes |
| --- | --- | --- |
| `url` | str | Canonical page URL (unique key) |
| `title` | str, nullable | Page title |
| `meeting_date` | datetime, nullable | Final day of the MPC meeting (the decision date) |
| `published_date` | datetime, nullable | Date the minutes were published |
| `source`, `pdf_url`, `text` | | As above |

## Avoiding look-ahead bias

Use **`published_date`** — not `speech_date` or `meeting_date` — whenever you ask "what
did the market know on day *t*?". Minutes in particular were published about two weeks
after the meeting until August 2015, and on the same day as the decision since then.

## Known gaps and caveats

- Speaker and role are parsed from the text with heuristics; panel remarks, joint speeches
  and some early PDFs have them missing (`None`). They are never guessed.
- `speech_date` is only filled when the page states when the speech was given; otherwise
  fall back to `published_date`.
- Scanned PDFs without a text layer produce little or no text; these rows will have a short
  `text` and should be checked before scoring.
- Discovery relies on the BoE sitemaps. Speech URLs are matched on `/speech/<year>/…` and
  minutes on `/monetary-policy-summary-and-minutes/<year>/…`; anything the Bank filed under
  another path is not collected.
