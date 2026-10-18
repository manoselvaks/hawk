# Data

| File | What it is |
| --- | --- |
| `speeches.parquet` | One row per Bank of England speech since 1997 |
| `minutes.parquet` | One row per set of MPC minutes / Monetary Policy Summary since 1997 |
| `raw/` | Download cache used by the collector (gitignored, rebuildable) |
| `collect_failures.csv` | URLs that could not be collected on the last run, with the error (only written if any failed) |

Rebuild everything with `python -m hawk.speeches.collect` (see the main README).

## Coverage (build of 18 October 2026)

**1,544 speeches** (published 25 February 1997 to 16 October 2026) and **315 sets of MPC
minutes** (meetings from 6 June 1997 to 16 September 2026). No URL failed, so there is
no `collect_failures.csv`. The full download (about 3,200 requests) took 55 minutes at one request
per second; a re-run from the `data/raw/` cache takes about 10 minutes, almost all of it
PDF text extraction.

Records per year (speeches by `published_date`, minutes by `meeting_date`):

| year | speeches | minutes | | year | speeches | minutes |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| 1997 | 5 | 7 | | 2012 | 67 | 12 |
| 1998 | 17 | 12 | | 2013 | 60 | 12 |
| 1999 | 30 | 12 | | 2014 | 71 | 12 |
| 2000 | 36 | 12 | | 2015 | 82 | 12 |
| 2001 | 40 | 13 | | 2016 | 78 | 11 |
| 2002 | 30 | 12 | | 2017 | 61 | 8 |
| 2003 | 19 | 12 | | 2018 | 62 | 8 |
| 2004 | 28 | 12 | | 2019 | 81 | 8 |
| 2005 | 28 | 12 | | 2020 | 61 | 9 |
| 2006 | 35 | 12 | | 2021 | 72 | 8 |
| 2007 | 35 | 12 | | 2022 | 68 | 8 |
| 2008 | 39 | 12 | | 2023 | 74 | 8 |
| 2009 | 49 | 12 | | 2024 | 63 | 8 |
| 2010 | 46 | 12 | | 2025 | 83 | 8 |
| 2011 | 68 | 12 | | 2026 | 55 | 6 |

The 2020 minutes count leaves out the 19 March special meeting, whose `meeting_date` is
missing (10 records in all that year). The MPC met monthly until 2016 and eight times a year since.

Text source: speeches 1,168 PDF / 376 HTML (the Bank published speeches as PDFs until
about 2020), minutes 271 PDF / 44 HTML. Median text length is about 24,500 characters per
speech and 31,000 per set of minutes.

Each of the 315 MPC Bank Rate decisions in `data/market/mpc_decisions.parquet` has a
matching record here. Matching them takes some care; see "Joining minutes to decisions"
below.

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

## Joining minutes to decisions

`meeting_date` is the final day of the meeting as the minutes state it. Before August 2015
that was the day of the announcement. Since August 2015 the MPC has usually finished on the
Wednesday and announced on the Thursday, and occasionally two days later (6 Aug 2020,
24 Jun 2021, 4 Nov 2021). From August 2015 the minutes are published with the decision,
so `published_date` equals the announcement date for every set except those of the
11 March 2020 emergency cut, which were published on 13 March. To join minutes to decisions, use `published_date` from
August 2015 and `meeting_date` before it. Up to July 2015 the minutes came out 9 to 41
days after the meeting (13 days typically).

## Known gaps and caveats

- **Short or empty texts** (worth excluding before scoring):
  - 1 set of minutes with no usable text: **August 1997**. The PDF is a scan with no text
    layer, so only the page's 154-character summary is kept.
  - 1 minutes record is a summary only: the **19 March 2020** special meeting
    (2,638 characters). Its `meeting_date`
    is missing because the page says "19 March" without a year.
  - 4 speeches under 1,000 characters, all pages with a video or slides and no
    transcript: Carney at the Inclusive Capitalism Conference (2015), Bailey on the Money &
    Me schools resource (2020), Ramsden at the NFU conference (2022) and Pill's NatWest
    fireside-chat slides (2026).
  - 13 more speeches between 1,000 and 3,000 characters: short remarks, award
    acceptances and slide decks. They are real but say little.
- **Placeholder pages are skipped.** The sitemap lists pages for scheduled meetings up
  to 2027 ("to be published at 12pm"); 13 such pages with a future publication date were
  skipped, not counted as failures.
- **Mac Roman characters** in one set of 1997 minutes: some apostrophes and quotes appear
  as `Õ`, `Ò`, `Ó`. This affects one record, so the text is left as published.

- Speaker and role are parsed from the title, the banner under it and the opening of the
  text, with heuristics. Honorifics are dropped ("Sir Jon Cunliffe" becomes "Jon Cunliffe").
  Co-authored papers, panels and some early PDFs have no speaker (`None`): 21
  speeches. Nothing is guessed. One person can still appear under two first names
  (Andrew/Andy Haldane), so normalise names before grouping by speaker. Role is missing
  for most HTML-era speeches, whose pages do not state it.
- `published_date` is missing for one speech (David Chaplin, June 2026), whose page has
  no "Published on" line.
- `speech_date` is only filled when the page states when the speech was given; otherwise
  fall back to `published_date`.
- Scanned PDFs without a text layer produce little or no text; these rows will have a short
  `text` and should be checked before scoring.
- Discovery relies on the BoE sitemap. Speech URLs are matched on `/speech/<year>/…`.
  Minutes are matched on `/monetary-policy-summary-and-minutes/<year>/…` (since August
  2015) and on the MPC slugs under `/minutes/<year>/…` (`monetary-policy-committee-<month>-<year>`,
  or `minutes-<month>-<year>` in 2003–05), which also hold other committees' minutes.
  Anything the Bank filed under another path is not collected.
- `meeting_date` comes from the minutes' own wording. In September 2013 the title says
  "held on 3 and 4 September" although the decision was announced on 5 September.
