.PHONY: install lint typecheck test check collect collect-sample pilot labelling-set site serve screenshots findings-json social-preview

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

test:
	pytest

check: lint typecheck test

# Full rebuild of data/speeches.parquet and data/minutes.parquet (about 1 hour at 1 request/second; minutes from cache).
collect:
	python -m hawk.speeches.collect

# Quick smoke run: 20 speeches and 10 sets of minutes.
collect-sample:
	python -m hawk.speeches.collect --limit-speeches 20 --limit-minutes 10

# Compare candidate LLMs on 20 documents (cached; first run costs about $0.07).
pilot:
	python -m hawk.scoring.pilot

# Rebuild labelling/label.html and labelling/labelling_set.csv.
labelling-set:
	python -m hawk.scoring.make_labelling_set

# Build the static website into site/_build/ (preview mode until data/scores.parquet exists).
site:
	python -m hawk.site.build

# Build and serve the site on http://localhost:8000
serve:
	python -m hawk.site.serve

# Screenshots of the main pages into docs/screenshots/ (needs Playwright and Chromium).
screenshots: site
	NODE_PATH="$$(npm root -g)" node scripts/screenshots.cjs site/_build docs/screenshots

# Rewrite findings.json (and the dissent chart) from findings_detail.json; re-runs no analysis.
findings-json:
	python -m hawk.analysis.run --rebuild-json

# docs/social-preview.png (1280x640) for GitHub's social preview: the site's Open Graph card.
social-preview: site
	cp site/_build/og.png docs/social-preview.png
