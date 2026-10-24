# Changelog

A short history of the project, one entry per merged pull request.

## 2026-10-24: Polish for recruiters

- Home page leads with the three main findings as tiles, with the AI's accuracy in a
  visible line underneath; the findings page gives the dissent result its own section
  with a chart and its two cautions.
- Content is visible by default (the reveal animation is now progressive enhancement).
- Lighthouse 100 for performance, accessibility, best practices and SEO on the home,
  speeches and findings pages (colour contrast and a layout shift fixed).
- README rewritten; demo GIF, social preview image, `CITATION.cff` and this changelog.

## 2026-10-24: Evaluation, final findings and go-live (#6)

- 36 blind hand labels; GPT-6 Luna chosen as the production scorer (tied on agreement
  with the best model, and cheapest).
- All 1,853 documents scored for $0.59; the four primary tests run on the AI scores.
- Two primary results pass the multiple-testing threshold (event study, dissent); the
  prediction and gilt tests are null. Site switched from preview to final scores.

## 2026-10-19: Static website (#5)

- Jinja + uPlot static site: home chart, speech explorer, MPC member pages, findings
  and methodology, deployed to GitHub Pages on every push to `main`.

## 2026-10-18: Scoring design (#4)

- Word-list baseline, LLM scorer through OpenRouter with caching and a spend cap,
  blind labelling tool and evaluation harness.

## 2026-10-18: First real data collection (#3)

- 1,544 speeches and 315 sets of MPC minutes collected from the Bank of England site.

## 2026-10-18: Market data (#1) and collector (#2)

- Bank Rate, MPC decisions and votes, and 2-year gilt yields from the Bank's own data.
- Project scaffold, polite speech and minutes collector (robots.txt, rate limiting,
  download cache), CI with ruff, mypy and pytest.
