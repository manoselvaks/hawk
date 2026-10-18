"""Tone scoring for Hawk: text preparation, a word-list baseline and an LLM scorer.

The pieces, in the order a document passes through them:

* ``corpus`` loads speeches and minutes into one table of scorable documents
  (cleaned text, normalised speaker, MPC membership, exclusions logged);
* ``textprep`` cleans PDF debris and extracts the passages most about monetary policy;
* ``baseline`` scores a document with hawkish and dovish word lists (``lexicon``);
* ``llm`` scores it with a model through OpenRouter, with caching and a spend cap;
* ``evaluate`` compares both against hand labels.

See ``docs/methodology.md`` for the design and its limitations.
"""
