# Hand-labelling

36 documents to label: 30 speeches by MPC members and 6 sets of MPC minutes. Your labels
are the yardstick for both scorers, so they need to be your own reading of the text.
The tool never shows a model's score.

## How to open it

Double-click `label.html`. It opens in your browser and works offline: everything it needs
is inside the file. No server, no install.

Your labels save in the browser as you go, so you can close the tab and come back later
**in the same browser on the same computer**. (A private or incognito window does not
keep them.)

## What to do for each item

Read the policy passages (the paragraphs most about monetary policy), then pick a score.
Open **Show full text** only when the passages are not enough. Aim for under two minutes
per item: about an hour for the set.

Ask: *which way is the author leaning on the future path of UK interest rates, compared
with policy at the time?* Judge the lean, not the level of rates.

| score | meaning | sounds like |
| ---: | --- | --- |
| −2 | Very dovish: argues for cuts or more stimulus soon | "The case for a further cut in Bank Rate is now compelling." |
| −1 | Dovish: worried about weak demand or downside risks; no hurry to tighten | "With demand weak, there is no need to tighten any time soon." |
| 0 | Neutral: balanced, or describes without leaning | "Risks to inflation are broadly balanced." |
| +1 | Hawkish: worried about inflation pressure or upside risks | "I am watching wage growth closely; upside risks have grown." |
| +2 | Very hawkish: argues for rises soon | "Bank Rate needs to rise, and soon, to bring inflation back to target." |
| Not about monetary policy | The document is about something else | Financial stability, regulation, payments, banknotes, climate, the Bank itself |

Tips:

- For **minutes**, score the Committee as a whole, taking account of the vote split.
- Defending a high rate while hinting at cuts is **dovish**; holding rates while warning
  they may have to rise is **hawkish**.
- Try not to use what you know happened next. Score what the text says.
- If an item is hard to call, pick your best guess and add a note.

Keyboard: `1`–`5` give −2 to +2, `N` marks "not about monetary policy", `←` `→` move back
and forward, `F` toggles the full text.

## Sending the labels back

When the progress bar is full, press **Export CSV**. Your browser downloads `labels.csv`.
Send that file back (or commit it as `labelling/labels.csv`). It has one row per item:

| column | contents |
| --- | --- |
| `item`, `doc_id`, `kind` | which document |
| `score` | −2 to 2, blank if "not about monetary policy" |
| `not_monetary_policy` | 1 or 0 |
| `note` | your note, if any |
| `labelled_at` | when you last changed the label |

The evaluation then runs with
`python -m hawk.scoring.evaluate --labels labelling/labels.csv`.

## Files

- `label.html`: the tool, built by `python -m hawk.scoring.make_labelling_set`.
- `labelling_set.csv`: the 36 documents, with the era and policy context used to choose
  them. **Don't open this before labelling.** The policy context column says whether
  the next MPC decision was a hike, cut or hold, which would bias your labels.
