# Market data

Built by `python -m hawk.market.collect` from free Bank of England downloads.
Every file has a `date` column (pandas `datetime64`, no time zone) and covers
1 January 1997 onwards. Row counts, first and last dates and the build time of
the latest run are written to `manifest.json` next to the parquet files.

Raw downloads are cached in `data/market/.cache/` (gitignored) for 24 hours.
`--refresh` forces a fresh download.

## Coverage (build of 18 October 2026)

| file | rows | first date | last date |
| --- | ---: | --- | --- |
| `bank_rate.parquet` | 71 | 1997-05-06 | 2025-12-18 (no change since) |
| `mpc_decisions.parquet` | 315 | 1997-06-06 | 2026-09-17 |
| `gilt_yields.parquet` | 7,527 | 1997-01-02 | 2026-10-15 |

MPC decisions: 35 hikes, 35 cuts, 245 holds; 4 unscheduled. Spot checks against the
public record: Bank Rate cut to 0.1% on 19 March 2020; the 5.25% peak set on 3 August
2023 (6-3 vote); the 2008 cuts of 50bp (8 October, unscheduled), 150bp (6 November) and
100bp (4 December), reaching 0.5% on 5 March 2009; the 2-year spot yield peaking at
4.53% on 27 September 2022 after the mini-budget.

## Files

### `bank_rate.parquet`: one row per Bank Rate change

| column | meaning |
| --- | --- |
| `date` | day the new rate took effect |
| `rate_pct` | new Bank Rate, % |
| `prev_rate_pct` | rate it replaced, % |
| `change_bp` | `rate_pct - prev_rate_pct` in basis points |
| `mpc_match` | `scheduled`, `unscheduled` (emergency), or `pre_mpc` (see below) |

**Source:** the Bank's
[Bank Rate history table](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp),
which lists every change since 1975 (the same data as IADB series `IUDBEDR`, whose
CSV download endpoint is disallowed by the Bank's robots.txt). Starting in 1975 means
the first 1997 change has a previous rate. The 6 May 1997 rise was from 5.94%: rates
before 1997 were set in fractions such as 5.9375% and the table rounds them.

### `mpc_decisions.parquet`: one row per MPC Bank Rate decision

| column | meaning |
| --- | --- |
| `date` | announcement date, as given in the voting workbook |
| `decision` | `hike`, `cut` or `hold` |
| `change_bp` | size of the move in basis points |
| `rate_pct`, `prev_rate_pct` | Bank Rate agreed, and the rate in force the day before, % |
| `scheduled` | `False` for decisions taken outside the meeting calendar |
| `vote_split` | members voting for the agreed rate, then everyone else, e.g. `7-2` |
| `votes_hike`, `votes_hold`, `votes_cut` | members preferring a rise, no change, or a cut from `prev_rate_pct` |
| `dissent_higher`, `dissent_lower` | members who wanted a rate above or below the agreed rate |
| `dissenters` | e.g. `Name (cut 25bp); Name (hold)`, each move measured from `prev_rate_pct` |

**Source:** the Bank's MPC voting record workbook,
[`mpcvoting.xlsx`](https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy-summary-and-minutes/mpcvoting.xlsx),
sheet `Bank Rate Decisions`. It lists every member's preferred Bank Rate at
every decision since June 1997, stored as fractions (0.0525 = 5.25%). No
single BoE file has the decision type and vote split ready-made, so the
collector works them out from the votes: the agreed rate comes from the
workbook, the previous rate is the Bank Rate in force the day before (from the
history table), and each member's vote is compared with both.

In 1998 the workbook records some dissents only as `Increase` or `Decrease`: a rate
above or below the one agreed, size not given (23 votes at 9 meetings). These count
as dissents and appear in `dissenters` as e.g. `Alan Budd (higher, size not recorded)`.
They count as a hike or cut where the direction settles it; the one vote where it
does not (DeAnne Julius on 4 June 1998, wanting less than the agreed hike: either no
change or a smaller rise) is left out of `votes_hike/hold/cut`, so for that meeting
those three add up to 8, not 9.

### `gilt_yields.parquet`: one row per business day

| column | meaning |
| --- | --- |
| `date` | business day (weekends dropped; UK bank holidays have no row) |
| `gilt_2y` | 2-year nominal **spot** (zero-coupon) yield, % |
| `gilt_10y` | 10-year nominal **spot** (zero-coupon) yield, % |

**Source:** the Bank's nominal government liability curve (GLC), daily, from the
[yield curve archive](https://www.bankofengland.co.uk/statistics/yield-curves):
[`glcnominalddata.zip`](https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip)
for history plus
[`latest-yield-curve-data.zip`](https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip)
for the current month. From each `GLC Nominal daily data*.xlsx` workbook the
collector reads sheet `4. spot curve` at the 2.0 and 10.0 year maturities.
Where workbooks overlap, the later file wins.

The 10-year figure should match IADB series `IUDMNZC` (10-year nominal
zero-coupon yield). IADB has no 2-year equivalent, which is why the curve
files are the source.

## Validation

The collector writes nothing unless these checks pass:

* no duplicate or unsorted dates in any file, and no dates in the future;
* Bank Rate between 0% and 20%, gilt yields between -2% and 20%;
* no weekend dates in the gilt file;
* every Bank Rate change matches an MPC decision on the same day setting the
  same rate, and every hike or cut matches a Bank Rate change;
* every decision has a known previous rate.

Expected exceptions are logged as flags, not errors:

* **Unscheduled MPC moves**, tagged `mpc_match = unscheduled` and
  `scheduled = False`: 18 Sep 2001 (after the 11 September attacks),
  8 Oct 2008 (coordinated cut with other central banks), and the Covid
  emergency cuts of 11 Mar 2020 and 19 Mar 2020. The list is kept in
  `hawk.market.sources.UNSCHEDULED_DECISIONS`.
* **Pre-MPC changes**, tagged `mpc_match = pre_mpc`: the Chancellor still set
  Bank Rate until the MPC's first decision on 6 Jun 1997, so the 6 May 1997
  rise has no MPC decision behind it.

## Caveats

* `date` in `mpc_decisions` is the date in the voting workbook. The validation
  check that it equals the day Bank Rate changed confirms it is the
  announcement date. Up to 2015 the MPC met over two days and announced on the
  second, so meeting start dates are a day earlier.
* Votes on asset purchases (QE) and other tools are not included. These are
  Bank Rate votes only.
* GLC yields are points on a smoothed fitted curve, not quotes for particular
  gilts. The Bank's methodology notes on the yield curve page explain the
  fitting and compounding conventions. The short end of the curve can be
  noisier than the 10-year point.
* Bank Rate and yields are reported in percent, rounded as the Bank publishes them.
