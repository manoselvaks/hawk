# Hawk — project plan

**One line:** An open-source tool that scores every Bank of England speech and set of MPC minutes since 1997 on a hawkish ↔ dovish scale, and tests whether shifts in tone predicted rate decisions and gilt-yield moves.

**Owner:** Manoj (GitHub: `manoselvaks`) · **Target roles:** markets / macro (S&T, rates, economics research)
**Deadline:** finish by **3 Nov 2026**

## The research question
> Did the tone of BoE communication shift *before* rate decisions, and did markets (2-year gilt yields) react to tone, beyond what the decision itself explains?

## Data (all free and public)
- Speeches (1997 onward): Bank of England website, Speeches section
- MPC minutes and Monetary Policy Summaries: Bank of England website
- Bank Rate history and MPC meeting dates and votes: BoE Statistical Interactive Database
- Gilt yields (2y, 10y): BoE yield curve data

## How scoring works
1. Baseline: word-list method (hawkish and dovish phrase counts).
2. AI scorer: a cheap model through OpenRouter returns a score from −2 (very dovish) to +2 (very hawkish) plus a one-sentence reason.
3. Accuracy check: ~30 hand-labelled speeches; both methods are scored against them.
4. Spending cap: the scorer stops if API spend passes £5.

## Analysis
- Event study: tone before hikes, cuts and holds.
- Prediction test: does the change in tone before a meeting predict the decision, on top of the previous decision?
- Market reaction: 2y gilt yield moves on speech days compared with normal days.
- No look-ahead: only information available at the time is used.

## Website
A static site on GitHub Pages: tone timeline against Bank Rate, per-speech pages, findings page.
