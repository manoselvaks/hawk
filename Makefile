.PHONY: install lint typecheck test check collect collect-sample pilot labelling-set

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
